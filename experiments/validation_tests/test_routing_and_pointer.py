"""Phase 5: routing herding, k>0 tie-breaking, occupancy ignoring queued jobs, CI pointer lag."""
import unittest
from datetime import datetime

from _common import Job, SimulationTime, quiet, tiny_cluster
from globalqueue.RoutingPolicies import CapacityAwareCIRouting, OriginCapacityAwareCIRouting


class Fake:
    def __init__(self, site_id, ci, occ, cores=100):
        self.site_id, self._ci, self._occ, self._cores = site_id, ci, occ, cores

    def get_carbon_intensity(self): return self._ci
    def cluster_occupancy(self): return self._occ
    def get_number_of_cores(self): return self._cores


class ClusterAdapter:
    """Same interface the policies use on JobScheduler, backed by a real Cluster."""
    def __init__(self, site_id, cluster): self.site_id, self._c = site_id, cluster
    def get_carbon_intensity(self): return self._c.get_current_carbon_intensity()
    def cluster_occupancy(self): return self._c.cluster_occupancy()
    def get_number_of_cores(self): return self._c.get_number_of_cores()


CLOCK = SimulationTime({'output': {'verbosity': 'low'}}, '2030-01-01 00:00')   # only used by prepare() for logging


def route(policy, sites, n, cores=8, origin='B'):
    if getattr(policy, '_simulation_time', 1) is None:
        policy._simulation_time = CLOCK
    d = {s.site_id: s for s in sites}
    policy.prepare(d)
    out = {}
    for i in range(n):
        j = Job(f'j{i}', 600, 2, cores, origin)
        sid = policy.choose_scheduler(j, d).site_id
        out[sid] = out.get(sid, 0) + 1
    return out


class TestHerding(unittest.TestCase):
    def sites(self):
        return [Fake('A', 100, 0.5), Fake('B', 200, 0.5), Fake('C', 300, 0.5)]   # 50 free cores each

    def test_current_capacity_aware_sends_whole_step_to_one_site(self):
        self.assertEqual(route(CapacityAwareCIRouting(k=1.3), self.sites(), 500), {'A': 500})   # 4000 cores into 50 free

    @unittest.expectedFailure
    def test_expected_capacity_aware_respects_capacity_within_step(self):
        self.assertLessEqual(route(CapacityAwareCIRouting(k=1.3), self.sites(), 500).get('A', 0), 7)

    def test_origin_capacity_aware_updates_occupancy_within_step(self):
        out = route(OriginCapacityAwareCIRouting(k=1.3, origin_bias=1.0), self.sites(), 500)
        self.assertGreater(len(out), 1)


class TestZeroOccupancyTie(unittest.TestCase):
    def sites(self):
        return [Fake('DIRTY', 400, 0.0), Fake('CLEAN', 50, 0.0)]

    def test_current_k_positive_empty_sites_tie_first_listed_wins(self):
        self.assertEqual(route(CapacityAwareCIRouting(k=1.3), self.sites(), 1), {'DIRTY': 1})
        self.assertEqual(route(OriginCapacityAwareCIRouting(k=1.3, origin_bias=1.0), self.sites(), 1, origin='X'), {'DIRTY': 1})

    @unittest.expectedFailure
    def test_expected_lower_ci_preferred_when_both_empty(self):
        self.assertEqual(route(CapacityAwareCIRouting(k=1.3), self.sites(), 1), {'CLEAN': 1})


class TestOccupancyIgnoresQueue(unittest.TestCase):
    def _backlogged(self):
        st, cl, dl = tiny_cluster(ci_rows=[['2030-01-01T00:00:00', '10', '10'], ['2030-01-01T00:30:00', '10', '10']])
        with quiet():
            first = Job('run', 36000, 1, 1); first.submit_time = st.get_current_datetime(); cl.submit_job(first); cl.update()
            for i in range(50):
                j = Job(f'q{i}', 600, 1, 2); j.submit_time = st.get_current_datetime(); cl.submit_job(j)
            cl.update()
        return cl

    def test_current_occupancy_unchanged_by_50_queued_jobs(self):
        cl = self._backlogged()
        self.assertEqual(len(cl._queued_jobs), 50)
        self.assertEqual(cl.cluster_occupancy(), 0.5)

    def test_current_origin_capacity_aware_still_routes_to_backlogged_site(self):
        cl = self._backlogged()
        sites = [ClusterAdapter('BACKLOG', cl), Fake('FREE', 200, 0.0, cores=1000)]
        self.assertEqual(route(OriginCapacityAwareCIRouting(k=0.0, origin_bias=1.0), sites, 1, cores=1, origin='X'), {'BACKLOG': 1})

    @unittest.expectedFailure
    def test_expected_backlog_counted_in_occupancy(self):
        self.assertGreaterEqual(self._backlogged().cluster_occupancy(), 0.9)


class TestCIPointer(unittest.TestCase):
    """Energy for step t covers [t, t+dt); correct CI is the half-hour segment containing t."""
    ROWS = [[f'2030-01-01T{h:02d}:{m:02d}:00', str(v), str(v)] for (h, m), v in
            zip([(0, 0), (0, 30), (1, 0), (1, 30)], [100, 200, 300, 400])]
    TIMES = ['00:00', '00:10', '00:20', '00:30', '00:40', '00:50', '01:00', '01:10']
    CORRECT = [100, 100, 100, 200, 200, 200, 300, 300]

    def _trace(self):
        st, cl, dl = tiny_cluster(ci_rows=self.ROWS)
        decision, energy = [], []
        with quiet():
            j = Job('long', 36000, 1, 1); j.submit_time = st.get_current_datetime(); cl.submit_job(j)
            for _ in self.TIMES:
                decision.append(cl.get_current_carbon_intensity())   # what JobScheduler/routing read (before cluster.update)
                cl.update()
                energy.append(dl._timestep_carbon_intensities[-1])  # CI applied to this step's energy
                st.advance()
        return decision, energy

    def test_current_energy_ci_lags_on_half_hour_boundaries(self):
        decision, energy = self._trace()
        self.assertEqual(energy, [100, 100, 100, 100, 200, 200, 200, 300])

    def test_current_decision_ci_lags_up_to_two_steps(self):
        decision, energy = self._trace()
        self.assertEqual(decision, [100, 100, 100, 100, 100, 200, 200, 200])

    @unittest.expectedFailure
    def test_expected_energy_ci_matches_segment(self):
        self.assertEqual(self._trace()[1], self.CORRECT)

    @unittest.expectedFailure
    def test_expected_decision_ci_matches_segment(self):
        self.assertEqual(self._trace()[0], self.CORRECT)


if __name__ == '__main__':
    unittest.main()

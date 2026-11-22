"""Phase 3 dimensional check: 1-node / 1-step fixture against hand calculation.

Hand calculation (tiny node: 2 threads = 1 physical core, idle 100 W, max 300 W, HT overhead 20%):
  2 threads busy : P = 300 W                    -> E = 300*600/3.6e6 = 0.050000 kWh
  1 thread busy  : P = 300/1.2 = 250 W          -> E = 250*600/3.6e6 = 0.041667 kWh
  idle           : P = 100 W                    -> E = 100*600/3.6e6 = 0.016667 kWh
  emissions      : g = E[kWh] * ACTUAL CI (column 3 = 250 g/kWh; forecast column = 150 must NOT be used)
"""
import unittest
from datetime import timedelta

from _common import Job, Simulation, quiet, sim_configs, tiny_cluster


def run_one_step(cores):
    st, cl, dl = tiny_cluster()
    job = Job('j', 3600, memory_req=1, cores_req=cores, origin_site='T')
    job.submit_time = st.get_current_datetime()
    with quiet():
        cl.submit_job(job)
        cl.update()
    return dl


class TestDimensional(unittest.TestCase):
    def test_full_node_energy_and_carbon(self):
        dl = run_one_step(2)
        self.assertAlmostEqual(dl._total_energy_consumed, 300 * 600 / 3.6e6, places=12)
        self.assertAlmostEqual(dl._total_carbon_consumed, 300 * 600 / 3.6e6 * 250, places=9)

    def test_half_node_energy_and_carbon(self):
        dl = run_one_step(1)
        self.assertAlmostEqual(dl._total_energy_consumed, 250 * 600 / 3.6e6, places=12)
        self.assertAlmostEqual(dl._total_carbon_consumed, 250 * 600 / 3.6e6 * 250, places=9)

    def test_emissions_use_actual_not_forecast_column(self):
        dl = run_one_step(2)
        self.assertNotAlmostEqual(dl._total_carbon_consumed, 0.05 * 150, places=6)


class TestHorizonStepCount(unittest.TestCase):
    """Simulation.start() evaluates t=0 AND t=simulation_length: N+1 energy steps for an N-step horizon."""

    def _run(self):
        cfg, cl = sim_configs('2030-01-01 00:00', 600, [{'site_id': 'T', 'ci_file': 'flat_equal_Scot.csv', 'initial': {'GridPP': 1}}])
        with quiet():
            sim = Simulation(cfg, cl)
            sim.start()
        return sim._site_list[0].data_logger

    def test_current_behaviour_logs_two_steps_for_600s_horizon(self):
        dl = self._run()
        self.assertAlmostEqual(dl._total_energy_consumed, 2 * 250 * 600 / 3.6e6, places=12)

    @unittest.expectedFailure
    def test_expected_one_step_for_600s_horizon(self):
        dl = self._run()
        self.assertAlmostEqual(dl._total_energy_consumed, 1 * 250 * 600 / 3.6e6, places=12)


if __name__ == '__main__':
    unittest.main()

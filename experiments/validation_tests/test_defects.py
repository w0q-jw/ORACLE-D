"""Phase 5 regression tests for suspected defects B1, B3, B4, B5, B6, B8, B9, B10.

Convention: `test_Bx_current_*` asserts the behaviour the code exhibits today (passes while the defect exists).
            `test_Bx_expected_*` asserts the correct behaviour and is marked @expectedFailure.
            If a defect is fixed, the expected test reports "unexpected success" -> update both tests.
"""
import logging
import random
import re
import unittest
from datetime import datetime, timedelta

from _common import (DataLogger, Job, LogCapture, RAM_INV, Simulation, quiet, sim_configs, tiny_cluster)


# --------------------------------------------------------------------------------------------- B1
class TestB1DurationTruncation(unittest.TestCase):
    def _run(self, hours):
        st, cl, dl = tiny_cluster()
        job = Job('long', hours * 3600, memory_req=1, cores_req=1)
        job.submit_time = st.get_current_datetime()
        with quiet():
            cl.submit_job(job); cl.update()
            st._time = st._time + timedelta(hours=hours + 1)
            cl.update()
        return job, dl

    def test_B1_current_30h_job_recorded_as_6h(self):
        job, dl = self._run(30)
        self.assertEqual(dl._jobs_finished, 1)
        self.assertEqual(job.duration, 6 * 3600)                 # 108000 s mod 86400
        self.assertEqual(dl._cumulative_cpu_time, 6 * 3600)

    def test_B1_under_24h_unaffected(self):
        job, dl = self._run(20)
        self.assertEqual(job.duration, 20 * 3600)

    @unittest.expectedFailure
    def test_B1_expected_total_seconds(self):
        job, dl = self._run(30)
        self.assertEqual(dl._cumulative_cpu_time, 30 * 3600)


# --------------------------------------------------------------------------------------------- B3
class TestB3MissingCIExit(unittest.TestCase):
    def _cfg(self):
        return sim_configs('2030-01-01 00:00', 12 * 3600,
                           [{'site_id': 'T', 'ci_file': 'defect_blank.csv', 'incoming': {'GridPP': 1}}])

    def test_B3_current_message_printed_but_no_exit_then_crash_later(self):
        cfg, cl = self._cfg()
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sim = Simulation(cfg, cl)                            # no SystemExit despite blank rows
        self.assertIn('You are missing forecast CI data', buf.getvalue())
        self.assertEqual(len(sim._site_list[0].cluster._carbondata), 25)   # blank rows were kept
        with quiet(), self.assertRaises(ValueError):             # float('') when pointer reaches 06:00
            sim.start()

    @unittest.expectedFailure
    def test_B3_expected_controlled_exit_at_load(self):
        cfg, cl = self._cfg()
        with quiet(), self.assertRaises(SystemExit):
            Simulation(cfg, cl)


# --------------------------------------------------------------------------------------------- B4
class TestB4CarbonPerCpuHour(unittest.TestCase):
    def _loggers(self, cpu_s_policy=7200):
        cfg = {'output': {'verbosity': 'low', 'run_dir': '/tmp'}}
        base, pol = DataLogger(cfg), DataLogger(cfg)
        for dl, g, cpu in ((base, 7200.0, 7200), (pol, 3600.0, cpu_s_policy)):
            dl._total_carbon_consumed = g; dl._cumulative_cpu_time = cpu; dl._jobs_finished = 1; dl._jobs_started = 1
        return base, pol

    def test_B4_current_value_is_grams_per_core_second(self):
        base, pol = self._loggers()
        c = pol.comparison(base, 0, 0, 0)
        self.assertAlmostEqual(c['carbon_per_cpu_hour_baseline'], 1.0)     # 7200 g / 7200 core-s
        self.assertAlmostEqual(c['carbon_per_cpu_hour_percentage'], 50.0)   # ratio unaffected by the 3600 factor

    def test_B4_current_label_says_g_per_kWh(self):
        base, pol = self._loggers()
        lines = pol._format_comparison_lines(pol.comparison(base, 0, 0, 0))
        self.assertTrue(any('per CPU hour' in l and 'g/kWh' in l for l in lines))

    @unittest.expectedFailure
    def test_B4_expected_grams_per_core_hour(self):
        base, pol = self._loggers()
        self.assertAlmostEqual(pol.comparison(base, 0, 0, 0)['carbon_per_cpu_hour_baseline'], 3600.0)

    def test_B4_current_zero_cpu_raises(self):
        base, pol = self._loggers(cpu_s_policy=0)
        with self.assertRaises(ZeroDivisionError):
            pol.comparison(base, 0, 0, 0)


# --------------------------------------------------------------------------------------------- B5
class TestB5RamAdmission(unittest.TestCase):
    def _node(self):
        st, cl, dl = tiny_cluster(inventory=RAM_INV, cluster_name='RAMTEST')   # 8 threads, 4 GB
        return cl._worker_nodes[0]

    def test_B5_current_admits_job_needing_8GB_on_4GB_node(self):
        wn = self._node()
        job = Job('ram', 600, memory_req=1, cores_req=8)                     # 1 GB/core x 8 cores = 8 GB
        self.assertTrue(wn.can_schedule_job(job))
        with quiet():
            wn.set_datalogger_handlers(lambda *a: None, lambda *a: None)
            wn.start_job(job)
        self.assertGreater(wn.busy_RAM, wn.max_RAM)                          # 8 > 4: over-allocated

    @unittest.expectedFailure
    def test_B5_expected_rejects_total_ram_over_capacity(self):
        wn = self._node()
        self.assertFalse(wn.can_schedule_job(Job('ram', 600, memory_req=1, cores_req=8)))


# --------------------------------------------------------------------------------------------- B6
class TestB6AtlasLogging(unittest.TestCase):
    def test_B6_current_logged_duration_differs_from_job(self):
        from jobs.VOJobFactory import ATLASJobFactory
        log = logging.getLogger('CLUSTERSIM'); cap = LogCapture(); log.addHandler(cap); old = log.level; log.setLevel(logging.INFO)
        try:
            random.seed(12345)
            f = ATLASJobFactory('A-')
            jobs = [f.create_job() for _ in range(10)]
        finally:
            log.removeHandler(cap); log.setLevel(old)
        logged = [float(m) for m in re.findall(r'duration=([0-9.]+)s', '\n'.join(cap.records))]
        self.assertEqual(len(logged), 10)
        mismatches = sum(abs(a - j.duration) > 1e-6 for a, j in zip(logged, jobs))
        self.assertGreaterEqual(mismatches, 9)      # essentially every logged value is a fresh draw
        self.mismatches = mismatches

    def test_B6_current_extra_rng_draws_for_first_10_jobs(self):
        from jobs.VOJobFactory import ATLASJobFactory
        counts = []
        orig_r, orig_g = random.random, random.gauss
        n = {'k': 0}
        def r(): n['k'] += 1; return orig_r()
        def g(mu, s): n['k'] += 1; return orig_g(mu, s)
        random.random, random.gauss = r, g
        try:
            random.seed(1)
            f = ATLASJobFactory('A-')
            for _ in range(12):
                n['k'] = 0; f.create_job(); counts.append(n['k'])
        finally:
            random.random, random.gauss = orig_r, orig_g
        self.assertEqual(counts[:10], [6] * 10)      # 3 draws for the job + 3 for the log line
        self.assertEqual(counts[10:], [3, 3])

    @unittest.expectedFailure
    def test_B6_expected_log_matches_job(self):
        from jobs.VOJobFactory import ATLASJobFactory
        log = logging.getLogger('CLUSTERSIM'); cap = LogCapture(); log.addHandler(cap); old = log.level; log.setLevel(logging.INFO)
        try:
            random.seed(12345); f = ATLASJobFactory('A-'); job = f.create_job()
        finally:
            log.removeHandler(cap); log.setLevel(old)
        logged = float(re.findall(r'duration=([0-9.]+)s', cap.records[0])[0])
        self.assertAlmostEqual(logged, job.duration, places=2)


# --------------------------------------------------------------------------------------------- B8
def ci_trace(start, length_s, ci_file):
    cfg, cl = sim_configs(start, length_s, [{'site_id': 'T', 'ci_file': ci_file, 'incoming': {'GridPP': 1}}])
    with quiet():
        sim = Simulation(cfg, cl)
        sim.start()
    dl = sim._site_list[0].data_logger
    return sim, list(zip(dl._timestep_timestamps, dl._timestep_carbon_intensities))


class TestB8TimestampGaps(unittest.TestCase):
    def test_B8_current_gap_reuses_stale_value_for_24h(self):
        sim, trace = ci_trace('2030-01-01 12:00', 36 * 3600, 'defect_gap.csv')
        in_gap = [ci for t, ci in trace if datetime(2030, 1, 2, 0, 0) <= t <= datetime(2030, 1, 3, 0, 0)]
        self.assertEqual(len(in_gap), 145)
        self.assertTrue(all(ci == 195.0 for ci in in_gap))     # value of 2030-01-01T23:30 reused for 24 h

    @unittest.expectedFailure
    def test_B8_expected_gap_detected(self):
        cfg, cl = sim_configs('2030-01-01 12:00', 36 * 3600, [{'site_id': 'T', 'ci_file': 'defect_gap.csv', 'incoming': {'GridPP': 1}}])
        with quiet(), self.assertRaises((ValueError, SystemExit)):
            Simulation(cfg, cl)

    def test_B8_current_start_inside_gap_crashes_with_indexerror_at_runtime(self):
        cfg, cl = sim_configs('2030-01-02 06:00', 3600, [{'site_id': 'T', 'ci_file': 'defect_gap.csv', 'incoming': {'GridPP': 1}}])
        with quiet():
            sim = Simulation(cfg, cl)                          # constructs silently with 0 CI rows
        self.assertEqual(len(sim._site_list[0].cluster._carbondata), 0)
        with quiet(), self.assertRaises(IndexError):
            sim.start()

    def test_B8_current_end_inside_gap_reads_to_end_of_file(self):
        cfg, cl = sim_configs('2030-01-01 12:00', 12 * 3600, [{'site_id': 'T', 'ci_file': 'defect_gap.csv', 'incoming': {'GridPP': 1}}])
        with quiet():
            sim = Simulation(cfg, cl)
        self.assertGreater(len(sim._site_list[0].cluster._carbondata), 25 + 100)   # needed ~25 rows

    def test_B8_current_duplicate_timestamp_second_value_used(self):
        sim, trace = ci_trace('2030-01-01 05:00', 3 * 3600, 'defect_duplicate.csv')
        used = dict(trace)
        self.assertEqual(used[datetime(2030, 1, 1, 6, 10)], 1160.0)      # the duplicate row silently wins

    def test_B8_reference_clean_file(self):
        sim, trace = ci_trace('2030-01-01 05:00', 3 * 3600, 'defect_index.csv')
        self.assertEqual(dict(trace)[datetime(2030, 1, 1, 6, 10)], 160.0)


# --------------------------------------------------------------------------------------------- B9
class TestB9InitialJobsHeld(unittest.TestCase):
    def _sim(self):
        cfg, cl = sim_configs('2030-01-01 00:00', 86400,
                              [{'site_id': 'T', 'ci_file': 'falling_Scot.csv', 'initial': {'GridPP': 3}, 'temporal': 'sustainable_queue'}])
        with quiet():
            return Simulation(cfg, cl)

    def test_B9_current_initial_jobs_enter_sustainable_queue(self):
        sim = self._sim()
        self.assertEqual(sim._site_list[0].job_scheduler._temporal_shifter.held_jobs, 3)
        self.assertEqual(len(sim._site_list[0].cluster._queued_jobs), 0)

    @unittest.expectedFailure
    def test_B9_expected_initial_jobs_bypass_temporal_holding(self):
        self.assertEqual(self._sim()._site_list[0].job_scheduler._temporal_shifter.held_jobs, 0)


# -------------------------------------------------------------------------------------------- B10
class TestB10IdleEnergy(unittest.TestCase):
    IDLE_STEP_KWH = 100 * 600 / 3.6e6

    def test_B10_current_empty_cluster_logs_zero(self):
        st, cl, dl = tiny_cluster()
        with quiet():
            cl.update()
        self.assertEqual(dl._total_energy_consumed, 0.0)

    @unittest.expectedFailure
    def test_B10_expected_empty_cluster_logs_idle(self):
        st, cl, dl = tiny_cluster()
        with quiet():
            cl.update()
        self.assertAlmostEqual(dl._total_energy_consumed, self.IDLE_STEP_KWH, places=12)

    def test_B10_current_empty_site_in_multisite_run(self):
        cfg, cl = sim_configs('2030-01-01 00:00', 3600, [
            {'site_id': 'BUSY', 'ci_file': 'flat_equal_Scot.csv', 'incoming': {'GridPP': 1}},
            {'site_id': 'EMPTY', 'ci_file': 'flat_equal_UoM.csv'}])
        with quiet():
            sim = Simulation(cfg, cl); sim.start()
        empty = [s for s in sim._site_list if s.site_id == 'EMPTY'][0]
        self.assertFalse(empty.finished and empty.finish_reason == 'no_jobs')
        self.assertEqual(empty.data_logger._total_energy_consumed, 0.0)   # 7 steps x 0.01667 kWh expected


if __name__ == '__main__':
    unittest.main()

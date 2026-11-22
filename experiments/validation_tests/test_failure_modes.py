"""Phase 3: behaviour on invalid configuration, missing files, invalid CI data and zero baseline."""
import unittest

from _common import Simulation, quiet, sim_configs


def build(**over):
    spec = {'site_id': 'T', 'ci_file': 'flat_equal_Scot.csv', 'incoming': {'GridPP': 1}}
    routing = over.pop('routing', None)
    start = over.pop('start', '2030-01-01 00:00')
    spec.update(over)
    cfg, cl = sim_configs(start, 3600, [spec], routing=routing)
    return cfg, cl


class TestInvalidConfig(unittest.TestCase):
    def test_unknown_routing_policy_informative(self):
        cfg, cl = build(routing={'policy': 'teleport'})
        with quiet(), self.assertRaisesRegex(ValueError, 'teleport'):
            Simulation(cfg, cl)

    def test_unknown_temporal_policy_informative(self):
        cfg, cl = build(temporal='later')
        with quiet(), self.assertRaisesRegex(ValueError, 'later'):
            Simulation(cfg, cl)

    def test_missing_ci_file_informative(self):
        cfg, cl = build(ci_file='does_not_exist.csv')
        with quiet(), self.assertRaisesRegex(FileNotFoundError, 'does_not_exist.csv'):
            Simulation(cfg, cl)

    def test_bad_start_format(self):
        cfg, cl = build(start='05/01/2030 16:00')
        with quiet(), self.assertRaises(ValueError):
            Simulation(cfg, cl)

    def test_missing_jobs_key_is_bare_keyerror(self):
        cfg, cl = build()
        del cl[0]['jobs']
        with quiet(), self.assertRaises(KeyError) as ctx:
            Simulation(cfg, cl)
        self.assertEqual(ctx.exception.args, ('jobs',))      # controlled, but not explanatory

    def test_start_outside_ci_range_not_caught_at_load(self):
        cfg, cl = build(start='2031-06-01 00:00')
        with quiet():
            sim = Simulation(cfg, cl)
        self.assertEqual(len(sim._site_list[0].cluster._carbondata), 0)
        with quiet(), self.assertRaises(IndexError):
            sim.start()


class TestZeroBaseline(unittest.TestCase):
    def _pair(self):
        sims = []
        for _ in range(2):
            cfg, cl = build(incoming={})
            with quiet():
                s = Simulation(cfg, cl); s.start()
            sims.append(s)
        return sims

    def test_current_no_jobs_comparison_raises_zero_division(self):
        base, pol = self._pair()
        self.assertEqual(base._global_logger._total_carbon_consumed, 0)
        with quiet(), self.assertRaises(ZeroDivisionError):
            pol.compare_to_baseline(base, 0)

    @unittest.expectedFailure
    def test_expected_no_jobs_comparison_controlled(self):
        base, pol = self._pair()
        try:
            with quiet():
                result = pol.compare_to_baseline(base, 0)
        except ZeroDivisionError as e:
            self.fail(f'comparison with zero baseline raised {e!r}')
        self.assertIsInstance(result, dict)


if __name__ == '__main__':
    unittest.main()

"""Shared helpers. Tests import the PRISTINE git-archive copy of src (commit 8ceee65), never the worktree."""
import contextlib
import io
import logging
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
XP = os.path.dirname(HERE)
SRC = os.path.join(XP, '_pristine', 'src')
FIX = os.path.join(HERE, 'fixtures')
CI_DIR = os.path.join(FIX, 'ci') + '/'
TINY_INV = os.path.join(FIX, 'cluster', 'tiny_inventory.csv')
RAM_INV = os.path.join(FIX, 'cluster', 'ramtest_inventory.csv')
TINY_FREQ = os.path.join(FIX, 'cluster', 'tiny_frequency.csv')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

os.environ.setdefault('MPLBACKEND', 'Agg')

from simulation.Time import SimulationTime            # noqa: E402
from simulation.Simulation import Simulation           # noqa: E402
from cluster.Cluster import Cluster                    # noqa: E402
from cluster.ClusterLoader import load_cluster_inventory  # noqa: E402
from datalogger.DataLogger import DataLogger           # noqa: E402
from jobs.Jobs import Job                              # noqa: E402


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def tiny_cluster(start='2030-01-01 00:00', ci_rows=None, inventory=TINY_INV, timestep=600, cluster_name='TINY'):
    """1-node cluster wired to a DataLogger, exactly as Simulation._build_site wires it."""
    tmp = tempfile.mkdtemp(prefix='xp_')
    cfg = {'site_id': 'T', 'output': {'verbosity': 'low', 'run_dir': tmp}}
    st = SimulationTime(cfg, start)
    st._timestep_seconds = timestep
    inv = load_cluster_inventory(inventory, TINY_FREQ, cluster_name=cluster_name, strict=True)
    ci_rows = ci_rows or [['2030-01-01T00:00:00', '150', '250'], ['2030-01-01T00:30:00', '150', '250']]
    cl = Cluster(cfg, st, inv, ci_rows, 'none', 200)
    dl = DataLogger(cfg)
    cl.set_datalogger_handlers(dl.job_submit, dl.job_start, dl.job_finish, dl.energy_and_carbon_consumed,
                               dl.sum_occupancy, dl.record_timestep_metrics)
    return st, cl, dl


def sim_configs(start, length_s, site_specs, routing=None, timestep=600):
    """site_specs: list of dicts with keys site_id, ci_file, initial, incoming, temporal, inventory."""
    tmp = tempfile.mkdtemp(prefix='xp_sim_')
    config = {'Simulation': {'desired_starttime': start, 'simulation_length': length_s, 'timestep': timestep,
                             'routing': routing or {'policy': 'origin_site'}},
              'output': {'verbosity': 'low', 'debug': False, 'run_dir': tmp, 'run_label': 'xp_test'}}
    clusters = []
    for s in site_specs:
        inv = s.get('inventory', TINY_INV)
        clusters.append({
            'site_id': s['site_id'],
            'cluster': {'cluster_name': s.get('cluster_name', 'TINY'), 'inventory_csv': inv,
                        'frequency_csv': TINY_FREQ, 'strict': True},
            'carbon_intensity': {'folder': s.get('ci_folder', CI_DIR), 'filename': s['ci_file'], 'high_CI_threshold': 300},
            'jobs': {'initial_mix': s.get('initial', {}), 'regular_incoming_mix': s.get('incoming', {}),
                     'incoming_timestep': s.get('incoming_timestep', 600)},
            'savings_policy': 'none',
            'temporal_shifting': {'policy': s.get('temporal', 'submit_immediately')},
        })
    return config, clusters


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())

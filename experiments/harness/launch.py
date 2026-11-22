"""Run the UNMODIFIED ORACLE-D src/Main.py with a controlled seed and passive instrumentation.

Usage (cwd must be the per-run root containing src/, configs/, data/):
    python launch.py <seed> <metrics_dir> <instrument:0|1>

* Seed control: Main.py draws `run_seed = random.randint(0, 2**32-1)` exactly once.
  We replace random.randint for that single call only, so run_seed == <seed>.
  Main.py then re-seeds `random` and `np.random` with run_seed before each of the
  baseline and policy simulations, exactly as in production.
* Instrumentation (instrument=1) wraps a few methods at runtime. Every wrapper calls
  the original first/unchanged and only READS state; none draws random numbers.
  No source file is modified. Equivalence with instrument=0 is checked in Phase 3.
"""
import atexit
import hashlib
import json
import os
import random
import resource
import runpy
import sys
import time

seed = int(sys.argv[1])
metrics_dir = os.path.abspath(sys.argv[2])
instrument = sys.argv[3] == '1'
os.makedirs(metrics_dir, exist_ok=True)

root = os.getcwd()
src = os.path.join(root, 'src')
sys.path.insert(0, src)

# ---- seed injection (single call) -------------------------------------------------
_orig_randint = random.randint
def _seeded_randint(a, b):
    random.randint = _orig_randint
    return seed
random.randint = _seeded_randint

_t0 = time.time()

def _write_process_stats():
    with open(os.path.join(metrics_dir, 'process.json'), 'w') as f:
        json.dump({'peak_rss_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   'elapsed_s_in_process': time.time() - _t0,
                   'seed_injected': seed}, f)
atexit.register(_write_process_stats)


def _pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    lo = int(k); hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _stats(values):
    if not values:
        return {'n': 0, 'mean': None, 'median': None, 'p95': None, 'max': None}
    return {'n': len(values), 'mean': sum(values) / len(values), 'median': _pct(values, 50),
            'p95': _pct(values, 95), 'max': max(values)}


if instrument:
    from simulation.Simulation import Simulation
    from cluster.Cluster import Cluster
    from datalogger.DataLogger import DataLogger
    from jobs.Jobs import Job
    from cluster.WorkerNode import WorkerNode

    class Collector:
        def __init__(self):
            self.job_hash = hashlib.sha256()
            self.jobs_created = 0
            self.true_cpu_core_s = 0.0     # duration measured with total_seconds() BEFORE the .seconds rewrite
            self.jobs_over_24h = 0
            self.waits_h = []          # start - submit (includes temporal deferral), hours
            self.turnaround_h = []     # end - submit for finished jobs, hours
            self.route = {}            # "origin->destination" -> jobs started
            self.site = {}             # per-site step accounting
            self.series = {}           # step datetime -> aggregated values
            self.energy_calls = {}
            self.last_energy = {}

    STATE = {'current': None, 'index': 0}

    _orig_job_init = Job.__init__
    def job_init(self, name, duration, memory_req=1, cores_req=1, origin_site=None):
        _orig_job_init(self, name, duration, memory_req, cores_req, origin_site)
        c = STATE['current']
        if c is not None:
            c.jobs_created += 1
            c.job_hash.update(f'{name}|{duration!r}|{memory_req}|{cores_req}|{origin_site};'.encode())
    Job.__init__ = job_init

    _orig_sim_init = Simulation.__init__
    def sim_init(self, config, cluster_configs):
        STATE['current'] = Collector()
        self._xp_collector = STATE['current']
        _orig_sim_init(self, config, cluster_configs)
    Simulation.__init__ = sim_init

    _orig_start = DataLogger.job_start
    def job_start(self, job, worker_node):
        _orig_start(self, job, worker_node)
        c = STATE['current']
        if job.submit_time is not None and job.start_time is not None:
            c.waits_h.append((job.start_time - job.submit_time).total_seconds() / 3600)
        key = f'{job.origin_site}->{self._site_id}'
        c.route[key] = c.route.get(key, 0) + 1
    DataLogger.job_start = job_start

    _orig_wn_update = WorkerNode.update
    def wn_update(self):
        now = self._simulation_time.get_current_datetime()
        for job in self._jobs:
            if job.end_time <= now:
                job._xp_true_end = job.end_time          # read-only snapshot before WorkerNode.update rewrites it
        _orig_wn_update(self)
    WorkerNode.update = wn_update

    _orig_finish = DataLogger.job_finish
    def job_finish(self, job, worker_node):
        _orig_finish(self, job, worker_node)
        c = STATE['current']
        true_end = getattr(job, '_xp_true_end', job.end_time)
        true_s = (true_end - job.start_time).total_seconds()
        c.true_cpu_core_s += true_s * job.cores_req
        if true_s > 86400:
            c.jobs_over_24h += 1
        if job.submit_time is not None:
            c.turnaround_h.append((true_end - job.submit_time).total_seconds() / 3600)
    DataLogger.job_finish = job_finish

    _orig_energy = DataLogger.energy_and_carbon_consumed
    def energy(self, e_kwh, ci):
        _orig_energy(self, e_kwh, ci)
        c = STATE['current']
        c.energy_calls[self._site_id] = c.energy_calls.get(self._site_id, 0) + 1
        c.last_energy[self._site_id] = (e_kwh, ci)
    DataLogger.energy_and_carbon_consumed = energy

    _orig_cluster_update = Cluster.update
    def cluster_update(self):
        c = STATE['current']
        sid = self.site_id
        before = c.energy_calls.get(sid, 0)
        _orig_cluster_update(self)
        logged = c.energy_calls.get(sid, 0) > before
        dt = self._simulation_time.get_timestep()
        busy = sum(wn.busy_cores for wn in self._worker_nodes)
        ref_work_core_s = sum(wn.busy_cores / wn._fixed_duration_multiplier for wn in self._worker_nodes) * dt
        row = self._get_carbon_data_row()
        try:
            ci_actual = float(row[2]); ci_forecast = float(row[1])
        except (ValueError, IndexError):
            ci_actual = ci_forecast = float('nan')
        s = c.site.setdefault(sid, {'steps': 0, 'logged_steps': 0, 'unlogged_steps': 0,
                                    'unlogged_idle_kwh': 0.0, 'unlogged_idle_g': 0.0,
                                    'logged_kwh': 0.0, 'logged_g': 0.0,
                                    'busy_core_s': 0.0, 'ref_work_core_s': 0.0,
                                    'total_cores': self.get_number_of_cores(),
                                    'idle_power_kw': sum(wn.powerusage_idle * 3600 for wn in self._worker_nodes) / 1000})
        s['steps'] += 1
        s['busy_core_s'] += busy * dt
        s['ref_work_core_s'] += ref_work_core_s
        if logged:
            e, ci_used = c.last_energy[sid]
            s['logged_steps'] += 1; s['logged_kwh'] += e; s['logged_g'] += e * ci_used
            e_step, g_step = e, e * ci_used
        else:
            # What the model's own power function returns for the (idle) nodes at this step.
            idle_kwh = sum(wn.timestep_power_dissipated() for wn in self._worker_nodes)
            s['unlogged_steps'] += 1; s['unlogged_idle_kwh'] += idle_kwh; s['unlogged_idle_g'] += idle_kwh * ci_actual
            e_step, g_step = 0.0, 0.0
        t = self._simulation_time.get_current_datetime().isoformat()
        p = c.series.setdefault(t, {'kwh': 0.0, 'g': 0.0, 'busy_cores': 0, 'queued': 0, 'ci': {}})
        p['kwh'] += e_step; p['g'] += g_step; p['busy_cores'] += busy
        p['queued'] += len(self._queued_jobs)
        p['ci'][sid] = ci_actual
    Cluster.update = cluster_update

    _orig_sim_start = Simulation.start
    def sim_start(self):
        t = time.time()
        _orig_sim_start(self)
        self._xp_elapsed = time.time() - t
    Simulation.start = sim_start

    _orig_finalise = Simulation._finalise
    def finalise(self, reason):
        c = self._xp_collector
        # Cut-off state, read BEFORE finalise (which does not alter job state anyway).
        sites = {}
        for site in self._site_list:
            sh = site.job_scheduler._temporal_shifter
            running = sum(len(wn._jobs) for wn in site.cluster._worker_nodes)
            sites[site.site_id] = {
                'generated_at_origin': site.job_scheduler._total_jobs_generated,
                'started_here': site.data_logger._jobs_started,
                'finished_here': site.data_logger._jobs_finished,
                'running_here': running,
                'cluster_queued_here': len(site.cluster._queued_jobs),
                'held_by_temporal_here': sh.held_jobs,
                'deferral_released': getattr(sh, '_released_jobs', 0),
                'release_counts': dict(getattr(sh, '_release_counts', {})),
                'held_for_capacity_events': getattr(sh, '_held_for_capacity', 0),
                'ci_rows_loaded': len(site.cluster._carbondata),
                'cpu_core_s_finished': site.data_logger._cumulative_cpu_time,
                'energy_kwh_logged': site.data_logger._total_energy_consumed,
                'carbon_g_logged': site.data_logger._total_carbon_consumed,
                'temporal_policy': type(sh).__name__,
                **c.site.get(site.site_id, {}),
            }
        tot = lambda k: sum(v[k] for v in sites.values())
        generated = tot('generated_at_origin')
        accounted = tot('finished_here') + tot('running_here') + tot('cluster_queued_here') + tot('held_by_temporal_here') + len(self._global_scheduler._global_queue)
        _orig_finalise(self, reason)
        out = {
            'role': 'baseline' if os.path.basename(os.path.normpath(self._run_dir)) == 'baseline' else 'policy',
            'order_index': STATE['index'],
            'run_dir': self._run_dir,
            'routing_policy': self.routing_policy_name,
            'routing_config': self._config['Simulation'].get('routing', {}),
            'sim_seconds': self._simtottime.total_seconds(),
            'timestep_s': self._simulation_time.get_timestep(),
            'wall_s': getattr(self, '_xp_elapsed', None),
            'workload_sha256': c.job_hash.hexdigest(),
            'jobs_created_objects': c.jobs_created,
            'totals': {
                'generated': generated,
                'started': tot('started_here'),
                'finished': tot('finished_here'),
                'running_at_cutoff': tot('running_here'),
                'cluster_queued_at_cutoff': tot('cluster_queued_here'),
                'held_temporal_at_cutoff': tot('held_by_temporal_here'),
                'global_queue_at_cutoff': len(self._global_scheduler._global_queue),
                'conservation_ok': generated == accounted,
                'deferred_ever': tot('deferral_released') + tot('held_by_temporal_here'),
                'energy_kwh_logged': tot('energy_kwh_logged'),
                'carbon_g_logged': tot('carbon_g_logged'),
                'unlogged_idle_kwh': tot('unlogged_idle_kwh'),
                'unlogged_idle_g': tot('unlogged_idle_g'),
                'cpu_core_s_finished': tot('cpu_core_s_finished'),
                'cpu_core_s_finished_true': c.true_cpu_core_s,
                'finished_jobs_over_24h': c.jobs_over_24h,
                'busy_core_s': tot('busy_core_s'),
                'ref_work_core_s': tot('ref_work_core_s'),
            },
            'sites': sites,
            'routes': c.route,
            'wait_h': _stats(c.waits_h),
            'turnaround_h': _stats(c.turnaround_h),
            'wait_hist_h': _hist(c.waits_h),
            'series': c.series,
        }
        name = f"sim_{STATE['index']}_{out['role']}.json"
        with open(os.path.join(metrics_dir, name), 'w') as f:
            json.dump(out, f, default=str)
        STATE['index'] += 1
    Simulation._finalise = finalise


def _hist(values):
    edges = [0, 0.1667, 0.5, 1, 2, 4, 6, 8, 12, 16, 20, 24, 30, 48, 1e9]
    counts = [0] * (len(edges) - 1)
    for v in values:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
    return {'edges_h': edges, 'counts': counts}


code = 0
try:
    runpy.run_path(os.path.join(src, 'Main.py'), run_name='__main__')
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
sys.exit(code)

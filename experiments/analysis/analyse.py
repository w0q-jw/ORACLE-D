"""Phase 6: fair carbon-savings analysis from instrumented paired runs.

Writes:
  experiments/results_summary.csv      one row per paired run (baseline vs policy), units in column names
  experiments/results_by_scenario.csv  mean / sd / 95% CI across seeds per scenario
Definitions (all from instrumentation; see README):
  *_logged            exactly what ORACLE-D's DataLogger accumulates (what the model reports)
  *_corrected         logged + idle energy of steps where a site had no running/queued jobs and the model
                      skipped logging (B10). Idle energy is the model's own WorkerNode power at 0 busy cores.
  ref_work_core_h     CPU work delivered within the horizon, normalised to the 1939.6-HEPScore reference node
                      (busy cores x dt / node duration multiplier), counts partially-executed jobs.
  g_per_ref_core_h    carbon / ref_work_core_h  (work-normalised intensity of the delivered computation).
"""
import csv
import json
import math
import os
import re
import statistics
import sys

XP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(XP)
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def load(run_id):
    d = os.path.join(XP, 'runs', run_id, 'metrics')
    out = {}
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.startswith('sim_'):
                m = json.load(open(os.path.join(d, fn)))
                out[m['role']] = m
    return out


def model_reported_saving(output_dir):
    p = os.path.join(REPO, output_dir, 'carbon_savings_summary.txt')
    if not os.path.exists(p):
        return None
    m = re.search(r'Carbon saved percentage\s*:\s*(-?[0-9.]+)', open(p).read())
    return float(m.group(1)) if m else None


def pct_saving(base, pol):
    return 100.0 * (base - pol) / base if base else float('nan')


def pair_row(man):
    m = load(man['run_id'])
    if 'baseline' not in m or 'policy' not in m:
        return None
    B, P = m['baseline'], m['policy']
    tb, tp = B['totals'], P['totals']
    steps = next(iter(P['sites'].values()))['steps']
    dt = P['timestep_s']

    def side(M, t):
        cores = sum(s['total_cores'] for s in M['sites'].values())
        started_over_1step = sum(M['wait_hist_h']['counts'][1:])
        moved = sum(v for k, v in M['routes'].items() if k.split('->')[0] != k.split('->')[1])
        return {
            'carbon_kg_logged': t['carbon_g_logged'] / 1e3,
            'carbon_kg_corrected': (t['carbon_g_logged'] + t['unlogged_idle_g']) / 1e3,
            'energy_kwh_logged': t['energy_kwh_logged'],
            'energy_kwh_corrected': t['energy_kwh_logged'] + t['unlogged_idle_kwh'],
            'unlogged_idle_kwh': t['unlogged_idle_kwh'],
            'generated': t['generated'], 'finished': t['finished'], 'running_at_cutoff': t['running_at_cutoff'],
            'cluster_queued_at_cutoff': t['cluster_queued_at_cutoff'], 'held_temporal_at_cutoff': t['held_temporal_at_cutoff'],
            'global_queue_at_cutoff': t['global_queue_at_cutoff'], 'unfinished_at_cutoff': t['generated'] - t['finished'],
            'passed_through_temporal_queue': t['deferred_ever'], 'started_after_wait_gt_10min': started_over_1step,
            'jobs_moved_off_origin': moved, 'conservation_ok': t['conservation_ok'],
            'wait_mean_h': M['wait_h']['mean'], 'wait_median_h': M['wait_h']['median'], 'wait_p95_h': M['wait_h']['p95'],
            'turnaround_mean_h': M['turnaround_h']['mean'], 'turnaround_median_h': M['turnaround_h']['median'],
            'turnaround_p95_h': M['turnaround_h']['p95'],
            'cpu_core_h_finished_recorded': t['cpu_core_s_finished'] / 3600,
            'cpu_core_h_finished_true': t.get('cpu_core_s_finished_true', float('nan')) / 3600,
            'busy_core_h': t['busy_core_s'] / 3600, 'ref_work_core_h': t['ref_work_core_s'] / 3600,
            'occupancy_mean_frac': t['busy_core_s'] / (cores * steps * dt) if cores else float('nan'),
            'g_per_ref_core_h_logged': t['carbon_g_logged'] / (t['ref_work_core_s'] / 3600) if t['ref_work_core_s'] else float('nan'),
            'g_per_ref_core_h_corrected': (t['carbon_g_logged'] + t['unlogged_idle_g']) / (t['ref_work_core_s'] / 3600) if t['ref_work_core_s'] else float('nan'),
            'wall_s': M['wall_s'],
        }

    b, p = side(B, tb), side(P, tp)
    row = {k: man[k] for k in ('run_id', 'scenario_id', 'stage', 'seed', 'routing_policy', 'k', 'origin_bias',
                               'temporal_policy', 'sites', 'start', 'length_s', 'ci_source')}
    row['n_sites'] = len(man['sites'].split('|'))
    row['load_initial_per_site'] = man['initial_jobs_per_site']
    row['load_incoming_per_10min_per_site'] = man['incoming_jobs_per_step_per_site']
    row['workload_identical'] = B['workload_sha256'] == P['workload_sha256']
    row['saving_pct_logged'] = pct_saving(b['carbon_kg_logged'], p['carbon_kg_logged'])
    row['saving_pct_model_reported'] = model_reported_saving(man['output_dir'])
    row['saving_pct_corrected_B10'] = pct_saving(b['carbon_kg_corrected'], p['carbon_kg_corrected'])
    row['energy_saving_pct_logged'] = pct_saving(b['energy_kwh_logged'], p['energy_kwh_logged'])
    row['energy_saving_pct_corrected_B10'] = pct_saving(b['energy_kwh_corrected'], p['energy_kwh_corrected'])
    row['finished_pct_of_baseline_finished'] = 100.0 * p['finished'] / b['finished'] if b['finished'] else float('nan')
    row['finished_pct_of_generated_policy'] = 100.0 * p['finished'] / p['generated'] if p['generated'] else float('nan')
    row['ref_work_pct_of_baseline'] = 100.0 * p['ref_work_core_h'] / b['ref_work_core_h'] if b['ref_work_core_h'] else float('nan')
    row['work_norm_saving_pct_logged'] = pct_saving(b['g_per_ref_core_h_logged'], p['g_per_ref_core_h_logged'])
    row['work_norm_saving_pct_corrected_B10'] = pct_saving(b['g_per_ref_core_h_corrected'], p['g_per_ref_core_h_corrected'])
    for k, v in b.items():
        row[f'base_{k}'] = v
    for k, v in p.items():
        row[f'pol_{k}'] = v
    return row


def agg(rows, key):
    vals = [r[key] for r in rows if isinstance(r[key], (int, float)) and not (isinstance(r[key], float) and math.isnan(r[key]))]
    n = len(vals)
    if n == 0:
        return {'n': 0, 'mean': '', 'sd': '', 'ci95_lo': '', 'ci95_hi': ''}
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if n > 1 else float('nan')
    half = T95.get(n - 1, 1.96) * sd / math.sqrt(n) if n > 1 else float('nan')
    return {'n': n, 'mean': mean, 'sd': sd, 'ci95_lo': mean - half, 'ci95_hi': mean + half}


AGG_KEYS = ['saving_pct_logged', 'saving_pct_corrected_B10', 'energy_saving_pct_logged',
            'finished_pct_of_baseline_finished', 'ref_work_pct_of_baseline', 'work_norm_saving_pct_logged',
            'work_norm_saving_pct_corrected_B10', 'pol_wait_mean_h', 'pol_wait_p95_h', 'pol_turnaround_mean_h',
            'pol_held_temporal_at_cutoff', 'pol_cluster_queued_at_cutoff', 'pol_started_after_wait_gt_10min',
            'pol_jobs_moved_off_origin', 'pol_unlogged_idle_kwh', 'base_carbon_kg_logged', 'pol_carbon_kg_logged',
            'base_energy_kwh_logged', 'pol_energy_kwh_logged', 'pol_occupancy_mean_frac', 'pol_wall_s']


def main():
    man = list(csv.DictReader(open(os.path.join(XP, 'run_manifest.csv'))))
    rows, skipped = [], []
    for r in man:
        if r['exit_code'] != '0' or r['stage'] not in ('P3', 'P4A', 'P4B', 'P4H'):
            continue
        row = pair_row(r)
        (rows.append(row) if row else skipped.append(r['run_id']))
    fields = list(rows[0].keys())
    with open(os.path.join(XP, 'results_summary.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})
    by = {}
    for r in rows:
        by.setdefault(r['scenario_id'], []).append(r)
    out = []
    for sid, rs in by.items():
        o = {'scenario_id': sid, 'stage': rs[0]['stage'], 'n_seeds': len(rs), 'seeds': '|'.join(sorted({str(r['seed']) for r in rs})),
             'run_ids': '|'.join(r['run_id'] for r in rs), 'all_workloads_identical': all(r['workload_identical'] for r in rs)}
        for k in AGG_KEYS:
            a = agg(rs, k)
            for s in ('mean', 'sd', 'ci95_lo', 'ci95_hi'):
                o[f'{k}__{s}'] = round(a[s], 6) if isinstance(a[s], float) else a[s]
        out.append(o)
    with open(os.path.join(XP, 'results_by_scenario.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f'{len(rows)} paired runs summarised; {len(out)} scenarios; skipped (no metrics): {skipped}')


if __name__ == '__main__':
    main()

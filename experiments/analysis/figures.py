"""Phase 7 figures. Every figure carries units, scenario/run provenance and an OBSERVED vs SYNTHETIC label.

OBSERVED  = output of ORACLE-D simulations (commit 8ceee65) driven by repository regional CI data.
            These are model outputs, not real-world measurements.
SYNTHETIC = simulations driven by the fictional-2030 CI fixtures in validation_tests/fixtures (illustrative).
"""
import csv
import json
import os
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

XP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(XP)
FIG = os.path.join(XP, 'figures')
COMMIT = '8ceee65'
os.makedirs(FIG, exist_ok=True)

ROWS = list(csv.DictReader(open(os.path.join(XP, 'results_summary.csv'))))
SCEN = {r['scenario_id']: r for r in csv.DictReader(open(os.path.join(XP, 'results_by_scenario.csv')))}
CAPTIONS = []

POL_ORDER = ['NULL', 'CA_k0', 'CA_k1.3', 'CA_k2', 'OCA_k0_OB0.9', 'OCA_k1.3_OB0.9', 'OCA_k2_OB0.9',
             'OCA_k1.3_OB1.0', 'OCA_k1.3_OB0.8', 'SQ', 'OCA_ref+SQ']


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float('nan')


def stamp(fig, text, kind='OBSERVED'):
    colour = '#1f4e79' if kind == 'OBSERVED' else '#9c2c2c'
    fig.text(0.005, 0.005, f'[{kind}] ORACLE-D commit {COMMIT}. {text}', fontsize=6.5, color=colour, ha='left', va='bottom', wrap=True)


def save(fig, name, caption):
    fig.savefig(os.path.join(FIG, name), dpi=150)
    plt.close(fig)
    CAPTIONS.append((name, caption))


def sid(pol, load='med', n=3, w='WIN'):
    return f'B:{pol}:{load}:{n}site:{w}'


def mean_ci(s, key):
    r = SCEN.get(s)
    if not r:
        return float('nan'), float('nan')
    m, lo, hi = f(r[f'{key}__mean']), f(r[f'{key}__ci95_lo']), f(r[f'{key}__ci95_hi'])
    return m, (hi - lo) / 2 if hi == hi else 0.0


# ---------------------------------------------------------------- F1 CI over time
def fig1():
    regions = {'DESYScot (South Scotland)': 'south_scotland', 'UoM (North West England)': 'north_west_england',
               'RAL (Southern England)': 'southern_england', 'QMUL (London)': 'london', 'West Midlands': 'west_midlands'}
    windows = {'Winter window 2026-01-05 16:00 + 7 d': datetime(2026, 1, 5, 16), 'Summer window 2026-06-15 00:00 + 7 d': datetime(2026, 6, 15)}
    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    for ax, (title, start) in zip(axes[:2], windows.items()):
        end = start + timedelta(days=7)
        for label, fn in regions.items():
            xs, ys = [], []
            for line in open(os.path.join(REPO, 'data', 'carbon_intensity', f'{fn}_intensity.csv')).read().splitlines()[1:]:
                p = line.split(',')
                t = datetime.strptime(p[0], '%Y-%m-%dT%H:%M:%S')
                if start <= t <= end and p[2] != '':
                    xs.append(t); ys.append(float(p[2]))
            ax.plot(xs, ys, lw=1, label=label)
        ax.set_title(title + '  [OBSERVED input data: repository regional CSVs; forecast column == actual column]', fontsize=9)
        ax.set_ylabel('Carbon intensity (gCO$_2$e/kWh)')
        ax.legend(fontsize=7, ncol=3)
        ax.grid(alpha=.3)
    ax = axes[2]
    fixdir = os.path.join(XP, 'validation_tests', 'fixtures', 'ci')
    for pat in ['flat_equal', 'rising', 'falling', 'step']:
        xs, ys = [], []
        for line in open(os.path.join(fixdir, f'{pat}_Scot.csv')).read().splitlines()[1:]:
            p = line.split(',')
            t = datetime.strptime(p[0], '%Y-%m-%dT%H:%M:%S')
            if datetime(2030, 1, 1) <= t <= datetime(2030, 1, 8):
                xs.append(t); ys.append(float(p[2]))
        ax.plot(xs, ys, lw=1.4, label=f'{pat} (all sites)')
    ax.axhline(50, ls=':', c='g', lw=1, label='differing: Scot 50 / UoM 200 / RAL 400')
    ax.axhline(400, ls=':', c='r', lw=1)
    ax.set_title('SYNTHETIC fixtures (fictional 2030 dates; illustrative mechanism tests only)', fontsize=9, color='#9c2c2c')
    ax.set_ylabel('gCO$_2$e/kWh'); ax.legend(fontsize=7, ncol=3); ax.grid(alpha=.3)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp(fig, 'Panels 1-2: data/carbon_intensity/*_intensity.csv (sha256 in env/inputs_sha256.txt). Panel 3: validation_tests/fixtures/make_fixtures.py.', 'OBSERVED')
    save(fig, 'F1_carbon_intensity_by_site.png',
         'Carbon intensity (gCO2e/kWh, half-hourly "actual" column) for each regional site over the two 7-day study windows, and the synthetic fixture patterns used for mechanism tests. Regional forecast and actual columns are identical in every row, so policies effectively have perfect foresight.')


# ---------------------------------------------------------------- F2 baseline vs policy carbon/energy
def fig2():
    pols = [p for p in POL_ORDER if sid(p) in SCEN]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for col, w in enumerate(['WIN', 'SUM']):
        for row, (key_b, key_p, unit) in enumerate([('base_carbon_kg_logged', 'pol_carbon_kg_logged', 'Total emissions (kgCO$_2$e)'),
                                                    ('base_energy_kwh_logged', 'pol_energy_kwh_logged', 'Total energy (kWh)')]):
            ax = axes[row, col]
            x = np.arange(len(pols))
            bm = [mean_ci(sid(p, w=w), key_b) for p in pols]
            pm = [mean_ci(sid(p, w=w), key_p) for p in pols]
            ax.bar(x - .2, [m for m, _ in bm], .4, yerr=[e for _, e in bm], label='baseline (origin_site + submit_immediately)', color='#999')
            ax.bar(x + .2, [m for m, _ in pm], .4, yerr=[e for _, e in pm], label='policy', color='#1f77b4')
            ax.set_xticks(x); ax.set_xticklabels(pols, rotation=35, ha='right', fontsize=7)
            ax.set_ylabel(unit); ax.set_title(f'{"Winter" if w == "WIN" else "Summer"} window, 3 sites, medium load (mean ± 95% CI, n=5 seeds)', fontsize=8.5)
            lo = min([m for m, _ in bm + pm if m == m] or [0]) * 0.97
            ax.set_ylim(bottom=lo); ax.grid(axis='y', alpha=.3)
            if row == 0 and col == 0:
                ax.legend(fontsize=7)
    fig.suptitle('Baseline vs policy: emissions and energy AS LOGGED BY THE MODEL (fixed 7-day horizon; y-axis truncated)', fontsize=10)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    stamp(fig, 'Scenarios B:<policy>:med:3site:<WIN|SUM>; seeds 101,202,303,404,505; see results_by_scenario.csv for run ids.')
    save(fig, 'F2_baseline_vs_policy_emissions_energy.png',
         'Mean total emissions (kgCO2e) and energy (kWh) for baseline and policy runs as accumulated by ORACLE-D DataLogger. Bars share workload (identical seeds). Y-axes are truncated to make differences visible; differences are small relative to totals.')


# ---------------------------------------------------------------- F3 savings vs completed work / backlog
def fig3():
    pols = [p for p in POL_ORDER if sid(p) in SCEN]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    ax = axes[0]
    x = np.arange(len(pols)); wdt = 0.2
    for i, (key, lab) in enumerate([('saving_pct_logged', 'carbon saving, as logged'),
                                    ('saving_pct_corrected_B10', 'carbon saving, idle-corrected (B10)'),
                                    ('work_norm_saving_pct_logged', 'saving in g per reference core-hour delivered'),
                                    ('ref_work_pct_of_baseline', 'work delivered, % of baseline − 100')]):
        vals = [mean_ci(sid(p), key) for p in pols]
        ms = [(m - 100 if key == 'ref_work_pct_of_baseline' else m) for m, _ in vals]
        ax.bar(x + (i - 1.5) * wdt, ms, wdt, yerr=[e for _, e in vals], label=lab)
    ax.axhline(0, c='k', lw=.8)
    ax.set_xticks(x); ax.set_xticklabels(pols, rotation=35, ha='right', fontsize=7)
    ax.set_ylabel('Percent (%)'); ax.legend(fontsize=7); ax.grid(axis='y', alpha=.3)
    ax.set_title('Winter, 3 sites, medium load: savings vs work actually delivered (mean ± 95% CI, n=5)', fontsize=8.5)
    ax = axes[1]
    comp = [('pol_held_temporal_at_cutoff', 'held by SustainableQueue'), ('pol_cluster_queued_at_cutoff', 'queued at cluster')]
    bottom = np.zeros(len(pols))
    for key, lab in comp:
        v = np.array([mean_ci(sid(p), key)[0] for p in pols])
        v = np.nan_to_num(v)
        ax.bar(x, v, .6, bottom=bottom, label=lab); bottom += v
    ax.set_xticks(x); ax.set_xticklabels(pols, rotation=35, ha='right', fontsize=7)
    ax.set_yscale('symlog'); ax.set_ylabel('Jobs not started at cut-off (count, symlog)')
    ax2 = ax.twinx()
    ax2.plot(x, [mean_ci(sid(p), 'finished_pct_of_baseline_finished')[0] for p in pols], 'ko-', label='jobs finished, % of baseline finished')
    ax2.set_ylabel('Jobs finished (% of baseline finished)')
    ax.legend(fontsize=7, loc='upper left'); ax2.legend(fontsize=7, loc='upper right')
    ax.set_title('Backlog at cut-off and completed jobs (policy runs)', fontsize=8.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp(fig, 'Scenarios B:<policy>:med:3site:WIN; seeds 101-505. Work-normalised metric = gCO2e / reference(1939.6 HS) core-hour executed within horizon.')
    save(fig, 'F3_savings_vs_completed_work_and_backlog.png',
         'Left: carbon saving as logged by the model, after adding unlogged idle energy (B10), and normalised by computation delivered within the horizon; plus work delivered relative to baseline. Right: jobs left unstarted at the cut-off and jobs finished as a percentage of baseline finished. A saving that coincides with less delivered work is a deferral/throughput effect, not an efficiency gain.')


# ---------------------------------------------------------------- F4 wait distributions
def fig4():
    pols = [p for p in ['NULL', 'OCA_k1.3_OB0.9', 'SQ', 'OCA_ref+SQ', 'CA_k0', 'CA_k1.3'] if sid(p) in SCEN]
    fig, ax = plt.subplots(figsize=(11, 5))
    edges = None
    for i, p in enumerate(pols):
        counts = None
        for r in [r for r in ROWS if r['scenario_id'] == sid(p)]:
            m = json.load(open(os.path.join(XP, 'runs', r['run_id'], 'metrics', 'sim_1_policy.json')))
            c = np.array(m['wait_hist_h']['counts'], float); edges = m['wait_hist_h']['edges_h']
            counts = c if counts is None else counts + c
        frac = counts / counts.sum() * 100
        ax.bar(np.arange(len(frac)) + (i - len(pols) / 2) * 0.13, np.maximum(frac, 1e-4), 0.13, label=p)
    labels = [f'{edges[i]:g}–{edges[i + 1]:g}' if edges[i + 1] < 1e8 else f'≥{edges[i]:g}' for i in range(len(edges) - 1)]
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=35, fontsize=7)
    ax.set_yscale('log'); ax.set_ylim(1e-3, 150)
    ax.set_xlabel('Wait from generation to start (hours; includes temporal deferral and cluster queueing)')
    ax.set_ylabel('Share of started jobs (%, log)')
    ax.set_title('Wait-time distribution, winter window, 3 sites, medium load (pooled over 5 seeds)', fontsize=9)
    ax.legend(fontsize=7); ax.grid(axis='y', alpha=.3)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp(fig, 'Scenarios B:<policy>:med:3site:WIN, seeds 101-505 pooled. First bin [0, 10 min) contains the one-timestep SustainableQueue hand-off.')
    save(fig, 'F4_wait_time_distribution.png', 'Distribution of wait from job generation to start for started jobs, pooled across seeds. Jobs never started by the cut-off are not included (see F3).')


# ---------------------------------------------------------------- F5 routing heatmaps
def fig5():
    pols = [p for p in ['OCA_k1.3_OB0.9', 'OCA_k0_OB0.9', 'CA_k0', 'CA_k1.3'] if sid(p) in SCEN]
    if not pols:
        return
    fig, axes = plt.subplots(1, len(pols), figsize=(4.2 * len(pols), 4))
    axes = np.atleast_1d(axes)
    sites = ['DESYScot', 'UoM', 'RAL']
    for ax, p in zip(axes, pols):
        rid = [r['run_id'] for r in ROWS if r['scenario_id'] == sid(p) and r['seed'] == '101']
        if not rid:
            continue
        routes = json.load(open(os.path.join(XP, 'runs', rid[0], 'metrics', 'sim_1_policy.json')))['routes']
        M = np.array([[routes.get(f'{o}->{d}', 0) for d in sites] for o in sites], float)
        share = M / M.sum(axis=1, keepdims=True) * 100
        ax.imshow(share, cmap='Blues', vmin=0, vmax=100)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f'{share[i, j]:.1f}%\n({int(M[i, j]):,})', ha='center', va='center', fontsize=7,
                        color='white' if share[i, j] > 60 else 'black')
        ax.set_xticks(range(3)); ax.set_xticklabels(sites, fontsize=7); ax.set_yticks(range(3)); ax.set_yticklabels(sites, fontsize=7)
        ax.set_xlabel('Destination (site where job started)'); ax.set_ylabel('Origin site')
        ax.set_title(f'{p}\nrun {rid[0]}', fontsize=7.5)
    fig.suptitle('Job routing: share of started jobs by origin → destination (winter, medium load, seed 101)', fontsize=9.5)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    stamp(fig, 'Counts are jobs STARTED by cut-off (instrumented DataLogger.job_start). Initial jobs are forced to origin (force_origin=True).')
    save(fig, 'F5_routing_origin_destination.png', 'Origin-to-destination routing matrices (row-normalised %, counts in brackets) for spatial policies. capacity_aware_CI concentrates nearly all routed jobs on the lowest-CI site (herding).')


# ---------------------------------------------------------------- F6 sensitivity
def fig6():
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    def plot(ax, xs, sids, label, key, style):
        vals = [mean_ci(s, key) for s in sids]
        ok = [(x, m, e) for x, (m, e) in zip(xs, vals) if m == m]
        if ok:
            ax.errorbar([o[0] for o in ok], [o[1] for o in ok], yerr=[o[2] for o in ok], fmt=style, capsize=3, label=label)
    for w, mk in (('WIN', 'o-'), ('SUM', 's--')):
        for pol in ('OCA_k1.3_OB0.9', 'SQ'):
            plot(axes[0], [1, 2, 3], [sid(pol, l, 3, w) for l in ('low', 'med', 'high')], f'{pol} {w}', 'saving_pct_logged', mk)
        plot(axes[1], [0, 1.3, 2], [sid(p, w=w) for p in ('OCA_k0_OB0.9', 'OCA_k1.3_OB0.9', 'OCA_k2_OB0.9')], f'origin_capacity_aware OB=0.9 {w}', 'saving_pct_logged', mk)
        plot(axes[1], [0, 1.3, 2], [sid(p, w=w) for p in ('CA_k0', 'CA_k1.3', 'CA_k2')], f'capacity_aware {w}', 'saving_pct_logged', mk.replace('o', '^'))
        plot(axes[2], [0.8, 0.9, 1.0], [sid(p, w=w) for p in ('OCA_k1.3_OB0.8', 'OCA_k1.3_OB0.9', 'OCA_k1.3_OB1.0')], f'origin_capacity_aware k=1.3 {w}', 'saving_pct_logged', mk)
    axes[0].set_xticks([1, 2, 3]); axes[0].set_xticklabels(['low\n875 + 40/10min', 'medium\n1750 + 80/10min', 'high\n3500 + 160/10min'], fontsize=7)
    axes[0].set_xlabel('Offered load per site (initial + arrivals)'); axes[1].set_xlabel('Occupancy exponent k'); axes[2].set_xlabel('Origin bias OB')
    for ax, t in zip(axes, ['Load', 'k', 'Origin bias']):
        ax.set_ylabel('Carbon saving as logged (%)'); ax.axhline(0, c='k', lw=.7); ax.grid(alpha=.3); ax.legend(fontsize=6.5)
        ax.set_title(f'Sensitivity to {t} (mean ± 95% CI, n=5 seeds, 3 sites)', fontsize=8.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp(fig, 'One-factor-at-a-time around reference origin_capacity_aware_CI k=1.3 OB=0.9; scenario ids B:<policy>:<load>:3site:<WIN|SUM>.')
    save(fig, 'F6_sensitivity_load_k_ob.png', 'Sensitivity of the logged carbon saving to offered load, occupancy exponent k and origin bias OB. Each point is a mean over 5 seeds with a t-based 95% CI.')


# ---------------------------------------------------------------- F7 seed variation
def fig7():
    sids = [s for s in [sid(p, w=w) for w in ('WIN', 'SUM') for p in POL_ORDER] if s in SCEN]
    fig, ax = plt.subplots(figsize=(14, 5))
    for i, s in enumerate(sids):
        vals = [f(r['saving_pct_logged']) for r in ROWS if r['scenario_id'] == s]
        ax.scatter([i] * len(vals), vals, s=14, color='#1f77b4' if s.endswith('WIN') else '#ff7f0e')
        m, e = mean_ci(s, 'saving_pct_logged')
        ax.errorbar(i + .25, m, yerr=e, fmt='k_', capsize=3)
    ax.set_xticks(range(len(sids))); ax.set_xticklabels([s.split(':')[1] + ('\nwinter' if s.endswith('WIN') else '\nsummer') for s in sids], rotation=60, fontsize=6.5)
    ax.axhline(0, c='k', lw=.7); ax.grid(axis='y', alpha=.3)
    ax.set_ylabel('Carbon saving as logged (%)')
    ax.set_title('Seed-to-seed variation: each dot is one paired run (seeds 101,202,303,404,505); black bar = mean ± 95% CI', fontsize=9)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp(fig, 'Scenarios B:<policy>:med:3site:<WIN|SUM>. Baseline and policy share the seed (common random numbers) within each pair.')
    save(fig, 'F7_seed_variation.png', 'Per-seed logged carbon savings for each policy and window, showing seed-to-seed spread.')


# ---------------------------------------------------------------- F8 deferral time series
def fig8():
    want = [('SQ', 'B-SQ-med-3s-WIN-s101'), ('OCA_k1.3_OB0.9', 'B-OCA_k1.3_OB0.9-med-3s-WIN-s101')]
    have = [(p, r) for p, r in want if os.path.exists(os.path.join(XP, 'runs', r, 'metrics', 'sim_1_policy.json'))]
    if not have:
        return
    fig, axes = plt.subplots(len(have), 1, figsize=(12, 4 * len(have)), squeeze=False)
    for ax, (p, rid) in zip(axes[:, 0], have):
        B = json.load(open(os.path.join(XP, 'runs', rid, 'metrics', 'sim_0_baseline.json')))['series']
        P = json.load(open(os.path.join(XP, 'runs', rid, 'metrics', 'sim_1_policy.json')))['series']
        ts = sorted(set(B) & set(P))
        t = [datetime.fromisoformat(x) for x in ts]
        cb = np.cumsum([B[x]['g'] for x in ts]) / 1e3
        cp = np.cumsum([P[x]['g'] for x in ts]) / 1e3
        ax.plot(t, cb - cp, c='#2ca02c', label='cumulative carbon saved so far (kgCO$_2$e, baseline − policy)')
        ax.set_ylabel('kgCO$_2$e'); ax.grid(alpha=.3)
        ax2 = ax.twinx()
        ax2.plot(t, [P[x]['busy_cores'] - B[x]['busy_cores'] for x in ts], c='#d62728', lw=.7, alpha=.8, label='busy cores, policy − baseline')
        ax2.set_ylabel('Δ busy cores (count)')
        ax.legend(loc='upper left', fontsize=7); ax2.legend(loc='upper right', fontsize=7)
        ax.set_title(f'{p}: run {rid} (winter, 3 sites, medium load, seed 101)', fontsize=9)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    stamp(fig, 'Per-timestep series from instrumentation (logged energy x CI). Negative Δ busy cores = work postponed relative to baseline.')
    save(fig, 'F8_cumulative_saving_timeseries.png', 'Cumulative carbon saved over the horizon and the difference in busy cores between policy and baseline. For deferral policies, saving accrues while less work is running; it can be partly repaid when deferred work runs later, and work still deferred at the cut-off is never charged.')


# ---------------------------------------------------------------- F9 synthetic mechanism matrix
def fig9():
    rows = [r for r in ROWS if r['stage'] == 'P4A']
    if not rows:
        return
    pats = ['flat_equal', 'differing', 'rising', 'falling', 'step', 'fcmismatch']
    pols = ['CA_k0', 'OCA_k1.3_OB0.9', 'SQ']
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.2))
    for ax, key, title in [(axes[0], 'saving_pct_logged', 'Carbon saving as logged (%)'),
                           (axes[1], 'finished_pct_of_baseline_finished', 'Jobs finished (% of baseline finished)')]:
        M = np.full((len(pols), len(pats)), np.nan)
        for i, p in enumerate(pols):
            for j, c in enumerate(pats):
                v = [f(r[key]) for r in rows if r['scenario_id'] == f'A:{c}:{p}']
                if v:
                    M[i, j] = np.mean(v)
        im = ax.imshow(M, cmap='RdYlGn' if key.startswith('saving') else 'viridis', aspect='auto')
        for i in range(len(pols)):
            for j in range(len(pats)):
                if M[i, j] == M[i, j]:
                    ax.text(j, i, f'{M[i, j]:.2f}', ha='center', va='center', fontsize=8)
        ax.set_xticks(range(len(pats))); ax.set_xticklabels(pats, fontsize=8); ax.set_yticks(range(len(pols))); ax.set_yticklabels(pols, fontsize=8)
        ax.set_title(title + ' — SYNTHETIC CI', fontsize=9, color='#9c2c2c'); fig.colorbar(im, ax=ax, shrink=.8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    stamp(fig, 'Stage A runs A-<pattern>-<policy>-s<seed>, seeds 101 & 202 (mean). fcmismatch: forecast ranks Scot cleanest, actual ranks it dirtiest.', 'SYNTHETIC')
    save(fig, 'F9_synthetic_mechanism_matrix.png', 'Mechanism tests on synthetic CI (illustrative only): logged carbon saving and completed jobs by CI pattern and policy.')


if __name__ == '__main__':
    for fn in (fig1, fig2, fig3, fig4, fig5, fig6, fig7, fig8, fig9):
        try:
            fn()
        except Exception as e:  # keep going; report
            print(f'{fn.__name__} FAILED: {e!r}')
    with open(os.path.join(FIG, 'CAPTIONS.md'), 'w') as fh:
        fh.write('# Figure captions\n\nOBSERVED = ORACLE-D simulation outputs driven by repository regional CI (model outputs, not measurements). '
                 'SYNTHETIC = fictional-2030 fixture CI (illustrative).\n\n')
        for name, cap in CAPTIONS:
            fh.write(f'- **{name}** — {cap}\n')
    print('figures:', [c[0] for c in CAPTIONS])

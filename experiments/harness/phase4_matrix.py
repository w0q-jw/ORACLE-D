"""Phase 4 scenario matrix (one factor at a time). Usage: python phase4_matrix.py A|B|H

Stage A: mechanism checks on SYNTHETIC CI fixtures (fictional 2030 dates), 2 seeds.
Stage B: realistic regional CI, OAT around a reference, 2 windows x 5 seeds (common random numbers).
Stage H: job edge case: large initial backlog.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

SEEDS = [101, 202, 303, 404, 505]
SITES3 = ['Scot', 'UoM', 'RAL']
SITES5 = ['Scot', 'UoM', 'RAL', 'QMUL', 'WestMids']
WINDOWS = {'WIN': '2026-01-05 16:00', 'SUM': '2026-06-15 00:00'}
WEEK = 7 * 86400
LOADS = {'low': {'initial': 875, 'incoming': 40}, 'med': {'initial': 1750, 'incoming': 80}, 'high': {'initial': 3500, 'incoming': 160}}

POLICIES = {   # id -> (routing, k, origin_bias, temporal)
    'NULL':            ('origin_site', None, None, 'submit_immediately'),
    'CA_k0':           ('capacity_aware_CI', 0.0, None, 'submit_immediately'),
    'CA_k1.3':         ('capacity_aware_CI', 1.3, None, 'submit_immediately'),
    'CA_k2':           ('capacity_aware_CI', 2.0, None, 'submit_immediately'),
    'OCA_k0_OB0.9':    ('origin_capacity_aware_CI', 0.0, 0.9, 'submit_immediately'),
    'OCA_k1.3_OB0.9':  ('origin_capacity_aware_CI', 1.3, 0.9, 'submit_immediately'),   # reference spatial policy
    'OCA_k2_OB0.9':    ('origin_capacity_aware_CI', 2.0, 0.9, 'submit_immediately'),
    'OCA_k1.3_OB1.0':  ('origin_capacity_aware_CI', 1.3, 1.0, 'submit_immediately'),
    'OCA_k1.3_OB0.8':  ('origin_capacity_aware_CI', 1.3, 0.8, 'submit_immediately'),
    'SQ':              ('origin_site', None, None, 'sustainable_queue'),
    'OCA_ref+SQ':      ('origin_capacity_aware_CI', 1.3, 0.9, 'sustainable_queue'),
}


def spec(run_id, scenario, stage, policy, seed, start, sites=SITES3, load='med', ci=None, length=WEEK, notes=''):
    routing, k, ob, temporal = POLICIES[policy]
    s = dict(run_id=run_id, scenario_id=scenario, stage=stage, seed=seed, start=start, length_s=length, sites=sites,
             routing=routing, k=k, origin_bias=ob, temporal=temporal, load=LOADS[load] if isinstance(load, str) else load,
             notes=notes or f'policy={policy}; load={load}; sites={len(sites)}')
    if ci:
        folder = os.path.join(H.XP, 'validation_tests', 'fixtures', 'ci')
        s['ci_override'] = {'name': ci, 'folder': folder, 'files': {x: f'{ci}_{x}.csv' for x in sites}}
    return s


def stage_a():
    out = []
    for ci in ['flat_equal', 'differing', 'rising', 'falling', 'step', 'fcmismatch']:
        for pol in ['CA_k0', 'OCA_k1.3_OB0.9', 'SQ']:
            for seed in SEEDS[:2]:
                out.append(spec(f'A-{ci}-{pol}-s{seed}', f'A:{ci}:{pol}', 'P4A', pol, seed, '2030-01-01 00:00', ci=ci))
    return out


def stage_b():
    scen = [(p, 'med', SITES3) for p in POLICIES]
    scen += [(p, l, SITES3) for p in ('OCA_k1.3_OB0.9', 'SQ') for l in ('low', 'high')]
    scen += [(p, 'med', SITES5) for p in ('OCA_k1.3_OB0.9', 'SQ')]
    out = []
    for pol, load, sites in scen:
        for w, start in WINDOWS.items():
            # Documented deviation: capacity_aware_CI herds all jobs onto one site, making each run ~40+ min
            # (O(queue x nodes) per step). It is run with 2 seeds per window; all other scenarios use 5.
            for seed in (SEEDS[:2] if POLICIES[pol][0] == 'capacity_aware_CI' else SEEDS):
                sid = f'B:{pol}:{load}:{len(sites)}site:{w}'
                s = spec(f'B-{pol}-{load}-{len(sites)}s-{w}-s{seed}', sid, 'P4B', pol, seed, start, sites, load)
                s['timeout_s'] = 3600
                out.append(s)
    return out


def stage_h():
    out = []
    for pol in ('OCA_k1.3_OB0.9', 'SQ'):
        for seed in SEEDS[:2]:
            out.append(spec(f'H-backlog-{pol}-s{seed}', f'H:backlog8000:{pol}', 'P4H', pol, seed, WINDOWS['WIN'],
                            load={'initial': 8000, 'incoming': 80}, notes='initial backlog 8000 ATLAS/site'))
    return out


if __name__ == '__main__':
    which = sys.argv[1]
    specs = {'A': stage_a, 'B': stage_b, 'H': stage_h}[which]()
    # Longest-running first (capacity_aware_CI herds every job to one site -> very slow queue scans).
    specs.sort(key=lambda s: 0 if s['routing'] == 'capacity_aware_CI' else 1)
    print(f'stage {which}: {len(specs)} runs', flush=True)
    H.run_batch(specs, workers=int(os.environ.get('XP_WORKERS', 6)))

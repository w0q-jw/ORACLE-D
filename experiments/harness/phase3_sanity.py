"""Phase 3 end-to-end sanity and failure-mode runs through the unmodified Main.py."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

raw_cfg = open(os.path.join(H.REPO, 'configs', 'config.json')).read()
raw_sites = {f'{k}.json': open(os.path.join(H.REPO, 'configs', f'{k}.json')).read() for k in ('Scot', 'UoM', 'RAL')}
base = dict(sites=['Scot', 'UoM', 'RAL'], start='2026-01-05 16:00', length_s=7 * 86400, routing='origin_site',
            temporal='submit_immediately', seed=101, stage='P3')
specs = [
    dict(run_id='P3-05', scenario_id='UNCHANGED_REPO_CONFIG', stage='P3', seed=101, raw_config=raw_cfg, raw_site_files=raw_sites,
         sites=['Scot', 'UoM', 'RAL'], notes='instrumentation v2 (true-duration capture) equivalence vs P3-02'),
    dict(base, run_id='P3-06', scenario_id='EMPTY_SITE', site_overrides={'UoM': {'jobs': {'initial_mix': {}, 'regular_incoming_mix': {}, 'incoming_timestep': 600}}},
         notes='UoM has zero jobs: quantify unlogged idle energy (B10)'),
    dict(base, run_id='P3-07', scenario_id='FAIL_BAD_ROUTING', routing='teleport', length_s=3600, notes='invalid routing policy name'),
    dict(base, run_id='P3-08', scenario_id='FAIL_MISSING_CI', length_s=3600,
         site_overrides={'RAL': {'carbon_intensity': {'folder': 'data/carbon_intensity/', 'filename': 'nonexistent.csv', 'high_CI_threshold': 400}}},
         notes='missing CI file'),
    dict(base, run_id='P3-09', scenario_id='FAIL_START_IN_GAP', start='2024-01-26 12:00', length_s=6 * 3600, notes='start inside 2024-01-25..02-16 regional gap'),
    dict(base, run_id='P3-10', scenario_id='FAIL_BLANK_CI', start='2025-01-12 20:00', length_s=6 * 3600, notes='window covers blank CI rows from 2025-01-12 23:00'),
    dict(base, run_id='P3-11', scenario_id='FAIL_ZERO_JOBS', length_s=3600, load={'initial': 0, 'incoming': 0}, notes='no jobs anywhere -> zero baseline'),
]
H.run_batch(specs, workers=6)

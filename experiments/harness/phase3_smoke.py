"""Phase 3 smoke/sanity runs on the UNCHANGED repository configuration."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H

raw_cfg = open(os.path.join(H.REPO, 'configs', 'config.json')).read()
raw_sites = {f'{k}.json': open(os.path.join(H.REPO, 'configs', f'{k}.json')).read() for k in ('Scot', 'UoM', 'RAL')}
cfg = json.loads(raw_cfg)

def unchanged(run_id, seed, instrument, notes):
    # Byte-identical copy of configs/*.json except output.run_label (needed for unique folder naming is NOT needed: keep unchanged)
    return dict(run_id=run_id, scenario_id='UNCHANGED_REPO_CONFIG', stage='P3', seed=seed, instrument=instrument,
                raw_config=raw_cfg, raw_site_files=raw_sites, sites=['Scot', 'UoM', 'RAL'],
                temporal='submit_immediately (per site file)', notes=notes)

specs = [
    unchanged('P3-01', 101, True, 'unchanged repo config; instrumented'),
    unchanged('P3-02', 101, False, 'unchanged repo config; NOT instrumented (instrumentation-equivalence check vs P3-01)'),
    unchanged('P3-03', 101, True, 'unchanged repo config; replay of P3-01 (determinism check)'),
    dict(run_id='P3-04', scenario_id='SMOKE_NULL', stage='P3', seed=101, sites=['Scot', 'UoM', 'RAL'],
         start='2026-01-05 16:00', length_s=6 * 3600, routing='origin_site', temporal='submit_immediately',
         load={'initial': 50, 'incoming': 5}, notes='reduced smoke: 6 h, 50 initial + 5/10min per site'),
]
H.run_batch(specs, workers=4)

"""Run the non-capacity_aware_CI part of stage B concurrently (same specs as phase4_matrix.stage_b)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H, phase4_matrix as M
specs = [s for s in M.stage_b() if s['routing'] != 'capacity_aware_CI'
         and not os.path.exists(os.path.join(H.XP, 'runs', s['run_id']))]
print(f'fast stage B subset: {len(specs)} runs', flush=True)
H.run_batch(specs, workers=int(os.environ.get('XP_WORKERS', 3)))

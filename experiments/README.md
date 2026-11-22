# ORACLE-D (development @ 8ceee65) — WP3 reproducibility experiments

Everything in this folder is **additive and untracked**. Nothing was committed or pushed, and the `main`
branch was not touched. `configs/`, `data/` and `requirements.txt` are unmodified.

**Exception (requested by the user, 2026-11-05):** explanatory comments were added to the 14 files in `src/`
(129 added lines, 0 removed, every added line is a `#` comment; per-file Python ASTs are identical before
and after, and `src/simulation/Time.py`'s mixed CRLF/LF line endings were preserved). Behaviour is unchanged.
All experiments run against `_pristine/src` (a `git archive` of 8ceee65), so they are unaffected either way.
Line numbers quoted in the report refer to commit 8ceee65.

## 1. What was tested

| Item | Value |
|---|---|
| Repository / worktree | `ORACLE-D-dev` (git worktree of `ORACLE-D`), detached HEAD |
| Commit | `8ceee658bb5d285fe757644061b9b9e2d112d9fa` (= `origin/development`, 2026-09-15) |
| Source integrity | `_pristine/src` = `git archive 8ceee65 src`; every run's `src/` tree hash is recorded and compared (`src_matches_pristine` in the manifest) |
| Python | 3.14.7 (pre-existing user venv `ORACLE-D-dev/.venv`, used read-only) |
| Packages | `env/pip_freeze.txt` (numpy 2.4.3, matplotlib 3.11.2, …) |
| Platform | `env/environment.txt` (Linux 6.18, i5-12450H, 12 logical CPUs, 16 GB RAM) |
| Declared deps | `requirements.txt` lists only `numpy==2.4.3`; **matplotlib is imported but undeclared** (not changed) |
| Input hashes | `env/inputs_sha256.txt` (configs, cluster CSVs, CI CSVs), `env/src_sha256.txt` |

## 2. Layout

```
experiments/
  README.md                              this file
  NetDRIVE_WP3_Experimental_Findings.md  technical report
  SUPERVISOR_UPDATE.md                   200-word non-technical update
  run_manifest.csv                       provenance: one row per run (seed, hashes, versions, timing, RSS, exit code, paths)
  results_summary.csv                    one row per paired run (baseline vs policy), units in column names
  results_by_scenario.csv                mean / sd / 95% CI across seeds per scenario
  env/                                   environment record, test outputs, batch console logs
  harness/                               launch.py (seeded, instrumented runner), harness.py, phase scripts
  analysis/                              analyse.py, figures.py, compare_outputs.py
  figures/                               F1–F9 PNGs + CAPTIONS.md
  validation_tests/                      unittest suite + synthetic fixtures (fictional 2030 dates)
  configs/<run_id>/                      immutable (read-only) config snapshot actually read by that run
  runs/<run_id>/                         root/ (src copy, configs copy, data symlink, logs/runs/<model output>),
                                         metrics/ (instrumentation JSON), stdout.txt, stderr.txt
  _pristine/src                          git-archive copy of src @ 8ceee65
```

## 3. How a run works (no source changes)

`Main.py` hard-codes `<repo>/configs/config.json`, resolves data paths relative to the CWD, and draws a fresh
unrecorded-in-log seed with `random.randint`. The harness therefore:

1. writes the config snapshot to `configs/<run_id>/` and makes it read-only;
2. builds `runs/<run_id>/root/` = pristine `src/` + copy of the snapshot as `configs/` + `data -> ../../../../data` symlink;
3. runs `python -s harness/launch.py <seed> <metrics_dir> <instrument>` with CWD = that root and
   `PYTHONHASHSEED=0 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1`;
4. `launch.py` replaces `random.randint` **for its first call only** so `run_seed == <seed>`, then executes the
   unmodified `src/Main.py` via `runpy`. Main.py itself re-seeds `random`/`np.random` before baseline and policy.
5. With `instrument=1`, `launch.py` wraps a few methods at runtime (Job.__init__, Simulation.__init__/start/_finalise,
   Cluster.update, WorkerNode.update, DataLogger.job_start/job_finish/energy_and_carbon_consumed). Each wrapper
   calls the original unchanged and only reads state; none draws random numbers.
   **Verified:** instrumented vs uninstrumented runs with the same seed produce byte-identical model outputs
   (P3-01 vs P3-02, P3-05 vs P3-02: 31/31 files identical after removing wall-clock timestamps and run-folder paths).

## 4. Reproduce

```bash
cd ORACLE-D-dev
export PY=$PWD/.venv/bin/python
# validation tests (stdlib unittest, ~2 s)
(cd experiments/validation_tests && PYTHONHASHSEED=0 MPLBACKEND=Agg $PY -s fixtures/make_fixtures.py && \
   PYTHONHASHSEED=0 MPLBACKEND=Agg $PY -s -m unittest -v && $PY -s check_expected_failures.py)
# Phase 3 smoke / replay / instrumentation-equivalence / failure modes (~1 min)
$PY -s experiments/harness/phase3_smoke.py
$PY -s experiments/harness/phase3_sanity.py
python3 experiments/analysis/compare_outputs.py <output_dir_A> <output_dir_B>
# Phase 4 matrices (A: synthetic mechanisms; B: realistic OAT; H: backlog edge case)
XP_WORKERS=6 $PY -s experiments/harness/phase4_matrix.py A
XP_WORKERS=6 $PY -s experiments/harness/phase4_matrix.py B
XP_WORKERS=6 $PY -s experiments/harness/phase4_matrix.py H
# Phase 6/7 analysis + figures
$PY -s experiments/analysis/analyse.py
$PY -s experiments/analysis/figures.py
```

Run ids are immutable: the harness refuses to overwrite an existing `runs/<run_id>`; delete or rename to re-run.
To replay any single run, copy its `configs/<run_id>/spec.json` into a new spec with a new `run_id` and the same seed.

## 5. Data inputs

| Input | Use | Notes |
|---|---|---|
| `data/carbon_intensity/{south_scotland,north_west_england,southern_england,london,west_midlands}_intensity.csv` | regional CI for sites DESYScot, UoM, RAL, QMUL, West Midlands | half-hourly 2018-09-17 → 2026-07-24; **forecast == actual in every row**; shared gaps 2024-01-25→02-16 and 2025-07-27→08-03; shared blank runs 2024-06-11/12, 2025-01-12/13, 2025-08-10/11 |
| `data/cluster/default-*.csv` | node inventory and frequency/power/HEPScore | 9 node types, 22,797 threads and 43.44 kW idle per site |
| `validation_tests/fixtures/ci/*.csv` | synthetic CI (2030) | generated by `make_fixtures.py`; illustrative only |

Windows used (all inside clean 2026 data): smoke 2026-01-05 16:00 + 6 h; winter 2026-01-05 16:00 + 7 d;
summer 2026-06-15 00:00 + 7 d.

## 6. Metric definitions (results_summary.csv)

* `*_logged` — exactly what ORACLE-D's DataLogger accumulates and what `carbon_savings_summary.txt` reports
  (`saving_pct_model_reported` is parsed from that file as a cross-check).
* `*_corrected_B10` — logged + the model's own idle power for steps where a site had no running/queued jobs
  and `Cluster.update` returned before logging (defect B10).
* `ref_work_core_h` — computation executed **within the horizon**, in reference-node (HEPScore 1939.6) core-hours:
  Σ busy cores × dt / node duration multiplier. Includes partially executed jobs.
* `work_norm_saving_pct_*` — saving in gCO2e per reference core-hour delivered (throughput-normalised).
* `finished_pct_of_baseline_finished` vs `finished_pct_of_generated_policy` — deliberately separate.
* `started_after_wait_gt_10min` — jobs that waited more than one 600 s timestep (SustainableQueue holds every
  job for at least one step, so "passed through the queue" ≠ "deferred").
* Wait = start − generation time (includes temporal deferral and cluster queueing). Turnaround uses the true end
  time captured before the B1 `.seconds` rewrite.

## 7. Deviations from the original plan

* `capacity_aware_CI` runs take ~40+ minutes each because the policy herds every job onto one site and
  `Cluster.update` rescans the growing queue against every node each step. Stage B runs this policy with
  **2 seeds per window** (101, 202) instead of 5; all other scenarios use 5. Per-run timeout 3600 s
  (recorded as `exit_code=TIMEOUT`).
* A first Stage B launch was stopped after ~2 minutes to apply this change; its 5 incomplete run folders were
  deleted (they had no manifest rows). This is the only deletion performed, and only of harness scratch output.

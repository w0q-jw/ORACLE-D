"""Reproducible paired-run harness for ORACLE-D (development @ 8ceee65).

Never edits production files. For each run it creates:
  experiments/configs/<run_id>/            immutable config snapshot (config.json + site jsons)
  experiments/runs/<run_id>/root/          src/ (pristine git-archive copy), configs/ (snapshot copy), data -> repo data (symlink)
  experiments/runs/<run_id>/metrics/       instrumentation JSON (baseline + policy)
  experiments/runs/<run_id>/stdout.txt, stderr.txt
and appends one row to experiments/run_manifest.csv.
"""
import csv
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

XP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # experiments/
REPO = os.path.dirname(XP)
PRISTINE_SRC = os.path.join(XP, '_pristine', 'src')
PYTHON = os.path.join(REPO, '.venv', 'bin', 'python')
LAUNCH = os.path.join(XP, 'harness', 'launch.py')
MANIFEST = os.path.join(XP, 'run_manifest.csv')
COMMIT = '8ceee658bb5d285fe757644061b9b9e2d112d9fa'

MANIFEST_FIELDS = [
    'run_id', 'scenario_id', 'stage', 'timestamp_utc', 'commit', 'src_tree_sha256', 'src_matches_pristine',
    'config_sha256', 'site_configs_sha256', 'datasets', 'seed', 'python', 'numpy', 'matplotlib', 'platform',
    'routing_policy', 'k', 'origin_bias', 'temporal_policy', 'sites', 'start', 'length_s', 'timestep_s',
    'initial_jobs_per_site', 'incoming_jobs_per_step_per_site', 'ci_source', 'instrumented', 'notes',
    'elapsed_s', 'peak_rss_kb', 'exit_code', 'config_snapshot_dir', 'output_dir', 'metrics_dir', 'stdout', 'stderr',
]

_hash_cache = {}


def sha256_file(path):
    path = os.path.realpath(path)
    if path not in _hash_cache:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        _hash_cache[path] = h.hexdigest()
    return _hash_cache[path]


def sha256_tree(root, suffix='.py'):
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames[:] = sorted(d for d in dirnames if d != '__pycache__')
        for fn in sorted(filenames):
            if fn.endswith(suffix):
                p = os.path.join(dirpath, fn)
                h.update(os.path.relpath(p, root).encode())
                h.update(sha256_file(p).encode())
    return h.hexdigest()


PRISTINE_HASH = sha256_tree(PRISTINE_SRC)


def _versions():
    out = subprocess.run([PYTHON, '-c', 'import sys,numpy,matplotlib;print(sys.version.split()[0],numpy.__version__,matplotlib.__version__)'],
                         capture_output=True, text=True, env={'PATH': os.environ['PATH'], 'MPLBACKEND': 'Agg'})
    return out.stdout.split()


PY_V, NP_V, MPL_V = _versions()


def load_base_site(key):
    with open(os.path.join(REPO, 'configs', f'{key}.json')) as f:
        return json.load(f)


def build_configs(spec):
    """Return (config_dict, {filename: site_dict}) for a run spec."""
    routing = {'policy': spec.get('routing', 'origin_site')}
    if spec.get('k') is not None:
        routing['k'] = spec['k']
    if spec.get('origin_bias') is not None:
        routing['origin_bias'] = spec['origin_bias']
    site_files = {}
    for key in spec['sites']:
        site = load_base_site(key)
        load = spec.get('load')
        if load is not None:
            site['jobs'] = {'initial_mix': {'ATLAS': load['initial']} if load['initial'] else {},
                            'regular_incoming_mix': {'ATLAS': load['incoming']} if load['incoming'] else {},
                            'incoming_timestep': load.get('incoming_timestep', 600)}
        site['temporal_shifting'] = {'policy': spec.get('temporal', 'submit_immediately')}
        ci = spec.get('ci_override')
        if ci:
            site['carbon_intensity']['folder'] = ci['folder'].rstrip('/') + '/'
            site['carbon_intensity']['filename'] = ci['files'][key]
        for k, v in spec.get('site_overrides', {}).get(key, {}).items():
            site[k] = v
        site_files[f'{key}.json'] = site
    config = {
        'Simulation': {'desired_starttime': spec['start'], 'simulation_length': spec['length_s'],
                       'timestep': spec.get('timestep_s', 600), 'routing': routing},
        'sites': list(site_files.keys()),
        'output': {'verbosity': 'medium', 'debug': False, 'log_dir': 'logs/runs', 'run_label': spec['run_id']},
    }
    for k, v in spec.get('config_overrides', {}).items():
        config[k] = v
    return config, site_files


def prepare(spec):
    run_id = spec['run_id']
    snap = os.path.join(XP, 'configs', run_id)
    run_root = os.path.join(XP, 'runs', run_id)
    if os.path.exists(run_root) or os.path.exists(snap):
        raise FileExistsError(f'run_id {run_id} already exists; run ids are immutable')
    if 'raw_config' in spec:
        config, site_files = spec['raw_config'], spec['raw_site_files']
    else:
        config, site_files = build_configs(spec)
    os.makedirs(snap)
    with open(os.path.join(snap, 'config.json'), 'w') as f:
        json.dump(config, f, indent=4) if not isinstance(config, str) else f.write(config)
    for name, site in site_files.items():
        with open(os.path.join(snap, name), 'w') as f:
            json.dump(site, f, indent=2) if not isinstance(site, str) else f.write(site)
    with open(os.path.join(snap, 'spec.json'), 'w') as f:
        json.dump({k: v for k, v in spec.items() if k not in ('raw_config', 'raw_site_files')}, f, indent=2)
    os.chmod(snap, 0o555)
    for fn in os.listdir(snap):
        os.chmod(os.path.join(snap, fn), 0o444)
    root = os.path.join(run_root, 'root')
    shutil.copytree(PRISTINE_SRC, os.path.join(root, 'src'), ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(snap, os.path.join(root, 'configs'))
    os.symlink(os.path.join(REPO, 'data'), os.path.join(root, 'data'))
    return config, site_files, snap, run_root, root


def run(spec):
    config, site_files, snap, run_root, root = prepare(spec)
    metrics = os.path.join(run_root, 'metrics')
    src_hash = sha256_tree(os.path.join(root, 'src'))
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', ''), 'PYTHONHASHSEED': '0',
           'MPLBACKEND': 'Agg', 'PYTHONDONTWRITEBYTECODE': '1'}
    t0 = time.time()
    with open(os.path.join(run_root, 'stdout.txt'), 'w') as so, open(os.path.join(run_root, 'stderr.txt'), 'w') as se:
        try:
            proc = subprocess.run([PYTHON, '-s', LAUNCH, str(spec['seed']), metrics, '1' if spec.get('instrument', True) else '0'],
                                  cwd=root, stdout=so, stderr=se, env=env, timeout=spec.get('timeout_s', 3600))
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:          # subprocess.run kills the child on timeout
            exit_code = 'TIMEOUT'
    elapsed = time.time() - t0
    out_dirs = sorted(os.listdir(os.path.join(root, 'logs', 'runs'))) if os.path.isdir(os.path.join(root, 'logs', 'runs')) else []
    output_dir = os.path.join(root, 'logs', 'runs', out_dirs[-1]) if out_dirs else ''
    peak = ''
    pfile = os.path.join(metrics, 'process.json')
    if os.path.exists(pfile):
        peak = json.load(open(pfile))['peak_rss_kb']
    datasets = {}
    for name, site in site_files.items():
        if isinstance(site, dict):
            for p in (os.path.join(site['carbon_intensity']['folder'], site['carbon_intensity']['filename']),
                      site['cluster']['inventory_csv'], site['cluster']['frequency_csv']):
                full = p if os.path.isabs(p) else os.path.join(root, p)
                rel = os.path.relpath(os.path.realpath(full), REPO) if os.path.exists(full) else p
                datasets[rel] = sha256_file(full)[:16] if os.path.exists(full) else 'MISSING'
    sim = config.get('Simulation', {}) if isinstance(config, dict) else {}
    routing = sim.get('routing', {})
    first_site = next((s for s in site_files.values() if isinstance(s, dict)), {})
    jobs = first_site.get('jobs', {})
    row = {
        'run_id': spec['run_id'], 'scenario_id': spec.get('scenario_id', ''), 'stage': spec.get('stage', ''),
        'timestamp_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'commit': COMMIT,
        'src_tree_sha256': src_hash, 'src_matches_pristine': src_hash == PRISTINE_HASH,
        'config_sha256': sha256_file(os.path.join(snap, 'config.json')),
        'site_configs_sha256': json.dumps({n: sha256_file(os.path.join(snap, n))[:16] for n in site_files}),
        'datasets': json.dumps(datasets), 'seed': spec['seed'], 'python': PY_V, 'numpy': NP_V, 'matplotlib': MPL_V,
        'platform': platform.platform(), 'routing_policy': routing.get('policy', ''), 'k': routing.get('k', ''),
        'origin_bias': routing.get('origin_bias', ''), 'temporal_policy': spec.get('temporal', ''),
        'sites': '|'.join(spec.get('sites', [])), 'start': sim.get('desired_starttime', ''),
        'length_s': sim.get('simulation_length', ''), 'timestep_s': sim.get('timestep', ''),
        'initial_jobs_per_site': json.dumps(jobs.get('initial_mix', {})),
        'incoming_jobs_per_step_per_site': json.dumps(jobs.get('regular_incoming_mix', {})),
        'ci_source': 'synthetic:' + spec['ci_override']['name'] if spec.get('ci_override') else 'repository regional CSVs',
        'instrumented': spec.get('instrument', True), 'notes': spec.get('notes', ''),
        'elapsed_s': round(elapsed, 2), 'peak_rss_kb': peak, 'exit_code': exit_code,
        'config_snapshot_dir': os.path.relpath(snap, REPO), 'output_dir': os.path.relpath(output_dir, REPO) if output_dir else '',
        'metrics_dir': os.path.relpath(metrics, REPO), 'stdout': os.path.relpath(os.path.join(run_root, 'stdout.txt'), REPO),
        'stderr': os.path.relpath(os.path.join(run_root, 'stderr.txt'), REPO),
    }
    return row


def append_manifest(rows):
    with open(MANIFEST, 'a', newline='') as f:
        fcntl.flock(f, fcntl.LOCK_EX)           # several batch processes may append concurrently
        try:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if f.tell() == 0:
                w.writeheader()
            for r in rows:
                w.writerow(r)
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run_batch(specs, workers=6):
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run, s): s for s in specs}
        for i, fut in enumerate(as_completed(futs), 1):
            s = futs[fut]
            try:
                row = fut.result()
            except Exception as e:  # harness failure, not a model failure
                print(f'[{i}/{len(specs)}] HARNESS ERROR {s["run_id"]}: {e!r}', flush=True)
                continue
            append_manifest([row])
            rows.append(row)
            print(f'[{i}/{len(specs)}] {row["run_id"]} exit={row["exit_code"]} {row["elapsed_s"]}s rss={row["peak_rss_kb"]}kB', flush=True)
    return rows


def load_metrics(run_id):
    d = os.path.join(XP, 'runs', run_id, 'metrics')
    out = {}
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.startswith('sim_'):
                m = json.load(open(os.path.join(d, fn)))
                out[m['role']] = m
    return out

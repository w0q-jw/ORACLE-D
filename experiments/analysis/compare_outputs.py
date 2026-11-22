"""Compare two ORACLE-D run output trees ignoring only wall-clock / run-folder metadata."""
import hashlib, json, os, re, sys

VOLATILE = [
    (re.compile(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}\s+'), ''),      # log timestamp prefix
    (re.compile(r'logs/runs/\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_[A-Za-z0-9_]+'), 'logs/runs/<RUN>'),
    (re.compile(r'experiments/runs/[^/]+/root'), 'experiments/runs/<ID>/root'),
    (re.compile(r'Set origin: .*'), 'Set origin: <WALLCLOCK>'),
    (re.compile(r'Total Real-time Duration\s*:.*'), 'Total Real-time Duration: <WALLCLOCK>'),
]

def norm(text):
    out = []
    for line in text.splitlines():
        for rx, rep in VOLATILE:
            line = rx.sub(rep, line)
        out.append(line)
    return out

def files(root):
    res = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            res[os.path.relpath(p, root)] = p
    return res

def compare(a, b):
    fa, fb = files(a), files(b)
    report = {'only_a': sorted(set(fa) - set(fb)), 'only_b': sorted(set(fb) - set(fa)), 'identical': [], 'differ': {}}
    for rel in sorted(set(fa) & set(fb)):
        if rel.endswith('.png'):
            ha = hashlib.sha256(open(fa[rel], 'rb').read()).hexdigest(); hb = hashlib.sha256(open(fb[rel], 'rb').read()).hexdigest()
            (report['identical'].append(rel) if ha == hb else report['differ'].__setitem__(rel, 'png bytes differ'))
            continue
        la, lb = norm(open(fa[rel]).read()), norm(open(fb[rel]).read())
        if la == lb:
            report['identical'].append(rel)
        else:
            diffs = [(i, x, y) for i, (x, y) in enumerate(zip(la, lb)) if x != y][:3]
            report['differ'][rel] = {'n_lines_a': len(la), 'n_lines_b': len(lb), 'first_diffs': diffs}
    return report

if __name__ == '__main__':
    r = compare(sys.argv[1], sys.argv[2])
    print(json.dumps({k: (v if k != 'identical' else len(v)) for k, v in r.items()}, indent=1))

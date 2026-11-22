"""Generate SYNTHETIC carbon-intensity and cluster fixtures (provenance: this script; not real grid data).

All CI fixtures use the fictional year 2030 so they can never be confused with observed data.
Format matches the regional CSVs: datetime,forecast,actual  (gCO2e/kWh, half-hourly).
Run:  python make_fixtures.py   (writes ./ci/*.csv and ./cluster/*.csv, idempotent)
"""
import os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CI_DIR = os.path.join(HERE, 'ci')
CL_DIR = os.path.join(HERE, 'cluster')
T0 = datetime(2029, 12, 31, 0, 0)          # fixture coverage starts a day before the window
N = 12 * 48                                 # 12 days of half-hour slots
WIN = datetime(2030, 1, 1, 0, 0)            # simulation windows start here
WIN_SLOTS = 7 * 48


def write(name, forecast, actual=None, drop=(), blank=(), duplicate=()):
    actual = actual or forecast
    os.makedirs(CI_DIR, exist_ok=True)
    with open(os.path.join(CI_DIR, name), 'w') as f:
        f.write('datetime,forecast,actual\n')
        for i in range(N):
            if i in drop:
                continue
            t = (T0 + timedelta(minutes=30 * i)).strftime('%Y-%m-%dT%H:%M:%S')
            fv = '' if i in blank else f'{forecast(i):.3f}'
            av = '' if i in blank else f'{actual(i):.3f}'
            f.write(f'{t},{fv},{av}\n')
            if i in duplicate:
                f.write(f'{t},{forecast(i) + 1000:.3f},{actual(i) + 1000:.3f}\n')


def ramp(a, b):
    start = 48  # window start index
    return lambda i: a + (b - a) * min(max(i - start, 0), WIN_SLOTS) / WIN_SLOTS


SITES = ('Scot', 'UoM', 'RAL')

PATTERNS = {
    'flat_equal':  {s: (lambda i: 200.0) for s in SITES},
    'differing':   {'Scot': (lambda i: 50.0), 'UoM': (lambda i: 200.0), 'RAL': (lambda i: 400.0)},
    'rising':      {s: ramp(100, 400) for s in SITES},
    'falling':     {s: ramp(400, 100) for s in SITES},
    'step':        {s: (lambda i: 400.0 if i < 48 + WIN_SLOTS // 2 else 100.0) for s in SITES},
}


def build():
    for pat, fns in PATTERNS.items():
        for site, fn in fns.items():
            write(f'{pat}_{site}.csv', fn)
    # forecast != actual: forecast says Scot cleanest, reality is inverted
    fc = {'Scot': 50.0, 'UoM': 200.0, 'RAL': 400.0}
    ac = {'Scot': 400.0, 'UoM': 200.0, 'RAL': 50.0}
    for site in SITES:
        write(f'fcmismatch_{site}.csv', lambda i, v=fc[site]: v, lambda i, v=ac[site]: v)
    # Defect fixtures: value == slot index so a stale value is identifiable
    idx = lambda i: float(100 + i)
    gap = set(range(96, 144))                    # 2030-01-02 00:00 .. 23:30 missing (24 h)
    write('defect_gap.csv', idx, drop=gap)
    write('defect_blank.csv', idx, blank={60, 61})   # 2030-01-01 06:00 and 06:30 blank
    write('defect_duplicate.csv', idx, duplicate={60})
    write('defect_index.csv', idx)               # clean reference for the above

    # Tiny cluster: 1 node, 2 threads (1 physical core), 4 GB, idle 100 W, 300 W at 1.0 GHz, HEPScore 1939.6
    # (HEPScore equal to the 1939.6 reference -> duration multiplier exactly 1).
    os.makedirs(CL_DIR, exist_ok=True)
    with open(os.path.join(CL_DIR, 'tiny_frequency.csv'), 'w') as f:
        f.write('hostname,type,subtype,latest measurement,frequency_power_hepscore\n')
        f.write('tiny-T1,TINY,0,2030-01-01T00:00:00,1000_300_1939.6\n')
        f.write('tiny-T2,RAMTEST,0,2030-01-01T00:00:00,1000_300_1939.6\n')
    header = ('representative,timestamp_check,number_machines,number_decommissioned,type,subtype,comment,manufacturer,'
              'model,cpu_model,hepscore,installation_date,cluster(main_Puppet_hostgroup),total_cores,total_threads,'
              'total_mem_in_Gb,power_min_60d,power_max_60d\n')
    with open(os.path.join(CL_DIR, 'tiny_inventory.csv'), 'w') as f:
        f.write(header)
        f.write('tiny-T1,2030-01-01T00:00:00,1,0,TINY,0,synthetic fixture,,synthetic,synthetic,1939.6,2030,TINY,1,2,4,100,300\n')
    with open(os.path.join(CL_DIR, 'ramtest_inventory.csv'), 'w') as f:
        f.write(header)
        f.write('tiny-T2,2030-01-01T00:00:00,1,0,RAMTEST,0,synthetic fixture,,synthetic,synthetic,1939.6,2030,RAMTEST,4,8,4,100,300\n')


if __name__ == '__main__':
    build()
    print('fixtures written to', CI_DIR, 'and', CL_DIR)

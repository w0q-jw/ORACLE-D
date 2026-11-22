"""Run every @expectedFailure test WITHOUT the decorator and report whether it fails by AssertionError
(i.e. for the documented reason) rather than by an unrelated error."""
import sys, unittest
loader = unittest.TestLoader()
suite = loader.discover('.', pattern='test_*.py')
def walk(s):
    for t in s:
        yield from (walk(t) if isinstance(t, unittest.TestSuite) else [t])
bad = 0; n = 0
for test in walk(suite):
    fn = getattr(type(test), test._testMethodName)
    if not getattr(fn, '__unittest_expecting_failure__', False):
        continue
    n += 1
    raw = fn
    try: del raw.__unittest_expecting_failure__
    except AttributeError: pass
    res = unittest.TestResult(); test.run(res)
    kind = 'ASSERTION-FAIL (ok)' if res.failures else ('ERROR' if res.errors else 'PASSED?!')
    if not res.failures: bad += 1
    print(f'{kind:20s} {test.id()}')
    if res.errors: print(res.errors[0][1].splitlines()[-1])
print(f'{n} expected-failure tests; {bad} not failing by assertion')
sys.exit(1 if bad else 0)

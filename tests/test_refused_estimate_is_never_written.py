"""A refused estimate cannot be consumed, because it is never written.

Six routes consume an estimate snapshot and none checks whether it was
published:

    POST .../estimates/{id}:validate
    POST .../calibration
    POST .../delta-bridge
    POST .../estimates:ask
    POST .../estimates/{id}/recommendation:run
    PUT  .../domain-dispositions

On the route bodies alone that is a serious gap - the V1 questionnaire, the
savings recommendation and the calibration would all run on a refused
baseline. They cannot, because the refusal raises BEFORE the snapshot is
written, so no REFUSED snapshot exists to consume.

That is the stronger construction: a check can be forgotten at the seventh
consumer, and there is no seventh thing to forget.

But it is currently a property of statement order in one function and nothing
asserts it. Moving the write above the refusal would silently open all six
routes, and every one of them would look exactly as correct as it does now.
"""
import re
from pathlib import Path


def _api():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    return (app / "routers" / "api.py").read_text()


def _routes():
    """Each route body, as (method, path, body)."""
    api = _api()
    marks = [(m.group(1).upper(), m.group(2), m.start())
             for m in re.finditer(
                 r'@router\.(get|post|put|patch|delete)\("([^"]+)"', api)]
    out = []
    for i, (method, path, start) in enumerate(marks):
        end = marks[i + 1][2] if i + 1 < len(marks) else len(api)
        out.append((method, path, api[start:end]))
    return out


def test_the_refusal_precedes_the_snapshot_write():
    """Per route, by the position of the FIRST occurrence of each.

    Two earlier versions of this test passed on the regression it exists to
    catch. The first searched a 6,000-character window after the refusal and
    found the write either way. The second compared `body.index()` of each
    string - and the route contains the refusal twice, once in a comment
    quoting it, so the first index was still the earlier one.

    `insert(db.estimate_snapshot)` against the LAST refusal is the ordering
    that matters: every refusal has to come before the write, not just one.

    The sibling test below catches this regression by a different route, and
    `validate_flow` catches it too. Three guards on one invariant is
    deliberate - it is the property that makes six unchecked consumers safe.
    """
    checked = 0
    for method, path, body in _routes():
        if "insert(db.estimate_snapshot)" not in body:
            continue
        refusals = [m.start() for m in re.finditer(
            r'raise HTTPException\(409, \{"error": "V0 publication refused',
            body)]
        if not refusals:
            continue
        checked += 1
        write = body.index("insert(db.estimate_snapshot)")
        assert max(refusals) < write, (
            f"{method} {path}: a coverage refusal at {max(refusals)} comes "
            f"AFTER the snapshot write at {write} - a REFUSED estimate would "
            f"persist and six consumers would read it")
    assert checked >= 1, (
        "no route both refuses and writes a snapshot - the invariant this "
        "file protects has moved and the test needs rewriting, not deleting")


def test_no_consumer_has_to_check_because_none_can_exist():
    """The invariant stated as a test rather than as a comment.

    If a future change makes a REFUSED snapshot writable, this fails and
    points at the six routes that would then need a check each."""
    api = _api()
    for match in re.finditer(r'insert\(db\.estimate_snapshot\)', api):
        before = api[max(0, match.start() - 7000):match.start()]
        assert '"V0 publication refused (0.3C)"' in before, (
            "a snapshot is written on a path with no coverage refusal above "
            "it - a refused estimate would persist and six routes would "
            "consume it")


def test_the_status_written_is_the_one_coverage_decided():
    """Not a literal, and not a default. A snapshot whose status is set to
    anything other than what `coverage.assess` returned is a snapshot whose
    status means nothing."""
    api = _api()
    for match in re.finditer(r'insert\(db\.estimate_snapshot\)', api):
        window = api[match.start():match.start() + 900]
        found = re.search(r'v0_status=([^,)\s]+)', window)
        assert found, "a snapshot must record its coverage status"
        assert found.group(1) == 'cov["status"]', found.group(1)


def test_coverage_still_has_exactly_three_statuses():
    """A fourth would need a decision about which consumers accept it, and
    this test is where that decision gets noticed."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    coverage = (app / "domain" / "coverage.py").read_text()
    statuses = set(re.findall(r'status = "(\w+)"', coverage))
    statuses |= set(re.findall(r'"status": "(\w+)"', coverage))
    assert statuses <= {"REFUSED", "PARTIAL", "COMPLETE"}, statuses
    assert "REFUSED" in statuses and "PARTIAL" in statuses

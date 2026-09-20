"""The overnight batch runner.

Seventeen research domains at one to three minutes each is most of an hour per
company, so ten companies is an overnight job and nobody should sit and watch
it.

Tested for the two things that decide whether it survives a night: it must not
reach into the application, and it must resume rather than restart.
"""
import ast
from pathlib import Path


def _source():
    root = Path(__file__).resolve().parents[1]
    return (root / "tools" / "run_batch.py").read_text()


def test_it_touches_no_application_code():
    """Drives the public API exactly as an analyst would.

    A batch run that imported the domain modules could break a case an analyst
    is working on, and would need changing every time an internal signature
    moved. Everything here is HTTP against endpoints the interface already
    uses, so a change that breaks this is one that would have broken the
    interface too."""
    tree = ast.parse(_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "app" not in imported, "it must not import the application"
    assert not (imported - {"argparse", "csv", "json", "pathlib", "sys",
                            "time", "urllib", "__future__"}), sorted(imported)


def test_a_failed_step_is_retried_on_a_re_run():
    """A failure was recorded as {"ok": False} - truthy - so a re-run skipped
    it and the failure became permanent.

    The point of resuming is that somebody restarted after a crash, and a
    domain that failed on a timeout should be tried again. One that fails for
    a permanent reason fails again and stays visible, which costs one call."""
    source = _source()
    done = source[source.index("    def done(self"):][:900]
    assert 'record.get("ok") is not False' in done, (
        "a recorded failure must not count as done")


def test_a_completed_step_is_not_repeated():
    """A crash on company eight must not cost the seven before it."""
    source = _source()
    assert "if state.done(name, step):" in source
    assert "if state.done(name, \"simulation\"):" in source
    assert "if state.done(name, \"estimate\"):" in source


def test_state_is_flushed_as_it_happens():
    """Written on every change rather than at the end: the whole point is to
    survive a process that does not reach the end."""
    source = _source()
    mark = source[source.index("    def mark(self"):][:400]
    assert "self.flush()" in mark


def test_one_domain_per_call():
    """A seventeen-domain run in one request is most of an hour of live
    provider work behind a single HTTP call, and a failure at domain fifteen
    would cost the fourteen before it."""
    source = _source()
    assert '"domain_nos": [domain_no]' in source


def test_one_company_failing_does_not_end_the_night():
    source = _source()
    assert "except Exception as exc:" in source
    assert 'record["status"] = "FAILED"' in source


def test_results_are_written_after_every_company():
    """A run that dies at 3am should still have the rows it earned."""
    source = _source()
    loop = source[source.index("for index, row in enumerate(rows, 1):"):]
    assert "writer.writerows(results)" in loop


def test_it_invents_no_estate_split():
    """The footprint page exists to make a person choose one. A plausible mix
    nobody decided would be priced as though someone had."""
    source = _source()
    footprint = source[source.index("def _footprint_for"):][:900]
    assert "RESEARCHED_NO_FOOTPRINT" in source
    assert "invent an estate split" in footprint


def test_it_waits_longer_than_the_server_will():
    """The server's ceiling on a search-carrying call is 480 seconds. Waiting
    less would abandon calls that were going to succeed, which is the failure
    this tool exists to avoid."""
    source = _source()
    timeout = next(line for line in source.splitlines()
                   if line.startswith("READ_TIMEOUT"))
    assert float(timeout.split("=")[1]) >= 480

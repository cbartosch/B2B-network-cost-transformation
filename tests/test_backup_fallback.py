"""The backup has to work when the API does not.

`bundle-in` takes a case backup before merging, and that backup calls the API.
A merge before a fix is usually a merge because something is broken - so the
API is often down at exactly this moment.

It was: the backup was refused with WinError 10061 while the database
container reported healthy throughout. The one occasion the backup was most
needed was the one occasion it could not run, and the merge proceeded with
nothing saved.

pg_dump needs only the database. It is also the broader backup: the case
export covers what a person entered, the dump covers estimates, runs and
everything else.
"""
from pathlib import Path


def _bundle_in():
    root = Path(__file__).resolve().parents[1]
    script = (root / "make.ps1").read_text(encoding="utf-8")
    start = script.index("'bundle-in' {")
    return script[start:script.index("git bundle verify", start)]


def test_a_database_dump_is_attempted_when_the_api_is_down():
    block = _bundle_in()
    assert "pg_dump" in block
    assert "does not need it" in block or "not need the API" in block


def test_the_dump_is_attempted_before_anything_is_merged():
    """A backup after the merge is not a backup."""
    root = Path(__file__).resolve().parents[1]
    script = (root / "make.ps1").read_text(encoding="utf-8")
    start = script.index("'bundle-in' {")
    assert script.index("pg_dump", start) < script.index(
        "git bundle verify", start)


def test_an_empty_dump_is_deleted_rather_than_kept():
    """A zero-byte file looks like a backup. The only thing worse than no
    backup is one that is not there when it is restored."""
    block = _bundle_in()
    assert "Remove-Item $dump" in block
    assert ".Length -gt 0" in block


def test_neither_backup_working_is_said_plainly():
    """The operator has to be able to decide whether to continue."""
    block = _bundle_in()
    assert "cases are NOT saved" in block


def test_a_failed_backup_still_does_not_block_the_merge():
    """Best effort throughout. A backup that can stop a merge is one people
    route around, and the merge is often the fix for whatever broke the
    backup."""
    block = _bundle_in()
    assert "Merging anyway" in block
    assert "throw" not in block.split("pg_dump")[1][:600]

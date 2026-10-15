"""What `make bundle-out` ships, and what it used to ship by accident.

The target's own description has always said it produces "the CURRENT
branch plus main". The command said `git bundle create --all`, which
writes every ref under refs/ - ten of them in this repository, six being
refs/remotes/*. A receiver got the whole branch topology including work
abandoned months earlier.

The worst of it was feat/initial-workbench-scaffold: seven commits
carrying an entire parallel `src/network_cost_workbench/` tree that main
replaced with `api_service/app`. Someone opening the bundle to review a
change found two application layouts and nothing telling them which one
was real - in a repository that already has a documented history of /src
and /app being confused for each other.

Read out of make.ps1 as text, the way test_backup_fallback.py reads the
bundle-in block, because PowerShell is not importable here.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _bundle_out():
    script = (ROOT / "make.ps1")
    if not script.exists():
        pytest.skip("make.ps1 not present in this image")
    text = script.read_text(encoding="utf-8")
    start = text.index("'bundle-out' {")
    return text[start:text.index("'bundle-in' {", start)]


def test_the_bundle_is_not_every_ref_in_the_repository():
    block = _bundle_out()
    assert "'--all'" not in block, (
        "--all ships refs/remotes and every abandoned branch; the target "
        "promises the current branch plus main")


def test_it_carries_main_as_ancestry():
    """Without main the receiver can only send back an orphan, which is
    the failure the whole bundle workflow exists to replace."""
    block = _bundle_out()
    assert "'main'" in block


def test_head_is_carried_so_a_clone_lands_on_the_work():
    """A clone of the bundle checks out HEAD. Carrying it last puts the
    receiver on the branch being reviewed rather than on main."""
    block = _bundle_out()
    assert "'HEAD'" in block


def test_a_detached_head_is_refused_rather_than_guessed_at():
    """`git rev-parse --abbrev-ref HEAD` returns the string "HEAD" when
    detached, which would have been passed to git bundle as a branch
    name."""
    block = _bundle_out()
    assert "$branch -eq 'HEAD'" in block
    assert "throw" in block


def test_standing_on_main_does_not_name_it_twice():
    """`git bundle create out main main HEAD` is an error, and the one
    case where the current branch IS main is the likeliest way to hit
    it."""
    block = _bundle_out()
    assert "$branch -eq 'main'" in block

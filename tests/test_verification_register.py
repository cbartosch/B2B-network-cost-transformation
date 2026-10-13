"""The register that makes a changed site count auditable rather than explained.

An external audit raised FOOTPRINT_CHANGE_WITHOUT_VERIFICATION_RECORD on five
rows: a count that moved away from the declaration, with no entry carrying an
as-of date, an evidence reference and a site definition.

`footprint_provenance` already records what changed and why, with both figures
and the source URLs. That makes a change EXPLAINED. It does not make it
AUDITABLE - the explanation lives in the output of the run that made it, so a
reader has only the run's own word for it. A register is a separate, dated
statement a person signed.
"""
import csv
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTER = ROOT / "samples" / "verification_register.csv"


def _tool():
    f = ROOT / "tools" / "check_footprint_verification.py"
    if not f.exists():
        pytest.skip("checker not present")
    spec = importlib.util.spec_from_file_location("_fv", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def tool():
    return _tool()


def _rows():
    if not REGISTER.exists():
        pytest.skip("register not present")
    return list(csv.DictReader(REGISTER.open(encoding="utf-8")))


# ------------------------------------------- what an entry has to carry

def test_the_register_exists_and_has_entries():
    assert _rows()


@pytest.mark.parametrize("field", ["as_of", "site_definition", "verified_by",
                                   "verified_at", "disposition"])
def test_every_entry_carries_the_fields_that_make_it_a_record(field):
    """The audit asked for an as-of date, an evidence reference and a site
    definition. An entry missing one is a note, not a verification."""
    for row in _rows():
        assert (row.get(field) or "").strip(), (
            f"{row['slug']} {row['country']}/{row['archetype']}: no {field}")


def test_a_site_definition_says_what_counts_as_a_site():
    """The reason two sources disagree is usually that they are counting
    different things. Boots' GB count differs by 49% between sources, which
    is a definition difference rather than a fact in dispute."""
    for row in _rows():
        assert len(row["site_definition"]) > 40, (
            f"{row['slug']}: a one-word site definition settles nothing")


def test_an_accepted_or_excluded_entry_cites_evidence():
    """A DECLINED entry may have none - declining is a statement that the
    evidence was not good enough - but accepting or excluding a count on no
    reference is an assertion wearing a record's clothes."""
    for row in _rows():
        if row["disposition"] in ("VERIFIED", "EXCLUDED"):
            assert (row.get("evidence_ref") or "").strip().startswith("http"), (
                f"{row['slug']}: {row['disposition']} with no evidence_ref")


# ------------------------------------------------- what the checker does

def test_only_known_dispositions_are_accepted(tool, tmp_path):
    bad = tmp_path / "r.csv"
    bad.write_text("slug,country,archetype,disposition,as_of,site_definition,"
                   "verified_by\nx,GB,STORE,PROBABLY,2026-01-01,a site,me\n",
                   encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        tool.load_register(bad)
    assert "PROBABLY" in str(e.value)


def test_an_entry_missing_a_date_is_refused(tool, tmp_path):
    bad = tmp_path / "r.csv"
    bad.write_text("slug,country,archetype,disposition,as_of,site_definition,"
                   "verified_by\nx,GB,STORE,VERIFIED,,a site definition,me\n",
                   encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        tool.load_register(bad)
    assert "as_of" in str(e.value)


def test_the_committed_register_loads(tool):
    assert tool.load_register(REGISTER)


def test_an_exclusion_counts_as_a_change_needing_a_record(tool):
    """Research found sites and a scope rule kept them out. Silently dropping
    evidence needs a record as much as silently accepting it does - UPS
    excluded 5,603 franchises and UNFI 60,000 customer locations."""
    found = tool.changes(ROOT / "samples" / "outside_in",
                         ROOT / "samples" / "companies.json")
    kinds = {c["kind"] for c in found}
    assert "EXCLUDED" in kinds and "CHANGED" in kinds


def test_most_changes_are_still_unverified_and_that_is_the_point(tool):
    """The register's value is showing what is NOT verified. A checker that
    reported everything covered would mean the register had been written to
    match the output rather than the evidence."""
    register = tool.load_register(REGISTER)
    found = tool.changes(ROOT / "samples" / "outside_in",
                         ROOT / "samples" / "companies.json")
    covered = sum(1 for c in found
                  if (c["slug"], c["country"], c["archetype"]) in register)
    assert 0 < covered < len(found), (
        f"{covered} of {len(found)} covered - a register covering everything "
        f"has stopped being evidence")

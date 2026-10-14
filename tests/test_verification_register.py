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


# ------------------- findings that disqualify themselves in their own label

def test_a_divested_estate_is_detected_from_the_finding_label(tool):
    """The verification exercise's real finding. Saint-Gobain's German and
    UK builders' merchants were labelled "DIVESTED to STARK Group" in 2019
    and 2023, and promotion carried only (country, archetype, sites) - so
    820 sites it had sold were priced as its estate. BNP's Belgian row said
    "Fintro franchise branches" and read exactly like the UPS Store network.

    Research wrote the disqualification down. Nothing read it.
    """
    warned = tool.label_warnings(ROOT / "samples" / "outside_in")
    pairs = {(w["slug"], w["country"], w["archetype"]) for w in warned}
    assert ("saint-gobain", "DE", "STORE") in pairs
    assert ("saint-gobain", "GB", "STORE") in pairs
    assert ("bnp-paribas", "BE", "STORE") in pairs


def test_every_flagged_pair_has_been_addressed(tool):
    """A warning nobody acts on is noise. Each flagged pair must carry a
    register entry saying what was decided."""
    register = tool.load_register(REGISTER)
    warned = tool.label_warnings(ROOT / "samples" / "outside_in")
    live = [w for w in warned
            if (w["slug"], w["country"], w["archetype"]) not in register]
    assert not live, f"unaddressed disqualifying labels: {live}"


def test_a_disqualified_finding_that_lost_is_not_warned_about(tool):
    """BNP's Fintro franchise also appears under BRANCH and Nestle has a DC
    sold to Orllati - both promoted, both beaten by the declared figure, so
    neither is priced. Warning about them trains a reader to skim."""
    warned = tool.label_warnings(ROOT / "samples" / "outside_in")
    pairs = {(w["slug"], w["country"], w["archetype"]) for w in warned}
    assert ("bnp-paribas", "BE", "BRANCH") not in pairs
    assert ("nestle", "CH", "DC") not in pairs


def test_referred_is_a_disposition_a_person_still_owes_a_decision_on(tool):
    """Three changes are sound counts whose membership of the estate is a
    scope judgement, not a fact: Shell's dealer-owned Dutch forecourts,
    DHL's drop-off counters inside third-party shops, and Allianz's
    tied-agent offices. Deciding any of them from a label would be inventing
    a policy, so they are recorded as REFERRED and stay in the estate."""
    assert "REFERRED" in tool.DISPOSITIONS
    register = tool.load_register(REGISTER)
    referred = [e for e in register.values() if e["disposition"] == "REFERRED"]
    assert referred, "no referred entries"
    for e in referred:
        assert e["note"], f"{e['slug']}: REFERRED with no note saying why"


def test_a_count_of_closures_is_not_a_count_of_sites():
    """UNFI's US/DC went 2 -> 4 on a finding labelled "DC closures and
    consolidations in FY2026". Sites being shut, added as sites gained."""
    import json
    spec = json.loads((ROOT / "samples" / "companies.json").read_text("utf-8"))
    unfi = next(c for c in spec["companies"] if c["slug"] == "unfi")
    assert any(r.get("country") == "US" and r.get("archetype") == "DC"
               for r in (unfi.get("excluded") or [])), (
        "country is optional in an exclusion - omitted means every country - "
        "so this must not subscript it")


# ------------------------------------------- how old the evidence is

OUT = ROOT / "samples" / "outside_in"
SPEC = ROOT / "samples" / "companies.json"


def test_a_site_count_carries_an_as_of_that_nothing_prices_on(tool):
    """The gap this check exists to close.

    A price has `expires`, and `coverage.expired_price_share` reports how
    much of the estate is priced on a rate past it. A site count has `as_of`
    and no equivalent: a promoted row records when the figure was true and
    nothing reads it, so a count from 2002 enters the estate weighted
    exactly like one from this year and no output says which is which.
    """
    import json
    dated = undated = 0
    for d in sorted(OUT.iterdir()):
        f = d / "research.json"
        if not (d.is_dir() and f.exists()):
            continue
        for row in (json.loads(f.read_text("utf-8")).get(
                "evidenced_footprint") or []):
            if row.get("as_of"):
                dated += 1
            else:
                undated += 1
    assert dated > 50, "as_of is recorded on most rows - the data is there"
    assert undated, (
        "every row is dated now; fold the undated branch of dated_changes "
        "into a hard failure rather than a report")


def test_a_row_with_no_date_is_reported_rather_than_skipped(tool):
    """The hole the first version of this check fell into.

    Tesco's Irish DC carries no as_of at all. Comparing a missing date
    against a cutoff silently passes, so the row nothing can be said about
    was the row nothing was said about. It is reported separately instead.
    """
    stale, undated = tool.dated_changes(OUT, SPEC, 2026)
    pairs = {(c["slug"], c["country"], c["archetype"]) for c in undated}
    assert ("tesco", "IE", "DC") in pairs
    assert not ({(c["slug"], c["country"], c["archetype"]) for c in stale}
                & pairs), "a change cannot be both dated and undated"


def test_a_fiscal_year_counts_as_a_date(tool):
    """Research writes "FY2025" and "FY2026 (Aug 2025 - Aug 2026)" as well as
    ISO dates. Reading the first four characters called both undated, which
    put two perfectly good dates in the list of rows that have none."""
    _, undated = tool.dated_changes(OUT, SPEC, 2026)
    pairs = {(c["slug"], c["country"], c["archetype"]) for c in undated}
    assert ("shell", "DE", "PLANT") not in pairs
    assert ("unfi", "US", "DC") not in pairs


def test_the_twenty_four_year_old_data_centre_is_found(tool):
    """Nestle's German DC entered the estate on a finding dated 2002 and
    labelled an IBM-era regional DC. Its Swiss sibling carries the same date
    and the words "sold to Orllati", and a third finding records no
    Nestle-owned DC in France at all - so the company's DC evidence
    describes an outsourcing estate since disposed of."""
    stale = tool.stale_evidence(OUT, SPEC, 2026)
    hit = next((c for c in stale if c["slug"] == "nestle"
                and c["country"] == "DE" and c["archetype"] == "DC"), None)
    assert hit, "the oldest evidence in the set is not being reported"
    assert hit["age"] >= 20


def test_the_stale_data_centre_was_excluded_not_merely_noted():
    import json
    spec = json.loads(SPEC.read_text("utf-8"))
    nestle = next(c for c in spec["companies"] if c["slug"] == "nestle")
    assert any(r.get("country") == "DE" and r.get("archetype") == "DC"
               for r in (nestle.get("excluded") or []))


def test_recent_evidence_is_not_flagged(tool):
    """Most of the set is current. A staleness check that fired on
    everything would be a count of changes wearing a different name."""
    stale = tool.stale_evidence(OUT, SPEC, 2026)
    found = tool.changes(OUT, SPEC)
    assert 0 < len(stale) < len(found), (
        f"{len(stale)} of {len(found)} flagged stale")


def test_every_stale_row_is_reported_oldest_first(tool):
    ages = [c["age"] for c in tool.stale_evidence(OUT, SPEC, 2026)]
    assert ages == sorted(ages, reverse=True)


def test_an_opening_date_is_not_the_same_as_a_stale_count(tool):
    """Shell's Amsterdam campus was flagged at four years old because its
    as_of is when the campus opened, not when somebody last counted it. The
    check cannot tell those apart, so a flag is a question for a reader
    rather than a defect - this one was answered VERIFIED."""
    register = tool.load_register(REGISTER)
    entry = register.get(("shell", "NL", "CAMPUS"))
    assert entry and entry["disposition"] == "VERIFIED"


def test_an_all_site_types_total_is_not_one_archetype():
    """BASF's researched 54 is labelled "all site types, Germany" and was
    promoted as PLANT on top of declared offices and DCs, making the German
    estate 73 against a source that says the whole of it is 54."""
    import json
    spec = json.loads((ROOT / "samples" / "companies.json").read_text("utf-8"))
    basf = next(c for c in spec["companies"] if c["slug"] == "basf")
    assert any(r.get("country") == "DE" and r.get("archetype") == "PLANT"
               for r in (basf.get("excluded") or []))

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
import collections
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


def test_the_register_records_refusals_and_not_only_acceptances(tool):
    """What this used to assert, and why it had to change.

    It required that MOST changes be unverified - the reasoning being
    that a register covering everything would have been written to match
    the output rather than the evidence. That was true while the register
    was 14 entries against 61 changes. Every change now carries a dated
    decision, so the shape of the guard has to move rather than be
    dropped.

    The thing actually worth protecting is that verifying was not a
    rubber stamp. A register where every entry says VERIFIED would mean
    nobody refused anything, which is not what checking 67 changes looks
    like: this one excluded the same network counted twice under two
    archetype names five times over, declined an apprenticeship
    announcement read as a site count, and referred four apportioned
    plant counts and three scope questions to an owner - who ruled on all
    seven on 2026-10-14, which is why REFERRED is now empty and not
    required below.
    """
    register = tool.load_register(REGISTER)
    kinds = collections.Counter(e["disposition"] for e in register.values())
    refused = sum(n for d, n in kinds.items() if d != "VERIFIED")
    assert kinds["VERIFIED"], "nothing verified"
    assert refused >= len(register) // 4, (
        f"only {refused} of {len(register)} entries refused anything "
        f"({dict(kinds)}) - a register that accepts everything put in "
        f"front of it has stopped being evidence")
    for name in ("EXCLUDED", "DECLINED"):
        assert kinds[name], f"no {name} entries - every refusal looks alike"
    # REFERRED is deliberately not required. All seven open referrals were
    # ruled on 2026-10-14 and the disposition emptied; requiring one would
    # mean keeping a question open to satisfy a test.


def test_every_change_now_carries_a_decision(tool):
    """The gap the external audit raised, closed. --strict exits 0."""
    register = tool.load_register(REGISTER)
    found = tool.changes(ROOT / "samples" / "outside_in",
                         ROOT / "samples" / "companies.json")
    bare = [(c["slug"], c["country"], c["archetype"]) for c in found
            if (c["slug"], c["country"], c["archetype"]) not in register]
    assert not bare, f"{len(bare)} changes with no dated entry: {bare[:5]}"


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


def test_referred_stays_available_even_with_nothing_outstanding(tool):
    """REFERRED is for a sound count whose membership of the estate is a
    scope judgement rather than a fact - Allianz's tied-agent offices,
    DHL's counters inside third-party shops, Iberdrola's wind farms, and
    four apportioned plant counts. Deciding one from a label would be
    inventing a policy, so they waited for an owner.

    All seven were ruled on 2026-10-14 and the disposition is now empty.
    This used to assert that referrals EXIST, which would now require
    keeping a question open to keep a test green. The disposition must
    stay available, and anything filed under it must still say why.
    """
    assert "REFERRED" in tool.DISPOSITIONS
    register = tool.load_register(REGISTER)
    for e in register.values():
        if e["disposition"] == "REFERRED":
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


def test_a_room_of_equipment_inside_a_building_is_not_a_site(tool):
    """Found by chasing a stale date and arriving somewhere worse.

    Tesco's Irish DC rested on an IT contractor's project page reading
    "Smart Hands call-outs to satellite IT rooms in Slough, Dundee, and
    Dublin". A room of equipment inside a building Tesco already occupies
    was promoted as a site, which invented an Irish building and gave it a
    data centre's bandwidth. The unit gate cannot catch it - the unit says
    "sites" and the disqualification is in the label, the same shape as
    the DIVESTED merchants.

    Built on a fixture rather than the published samples. The 20 October
    rerun re-researched Tesco and the IT-room label is no longer among its
    findings - the IE/DC exclusion still keeps the room out of the estate,
    but there is nothing left in the real data for this rule to catch, and
    a test that depends on what research happens to return stops testing
    the rule the day research returns something else.
    """
    import json
    import tempfile
    out = pathlib.Path(tempfile.mkdtemp()) / "out"
    (out / "tesco").mkdir(parents=True)
    (out / "tesco" / "research.json").write_text(json.dumps({
        "dispositions": [{"domain_no": 6, "evidence": {"quantities": [{
            "label": "DC – IE satellite IT room (Dublin)",
            "country": "IE", "value": 1, "unit": "sites"}]}}]}),
        encoding="utf-8")
    (out / "tesco" / "manifest.json").write_text(json.dumps({
        "footprint_provenance": [{"country": "IE", "archetype": "DC",
                                  "sites": 1, "origin": "RESEARCHED"}]}),
        encoding="utf-8")
    warned = tool.label_warnings(out)
    pairs = {(w["slug"], w["country"], w["archetype"]) for w in warned}
    assert ("tesco", "IE", "DC") in pairs


def test_the_room_rule_does_not_catch_real_premises(tool):
    """"room" would match Accor's hotel rooms and "satellite" would match
    Simmons Bank's West Little Rock satellite OFFICE, which is a building."""
    warned = tool.label_warnings(OUT)
    pairs = {(w["slug"], w["country"], w["archetype"]) for w in warned}
    assert ("accor", "FR", "HOTEL") not in pairs
    assert ("simmons-bank", "US", "LARGE_OFFICE") not in pairs


def test_every_change_old_enough_to_flag_carries_a_decision(tool):
    """The staleness report is only worth running if somebody answers it.
    Eight changes are three to twenty-four years old and each now has a
    disposition - two excluded, one declined, five verified or referred."""
    register = tool.load_register(REGISTER)
    stale, _ = tool.dated_changes(OUT, SPEC, 2026)
    missing = [(c["slug"], c["country"], c["archetype"]) for c in stale
               if (c["slug"], c["country"], c["archetype"]) not in register]
    assert not missing, f"stale changes with nobody's decision on them: {missing}"


def test_a_figure_the_company_still_publishes_is_verified_not_aged_out():
    """Nestle's French R&D and distribution centres were flagged at five
    years old. The cited page still states "4 centres de Recherche &
    Developpement" and "12 centres de distribution", so the age was a
    question and the answer was that the figures stand. A staleness check
    that excluded on age alone would have removed sixteen real sites."""
    rows = {(r["slug"], r["country"], r["archetype"]): r for r in _rows()}
    for arch in ("LARGE_OFFICE", "WAREHOUSE"):
        entry = rows.get(("nestle", "FR", arch))
        assert entry and entry["disposition"] == "VERIFIED", (
            f"nestle FR/{arch} has no verification")
        assert entry["evidence_ref"].startswith("https://www.nestle.fr")


def test_an_estate_priced_above_everything_research_found_is_reported(tool):
    """The opposite failure to a changed count, and invisible to the
    register because nothing changed.

    Nestle's French plants: three sources looked - the Office francais de
    la biodiversite at 18, nestle.fr at 13, an aggregator at 12 - and the
    estate prices 28, which is an apportionment of a published group
    factory total across ten countries rather than a figure anybody
    published about France. Research was refused on a 38% spread, the
    declared figure stood unchallenged, and nothing said that every source
    which looked said something smaller.
    """
    over = tool.priced_above_research(OUT, SPEC)
    # The case this was written for - Nestle FR, 28 declared against 18
    # found - was ruled on 2026-10-14 and the declaration corrected to 18,
    # so it correctly no longer appears. Germany is the same defect one
    # country across and still open at 13 against 12.
    hit = next((c for c in over if c["slug"] == "nestle"
                and c["country"] == "DE" and c["archetype"] == "PLANT"), None)
    assert hit, "the apportioned-overstatement case is not reported"
    assert hit["used"] > hit["highest_found"]
    assert hit["apportioned"], (
        "the CR-02b note is what separates an unsourced declaration from "
        "research simply being incomplete")
    assert not any(c["slug"] == "nestle" and c["country"] == "FR"
                   for c in over), (
        "the French plant count was ruled and should have left this report")


def test_the_apportioned_marker_distinguishes_the_two_causes(tool):
    """Most rows here are research being incomplete, not a declaration
    being wrong: one Tesco office found against twelve declared is
    research's limit. The marker is what makes the list readable."""
    over = tool.priced_above_research(OUT, SPEC)
    assert any(not c["apportioned"] for c in over), "no incomplete-research rows"
    assert any(c["apportioned"] for c in over), "no apportioned rows"


def test_the_report_separates_an_unexamined_figure_from_a_contested_one(tool):
    """Two tiers, because they ask different questions.

    NOTHING_SURVIVED means research produced no usable row and the
    declaration stands unexamined. APPORTIONED_BEATEN means research did
    produce one and lost to a declaration that is itself an apportionment
    of a group total. The delta-and-closure gate moved Nestle's French
    plants from the first tier into the second - the aggregator's 12 now
    classifies and promotes, then loses to the declared 28 - and a check
    that only reported the first would have quietly retired the case it
    was written for.
    """
    over = tool.priced_above_research(OUT, SPEC)
    kinds = {c["kind"] for c in over}
    assert kinds == {"NOTHING_SURVIVED", "APPORTIONED_BEATEN"}
    # Nestle FR was the case that forced the second tier into existence and
    # has since been ruled out of the report entirely. Both tiers still
    # carry rows, which is what this is really asserting.
    for kind in kinds:
        assert [c for c in over if c["kind"] == kind]


def test_every_unexamined_apportioned_figure_carries_a_referral(tool):
    """An unsourced figure standing above every source that looked, with
    nothing research found surviving to argue with it, is a decision for
    an owner - which legal entities count as Nestle France - not
    something the model may settle.

    Gated on the NOTHING_SURVIVED tier only. Requiring a referral for
    every apportioned row would demand twenty-one of them, and a register
    filled to satisfy a check has stopped being evidence.
    """
    register = tool.load_register(REGISTER)
    over = [c for c in tool.priced_above_research(OUT, SPEC)
            if c["apportioned"] and c["kind"] == "NOTHING_SURVIVED"]
    assert over, "the tier this gates on is empty"
    missing = [(c["slug"], c["country"], c["archetype"]) for c in over
               if (c["slug"], c["country"], c["archetype"]) not in register]
    assert not missing, f"apportioned overstatements with no referral: {missing}"


def test_one_network_counted_twice_under_two_archetypes_is_found(tool):
    """The largest footprint defect in the set, and the last one found.

    The merge keys on (country, archetype), so research typing a network
    differently from the declaration ADDS it rather than reconciling it.
    Simmons Bank's 222 "financial centres" beside its 230 declared
    branches was caught by hand months earlier; nobody looked for the
    same shape elsewhere. It was everywhere:

        fresenius    US  STORE 2,624 beside BRANCH 2,600
        saint-gobain FR  STORE 2,000 beside WAREHOUSE 900
        shell        DE  STORE 1,916 beside SERVICE_POINT 1,900
        bnp-paribas  FR  STORE 1,474 beside BRANCH 1,600
        shell        NL  STORE   662 beside SERVICE_POINT 500

    Eleven thousand phantom sites, a tenth of the set's baseline, and
    every one of them evidenced: the research is right and the
    declaration is right and they are the same buildings.
    """
    found = tool.archetype_collisions(OUT, SPEC)
    pairs = {(c["slug"], c["country"]) for c in found}
    for expected in (("fresenius", "US"), ("saint-gobain", "FR"),
                     ("shell", "DE"), ("bnp-paribas", "FR"),
                     ("simmons-bank", "US")):
        assert expected in pairs, f"{expected} not detected"


def test_the_collision_check_does_not_fire_on_different_buildings(tool):
    """A warehouse is not a shop, and the pairs are listed rather than
    inferred. Without that constraint the check returns 22 rows including
    a one-site warehouse beside a one-site data centre, which is two
    buildings and not one network."""
    found = tool.archetype_collisions(OUT, SPEC)
    for c in found:
        assert frozenset({c["archetype"], c["declared_as"]}) \
            in tool.SAME_PREMISES
    pairs = {(c["slug"], c["country"], c["archetype"]) for c in found}
    assert ("lufthansa", "DE", "WAREHOUSE") not in pairs
    assert ("victorias-secret", "US", "WAREHOUSE") not in pairs


def test_every_collision_carries_a_decision(tool):
    """Nine found, nine recorded. A detector whose output nobody acts on
    is the condition this whole register exists to end."""
    register = tool.load_register(REGISTER)
    live = [(c["slug"], c["country"], c["archetype"])
            for c in tool.archetype_collisions(OUT, SPEC)
            if (c["slug"], c["country"], c["archetype"]) not in register]
    assert not live, f"collisions with no register entry: {live}"


def test_an_all_site_types_total_is_not_one_archetype():
    """BASF's researched 54 is labelled "all site types, Germany" and was
    promoted as PLANT on top of declared offices and DCs, making the German
    estate 73 against a source that says the whole of it is 54."""
    import json
    spec = json.loads((ROOT / "samples" / "companies.json").read_text("utf-8"))
    basf = next(c for c in spec["companies"] if c["slug"] == "basf")
    assert any(r.get("country") == "DE" and r.get("archetype") == "PLANT"
               for r in (basf.get("excluded") or []))


def test_a_divestment_is_not_a_measurement_of_the_estate(tool):
    """What priced_above_research asks is: what is the highest figure
    research found for this pair? A divestment is not that.

    BASF's Brazilian row is the case. The only (BR, PLANT) finding is
    "PLANT sites divested in Brazil - sale of decorative paints business
    to Sherwin-Williams" at 2 - the Demarchi and Jaboatao plants it SOLD.
    Read as a count it made the declared 11 look like a 5.5x
    overstatement of something research had measured, when research had
    measured nothing, and the referral test then demanded an owner ruling
    on a non-issue.
    """
    over = tool.priced_above_research(OUT, SPEC)
    pairs = {(c["slug"], c["country"], c["archetype"]) for c in over}
    assert ("basf", "BR", "PLANT") not in pairs


def test_the_check_still_reports_real_overstatements(tool):
    """The filter must not empty the report. Nestle's German plants are
    still 13 in the estate against 12 found."""
    over = tool.priced_above_research(OUT, SPEC)
    assert len(over) > 10
    assert any(c["slug"] == "nestle" and c["archetype"] == "PLANT"
               for c in over)

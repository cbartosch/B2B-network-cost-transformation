"""Tier 3: a research finding reaching the numbers the estimate actually uses.

Before this, `quantities` was written into domain_disposition.evidence and
read by nothing - the footprint came from what an analyst typed, so a perfect
answer on domain 2 moved the confidence score and not one number in the
estimate. These cover the promotion path and, as importantly, its limits.
"""
import re
import uuid

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import promotion


def _case_with_finding(session, quantity, disposition="EVIDENCED_PUBLIC"):
    case_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    # A real quantity carries the candidates it was triangulated from, and
    # each candidate names the document it was read out of. The fixture
    # omitted them, so it could not have caught a promoted row citing the
    # domain's whole source pool instead of its own evidence.
    quantity = {"candidates": [{"value": quantity.get("value"),
                                "source_url": "https://example.com/ar"}],
                **quantity}
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=2, domain_name="Location footprint",
        disposition=disposition, reason=None, agent_run_id=run_id,
        evidence={"quantities": [quantity],
                  "sources": [{"url": "https://example.com/ar"}]}))
    session.commit()
    return case_id, run_id


def test_a_site_count_reaches_the_footprint_the_simulation_reads(session):
    q = {"label": "WAREHOUSE", "value": 340, "unit": "sites",
         "country": "DE", "as_of": "2024-12-31"}
    case_id, run_id = _case_with_finding(session, q)

    cands = promotion.candidates(session, case_id)
    assert len(cands["footprint_candidates"]) == 1
    cid = cands["footprint_candidates"][0]["candidate_id"]

    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")

    fp = promotion.evidenced_footprint(session, case_id)
    # Exact equality kept deliberately - it catches a field being dropped as
    # well as a value changing. The row has since grown its provenance
    # (domain_no, the band, the source count and the URLs) and the literal was
    # never extended, so the only thing this asserted was that the shape had
    # not moved. Every value it did name was already correct.
    assert fp == [{"country": "DE", "archetype": "WAREHOUSE", "sites": 340,
                   "as_of": "2024-12-31", "agent_run_id": run_id,
                   "promoted_by": "Priya Raman", "domain_no": 2,
                   "band_low": None, "band_high": None, "source_count": None,
                   "source_urls": ["https://example.com/ar"]}]


def test_a_row_cites_its_own_evidence_not_the_domains_pool(session):
    """Which document says this number.

    Every promoted row used to carry `evidence.sources` - everything the
    research domain read, across all of its findings - so two site counts
    from one domain cited the same list. In the published set that averaged
    7.7 URLs against 1.8 actually behind the figure, and Nestle's French
    office row cited a swissinfo piece about a German factory closing. A
    reader checking the number had no way to tell which link to open, which
    is most of why verifying a changed count is hand work.
    """
    case_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=2, domain_name="Location footprint",
        disposition="EVIDENCED_PUBLIC", reason=None, agent_run_id=run_id,
        evidence={"quantities": [
            {"label": "WAREHOUSE", "value": 12, "unit": "sites",
             "country": "DE", "as_of": "2025",
             "candidates": [{"value": 12,
                             "source_url": "https://example.com/warehouses"}]},
            {"label": "STORE", "value": 400, "unit": "sites",
             "country": "FR", "as_of": "2025",
             "candidates": [{"value": 400,
                             "source_url": "https://example.com/stores"}]}],
            "sources": [{"url": "https://example.com/warehouses"},
                        {"url": "https://example.com/stores"},
                        {"url": "https://example.com/unrelated-press"}]}))
    session.commit()

    cands = promotion.candidates(session, case_id)["footprint_candidates"]
    promotion.promote(session, case_id=case_id,
                      candidate_ids=[c["candidate_id"] for c in cands],
                      promoted_by="Priya Raman")

    cited = {r["archetype"]: r["source_urls"]
             for r in promotion.evidenced_footprint(session, case_id)}
    assert cited["WAREHOUSE"] == ["https://example.com/warehouses"]
    assert cited["STORE"] == ["https://example.com/stores"]
    for urls in cited.values():
        assert "https://example.com/unrelated-press" not in urls


def test_a_finding_with_no_document_cites_nothing(session):
    """Six findings in the published set have no candidate URL at all, and
    none of them has a document behind it: EUR/EUR is 1.0 because the
    countries are all eurozone, three IT-spend proxies are 3/4/5% of net
    sales, and two are explicit negatives - no Inditex DC found in France or
    Germany. Lending those the domain's pool would make a derivation and a
    dead end look sourced."""
    case_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=2, domain_name="Location footprint",
        disposition="EVIDENCED_PUBLIC", reason=None, agent_run_id=run_id,
        evidence={"quantities": [
            {"label": "DC", "value": 0, "unit": "sites", "country": "FR",
             "as_of": "2024",
             "candidates": [{"value": 0, "source_url": None,
                             "publisher": "No source found"}]}],
            "sources": [{"url": "https://example.com/ar"}]}))
    session.commit()

    cid = promotion.candidates(
        session, case_id)["footprint_candidates"][0]["candidate_id"]
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")
    row = promotion.evidenced_footprint(session, case_id)[0]
    assert row["source_urls"] == []


def _case_with_band(session, quantity, triangulated):
    case_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=2, domain_name="Location footprint",
        disposition="EVIDENCED_PUBLIC", reason=None, agent_run_id=run_id,
        evidence={"quantities": [quantity], "triangulated": [triangulated],
                  "sources": [{"url": "https://example.com/ar"}]}))
    session.commit()
    return case_id


def test_a_refusal_names_the_reason_it_actually_failed(session):
    """review_required fires on three flags and the refusal reported one.

    Nestle's German plant count is a unit mismatch between two sources
    both stating 12, so the refusal read "sources disagree by 0% (12 to
    12)" - a sentence that invites an analyst to dismiss it as noise.
    """
    q = {"label": "PLANT", "value": 12, "unit": "sites", "country": "DE",
         "as_of": "2024",
         "candidates": [{"value": 12, "source_url": "https://example.com/a"}]}
    case_id = _case_with_band(session, q, {
        "label": "PLANT", "country": "DE", "low": "12", "high": "12",
        "base": "12", "spread_share": 0.0, "candidate_count": 2,
        "flags": ["UNIT_MISMATCH", "SINGLE_SOURCE"], "review_required": True})
    cid = promotion.candidates(
        session, case_id)["footprint_candidates"][0]["candidate_id"]
    out = promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                            promoted_by="Priya Raman")
    assert len(out["declined"]) == 1
    reason = out["declined"][0]["reason"]
    assert "units" in reason, reason
    assert "disagree by 0%" not in reason, reason


def test_a_refusal_names_what_was_refused(session):
    """A manifest reading "sources disagree by 38% (13 to 18)" beside no
    subject cannot be acted on. Nestle's was its French plant count, and
    finding that out meant re-deriving it from the triangulated bands."""
    q = {"label": "PLANT (industrial sites) - France", "value": 18,
         "unit": "sites", "country": "FR", "as_of": "2024",
         "candidates": [{"value": 18, "source_url": "https://example.com/a"}]}
    case_id = _case_with_band(session, q, {
        "label": "PLANT (INDUSTRIAL SITES) - FRANCE", "country": "FR",
        "low": "13", "high": "18", "base": "15.5", "spread_share": 0.3846,
        "candidate_count": 2, "flags": ["MATERIAL_SPREAD"],
        "review_required": True})
    cid = promotion.candidates(
        session, case_id)["footprint_candidates"][0]["candidate_id"]
    out = promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                            promoted_by="Priya Raman")
    row = out["declined"][0]
    assert row["country"] == "FR"
    assert "PLANT" in row["label"]
    assert row["flags"] == ["MATERIAL_SPREAD"]
    assert "38%" in row["reason"]


def test_promotion_requires_a_named_person(session):
    q = {"label": "WAREHOUSE", "value": 12, "unit": "sites", "country": "GB"}
    case_id, _ = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["footprint_candidates"][0]["candidate_id"]
    with pytest.raises(promotion.NotPromotable):
        promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                          promoted_by="")


def test_a_promoted_price_is_unapproved_and_carries_its_provenance(session):
    """18.1: research proposes a governed value, it does not set one. An
    approved row would put a model's answer straight into every estimate with
    no steward in between."""
    # bandwidth_mbps as a field, not only inside the label. promote() reads
    # q["bandwidth_mbps"] and declines a rate with no tier - "a circuit rate
    # without a tier cannot be matched to any circuit" - which is deliberate:
    # a null-bandwidth row would sit in unit_cost_prior pricing nothing while
    # counting as coverage, the exact condition migration v17 deletes rows
    # for. So the candidate was declined and no row was ever written, and
    # this test failed on NoResultFound without reaching what it asserts.
    q = {"label": "DIA 100Mbps MRC", "value": 520, "unit": "USD/month",
         "country": "DE", "as_of": "2025", "bandwidth_mbps": 100}
    case_id, run_id = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["price_candidates"][0]["candidate_id"]

    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")

    row = session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.country == "DE",
        db.unit_cost_prior.c.product == "DIA",
        db.unit_cost_prior.c.approved.is_(False))).one()
    assert row.source_agent_run_id == run_id
    assert "Priya Raman" in row.source_note


def test_an_unusable_quantity_is_declined_rather_than_coerced(session):
    """A finding this model cannot consume is not a bad finding. Coercing
    'a large European network' into a site count would be silent; declining
    it is visible."""
    q = {"label": "network scale", "value": 220, "unit": "countries served"}
    case_id, _ = _case_with_finding(session, q)
    cands = promotion.candidates(session, case_id)
    assert not cands["footprint_candidates"]
    assert len(cands["unclassified"]) == 1


def test_promoting_the_same_finding_twice_replaces_rather_than_duplicates(session):
    q = {"label": "WAREHOUSE", "value": 340, "unit": "sites", "country": "DE"}
    case_id, _ = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["footprint_candidates"][0]["candidate_id"]
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="A")
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="B")
    fp = promotion.evidenced_footprint(session, case_id)
    assert len(fp) == 1 and fp[0]["promoted_by"] == "B"


# --- researched price vs the benchmark it would displace --------------------
def _benchmark(session, country="DE", product="DIA", low=420, base=580,
               high=800, bandwidth_mbps=None):
    # bandwidth_mbps defaults to None so the compare_to_benchmark tests keep
    # the untiered row they were written against. Only the promotion test
    # needs a tier, and it needs one because promote() will not compare a
    # 100 Mbps observation against a benchmark at no stated tier: that would
    # be a comparison of different products, so it reports
    # NO_BENCHMARK_AT_BANDWIDTH rather than judging it.
    session.execute(insert(db.unit_cost_prior).values(
        id=f"{country}-{product}", country=country, product=product,
        cost_layer="L0", low=low, base=base, high=high, currency="USD",
        price_year=2026, approved=True, bandwidth_mbps=bandwidth_mbps))
    session.commit()


def _policy(share="0.25"):
    from decimal import Decimal
    from app.domain.policy import PriceDivergencePolicy
    return PriceDivergencePolicy(set_name="t",
                                 material_divergence_share=Decimal(share))


def test_a_price_inside_the_band_corroborates_rather_than_contradicts(session):
    _benchmark(session)
    r = promotion.compare_to_benchmark(session, country="DE", product="DIA",
                                       value=520, policy=_policy())
    assert r["verdict"] == "WITHIN_BAND" and r["material"] is False


def test_a_materially_divergent_price_is_flagged_not_absorbed(session):
    """The gap this closes: a researched price landed unapproved with no
    comparison recorded, so a figure 60% off the governed band looked exactly
    like one that confirmed it. The disagreement is the finding."""
    _benchmark(session)
    r = promotion.compare_to_benchmark(session, country="DE", product="DIA",
                                       value=1280, policy=_policy())
    assert r["verdict"] == "OUTSIDE_BAND" and r["material"] is True
    assert r["direction"] == "above"


def test_divergence_is_measured_from_the_nearest_edge_not_the_midpoint(session):
    """A benchmark is a range. Measuring from the centre would call a price
    just outside a wide band a large disagreement."""
    _benchmark(session)
    r = promotion.compare_to_benchmark(session, country="DE", product="DIA",
                                       value=880, policy=_policy())
    assert r["divergence_share"] == pytest.approx(80 / 800, abs=1e-4)
    assert r["material"] is False


def test_a_country_with_no_benchmark_is_new_coverage_not_silence(session):
    r = promotion.compare_to_benchmark(session, country="AE", product="DIA",
                                       value=1300, policy=_policy())
    assert r["verdict"] == "NO_BENCHMARK" and r["material"] is False


def test_promotion_records_the_comparison_where_a_steward_will_see_it(session):
    _benchmark(session, bandwidth_mbps=100)
    # Same missing tier as above: declined before any comparison was made,
    # so material_divergences was empty rather than disagreeing.
    q = {"label": "DIA 100Mbps MRC", "value": 1280, "unit": "USD/month",
         "country": "DE", "as_of": "2025", "bandwidth_mbps": 100}
    case_id, _ = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["price_candidates"][0]["candidate_id"]

    out = promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                            promoted_by="Priya Raman",
                            divergence_policy=_policy())

    assert len(out["material_divergences"]) == 1
    row = session.execute(select(db.unit_cost_prior).where(
        # The tier is part of the key: row_id is
        # f"{country}-{product}-{mbps}-researched", because a promoted price
        # reachable only through the legacy fallback was the defect fixed in
        # 4.177. The literal here predates that.
        db.unit_cost_prior.c.id == "DE-DIA-100-researched")).one()
    assert row.approved is False
    assert "OUTSIDE_BAND" in row.source_note


def test_the_evidenced_footprint_carries_its_provenance(session):
    """The band and source count were added to the table in v22 and the
    accessor never selected them, so the interface could only show a bare
    number. A bare number cannot say whether three sources agreed on it or
    one source stated it - the difference between a count worth building an
    estimate on and one worth checking first."""
    q = {"label": "STORE", "value": 371, "unit": "sites", "country": "DE",
         "as_of": "2023"}
    case_id, run_id = _case_with_finding(session, q)
    cid = promotion.candidates(session, case_id)["footprint_candidates"][0]["candidate_id"]
    promotion.promote(session, case_id=case_id, candidate_ids=[cid],
                      promoted_by="Priya Raman")

    row = promotion.evidenced_footprint(session, case_id)[0]
    for field in ("band_low", "band_high", "source_count", "domain_no",
                  "source_urls", "agent_run_id", "as_of", "promoted_by"):
        assert field in row, f"{field} is not returned to the interface"
    assert row["agent_run_id"] == run_id


def test_a_string_value_can_still_be_classified(session):
    """A live break found while tracing the disposition-to-simulation chain.

    `value` became a string in 4.104.0 so a source stating "2 halls, 2.75 MW"
    could be kept as a qualitative finding instead of failing the schema. This
    classifier still tested isinstance(value, (int, float)), so from that
    release every quantity classified as unclassified and nothing at all could
    be promoted. The two changes were three releases apart and nothing
    connected them."""
    assert promotion._classify(
        {"label": "STORE", "country": "DE", "unit": "sites",
         "value": "341"}) == "footprint"
    assert promotion._classify(
        {"label": "DIA 100Mbps MRC", "country": "US", "unit": "USD/month",
         "value": "477.5"}) == "price"
    assert promotion._classify(
        {"label": "STORE", "country": "DE", "unit": "sites",
         "value": "2 halls, 2.75 MW"}) == "unclassified"


def test_only_counts_and_prices_can_reach_the_estimate(session):
    """The chain is deliberately narrow, and the narrowness is worth asserting:
    a quantity is routed only where it plainly carries what that destination
    needs, and everything else is declined visibly rather than guessed at."""
    for label, unit in (("HEADCOUNT", "people"), ("REVENUE", "EUR"),
                        ("DUAL_ACCESS", "percent")):
        assert promotion._classify(
            {"label": label, "country": "DE", "unit": unit,
             "value": "100"}) == "unclassified"


def test_every_classification_target_has_a_candidate_bucket():
    """The gap behind "I am not seeing how simulation connects to domain
    disposition data".

    _classify gained "archetype" and "anchor" and the bucket dict in
    candidates() did not, so buckets[target] raised KeyError the moment
    research produced one. Both the classification and the promote branch
    existed and nothing could reach them, because the list an analyst selects
    from was never built - the plumbing was in and the tap was not attached.
    """
    import ast
    import inspect

    from app.domain import promotion

    classify = inspect.getsource(promotion._classify)
    targets = set(re.findall(r'return "(\w+)"', classify))

    src = inspect.getsource(promotion.candidates)
    buckets = set(re.findall(r'"(\w+)"', src[src.index("buckets"):
                                             src.index("for entry in found")]))
    missing = targets - buckets
    assert not missing, f"_classify can return {sorted(missing)} with no bucket"


def test_candidates_surfaces_each_target_for_promotion():
    """A bucket nobody returns is a finding nobody can select."""
    import inspect
    from app.domain import promotion
    src = inspect.getsource(promotion.candidates)
    for key in ("footprint_candidates", "price_candidates",
                "archetype_candidates", "anchor_candidates"):
        assert f'"{key}"' in src, key
    for key in ("already_promoted_archetype", "already_promoted_anchor"):
        assert f'"{key}"' in src, (
            f"{key} - what is already promoted has to be visible or an analyst "
            f"cannot tell whether a finding took effect")


def test_the_review_panel_offers_every_target():
    """Surfaced by the API and not rendered is the same dead end one layer up."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    page = (root / "analyst_ui" / "streamlit_app" / "pages"
            / "4_Domain_dispositions.py").read_text()
    for key in ("archetype_candidates", "anchor_candidates"):
        assert key in page, key
    assert "feeds the simulation" in page, (
        "an analyst has to be told what promoting a topology field changes")

# ------------------------------- the label the prompt actually asks agents for

def test_an_archetype_named_with_its_mapping_still_reaches_the_footprint(session):
    """`label in ARCHETYPES` required the label to be nothing but the
    archetype, and the research prompt asks for the opposite.

    The archetype block tells the agent to "say in `finding` which mapping
    you chose and why", so a well-behaved agent returns
    "SERVICE_POINT - Iberdrola customer service and sales points". That fell
    through to unclassified every time, while an agent that ignored the
    instruction and emitted a bare "PLANT" classified fine.

    The sample set is the evidence: one company's agent described its
    mappings and produced 103 findings with 0 classified; another emitted
    bare labels and promoted 7 rows. The classifier worked only when the
    agent omitted what it had been asked for.
    """
    q = {"label": "SERVICE_POINT - Iberdrola customer service and sales points",
         "value": 650, "unit": "sites", "country": "ES", "as_of": "2025-06-30"}
    case_id, _ = _case_with_finding(session, q)
    cands = promotion.candidates(session, case_id)
    assert len(cands["footprint_candidates"]) == 1, (
        f"a described mapping was not offered: {cands['unclassified']}")
    assert not cands["unclassified"]


def test_the_classifier_and_the_writer_resolve_a_label_the_same_way(session):
    """What actually protects: a label the classifier accepted cannot be
    stored as something else.

    This asserted that both branches shared one leading-token helper, which
    was the implementation rather than the invariant. The two branches have
    genuinely different inputs - the brief asks for "ARCHETYPE - description"
    so an archetype leads, while research leads with the market and returns
    "US DIA 1 Gbps MRC" against a brief whose own example is "DIA 100Mbps
    MRC". Pinning them to one rule declined four real market medians on word
    order.

    So each branch has its own resolver and both are shared with promote().
    That is the property; the symmetry never was.
    """
    import inspect

    classify = inspect.getsource(promotion._classify)
    writer = inspect.getsource(promotion.promote)
    for resolver in ("archetype_of", "product_in"):
        assert resolver in classify, f"_classify should use {resolver}"
        assert resolver in writer, (
            f"promote() must resolve with {resolver}, or it can store "
            f"something the classifier never matched")
    assert promotion.archetype_of("SERVICE_POINT - a long description here")         == "SERVICE_POINT"
    assert promotion.product_in("US DIA 1 Gbps MRC - median") == "DIA"


def test_a_label_naming_two_archetypes_is_still_declined(session):
    """Widening the match must not make it a guess. "WAREHOUSE/BRANCH" names
    two, and a wrong promotion is silent where a declined one is visible."""
    q = {"label": "WAREHOUSE/BRANCH - operational offices and depots",
         "value": 34, "unit": "sites", "country": "GB", "as_of": "2024-12-31"}
    case_id, _ = _case_with_finding(session, q)
    cands = promotion.candidates(session, case_id)
    assert not cands["footprint_candidates"]
    assert len(cands["unclassified"]) == 1


def test_a_count_whose_unit_is_not_sites_is_still_declined(session):
    """30,000 distribution substations is a real finding and not a WAN site
    count. The unit gate is what keeps that judgement with a person."""
    q = {"label": "NETWORK_SITE - SP Energy Networks distribution substations",
         "value": 30000, "unit": "substations", "country": "GB",
         "as_of": "2024-12-31"}
    case_id, _ = _case_with_finding(session, q)
    cands = promotion.candidates(session, case_id)
    assert not cands["footprint_candidates"]
    assert len(cands["unclassified"]) == 1

def test_the_archetype_stored_is_the_one_the_classifier_matched(session):
    """_classify matched the leading token and promote() stored the whole
    label. They were the same string only while the classifier demanded a
    bare archetype name; widening it made them differ, and 56 characters went
    into archetype varchar(48) - every promotion 500'd.

    The length was the lesser half. The simulation keys archetypes by name,
    so a stored description would be a footprint row for an archetype that
    does not exist, priced at the DEFAULT prior, with the estate looking
    enumerated. The column being too short is the only reason it was visible.
    """
    q = {"label": "SERVICE_POINT - Iberdrola customer service and sales points",
         "value": 650, "unit": "sites", "country": "ES", "as_of": "2025-06-30"}
    case_id, _ = _case_with_finding(session, q)
    cands = promotion.candidates(session, case_id)
    ids = [c["candidate_id"] for c in cands["footprint_candidates"]]
    assert ids

    promotion.promote(session, case_id=case_id, candidate_ids=ids,
                      promoted_by="tester")
    rows = session.execute(select(db.evidenced_footprint).where(
        db.evidenced_footprint.c.case_id == case_id)).all()
    assert len(rows) == 1
    assert rows[0].archetype == "SERVICE_POINT", (
        f"stored {rows[0].archetype!r}, which is not an archetype the "
        f"simulation knows")
    assert rows[0].sites == 650
    assert len(rows[0].archetype) <= 48

def test_the_archetype_names_agree_with_themselves(session):
    """`in` and `set()` must answer the same question.

    ARCHETYPES was a frozenset subclass constructed empty, with Python-level
    __contains__ and __iter__ overrides. The C fast paths behind set(),
    list(), sorted() and the set operators read the empty underlying storage
    and never call __iter__, so "LARGE_OFFICE" in ARCHETYPES was True while
    set(ARCHETYPES) was empty - the same object answering two forms of one
    question differently.

    Product code only ever asks `in`, so nothing in the service was wrong.
    A caller outside it did `known = set(ARCHETYPES)`, concluded every
    archetype was unknown, and deleted 75 rows of promoted footprint
    evidence before anyone noticed.
    """
    from app.domain import promotion

    names = set(promotion.ARCHETYPES)
    assert names, "set() over the archetype names came back empty"
    assert len(names) == len(promotion.ARCHETYPES)
    assert sorted(names) == sorted(promotion.ARCHETYPES)
    for n in names:
        assert n in promotion.ARCHETYPES
    # The two spellings a caller might reach for, agreeing.
    assert "LARGE_OFFICE" in promotion.ARCHETYPES
    assert "LARGE_OFFICE" in set(promotion.ARCHETYPES)
    assert "NOT_AN_ARCHETYPE" not in promotion.ARCHETYPES
    assert "NOT_AN_ARCHETYPE" not in set(promotion.ARCHETYPES)

def test_a_value_the_classifier_accepts_is_a_value_promotion_can_write(session):
    """The classifier admits a quantity when triangulate.parse_value can read
    it - "1,250", "2.75", "3 million", "~10". The writer called int() on the
    raw string, so a candidate this module offered, and a person chose to
    promote, returned 500:

        ValueError: invalid literal for int() with base 10: '~10'

    Lufthansa lost all seven of its footprint rows to it and was priced from
    public disclosure alone, with nothing in the response saying which
    finding was at fault.
    """
    from sqlalchemy import select

    from app import db

    for raw, expected in (("~10", 10), ("1,250", 1250), ("341.0", 341),
                          (12, 12)):
        q = {"label": "LARGE_OFFICE - named operating sites", "value": raw,
             "unit": "sites", "country": "DE", "as_of": "2025-12-31"}
        case_id, _ = _case_with_finding(session, q)
        cands = promotion.candidates(session, case_id)
        assert cands["footprint_candidates"], f"{raw!r} was not offered"
        promotion.promote(
            session, case_id=case_id,
            candidate_ids=[c["candidate_id"]
                           for c in cands["footprint_candidates"]],
            promoted_by="tester")
        sites = session.execute(select(db.evidenced_footprint.c.sites).where(
            db.evidenced_footprint.c.case_id == case_id)).scalar()
        assert sites == expected, f"{raw!r} promoted as {sites}, want {expected}"


def test_a_value_nothing_can_read_is_refused_not_defaulted(session):
    """Unreachable through _classify, which declines it first. Guarded
    anyway: a site count nobody could parse must not quietly become 0 or 1.
    """
    import pytest

    with pytest.raises(ValueError, match="no readable value"):
        promotion._sites_from({"label": "LARGE_OFFICE", "value": "a handful"})


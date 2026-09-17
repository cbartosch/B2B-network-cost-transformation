"""What counts as a site.

The case declared which countries, which cost layers, which service families
and which legal entities were in scope, and nothing about what a *site* is. So
a footprint of 5,230 was unanswerable: hypermarkets only, all banners,
franchise convenience stores, every connected location?

It surfaced when a thirty-company run was checked against public store counts.
One figure was a store count and the other was connected locations in a single
country - both defensible, neither stated, and the disagreement unresolvable
because nobody had written the rule down.

A site count is the largest single driver of the baseline and was the one
number with no stated basis.
"""
import pytest

from app.domain import site_rule


def _full(**over):
    fields = dict(basis=site_rule.CONNECTED_LOCATION,
                  includes=["FRANCHISE", "SHARED_TENANCY"],
                  excludes=["UNMANNED", "SEASONAL", "PARTNER_OPERATED",
                            "UNDER_CONSTRUCTION"])
    fields.update(over)
    return site_rule.rule(**fields)


def test_a_rule_without_a_basis_is_refused():
    """Without a basis a count has no unit - 5,230 of what?"""
    with pytest.raises(site_rule.RuleInvalid, match="no unit"):
        site_rule.rule(basis="LOTS")


def test_a_complete_rule_leaves_nothing_undecided():
    rule = _full()
    assert rule["undecided"] == []
    assert rule["complete"] is True


def test_an_undecided_category_is_reported_not_defaulted():
    """A rule silent on franchise locations is the rule that produced the
    disagreement: one reader assumed they were in, the other assumed out, and
    both were reading the same number."""
    rule = site_rule.rule(basis=site_rule.OPERATED_FACILITY,
                          excludes=["UNMANNED"])
    assert "FRANCHISE" in rule["undecided"]
    assert rule["complete"] is False


def test_a_category_in_both_lists_is_refused():
    with pytest.raises(site_rule.RuleInvalid, match="does not say what it"):
        _full(includes=["FRANCHISE"], excludes=["FRANCHISE"])


def test_an_unknown_category_is_refused():
    """A category nobody named is one nobody can check."""
    with pytest.raises(site_rule.RuleInvalid, match="not things this rule"):
        _full(includes=["SHOPS_I_LIKE"])


def test_a_major_site_basis_needs_its_threshold():
    """Otherwise it means whatever the person counting thought it meant."""
    with pytest.raises(site_rule.RuleInvalid, match="makes a site major"):
        site_rule.rule(basis=site_rule.MAJOR_SITE,
                       includes=list(site_rule.INCLUSIONS))
    ok = site_rule.rule(basis=site_rule.MAJOR_SITE,
                        includes=list(site_rule.INCLUSIONS),
                        minimum_headcount=50)
    assert ok["minimum_headcount"] == 50


def test_the_bases_are_ordered_widest_to_narrowest():
    """Each is a subset of the one before, which is what makes two counts on
    different rules comparable in a stated direction."""
    order = [site_rule.BREADTH[b] for b in
             (site_rule.CONNECTED_LOCATION, site_rule.OPERATED_FACILITY,
              site_rule.OWNED_PREMISES, site_rule.MAJOR_SITE)]
    assert order == sorted(order, reverse=True)


def test_geography_is_checked_before_the_rule():
    """The defect in the first version of this module. It compared a
    France-only footprint of 5,230 against a global store count of 14,000 and
    reported a contradiction on breadth - the wider rule returning the smaller
    count. The rule was wider and the geography was a fraction, and a
    comparison that ignores the second calls a correct footprint wrong."""
    out = site_rule.compare(
        left_count=5230, left_rule=_full(), left_scope=["FR", "NL"],
        right_count=14000,
        right_rule=site_rule.rule(basis=site_rule.OPERATED_FACILITY,
                                  includes=list(site_rule.INCLUSIONS)),
        right_scope=["FR", "NL", "ES", "IT", "BE", "BR", "PL"])
    assert out["comparable"] is False
    assert out["reason"] == "different geography"
    assert "contradiction" not in out


def test_the_same_rule_and_geography_is_a_real_disagreement():
    """5,230 against 5,700 on one rule in one country is a question about the
    estate, and the model should say so rather than hedging."""
    rule = _full()
    out = site_rule.compare(left_count=5230, left_rule=rule,
                            left_scope=["FR"], right_count=5700,
                            right_rule=rule, right_scope=["FR"])
    assert out["comparable"] is True
    assert out["difference"] == "470"


def test_different_rules_on_one_geography_answer_different_questions():
    """And the difference is not an error in either."""
    # The wider rule has to return the larger count. My first version of this
    # test had CONNECTED_LOCATION at 5,230 against OPERATED_FACILITY at 6,100
    # - a genuine contradiction - and asserted there was none.
    out = site_rule.compare(
        left_count=6100, left_rule=_full(), left_scope=["FR"],
        right_count=5230,
        right_rule=site_rule.rule(basis=site_rule.OPERATED_FACILITY,
                                  includes=list(site_rule.INCLUSIONS)),
        right_scope=["FR"])
    assert out["comparable"] is False
    assert "different questions" in out["note"]
    assert out["contradiction"] is None


def test_a_wider_rule_returning_a_smaller_count_is_flagged():
    """On one geography that cannot both be true.

    The narrow rule must be narrower on BOTH axes. This asserted a
    contradiction against a MAJOR_SITE rule that included every category -
    narrower basis, wider inclusions - and neither rule contains the other,
    so no direction was ever available. A CONNECTED_LOCATION rule excluding
    franchise is genuinely narrower than an OPERATED_FACILITY rule including
    it, and calling the first "wider" accused a correct pair of counts of
    being impossible."""
    narrow = site_rule.rule(basis=site_rule.MAJOR_SITE,
                            includes=["FRANCHISE"],
                            excludes=[i for i in site_rule.INCLUSIONS
                                      if i != "FRANCHISE"],
                            minimum_headcount=50)
    out = site_rule.compare(left_count=400, left_rule=_full(),
                            left_scope=["FR"], right_count=900,
                            right_rule=narrow, right_scope=["FR"])
    assert out["contradiction"] is not None


@pytest.mark.parametrize("source,grade", [
    ("FILING", "B"), ("STORE_LOCATOR", "C"),
    ("CLIENT_STATED", "C"), ("ANALYST_ESTIMATE", "E"),
])
def test_the_grade_follows_from_the_source(source, grade):
    """A store locator is the company's own published data and beats an
    estimate; it is not a filing, because a locator changes daily and nobody
    signs it."""
    assert site_rule.grade_of(source) == grade


def test_an_unknown_source_is_ungradeable():
    with pytest.raises(site_rule.RuleInvalid, match="ungradeable"):
        site_rule.grade_of("SOMEBODY_SAID")


def test_an_incomplete_rule_becomes_a_named_assumption():
    """An undecided inclusion is an assumption with a known direction: the
    count is either too high or too low by that category's number."""
    entry = site_rule.as_assumption(
        site_rule.rule(basis=site_rule.OPERATED_FACILITY),
        case_id="c", raised_by="Jane Okafor")
    assert entry["gap"] == "site-inclusion rule incomplete"
    assert "franchise" in entry["detail"]
    assert entry["raised_by"] == "Jane Okafor"


def test_a_complete_rule_raises_no_assumption():
    assert site_rule.as_assumption(_full(), case_id="c",
                                   raised_by="Jane Okafor") == {}


def test_the_rule_prints_short_enough_to_sit_beside_a_number():
    """A count shown without its rule is the thing this prevents, so the rule
    has to fit in a footnote."""
    assert len(_full()["summary"]) < 200


def test_the_rule_is_pinned_into_the_run():
    """A count re-read later without its rule is the ambiguity this exists to
    remove."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert '"site_rule": (getattr(case_row, "site_rule", None)' in api


def test_a_footprint_row_can_say_where_its_number_came_from():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    block = api[api.index("class FootprintRow"):][:900]
    assert "count_source" in block


# ------------------- a rule is wider on two axes, not one
def test_basis_alone_does_not_decide_which_rule_is_wider():
    """The false contradiction this fixes.

    A CONNECTED_LOCATION rule that excludes franchise is *narrower* than an
    OPERATED_FACILITY rule that includes it - the basis is wider and the
    inclusions are not. Comparing the basis alone reported the first as "the
    wider rule returning the smaller count" and accused a correct pair of
    counts of being impossible.

    This came out of a real check: a France-only company-operated footprint of
    5,230 against a published global store count of 14,000."""
    narrow_basis_wide_inclusions = site_rule.rule(
        basis=site_rule.OPERATED_FACILITY,
        includes=["FRANCHISE", "PARTNER_OPERATED", "SHARED_TENANCY",
                  "SEASONAL"],
        excludes=["UNMANNED", "UNDER_CONSTRUCTION"])
    wide_basis_narrow_inclusions = site_rule.rule(
        basis=site_rule.CONNECTED_LOCATION,
        includes=["SHARED_TENANCY"],
        excludes=["FRANCHISE", "PARTNER_OPERATED", "UNMANNED", "SEASONAL",
                  "UNDER_CONSTRUCTION"])

    out = site_rule.compare(
        left_count=5230, left_rule=wide_basis_narrow_inclusions,
        right_count=14000, right_rule=narrow_basis_wide_inclusions,
        left_scope=["FR"], right_scope=["FR"])
    assert out["comparable"] is False
    assert out["wider"] is None, (
        "neither rule contains the other, so no direction can be claimed")
    assert not out.get("contradiction"), (
        "two overlapping rules returning different counts is not a "
        "contradiction")


def test_the_same_rule_makes_a_difference_a_real_disagreement():
    """Identical rules and different counts is the one case where somebody is
    actually wrong about the estate."""
    rule = site_rule.rule(basis=site_rule.OPERATED_FACILITY,
                          includes=["FRANCHISE"],
                          excludes=[i for i in site_rule.INCLUSIONS
                                    if i != "FRANCHISE"])
    out = site_rule.compare(left_count=5230, left_rule=rule,
                            right_count=5700, right_rule=rule,
                            left_scope=["FR"], right_scope=["FR"])
    assert out["comparable"] is True
    assert out["difference"] == "470"

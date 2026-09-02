"""What a known fact may claim, and in what unit.

BINDABLE says Location footprint means sites and Remote-user population means
users. Nothing enforced it: register() checked the asserter, the basis, the
verifiability and that some value existed, never the unit against the class.

So a disclosed cost line filed under Location footprint - 460,000,000 EUR per
year - became 460 million sites for a company with about two thousand stores,
and every stage after it behaved correctly on that premise. The resolver
reported 460 million sites to allocate, and the divergence message told the
analyst that *their* breakdown of the real stores was the thing that was wrong.
"""
import pytest

from app.domain import known_facts


# ----------------------------------- a unit that is not what the class counts
@pytest.mark.parametrize("unit", [
    "EUR/year", "EUR per year", "USD", "users", "Mbps", "%", "headcount",
])
def test_a_footprint_fact_refuses_a_unit_that_is_not_a_count_of_sites(
        session, unit):
    """The live failure: a disclosed cost line filed under Location footprint
    became 460,000,000 sites for a company with about 2,000 stores.

    BINDABLE already said Location footprint means sites and nothing enforced
    it - register() checked the asserter, the basis, the verifiability and that
    some value existed, never the unit against the class. Every stage after it
    then behaved correctly: the resolver reported 460 million sites to
    allocate, and told the analyst their breakdown of 100 real stores was
    wrong."""
    with pytest.raises(ValueError, match="not a unit of sites"):
        known_facts.register(
            session, case_id="c", fact_class="Location footprint",
            subject="Aldi Sued", value_base=460_000_000, unit=unit,
            asserted_by="CB", basis="THIRD_PARTY_REPORT",
            verifiability="PUBLICLY_VERIFIABLE")


@pytest.mark.parametrize("unit", [
    "sites", "locations", "Standorte", "branches", "stores", "outlets", None,
])
def test_a_footprint_fact_accepts_any_reasonable_word_for_a_site(session, unit):
    """Deliberately not an allowlist. A strict list would reject a correct
    entry, which teaches people to fight the field - so only units that plainly
    belong to another dimension are refused."""
    out = known_facts.register(
        session, case_id="c", fact_class="Location footprint",
        subject="Aldi Sued", value_base=2000, unit=unit, asserted_by="CB",
        basis="THIRD_PARTY_REPORT", verifiability="PUBLICLY_VERIFIABLE")
    assert out["known_fact_id"]


def test_a_class_that_binds_nothing_is_not_unit_checked(session):
    """Public cost evidence is measured in money and binds no driver, so the
    check must not reach it."""
    assert known_facts.unit_conflicts_with_class(
        "Public cost evidence", "EUR/year") is None


def test_the_refusal_says_which_of_the_two_to_change(session):
    """Both corrections are plausible - the class or the unit - so naming only
    the fault leaves the analyst guessing."""
    reason = known_facts.unit_conflicts_with_class(
        "Location footprint", "EUR/year")
    assert "the class is wrong" in reason
    assert "Public cost evidence" in reason


def test_the_resolver_defends_against_a_row_written_before_the_check():
    """Rows written before register() validated the unit already carry
    whatever was typed, and a cost line read as a site count is what this chain
    is worst at noticing - every stage after it behaves correctly.

    Checked on the source because exercising it needs a database: the resolver
    has to filter on the same rule rather than trust that nothing bad is
    stored."""
    import inspect
    from app.domain import footprint

    src = inspect.getsource(footprint._best_footprint_fact)
    assert "unit_conflicts_with_class" in src
    assert "ignored rather than read as site counts" in src


# ------------------------------- a value too large to be a count of anything
@pytest.mark.parametrize("value,refused", [
    (460_000_000, True),      # the live case: a EUR spend filed as sites
    (1_000_001, True),
    (1_000_000, False),       # exactly the bound
    (155_000, False),         # India Post, the real-world extreme
    (4_300, False),           # Aldi Sued in Germany
    (2_000, False),
    (None, False),
])
def test_a_site_count_larger_than_any_estate_is_refused(value, refused):
    """The unit check was not enough. It catches a cost line whose unit gives
    it away - "EUR/year" under Location footprint - and not one whose unit says
    "sites", which the entry form defaulted to for every class. So a disclosed
    spend of 460,000,000 arrived unit-consistent and value-absurd, and every
    stage after it behaved correctly on 460 million branches.

    The bound sits far above any real estate rather than near one, so it
    refuses nothing genuine: the largest retail and postal networks in the
    world are in the low hundreds of thousands of outlets."""
    reason = known_facts.value_implausible_for_class("Location footprint", value)
    assert (reason is not None) is refused, reason


def test_the_refusal_names_the_class_the_figure_probably_belongs_to():
    """An analyst told only that a number was refused has to guess what to do.
    A figure this size is almost always a cost line, and that class is also
    what the ANCHOR method wants - so the remedy is worth naming."""
    reason = known_facts.value_implausible_for_class(
        "Location footprint", 460_000_000)
    assert "Public cost evidence" in reason
    assert "max_plausible_sites" in reason, (
        "a genuinely enormous estate must be able to raise the bound rather "
        "than be refused by a constant")


def test_a_class_that_binds_nothing_has_no_plausible_bound():
    """460,000,000 EUR of annual spend is an ordinary figure. The check must
    reach only the classes that supply a count."""
    assert known_facts.value_implausible_for_class(
        "Public cost evidence", 460_000_000) is None


def test_the_bounds_are_governed_not_hardcoded():
    from app.domain.policy import KnownFactPolicy
    from decimal import Decimal
    policy = KnownFactPolicy(set_name="t", agreement_tolerance=Decimal("0.05"),
                             max_plausible_sites=50, max_plausible_users=100)
    assert policy.plausibility_bounds == {"sites": 50, "users": 100}
    assert known_facts.value_implausible_for_class(
        "Location footprint", 60, policy.plausibility_bounds)
    assert known_facts.value_implausible_for_class(
        "Location footprint", 40, policy.plausibility_bounds) is None


def test_a_missing_policy_row_still_refuses_the_absurd():
    """Degrading to "accept anything" is the wrong direction to fail in for a
    check whose whole job is catching a figure that reached the estimate
    unchallenged."""
    assert known_facts.value_implausible_for_class(
        "Location footprint", 460_000_000, bounds={})


def test_the_resolver_applies_both_checks_to_stored_rows():
    """The row is already in the database, so the producer-side refusal does
    nothing for it - and this is the message the analyst is actually looking
    at."""
    import inspect
    from app.domain import footprint
    src = inspect.getsource(footprint._best_footprint_fact)
    assert "unit_conflicts_with_class" in src
    assert "value_implausible_for_class" in src
    assert "cannot be a count of sites" in src


# ------------------------------------ a unit is a measure, not a qualification
def test_the_unit_that_broke_the_insert_is_split_not_truncated():
    """The reported failure: accepting twelve Boots proposals raised
    StringDataRightTruncation and wrote none of them.

    known_fact.unit was VARCHAR(32) and the sweep supplied "employees (total UK
    entity headcount band, Boots Management Services Ltd)" - 68 characters.

    Widening the column stops the error. It does not stop a scope
    qualification living in a field meant for a measure, where nothing can
    read it and grouping by unit breaks - and that qualification decides
    whether the figure is usable at all."""
    unit, note = known_facts.split_unit(
        "employees (total UK entity headcount band, "
        "Boots Management Services Ltd)")
    assert unit == "employees"
    assert "Boots Management Services Ltd" in note, (
        "the qualification must be kept, not discarded - it says which legal "
        "entity the headcount covers")


@pytest.mark.parametrize("unit", [
    "sites", "employees", "EUR/site/year", "retail stores (UK)",
    "employees (UK total workforce)", "GBP millions (FY2024 group revenue)",
])
def test_a_unit_that_fits_is_left_exactly_as_supplied(unit):
    """Splitting a short unit would rewrite correct data to no purpose."""
    assert known_facts.split_unit(unit) == (unit, None)


def test_a_long_unit_with_no_natural_break_keeps_its_head_and_the_whole_text():
    """Nothing is lost even when there is nowhere sensible to cut."""
    long = "an extremely long unit with no natural break point anywhere in it"
    unit, note = known_facts.split_unit(long)
    assert len(unit) <= known_facts.UNIT_MAX
    assert note == long


def test_an_empty_unit_stays_empty():
    assert known_facts.split_unit(None) == (None, None)
    assert known_facts.split_unit("") == (None, None)


def test_the_split_survives_the_unit_class_check():
    """The two rules have to compose: a split unit is then checked against the
    class, and "employees" under Remote-user population must pass."""
    unit, _ = known_facts.split_unit(
        "employees (total UK entity headcount band, Boots Management Services Ltd)")
    assert known_facts.unit_conflicts_with_class(
        "Remote-user population", unit) is None
    # and the same figure filed as a footprint is still refused
    assert known_facts.unit_conflicts_with_class("Location footprint", unit)

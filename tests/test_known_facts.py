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

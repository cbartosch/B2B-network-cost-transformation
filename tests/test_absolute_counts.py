"""Some site types do not scale with the size of the estate.

A data centre count follows a company's compute strategy, its regulatory
geography and how far it has moved to cloud - not how many outlets it has. A
retailer with 3,000 stores and one with 300 both run two to four.

Expressed as a percentage share it scaled with site count:

    POSTAL_AND_PARCEL_NETWORK   0.2%  of 38,000 =    76
    RETAIL_BANKING              3.0%  of 38,000 =  1140
    CLOUD_PROVIDER             25.0%  of 38,000 =  9500

Most large enterprises run five to ten. Even a hyperscaler runs tens.
"""
from pathlib import Path

from app.domain import absolute_counts


def test_a_large_estate_does_not_imply_a_large_data_centre_count():
    for industry, implied in (("POSTAL_AND_PARCEL_NETWORK", 76),
                              ("RETAIL_BANKING", 1140),
                              ("CHEMICALS", 1140),
                              ("SUPERMARKETS", 190)):
        result = absolute_counts.dc_count(
            industry=industry, estate_derived=implied)
        assert result["count"] <= 10, (industry, result)
        assert result["basis"] == absolute_counts.PEER_AVERAGE


def test_even_a_hyperscaler_runs_tens_not_thousands():
    result = absolute_counts.dc_count(
        industry="CLOUD_PROVIDER", estate_derived=9500)
    assert 10 <= result["count"] <= 60, result


def test_research_outranks_the_peer_average():
    """Domain 6 exists to establish this. A researched count is the answer;
    the sector norm is what covers its absence."""
    result = absolute_counts.dc_count(
        industry="RETAIL_BANKING", researched=9, estate_derived=1140)
    assert result["count"] == 9
    assert result["basis"] == absolute_counts.RESEARCHED
    assert result["researched"] == 9


def test_a_researched_count_is_still_capped_at_the_absolute_maximum():
    """A figure in the thousands means network sites and equipment rooms were
    counted as data centres - those are CORE_SITE and NETWORK_SITE here."""
    result = absolute_counts.dc_count(industry="RETAIL_BANKING",
                                      researched=3000)
    assert result["count"] == absolute_counts.DC_ABSOLUTE_MAX
    assert result["capped_at"] == absolute_counts.DC_ABSOLUTE_MAX
    assert "equipment rooms" in result["note"]


def test_a_shape_implying_fewer_than_the_norm_is_respected():
    """A shape saying fewer is telling us something; one saying more is
    arithmetic on site count."""
    result = absolute_counts.dc_count(industry="RETAIL_BANKING",
                                      estate_derived=2)
    assert result["count"] == 2


def test_an_unknown_industry_gets_the_generic_enterprise_range():
    result = absolute_counts.dc_count(industry="NOT_A_CODE",
                                      estate_derived=500)
    assert result["count"] <= 10
    assert result["basis"] == absolute_counts.GENERIC


def test_the_basis_is_reported_not_only_the_number():
    """"We could not establish this, so the sector norm was used" is a
    finding, not a detail."""
    result = absolute_counts.dc_count(industry="LOGISTICS",
                                      estate_derived=400)
    assert "sector" in result["note"]
    assert "domain 6" in result["note"]
    assert result["peer_range"] == list(
        absolute_counts.DC_BY_INDUSTRY["LOGISTICS"])


def test_the_proposer_applies_the_cap_and_still_adds_up():
    """A split that does not total the register reads as arithmetic. The
    surplus goes back to the largest row rather than being dropped."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "footprint.py").read_text()
    assert "absolute_counts.dc_count(" in source
    assert "counts[biggest] += implied - allowed" in source
    assert '"capped": capped_note' in source


def test_the_per_country_ceiling_agrees_that_the_number_is_small():
    """25 data centres in ONE country is already generous against a
    worldwide range of five to ten."""
    from app.domain import estate_plausibility

    assert estate_plausibility.PER_COUNTRY_CEILING["DC"] <= 25

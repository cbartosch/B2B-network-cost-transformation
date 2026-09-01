"""What the simulation is told about each site type, and where it came from.

The simulation used site counts and nothing else. Product pairs, dual-access
probability, bandwidth and users-per-site all came from
reference.archetype_prior, so research or an analyst could establish that a
client runs dual MPLS at 60% of branches and the model would still use the
seeded 0.55 - counts were evidence-driven and topology was not.

Four layers, weakest first: SEEDED_PRIOR, INDUSTRY_DEFAULT, KNOWN_FACT,
PROMOTED_RESEARCH. That is the confidence model's own order applied to
topology: reference is weaker than an attributed assertion, and an assertion is
weaker than public evidence.
"""
import types

import pytest

from app.domain import archetype, promotion

SEEDED = {"BRANCH": {"primary_product": "DIA",
                     "backup_product": "BROADBAND_PON",
                     "dual_access_probability": 0.55,
                     "users_base": 25, "bandwidth_mbps_base": 100}}


class _Row:
    def __init__(self, **kw):
        self.__dict__.update({"domain_no": None, "known_fact_id": None,
                              "reliability_grade": None, "recorded_by": None,
                              **kw})


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _query):
        return types.SimpleNamespace(all=lambda: self._rows)


def _resolve(rows, industry=None):
    return archetype.resolve(_Session(rows), case_id="c", seeded=SEEDED,
                             industry_bandwidth=industry)


# ------------------------------------------------------------- the precedence
def test_the_seeded_prior_is_the_floor():
    arch, basis = _resolve([])
    assert arch["BRANCH"]["dual_access_probability"] == 0.55
    assert basis["by_field"]["BRANCH.dual_access_probability"]["layer"] == \
        "SEEDED_PRIOR"
    assert not basis["evidenced_fields"], (
        "with nothing established, no field may claim to be evidence")


def test_an_industry_default_beats_the_seeded_prior():
    arch, basis = _resolve([], industry={"BRANCH": 200})
    assert arch["BRANCH"]["bandwidth_mbps_base"] == 200
    assert basis["by_field"]["BRANCH.bandwidth_mbps_base"]["layer"] == \
        "INDUSTRY_DEFAULT"


def test_a_known_fact_beats_an_industry_default():
    """An attributed assertion about this client outranks a sector default."""
    arch, basis = _resolve(
        [_Row(archetype="BRANCH", field="bandwidth_mbps_base", value="500",
              origin="KNOWN_FACT", known_fact_id="kf1", recorded_by="CB")],
        industry={"BRANCH": 200})
    assert arch["BRANCH"]["bandwidth_mbps_base"] == 500
    assert basis["by_field"]["BRANCH.bandwidth_mbps_base"]["layer"] == "KNOWN_FACT"


def test_promoted_research_beats_a_known_fact():
    """Public evidence over an assertion - the same ladder that decides whether
    a site count lifts a confidence ceiling."""
    arch, basis = _resolve([
        _Row(archetype="BRANCH", field="primary_product", value="ETHERNET",
             origin="KNOWN_FACT", known_fact_id="kf1"),
        _Row(archetype="BRANCH", field="primary_product", value="MPLS",
             origin="PROMOTED_RESEARCH", domain_no=8,
             reliability_grade="VERY_RELIABLE")])
    assert arch["BRANCH"]["primary_product"] == "MPLS"
    entry = basis["by_field"]["BRANCH.primary_product"]
    assert entry["layer"] == "PROMOTED_RESEARCH"
    assert entry["grade"] == "VERY_RELIABLE"


def test_every_field_reports_which_layer_it_came_from():
    """The whole value of establishing one is being able to tell which parts of
    the topology are evidence and which are still assumptions."""
    arch, basis = _resolve(
        [_Row(archetype="BRANCH", field="dual_access_probability", value="0.8",
              origin="KNOWN_FACT", known_fact_id="kf1")],
        industry={"BRANCH": 200})
    assert set(basis["evidenced_fields"]) == {"BRANCH.dual_access_probability"}
    assert "BRANCH.users_base" in basis["assumed_fields"]
    assert "BRANCH.bandwidth_mbps_base" in basis["assumed_fields"], (
        "an industry default is a sector assumption, not this client's evidence")


def test_the_seeded_prior_is_not_mutated():
    """It is global reference data. One client's estate is not a benchmark, and
    establishing this for one case must not retune every other."""
    before = dict(SEEDED["BRANCH"])
    _resolve([_Row(archetype="BRANCH", field="users_base", value="60",
                   origin="PROMOTED_RESEARCH", domain_no=15)])
    assert SEEDED["BRANCH"] == before


@pytest.mark.parametrize("field,raw,expected", [
    ("dual_access_probability", "0.6", 0.6),
    ("dual_access_probability", "1.9", 1.0),
    ("dual_access_probability", "-1", 0.0),
    ("users_base", "25.4", 25),
    ("bandwidth_mbps_base", "200", 200),
    ("primary_product", "mpls", "MPLS"),
    ("users_base", "not a number", None),
])
def test_a_stored_string_coerces_or_is_ignored(field, raw, expected):
    """Values are stored as strings for JSON safety, so the coercion is where a
    bad one has to be caught rather than reaching the model."""
    assert archetype._coerce(field, raw) == expected


# --------------------------------------------------- what qualifies as a finding
@pytest.mark.parametrize("quantity,field", [
    ({"label": "BRANCH", "unit": "Mbps", "value": "200"}, "bandwidth_mbps_base"),
    ({"label": "BRANCH", "unit": "users per site", "value": "25"}, "users_base"),
    ({"label": "BRANCH", "unit": "dual access share", "value": "0.6"},
     "dual_access_probability"),
    ({"label": "BRANCH", "unit": "primary access", "value": "MPLS"},
     "primary_product"),
    ({"label": "STORE", "unit": "backup product", "value": "MOBILE_5G"},
     "backup_product"),
    # A bare share says nothing about what it is a share of.
    ({"label": "BRANCH", "unit": "share", "value": "0.6"}, None),
    # Not an archetype.
    ({"label": "REVENUE", "unit": "Mbps", "value": "200"}, None),
])
def test_only_a_finding_that_names_its_dimension_qualifies(quantity, field):
    assert promotion.archetype_field(quantity) == field


def test_the_register_classes_that_can_describe_a_site_type_are_named():
    """A fact qualifies when its class is about architecture and its subject
    names an archetype. Left open, any fact about "BRANCH" would be read as an
    architecture statement."""
    assert "Resilience assumptions" in archetype.ARCHITECTURE_CLASSES
    assert "Location footprint" not in archetype.ARCHITECTURE_CLASSES, (
        "a site count is a count, not a statement about how a site is built")

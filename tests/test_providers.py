"""Who supplies what, and where.

Specification 0.4: vendor/product signals prepopulate provider and product,
"Treat as hypothesis until client evidence confirms."

The workbench had no concept of a carrier. Research domain 8 gathers exactly
this and promotion had nowhere to put the answer, so every finding about a
supplier was displayed once and lost.
"""
import pytest

from app.domain import providers


def _rel(**over):
    fields = dict(provider="BT", kind=providers.INCUMBENT,
                  role=providers.PRIMARY, country="GB",
                  standing=providers.EVIDENCED)
    fields.update(over)
    return providers.relationship(**fields)


def test_a_country_can_have_more_than_one_provider():
    """The normal case, not an edge case. Resilience needs a second carrier,
    and no carrier serves every country - an international estate is a
    patchwork by construction."""
    rels = [_rel(), _rel(provider="Virgin Media Business",
                         kind=providers.CHALLENGER, role=providers.BACKUP)]
    out = providers.diversity(rels, country="GB")
    assert out["carrier_diverse"] is True
    assert out["access_providers"] == ["BT", "Virgin Media Business"]
    assert not out["caveats"]


def test_a_carrier_and_its_manager_are_not_diversity():
    """Two providers in the same role is redundancy. Two in different roles is
    a supply chain, and counting them as diversity is the mistake this exists
    to prevent."""
    rels = [_rel(provider="Orange", country="FR"),
            _rel(provider="Accenture", kind=providers.MSP,
                 role=providers.MANAGEMENT, country="FR")]
    out = providers.diversity(rels, country="FR")
    assert out["carrier_diverse"] is False
    assert any("supply chain" in c for c in out["caveats"])


def test_a_reseller_is_flagged_because_two_names_is_not_two_ducts():
    """A challenger reselling the incumbent's fibre is one physical path
    wearing two names."""
    rels = [_rel(country="DE"),
            _rel(provider="Reseller X", kind=providers.RESELLER,
                 role=providers.BACKUP, country="DE")]
    out = providers.diversity(rels, country="DE")
    assert out["carrier_diverse"] is True
    assert any("not two ducts" in c for c in out["caveats"])


def test_diversity_claimed_only_on_public_signals_says_so():
    """Carrier diversity inferred from press releases is a research finding
    rather than a fact about the estate."""
    rels = [_rel(standing=providers.HYPOTHESIS, source="press release"),
            _rel(provider="Colt", kind=providers.CHALLENGER,
                 role=providers.BACKUP, standing=providers.HYPOTHESIS,
                 source="job advert")]
    out = providers.diversity(rels, country="GB")
    assert any("hypothesis" in c for c in out["caveats"])


def test_a_hypothesis_needs_the_signal_it_came_from():
    """An unsourced guess about who supplies a client is the kind of thing that
    ends up in a slide, and the control on this table is that it stays a
    hypothesis until the client confirms it."""
    with pytest.raises(providers.ProviderInvalid, match="signal"):
        providers.relationship(provider="BT", kind=providers.INCUMBENT,
                               role=providers.PRIMARY, country="GB",
                               standing=providers.HYPOTHESIS)


def test_a_share_of_zero_is_refused():
    """Zero means the provider is not there, which is an absent row rather than
    a row saying nothing."""
    with pytest.raises(providers.ProviderInvalid, match="portion"):
        _rel(share="0")
    assert _rel(share="0.6")["share"] == "0.6"


def test_an_unrecorded_country_is_a_gap_not_a_single_carrier_estate():
    """One belongs in the assumption register and the other is a finding about
    the client."""
    out = providers.coverage([_rel()], countries=["GB", "DE", "FR"])
    assert out["countries_without"] == ["DE", "FR"]
    assert "open question" in out["note"]


def test_a_country_with_nothing_recorded_says_so():
    out = providers.diversity([], country="NL")
    assert out["carrier_diverse"] is False
    assert "not the same as a single-carrier estate" in out["note"]


def test_the_providers_product_name_is_kept_verbatim():
    """A carrier's wording is how an invoice line is recognised later, and
    normalising it away loses the join."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "db.py").exists())
    assert "provider_product_name" in (app / "db.py").read_text()


@pytest.mark.parametrize("field,value", [
    ("kind", "PARTNER"), ("role", "SECONDARY"), ("standing", "PROBABLY"),
])
def test_a_vocabulary_it_does_not_know_is_refused(field, value):
    with pytest.raises(providers.ProviderInvalid):
        _rel(**{field: value})


# ------------------------- the carrier dimension reaches the resilience model
def _table():
    class _Row:
        def __init__(self, available, mbps):
            self.available, self.max_bandwidth_mbps = available, mbps
    return {("GB", "URBAN", t): _Row(True, 1000)
            for t in ("PON", "VDSL", "HFC", "ETHERNET_FIBRE", "MOBILE_5G")}


def _backup(primary=None, backup=None):
    from app.domain import serviceability
    return serviceability.resolve_backup(
        table=_table(), country="GB", density="URBAN",
        product="BROADBAND_PON", wanted_mbps=100,
        primary_product="ETHERNET_FIBRE",
        primary_providers=primary, backup_providers=backup)


def test_a_second_product_from_one_carrier_is_not_a_second_carrier():
    """The 4.157 product rule is a proxy for the thing that matters, and a
    proxy the moment a case records who actually supplies it. Two different
    products from one carrier still share a duct."""
    out = _backup(primary=["BT"], backup=["BT"])
    assert out["resilient"] is False
    assert out["carrier_diverse"] is False
    assert "same duct" in out["note"]


def test_a_different_carrier_is_a_second_path():
    out = _backup(primary=["BT"], backup=["Virgin Media Business"])
    assert out["resilient"] is True
    assert out["carrier_diverse"] is True


def test_one_shared_provider_does_not_defeat_a_second_one():
    """A country with two backup carriers, one of which also serves the
    primary, can still deliver a diverse second path."""
    out = _backup(primary=["BT"], backup=["BT", "Colt"])
    assert out["carrier_diverse"] is True
    assert "Colt" in out["note"]


def test_no_provider_recorded_is_silent_not_negative():
    """An estate is not single-carrier because nobody wrote the carriers down.
    None, not False - the same rule as an empty serviceability table."""
    out = _backup()
    assert out["carrier_diverse"] is None
    assert out["resilient"] is True


def test_the_two_reasons_for_a_single_path_are_distinguished():
    """A serviceability constraint and a supplier one need different remedies:
    one is a build, the other is a sourcing decision."""
    import inspect

    from app.domain import simulation

    source = inspect.getsource(simulation.one_pass)
    assert '"SAME_CARRIER"' in source
    assert '"NOT_DELIVERABLE"' in source


def test_only_access_roles_count_toward_diversity():
    """An MSP that manages a site supplies no path, and counting it would make
    a supply chain look like carrier diversity."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    helper = api[api.index("def _providers_by_role"):]
    assert 'in_(("PRIMARY", "BACKUP"))' in helper[:900]


def test_the_providers_are_pinned_to_the_run():
    """A resumed pass must judge diversity on the providers the run started
    with, not on whatever the case says now."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "jobs.py").exists())
    api = (app / "routers" / "api.py").read_text()
    jobs = (app / "jobs.py").read_text()
    assert '"providers_by_role": _providers_by_role' in api
    assert 'get("providers_by_role")' in jobs


def test_the_ensemble_forwards_the_providers():
    """run_ensemble accepted service_class_by_archetype and dropped it for
    twelve releases. Every parameter added since is checked for the same."""
    import inspect

    from app.domain import simulation

    assert "providers_by_role=providers_by_role" in inspect.getsource(
        simulation.run_ensemble)

"""A best-effort backup is bought as a plan, not at the primary's bandwidth.

The simulation asked for every backup at the primary's bandwidth. For a
committed service that is a real requirement. For a 5G or broadband backup it
is not a product: nobody sells a 275 Mbps 5G plan, the card's 5G tiers stop at
100, and so every such backup was unpriced - in Germany and the US as much as
anywhere, because no regional fallback can find a tier that does not exist.

It is now bought as the largest plan the card sells for that country, and the
run says which sites have a second path that carries less than their first.
"""
import uuid

from sqlalchemy import insert, select

from app import db, jobs
from app.domain import simulation
from app.domain.estimate import match_prior, plans_sold
from app.domain.scope import price_ladder

STORE = {"dual_access_probability": 1.0, "primary_product": "BROADBAND_HFC",
         "backup_product": "MOBILE_5G", "users_base": 12,
         "bandwidth_mbps_base": 275}
SOLD = {("GB", "MOBILE_5G"): [50, 100]}


def _pass(archetype=STORE, plan_tiers=SOLD, sites=20):
    return simulation.one_pass(
        42, [{"country": "GB", "archetype": "STORE", "sites": sites}],
        {"STORE": archetype}, plan_tiers=plan_tiers)


def _backups(result):
    return {p["bandwidth_mbps"]: p["count"] for p in result["products"]
            if p["role"] == "BACKUP"}


def test_a_5g_backup_is_bought_as_the_largest_plan_sold():
    out = _pass()
    assert _backups(out) == {100: 20}
    assert out["backups_below_primary"] == [
        {"country": "GB", "archetype": "STORE", "density": None,
         "product": "MOBILE_5G", "asked_mbps": 275, "sold_mbps": 100,
         "sites": 20}]
    assert {r["backup_mbps"] for r in out["estate_full"]} == {100}


def test_a_backup_a_plan_can_carry_keeps_its_size():
    """60 Mbps fits under the 100 Mbps plan. It is left as asked, and the
    matcher prices it at the cheapest tier above, exactly as before."""
    out = _pass({**STORE, "bandwidth_mbps_base": 60})
    assert _backups(out) == {60: 20}
    assert out["backups_below_primary"] == []


def test_a_committed_backup_is_left_as_asked():
    """A 10 Gbps DIA backup is a real circuit with a real price. A card
    without that tier is the finding, so it stays unpriced and reported -
    resizing it would quietly trade a gap for a smaller circuit."""
    out = _pass({**STORE, "primary_product": "ETHERNET",
                 "backup_product": "DIA", "bandwidth_mbps_base": 10000},
                plan_tiers={("GB", "DIA"): [100, 1000]})
    assert _backups(out) == {10000: 20}
    assert out["backups_below_primary"] == []


def test_a_run_pinned_before_plans_existed_is_unchanged():
    """No plans pinned, nothing resized: a stored run re-aggregates to the
    estate it always had."""
    out = _pass(plan_tiers=None)
    assert _backups(out) == {275: 20}
    assert out["backups_below_primary"] == []


def test_the_plans_are_the_tiers_the_matcher_can_reach():
    """A tier anywhere on the ladder counts, because match_prior falls to the
    next rung when the country has nothing at or above the requirement. So a
    backup sized to any plan this returns is one the estimate can price - the
    property that makes resizing worth doing."""
    rows = [("DE", "MOBILE_5G", 50), ("DE", "MOBILE_5G", 100),
            ("EUROPE_CENTRAL", "MOBILE_5G", 100), ("EMEA", "MOBILE_5G", 300),
            ("EMEA", "BROADBAND_PON", 1000)]
    ladders = {"DE": price_ladder("DE", "EUROPE_CENTRAL"),
               "HU": price_ladder("HU", "EUROPE_CENTRAL"),
               "XX": price_ladder("XX", None)}
    sold = plans_sold(rows, ladders)
    assert sold[("DE", "MOBILE_5G")] == [50, 100, 300]
    assert sold[("HU", "MOBILE_5G")] == [100, 300]
    assert sold[("HU", "BROADBAND_PON")] == [1000]
    assert not any(country == "XX" for country, _product in sold)

    priors = {(scope, product, mbps): {"base": "1", "scope": scope}
              for scope, product, mbps in rows}
    for (country, product), tiers in sold.items():
        for tier in tiers:
            hit, _s = match_prior(priors, country, product, tier,
                                  scopes=ladders[country])
            assert hit is not None, (country, product, tier)


def test_the_job_resizes_with_the_plans_it_was_pinned_with(session):
    """Through the runner, which reads the pin back from "COUNTRY|PRODUCT"
    keys - and through the aggregate's re-run of the median pass, which is
    where an input the passes had was last dropped."""
    rid = str(uuid.uuid4())
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=rid, case_id=None, model_version="sim-test",
        seed=42, ensemble_size=3,
        params={"footprint": [{"country": "GB", "archetype": "STORE",
                               "sites": 20}]},
        pinned_priors={"archetype_prior": {"STORE": STORE},
                       "plan_tiers": {"GB|MOBILE_5G": [50, 100]}},
        status=jobs.QUEUED, progress_completed=0, progress_total=3,
        cancel_requested=False))
    session.commit()

    jobs.run_job(rid)
    session.expire_all()
    output = session.execute(select(db.simulation_run.c.output).where(
        db.simulation_run.c.simulation_run_id == rid)).scalar()
    assert _backups(output) == {100: 20}
    assert output["backups_below_primary"][0]["sites"] == 20


def test_the_route_pins_the_plans_it_sized_against():
    """The runner can only read what the route pinned. Both halves, because a
    pin written under one key and read under another rebuilds an empty table
    and resizes nothing - silently, which is how serviceability failed once."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "jobs.py").exists())
    route = (app / "routers" / "api.py").read_text()
    assert "estimate.plans_sold(" in route
    assert '"plan_tiers": {f"{c}|{p}"' in route
    assert 'get("plan_tiers")' in (app / "jobs.py").read_text()

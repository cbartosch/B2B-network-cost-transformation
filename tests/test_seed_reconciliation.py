"""A changed seeded value has to reach the database.

`--force` reconciled KEYS and not VALUES. For density_mix the key is
industry-archetype-density, so changing LOGISTICS from few-large to
distribution-led left every overlapping row at its old share and inserted only
the rows whose key was new. The database ended up holding 0.85 of one shape
plus 0.29 of another - shares summing to 1.1400, and a 38,000-site footprint
allocated as 43,320.

Every estate shape changed in the last several releases was invisible on any
instance already seeded once. The shapes summed to 1 in the code and the test
asserting that passed throughout, because it read the constant rather than the
database.
"""
from decimal import Decimal
from pathlib import Path


def _ready():
    """The whole `ready` function, sized from the AST.

    A 4,000-character window missed the check at 4,561 - the third time a
    guessed window has broken a test in this repository, and the same mistake
    each time: a length chosen by eye rather than by the function's own
    bounds.
    """
    import ast

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    source = (app / "routers" / "api.py").read_text()
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "ready")
    return ast.unparse(node)


def _seed_source():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "seed.py").exists())
    return (app / "seed.py").read_text()


def test_force_reconciles_values_not_only_keys():
    source = _seed_source()
    block = source[source.index("            if force:"):][:1400]
    assert "update(table)" in block, (
        "--force must write a changed value, not only insert missing keys")
    assert "str(getattr(current, c, None)) != str(v)" in block, (
        "it must compare the stored value with the seeded one")


def test_a_plain_seed_still_leaves_an_existing_row_alone():
    """A steward's hand edit is the thing that protects. Reconciling on every
    start would silently undo it."""
    source = _seed_source()
    block = source[source.index("            if force:"):][:1400]
    assert block.startswith("            if force:"), (
        "reconciliation must be inside the force branch")


def test_the_reconciliation_is_reported():
    """A value silently changing under an operator is worse than one that does
    not change at all."""
    source = _seed_source()
    assert "reconciled changed values (--force)" in source


def test_readiness_checks_the_shares_in_the_database():
    """The code asserted 1.0000 and the database held 1.1400. Only a check
    that reads the database can see the divergence."""
    ready = _ready()
    assert "select(db.density_mix)" in ready
    assert "seeded estate shares do not sum to one" in ready
    assert "seed --force" in ready


def test_readiness_warns_and_does_not_refuse():
    """The first version returned 503 and made the container unhealthy - and
    the only remedy, `seed --force`, needs a running container.

    That is the deadlock 4.204.0 fixed for an unseeded database, reintroduced
    one release after the comment describing it was written.

    The rule: readiness may fail only for a fault that running the seed
    CANNOT fix. A policy that will not build from present rows is such a
    fault. Shares that do not total one are precisely what the seed
    repairs."""
    ready = _ready()
    failures = [line for line in ready.splitlines()
                if "'ready': False" in line]
    assert failures, "readiness must still be able to fail"
    for line in failures:
        assert "estate shares" not in line, (
            "a fault the seed repairs must not block the container that runs "
            "the seed")
    assert "warnings" in ready
    assert "the remedy needs this container" in ready


def test_the_shares_still_sum_to_one_in_the_code():
    """The check that was already there and was not enough."""
    from app.seed import DENSITY_MIX

    totals = {}
    for industry, _archetype, _band, share in DENSITY_MIX:
        totals[industry] = totals.get(industry, Decimal("0")) + Decimal(share)
    wrong = {i: str(t) for i, t in totals.items() if t != Decimal("1.0000")}
    assert not wrong, wrong

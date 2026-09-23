"""A group is not one industry.

DHL's German estate is a parcel network of 30,000 collection points AND a
contract-logistics estate of a few hundred depots. Priced from one industry,
the larger half is wrong whichever is chosen: as LOGISTICS the collection
points become 25,840 warehouses, as POSTAL_AND_PARCEL_NETWORK the depots
become parcel shops.

A footprint row may now name its own industry. The archetype tables are keyed
(industry, archetype) where a row does, and fall back to the archetype-only
key where it does not - so a footprint with no industries behaves exactly as
it did.

No migration: the footprint is JSON on the case, so a row could always have
carried the field. What it could not do was survive the reshape, or reach a
lookup that knew what to do with it.
"""
import inspect
from pathlib import Path


def _resolver():
    """`_for`, lifted out of one_pass."""
    from app.domain import simulation

    source = inspect.getsource(simulation.one_pass)
    start = source.index("    def _for(table, entry):")
    end = source.index("    for entry in sorted(footprint", start)
    namespace = {}
    exec("\n".join(line[4:] for line in source[start:end].splitlines()),
         namespace)
    return namespace["_for"]


TABLE = {
    "STORE": "case-default",
    ("POSTAL_AND_PARCEL_NETWORK", "STORE"): "parcel",
    ("LOGISTICS", "WAREHOUSE"): "logistics",
}


def test_a_row_naming_an_industry_gets_that_industrys_value():
    resolve = _resolver()
    assert resolve(TABLE, {"archetype": "STORE",
                           "industry": "POSTAL_AND_PARCEL_NETWORK"}) == "parcel"


def test_a_row_naming_no_industry_behaves_exactly_as_before():
    """Every existing footprint. This is what makes the change safe to
    deploy against live cases."""
    resolve = _resolver()
    assert resolve(TABLE, {"archetype": "STORE"}) == "case-default"


def test_an_industry_with_no_entry_falls_back_rather_than_failing():
    """A row may name an industry the tables do not cover - a legacy code, or
    one whose benchmark has no row for that archetype. Falling through to the
    archetype key is the same answer the case would have given."""
    resolve = _resolver()
    assert resolve(TABLE, {"archetype": "STORE",
                           "industry": "CHEMICALS"}) == "case-default"


def test_the_industry_is_normalised():
    resolve = _resolver()
    assert resolve(TABLE, {"archetype": "STORE",
                           "industry": "postal_and_parcel_network"}) == "parcel"


def test_one_resolver_serves_every_lookup():
    """Four inline lookups had to agree on the fallback order, and the order
    is the thing that must not differ between them."""
    from app.domain import simulation

    source = inspect.getsource(simulation.one_pass)
    assert source.count("_for(") >= 3
    assert 'get(entry["archetype"])' not in source, (
        "an inline archetype-only lookup bypasses the row's industry")


def test_the_route_builds_tables_for_every_industry_in_the_estate():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()

    assert "_row_industries = sorted({" in api
    assert "_industries = [_industry]" in api
    # both key shapes, so a row without an industry still resolves
    assert "_bw[(r.industry, r.archetype)]" in api
    assert "benchmark_committed[(_i, _r.archetype)]" in api


def test_the_single_industry_tables_are_not_rebuilt_afterwards():
    """They were, and a dict assignment does not complain - the
    multi-industry keys would have been silently replaced by the case
    industry's alone."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    # The rebuild took the form `benchmark_dual_access = {` followed by a
    # comprehension over _res_rows. The tuple unpack that initialises both
    # dicts matches that prefix too, so the assertion has to name the
    # comprehension rather than the assignment.
    assert "benchmark_dual_access = {\n            r.archetype:" not in api
    assert "_unused_committed" not in api, (
        "the placeholder left when the rebuild was removed should be gone")
    assert api.count(
        "benchmark_committed, benchmark_dual_access = {}, {}") == 1


def test_the_industry_survives_the_footprint_reshape():
    """Rebuilding a row from three fields dropped it silently, which is the
    only way this could have failed."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "footprint.py").read_text()
    assert '("industry", r.get("industry"))' in source


def test_the_request_model_declares_industry():
    """Pydantic drops an undeclared field before the route sees it.

    Without this, the whole of 4.252.0 was silently inert: the resolver would
    resolve, the tables would be keyed both ways, and no row would ever
    arrive carrying an industry."""
    import ast

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    node = next(n for n in ast.parse(api).body
                if isinstance(n, ast.ClassDef) and n.name == "FootprintRow")
    fields = [f.target.id for f in node.body if isinstance(f, ast.AnnAssign)]
    assert "industry" in fields


def test_no_request_model_declares_a_field_twice():
    """FootprintRow declared count_source twice with two different comments.
    Pydantic accepts that silently: the second wins and the first is dead
    text that reads as documentation."""
    import ast
    from collections import Counter

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()

    duplicated = {}
    for node in ast.parse(api).body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields = [f.target.id for f in node.body
                  if isinstance(f, ast.AnnAssign)]
        repeats = [k for k, n in Counter(fields).items() if n > 1]
        if repeats:
            duplicated[node.name] = repeats
    assert not duplicated, duplicated


def test_the_industry_is_read_from_the_payload_not_a_later_local():
    """`footprint` is built 194 lines below the block that needs it, so
    reading it there was an unbound local - the same shape as the `scope`
    shadowing at 4.218.0."""
    import ast

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    node = next(n for n in ast.parse(api).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "run_simulation")

    uses = [n.lineno for n in ast.walk(node)
            if isinstance(n, ast.Name) and n.id == "footprint"
            and isinstance(n.ctx, ast.Load)]
    binds = [n.lineno for n in ast.walk(node)
             if isinstance(n, ast.Name) and n.id == "footprint"
             and isinstance(n.ctx, ast.Store)]
    assert min(uses) > min(binds), (
        "footprint is read before the line that binds it")

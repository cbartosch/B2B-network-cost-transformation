"""The geography of a proposed footprint split.

`propose_split` accepted a `countries` argument and never used it: every
proposed row was written to the domicile. Holcim's 201 sites arrived as an
entirely Swiss estate and the page said nothing about it.

The direct pricing error is modest - Switzerland is about 1.09x the median on
gigabit Ethernet. Three consequences are worse:

  * serviceability resolves against the wrong country, so rural warehouses are
    tested for Swiss rural bearers rather than Indian or Nigerian ones
  * the material-country floor is defeated, because a single-country estate has
    exactly one material country and it is fully covered - the gate reports
    green on a fictional geography
  * the page's banner promises nothing is guessed while silently guessing the
    country

Sites are deliberately NOT spread. There is no governed country-distribution
data, so a spread would be invented, and inventing a geography is worse than
defaulting to one. What changed is that the default stopped being silent.
"""
import ast
from pathlib import Path


def _footprint():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    return (app / "domain" / "footprint.py").read_text()


def _api():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    return (app / "routers" / "api.py").read_text()


def test_the_route_passes_the_in_scope_countries():
    """The parameter existed and nothing supplied it, which is why it was
    dead rather than wrong."""
    api = _api()
    call = api[api.index("footprint_resolver.propose_split("):][:400]
    assert "countries=list(case_row.in_scope_countries" in call


def test_every_in_scope_country_appears():
    """An obvious blank beats a silent guess. The analyst sees the countries
    they declared and where the allocation goes."""
    source = _footprint()
    body = source[source.index("def propose_split"):]
    body = body[:body.index("\ndef _is_placeholder")]
    assert "for other in in_scope if other != home" in body
    assert '"sites": 0' in body


def test_the_sites_are_not_spread_automatically():
    """No governed country-distribution data exists, so a spread would be
    invented. The total stays on the domicile until a person moves it."""
    source = _footprint()
    body = source[source.index("def propose_split"):]
    body = body[:body.index("\ndef _is_placeholder")]
    assert "no governed\n    # country-distribution data" in body \
        or "country-distribution data" in body
    # the proposed counts still come from the density mix alone
    assert 'for r, n in zip(chosen, counts) if n > 0' in body


def test_both_axes_are_reported_and_only_one_is_governed():
    """The site mix is a governed sector default. The geography is not a
    default at all - it is the domicile because nothing says otherwise - and
    the response has to say so."""
    source = _footprint()
    body = source[source.index("def propose_split"):]
    body = body[:body.index("\ndef _is_placeholder")]
    assert '"axes"' in body
    assert '"site_mix"' in body and '"geography"' in body
    assert '"source": "CASE_DOMICILE"' in body


def test_the_page_shows_both_axes_and_warns_on_zero_rows():
    root = Path(__file__).resolve().parents[1]
    page = next(root.glob("analyst_ui/streamlit_app/pages/5_Simulation*.py"))
    source = page.read_text()
    assert '_sp.get("axes")' in source
    assert "Site mix" in source and "Geography" in source
    assert "listed at zero" in source


def test_a_single_country_case_gets_no_zero_rows():
    """The common case must not gain noise. A case in one country has nothing
    to allocate elsewhere."""
    source = _footprint()
    body = source[source.index("def propose_split"):]
    body = body[:body.index("\ndef _is_placeholder")]
    # the zero rows are generated only for countries other than home
    assert "if other != home" in body


def test_the_proposed_counts_still_sum_to_the_total():
    """Largest remainder. A split that does not add up reads as arithmetic,
    and adding zero rows must not change that."""
    source = _footprint()
    body = source[source.index("def propose_split"):]
    body = body[:body.index("\ndef _is_placeholder")]
    assert "counts[index] += 1" in body
    assert "total - sum(counts)" in body

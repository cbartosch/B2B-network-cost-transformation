"""Where a sample case's industry code came from, on every run.

Resolution never writes the code: `confirm` records what the resolver called
the sector as `industry_as_resolved` and leaves the code alone. So a known
code on a case came from the spec - the driver, on this run or an earlier
one - or from whoever set it on the case. The driver labelled every known
code ENTITY_RESOLUTION, which was true of none of the fifty: forty-eight said
so, and Maersk and Michelin said SPEC_FALLBACK only on the run that wrote
their codes, then ENTITY_RESOLUTION on the next.
"""
import importlib.util
import pathlib

import pytest
from sqlalchemy import insert, select, update

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _driver():
    f = ROOT / "tools" / "run_samples.py"
    if not f.exists():
        pytest.skip("driver not present in this image")
    spec = importlib.util.spec_from_file_location("_rs", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def case(session):
    """A case with no code yet, and two codes the seed can price."""
    from app import db
    session.execute(insert(db.archetype_bandwidth), [
        {"id": f"{code}-PLANT", "industry": code, "archetype": "PLANT",
         "bandwidth_mbps": 100} for code in ("AUTOMOTIVE_OEM", "LOGISTICS")])
    session.execute(insert(db.case).values(case_id="case-1",
                                           created_by="tester"))
    session.commit()
    return "case-1"


def _set_code(session, case_id, code):
    from app import db
    session.execute(update(db.case).where(db.case.c.case_id == case_id)
                    .values(industry=code))
    session.commit()


def _held(session, case_id):
    from app import db
    session.expire_all()
    return session.execute(select(db.case.c.industry).where(
        db.case.c.case_id == case_id)).scalar()


def test_the_spec_s_code_says_so_on_every_run(session, case):
    """The first run writes the code and the second finds it there. It is
    the spec's code both times, and the second run said ENTITY_RESOLUTION."""
    mod = _driver()
    spec = {"industry": "AUTOMOTIVE_OEM"}
    first = mod.set_industry_if_absent(case, spec)
    second = mod.set_industry_if_absent(case, spec)
    assert _held(session, case) == "AUTOMOTIVE_OEM"
    assert first["origin"] == second["origin"] == "SPEC_FALLBACK"


def test_an_unknown_code_on_the_case_gives_way_to_the_spec_s(session, case):
    """Maersk's case held SHIPPING_LOGISTICS, a code no reference table
    carries, which prices the estate on DEFAULT. The spec's code replaces
    it."""
    mod = _driver()
    _set_code(session, case, "SHIPPING_LOGISTICS")
    out = mod.set_industry_if_absent(case, {"industry": "LOGISTICS"})
    assert _held(session, case) == "LOGISTICS"
    assert (out["industry"], out["origin"]) == ("LOGISTICS", "SPEC_FALLBACK")


def test_a_known_code_that_is_not_the_spec_s_is_kept_and_says_so(session, case):
    """Set on the case some other way - by hand, or by an older spec, since a
    corrected spec does not overwrite a known code. Neither is research's
    choice, and the driver cannot tell which, so it keeps the code and names
    where it is: on the case."""
    mod = _driver()
    _set_code(session, case, "LOGISTICS")
    out = mod.set_industry_if_absent(case, {"industry": "AUTOMOTIVE_OEM"})
    assert _held(session, case) == "LOGISTICS"
    assert out["origin"] == "CASE_RECORD"


def test_a_disagreement_with_the_spec_is_said_out_loud():
    """A kept code that is not the spec's prices the estate, so the run log
    says which two codes disagree rather than leaving the reader to find a
    label in a manifest."""
    src = (ROOT / "tools" / "run_samples.py").read_text("utf-8")
    assert 'if ind["origin"] == "CASE_RECORD":' in src
    assert "INDUSTRY NOT THE SPEC'S" in src


def test_no_code_is_credited_to_entity_resolution():
    """It never writes one, so the driver has no case in which the label
    would be true."""
    src = (ROOT / "tools" / "run_samples.py").read_text("utf-8")
    assert '"ENTITY_RESOLUTION"' not in src

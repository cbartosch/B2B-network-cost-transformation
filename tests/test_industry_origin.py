"""Where a sample case's industry code came from, claiming nothing unseen.

Resolution never writes the code: `confirm` records what the resolver called
the sector as `industry_as_resolved` and leaves the code alone. The driver
labelled every known code ENTITY_RESOLUTION, which was true of none of the
fifty: forty-eight said so, and Maersk and Michelin said SPEC_FALLBACK only
on the run that wrote their codes, then ENTITY_RESOLUTION on the next.

Nor does a code equal to the spec's prove the spec supplied it - an analyst
can enter the same code through the intake form. Equality names the code,
not who chose it. So SPEC_FALLBACK is the run that writes the code, a code
already on the case is CASE_RECORD, and agrees_with_spec is a separate fact.
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
    """What the intake form's industry field does."""
    from app import db
    session.execute(update(db.case).where(db.case.c.case_id == case_id)
                    .values(industry=code))
    session.commit()


def _held(session, case_id):
    from app import db
    session.expire_all()
    return session.execute(select(db.case.c.industry).where(
        db.case.c.case_id == case_id)).scalar()


def _origin(out):
    return out["origin"], out["agrees_with_spec"]


def test_only_the_run_that_writes_the_code_credits_the_spec(session, case):
    """The first run writes the spec's code. The second finds it on the case
    and cannot see who put it there, so it says where it took the code from
    - and that the code is the spec's - rather than ENTITY_RESOLUTION, as it
    did."""
    mod = _driver()
    spec = {"industry": "AUTOMOTIVE_OEM"}
    first = mod.set_industry_if_absent(case, spec)
    second = mod.set_industry_if_absent(case, spec)
    assert _held(session, case) == "AUTOMOTIVE_OEM"
    assert _origin(first) == ("SPEC_FALLBACK", True)
    assert _origin(second) == ("CASE_RECORD", True)


def test_a_code_entered_on_the_case_is_not_credited_to_the_spec(session, case):
    """The review's case: an analyst enters the spec's own code through the
    intake form, and the run never wrote it. Equal is not supplied."""
    mod = _driver()
    _set_code(session, case, "AUTOMOTIVE_OEM")
    out = mod.set_industry_if_absent(case, {"industry": "AUTOMOTIVE_OEM"})
    assert _origin(out) == ("CASE_RECORD", True)


def test_an_unknown_code_on_the_case_gives_way_to_the_spec_s(session, case):
    """Maersk's case held SHIPPING_LOGISTICS, a code no reference table
    carries, which prices the estate on DEFAULT. The spec's code replaces
    it, and this run wrote it."""
    mod = _driver()
    _set_code(session, case, "SHIPPING_LOGISTICS")
    out = mod.set_industry_if_absent(case, {"industry": "LOGISTICS"})
    assert _held(session, case) == "LOGISTICS"
    assert _origin(out) == ("SPEC_FALLBACK", True)


def test_a_known_code_that_is_not_the_spec_s_is_kept_and_says_so(session, case):
    """Set on the case some other way - by hand, or by an older spec, since a
    corrected spec does not overwrite a known code. Kept, and reported as
    not the spec's."""
    mod = _driver()
    _set_code(session, case, "LOGISTICS")
    out = mod.set_industry_if_absent(case, {"industry": "AUTOMOTIVE_OEM"})
    assert _held(session, case) == "LOGISTICS"
    assert _origin(out) == ("CASE_RECORD", False)


def test_a_disagreement_with_the_spec_is_said_out_loud():
    """A kept code that is not the spec's prices the estate, so the run log
    says which two codes disagree rather than leaving the reader to find a
    flag in a manifest."""
    src = (ROOT / "tools" / "run_samples.py").read_text("utf-8")
    assert 'if not ind["agrees_with_spec"]:' in src
    assert "INDUSTRY NOT THE SPEC'S" in src


def test_no_code_is_credited_to_entity_resolution():
    """It never writes one, so the driver has no case in which the label
    would be true."""
    src = (ROOT / "tools" / "run_samples.py").read_text("utf-8")
    assert '"ENTITY_RESOLUTION"' not in src

"""A source fragment nobody can read proves nothing.

Spec 0.3A ties EVIDENCED_PUBLIC to "a stored source fragment". `resp.text`
decodes whatever bytes arrive, so fetching an annual report stored 600
characters of "%PDF-1.7 endstream obj" mojibake and satisfied that rule to
the letter while proving nothing.

The same bytes went to the claim check as the page text. Across the sample
set 395 captures are unreadable - 342 PDFs, 16 spreadsheets - and 36 of
them carry claim_verified=True: a figure marked independently verified
because its digits happened to fall inside compressed binary.
"""
import httpx
import pytest

from app.domain import research


class _Resp:
    def __init__(self, body, ctype, status=200):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.text = body
        self.content = body.encode("utf-8", "replace")


def _fetch(monkeypatch, resp):
    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return resp

    monkeypatch.setattr(research._transport, "outbound_client",
                        lambda timeout: _Client())
    return research._fetch_source_fragment("https://example.test/doc")


def test_a_pdf_is_reported_not_quoted(monkeypatch):
    out = _fetch(monkeypatch, _Resp("%PDF-1.7 \x00\x01 endstream obj",
                                    "application/pdf"))
    assert out is not None, "the fetch is real; the capture is kept"
    assert "no text extracted" in out["fragment"]
    assert "application/pdf" in out["fragment"]
    assert "%PDF" not in out["fragment"]


def test_an_unread_source_verifies_no_claim(monkeypatch):
    """The body is empty, so _claim_in_body answers honestly instead of
    matching a figure against compressed binary."""
    out = _fetch(monkeypatch, _Resp("%PDF-1.7 endstream 13706 obj",
                                    "application/pdf"))
    assert out["_body"] == ""
    found, _how = research._claim_in_body("13706", out["_body"])
    assert not found, "a claim cannot be verified against bytes nobody read"


def test_a_spreadsheet_is_treated_the_same(monkeypatch):
    out = _fetch(monkeypatch, _Resp(
        "PK\x03\x04\x00\x00 xl/worksheets",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    assert "no text extracted" in out["fragment"]


def test_a_pdf_served_as_html_is_still_caught(monkeypatch):
    """The content type gets a vote and so do the bytes: servers mislabel,
    and 26 of the unreadable captures came from URLs with no extension."""
    out = _fetch(monkeypatch, _Resp("%PDF-1.7 endstream obj junk",
                                    "text/html"))
    assert "no text extracted" in out["fragment"]


def test_mostly_control_characters_is_not_a_fragment(monkeypatch):
    out = _fetch(monkeypatch, _Resp("ab" + "\x01\x02\x03" * 40, "text/html"))
    assert "no text extracted" in out["fragment"]


def test_a_real_page_is_unchanged(monkeypatch):
    """The fix must not touch the 2,647 captures that are readable."""
    page = "<html><body>Tesco operates 182 stores in Ireland.</body></html>"
    out = _fetch(monkeypatch, _Resp(page, "text/html; charset=utf-8"))
    assert out["fragment"] == "Tesco operates 182 stores in Ireland."
    assert out["_body"] == "Tesco operates 182 stores in Ireland."
    found, _how = research._claim_in_body("182 stores", out["_body"])
    assert found


def test_json_still_counts_as_text(monkeypatch):
    out = _fetch(monkeypatch, _Resp('{"sites": 182}', "application/json"))
    assert out["fragment"] == '{"sites": 182}'
    assert out["_body"]


# ------------------------- captures stored before the fetch refused binary
def _disposition(session, *, fragment, grade, disposition, reason):
    import uuid

    from sqlalchemy import insert

    from app import db

    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester", price_year=2026,
        subject_entity_legal_name="Acme Global Logistics"))
    source = {"url": "https://example.test/annual-report.pdf",
              "publisher": "Acme plc", "source_class": "COMPANY_PUBLISHED",
              "how_read": "FULL_PAGE", "excerpt": "operates 2,600 stores",
              "fragment": fragment, "claim_verified": True,
              "claim_checked": "FIGURES_ONLY"}
    row_id = str(uuid.uuid4())
    session.execute(insert(db.domain_disposition).values(
        id=row_id, case_id=case_id, estimate_snapshot_id=None, domain_no=2,
        domain_name="Locations", disposition=disposition, reason=reason,
        agent_run_id=str(uuid.uuid4()),
        evidence={"sources": [source, {**source, "url": "https://b.test/",
                                       "fragment": "Acme operates 2,600 "
                                                   "stores across Europe"}],
                  "quantities": [{"label": "STORE", "value": 2600}],
                  "triangulated": [],
                  "reliability": {"grade": grade, "verified_sources": 2,
                                  "unconfirmed_sources": 0}}))
    session.commit()
    return row_id


def _policy():
    import types
    from decimal import Decimal

    return types.SimpleNamespace(min_independent_sources_material_fact=2,
                                 material_spread_share=Decimal("0.15"),
                                 stale_after_years=3)


def test_a_stored_binary_capture_is_re_read_and_the_finding_regraded(
        session):
    """The 2,600 was "verified" inside a compressed PDF stream. Read again
    with the reader the fetch uses now, that claim is unverified, and the
    finding is graded again from what was stored."""
    from sqlalchemy import select

    from app import db
    from app.domain import reliability

    row_id = _disposition(
        session, fragment="%PDF-1.7 2600 0 obj endstream",
        grade=reliability.VERY_RELIABLE, disposition="EVIDENCED_PUBLIC",
        reason=None)

    out = research.reverify_dispositions(session, policy=_policy())

    assert [o["captures_reread"] for o in out] == [1]
    row = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.id == row_id)).one()
    pdf, page = row.evidence["sources"]
    assert pdf["claim_verified"] is False and "no text extracted" in (
        pdf["fragment"])
    assert page["claim_verified"] is True
    assert row.evidence["reliability"]["grade"] != reliability.VERY_RELIABLE
    assert row.disposition == "DECLARED_UNKNOWN"
    assert research.reverify_dispositions(session, policy=_policy()) == []


def _stored(session, row_id):
    from sqlalchemy import select

    from app import db

    return session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.id == row_id)).one()


def test_a_disposition_a_person_set_keeps_it(session):
    """Not what its stored grade maps to, so somebody set it. What was read
    is corrected; what they decided is not."""
    from app.domain import reliability

    row_id = _disposition(session, fragment="%PDF-1.7 2600 0 obj endstream",
                          grade=reliability.RELIABLE,
                          disposition="EVIDENCED_PUBLIC", reason=None)
    research.reverify_dispositions(session, policy=_policy())
    row = _stored(session, row_id)
    assert row.disposition == "EVIDENCED_PUBLIC"
    assert row.evidence["sources"][0]["claim_verified"] is False


def test_a_finding_from_before_grading_keeps_its_disposition(session):
    """Every disposition on the sample set predates grading: no stored grade
    at all. The first version regraded them under today's rules and moved 69
    from EVIDENCED_PUBLIC to DECLARED_UNKNOWN - a change of rules, not a
    page re-read."""
    row_id = _disposition(session, fragment="%PDF-1.7 2600 0 obj endstream",
                          grade=None, disposition="EVIDENCED_PUBLIC",
                          reason=None)
    out = research.reverify_dispositions(session, policy=_policy())
    assert [o["disposition"] for o in out] == [["EVIDENCED_PUBLIC"] * 2]
    row = _stored(session, row_id)
    assert row.disposition == "EVIDENCED_PUBLIC" and row.reason is None
    assert row.evidence["sources"][0]["claim_verified"] is False
    assert row.evidence["reliability"]["grade"] is None

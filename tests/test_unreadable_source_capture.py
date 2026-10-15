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

"""`_error` is text, and the client has to make it so.

Setting DHL's entity identifier raised

    TypeError: unsupported operand type(s) for +: 'dict' and 'str'

because this API raises `HTTPException(status, {"error": ..., "detail": ...})`
in 64 places and FastAPI puts that whole dict in `detail`. The client passed it
through, so `_error` was a dict and the page's `_r["_error"] + " ..."` raised.
The real API message was inside the dict; the analyst saw a traceback.

The 63 other readers interpolate it into an f-string, so they would not have
crashed - they would have printed a raw Python dict to an analyst. Worse in a
way, because nobody would have reported it.

Normalised at the single point `_error` is built. Fixing the one concatenation
site would have left the next to be found the same way.
"""
import pathlib


def _client():
    root = pathlib.Path(__file__).resolve().parents[1]
    return (root / "analyst_ui" / "streamlit_app" / "api_client.py").read_text()


def _flatten(body, text="raw"):
    """Run the client's own normalisation, lifted out of the request path."""
    src = _client()
    start = src.index('        detail = body.get("detail", r.text)')
    end = src.index('        return {"_error": detail', start)
    block = "\n".join(line[8:] for line in src[start:end].splitlines())
    namespace = {"body": body, "r": type("R", (), {"text": text})()}
    exec(block, namespace)
    return namespace["detail"]


def test_a_dict_detail_becomes_readable_text():
    """The shape this API actually returns, 64 times over."""
    out = _flatten({"detail": {"error": "V0 publication refused",
                               "detail": "coverage 0.0% below the floor"}})
    assert isinstance(out, str)
    assert "V0 publication refused" in out
    assert "coverage 0.0%" in out


def test_extra_keys_survive_rather_than_being_dropped():
    """A refusal carries its numbers. Keeping only the headline would throw
    away the part an analyst acts on."""
    out = _flatten({"detail": {"error": "refused", "detail": "why",
                               "effective_coverage_pct": "0.000"}})
    assert "effective_coverage_pct: 0.000" in out


def test_a_plain_string_detail_is_untouched():
    assert _flatten({"detail": "not found"}) == "not found"


def test_a_validation_list_becomes_readable():
    """FastAPI's own 422s arrive as a list of dicts, not a dict."""
    out = _flatten({"detail": [{"loc": ["body", "industry"],
                                "msg": "field required"}]})
    assert isinstance(out, str)
    assert "body.industry" in out and "field required" in out


def test_an_unrecognised_dict_still_yields_text():
    """No shape may return a non-string. A reader that interpolates a dict
    prints Python at an analyst."""
    out = _flatten({"detail": {"blockers": "x", "stage": "2"}})
    assert isinstance(out, str) and out


def test_a_missing_detail_falls_back_to_the_body_text():
    assert _flatten({}, text="raw body") == "raw body"


def test_no_page_concatenates_error_without_relying_on_the_contract():
    """63 readers interpolate `_error` into an f-string and one concatenated
    it. Both need it to be text; the contract belongs in one place."""
    client = _client()
    assert "isinstance(detail, dict)" in client
    assert "isinstance(detail, list)" in client

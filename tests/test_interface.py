"""Interface boundary.

F-04: eight interface modules, 864 lines, zero test references. C2-04 - the API
enforcing a header the UI never sent - was exactly this gap, found by a user
running it rather than by the suite.

Rendering Streamlit pages needs a browser driver. What is testable without one
is the boundary: the client that wraps every call and interprets error shapes,
and the structural rules the pages must obey. Both are where the defects were.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "analyst_ui" / "streamlit_app"


def _client(token: str = ""):
    """Load api_client.py fresh, with the contract module importable as the UI
    image arranges it."""
    if not (UI / "api_client.py").exists():
        pytest.skip("analyst_ui not present in this image")
    os.environ["API_TOKEN"] = token
    sys.path.insert(0, str(UI.parent.parent / "contract"))
    sys.path.insert(0, str(UI))
    for name in ("api_client", "contract.auth"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("api_client", UI / "api_client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the token contract -----------------------------------------------------
def test_the_client_attaches_the_token_the_api_expects():
    from app import config
    client = _client("secret-value")
    assert client.auth_headers() == {config.AUTH_HEADER: "secret-value"}


def test_the_client_sends_nothing_when_no_token_is_configured():
    client = _client("")
    assert client.auth_headers() == {} and not client.auth_configured()


def test_the_client_and_the_api_resolve_one_header_definition():
    from app import config
    assert _client().AUTH_HEADER is config.AUTH_HEADER


# --- misconfiguration must be diagnosable, not silent -----------------------
def test_a_token_on_the_api_and_none_here_is_reported():
    """/v1/health is auth-exempt, so it succeeds while every other route 401s.
    Without this check the operator sees a green home page and failures
    everywhere else."""
    problem = _client("").probe_auth({"auth_required": True})
    assert problem and "no token" in problem.lower()


def test_a_token_here_and_none_on_the_api_is_reported():
    problem = _client("t").probe_auth({"auth_required": False, "auth_header": "X-API-Token"})
    assert problem and "out of step" in problem.lower()


def test_a_header_name_mismatch_is_reported():
    problem = _client("t").probe_auth({"auth_required": True,
                                       "auth_header": "X-Different-Header"})
    assert problem and "mismatch" in problem.lower()


def test_agreement_reports_no_problem():
    from app import config
    assert _client("").probe_auth({"auth_required": False,
                                   "auth_header": config.AUTH_HEADER}) is None


# --- structural rules the pages must obey -----------------------------------
def _pages():
    if not (UI / "pages").exists():
        pytest.skip("analyst_ui not present in this image")
    return sorted((UI / "pages").glob("*.py"))


def test_no_page_reaches_past_the_api():
    """Spec 2.1: Streamlit holds no database, model or Internet credentials and
    talks to nothing but the API."""
    import ast
    offenders = []
    for page in _pages() + [UI / "app.py"]:
        tree = ast.parse(page.read_text())
        for node in ast.walk(tree):
            # imports, not mentions: app.py names the key variables in a help
            # message, which is not the same as reading them.
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                name = getattr(node, "module", "") or ""
                names = [a.name for a in node.names] + [name]
                for n in names:
                    if n and n.split(".")[0] in ("httpx", "sqlalchemy", "psycopg", "app"):
                        offenders.append(f"{page.name}: imports {n}")
            # reading a credential from the environment
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") in ("getenv", "environ")):
                arg = node.args[0].value if node.args and hasattr(node.args[0], "value") else ""
                if str(arg).endswith(("_API_KEY", "DATABASE_URL")):
                    offenders.append(f"{page.name}: reads {arg}")
    assert not offenders, offenders


# Page 7 is the execution-integrity view: system-wide, not case-scoped.
CASE_SCOPED = [f"{n}_" for n in range(1, 7)]


def test_every_case_scoped_page_requires_a_case_before_acting():
    """Acting without one would produce a confusing failure deep in the API
    rather than a clear prompt."""
    missing = [p.name for p in _pages()
               if any(p.name.startswith(prefix) for prefix in CASE_SCOPED)
               and "case_id" not in p.read_text()]
    assert not missing, f"pages that do not check for a case: {missing}"


def test_every_page_handles_the_error_shape_the_client_returns():
    """The client signals failure with an `_error` key rather than raising, so a
    page that never checks it renders a traceback or, worse, nothing."""
    unchecked = [p.name for p in _pages() if "_error" not in p.read_text()]
    assert not unchecked, f"pages that ignore API errors: {unchecked}"

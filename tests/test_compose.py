"""Compose file validity.

`docker compose up` failed on a duplicate `environment:` key in the `ui`
service. Every "compose ok" check reported during development had used PyYAML's
default loader, which silently keeps the last of a duplicated key - so the file
validated locally and was rejected by Compose's Go parser, which does not.

Worse than the false pass: taking the *last* block meant `API_BASE_URL` was
being dropped, and the only reason the UI would have worked is that the client's
fallback happens to be the same value.

These tests use a loader that rejects duplicates, which is what Compose does.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


class _Strict(yaml.SafeLoader):
    pass


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None,
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}",
                key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                        _no_duplicate_keys)


@pytest.fixture(scope="module")
def compose():
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml not present in this image")
    with COMPOSE.open() as fh:
        return yaml.load(fh, Loader=_Strict)


def test_compose_has_no_duplicate_keys(compose):
    """The failure itself. PyYAML's default loader would not have caught it."""
    assert compose["services"]


def test_the_ui_knows_where_the_api_is(compose):
    """The duplicate block dropped this. It only looked harmless because the
    client's fallback is the same string."""
    assert compose["services"]["ui"]["environment"]["API_BASE_URL"] == "http://api:8000"


def test_the_ui_holds_no_database_or_provider_credentials(compose):
    """Spec 2.1: Streamlit reaches the system only through the API."""
    env = compose["services"]["ui"]["environment"]
    for forbidden in ("DATABASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert forbidden not in env


def test_the_ui_has_no_route_to_the_database(compose):
    """The boundary is a network attachment, not a convention."""
    assert "backend" not in compose["services"]["ui"]["networks"]
    assert compose["networks"]["backend"].get("internal") is True


def test_both_services_receive_the_shared_secret(compose):
    """C2-04: the API enforced a header the UI never sent. Compose has to pass
    the token to both or enabling it breaks the interface."""
    for svc in ("api", "ui"):
        assert "API_TOKEN" in compose["services"][svc]["environment"]


def test_every_compose_variable_is_read_by_the_code(compose):
    """A variable set in compose and read nowhere is the same defect this
    bundle has found repeatedly, in configuration rather than code."""
    root = COMPOSE.parent
    sources = []
    for folder in ("api_service/app", "analyst_ui", "contract"):
        path = root / folder
        if path.exists():
            sources += [p.read_text() for p in path.rglob("*.py")]
    blob = "\n".join(sources)
    if not blob:
        pytest.skip("application sources not present in this image")

    unread = []
    for svc in ("api", "ui"):
        for key in compose["services"][svc].get("environment", {}):
            if key in ("DATABASE_URL", "WORKBENCH_ENVIRONMENT"):
                continue                      # consumed via config indirection
            if f'"{key}"' not in blob and f"'{key}'" not in blob:
                unread.append(f"{svc}.{key}")
    assert not unread, f"set in compose, read nowhere: {unread}"


# --- Dockerfile paths -------------------------------------------------------
# `docker compose up` failed a second time on `COPY api_service/tests ./tests`:
# the tests live at the bundle root. The path had been wrong since the build
# context moved to the root in C2-04, and nothing noticed because nothing had
# built the image. A COPY source that does not exist is a build failure, not a
# runtime one, so no amount of testing the application would have caught it.

DOCKERFILES = {"api_service/Dockerfile": ".", "analyst_ui/Dockerfile": "."}


def _copy_sources(dockerfile: Path):
    import re
    return [m.group(1) for m in
            re.finditer(r"^COPY\s+(\S+)\s+(\S+)", dockerfile.read_text(), re.M)]


@pytest.mark.parametrize("dockerfile,context", sorted(DOCKERFILES.items()))
def test_every_dockerfile_copy_source_exists(dockerfile, context):
    root = COMPOSE.parent
    path = root / dockerfile
    if not path.exists():
        pytest.skip(f"{dockerfile} not present in this image")
    missing = [src for src in _copy_sources(path)
               if not (root / context / src).exists()]
    assert not missing, f"{dockerfile} copies paths that do not exist: {missing}"


def test_the_dockerfile_contexts_match_compose(compose):
    """A Dockerfile's COPY paths are relative to the context compose gives it,
    so the two have to be checked together or each looks fine alone."""
    for service, dockerfile in (("api", "api_service/Dockerfile"),
                                ("ui", "analyst_ui/Dockerfile")):
        build = compose["services"][service]["build"]
        assert build["context"] == DOCKERFILES[dockerfile]
        assert build["dockerfile"] == dockerfile


def test_the_api_image_receives_the_tests_it_is_told_to_run(compose):
    """`make test` runs pytest inside the api container, so the tests have to
    be in it."""
    root = COMPOSE.parent
    path = root / "api_service" / "Dockerfile"
    if not path.exists():
        pytest.skip("Dockerfile not present in this image")
    assert any(src.rstrip("/") == "tests" for src in _copy_sources(path)), \
        "the api image copies no tests directory"


# --- corporate TLS ----------------------------------------------------------
def test_the_trust_anchor_is_named_not_inherited(compose):
    """trust_env=False means SSL_CERT_FILE is ignored on purpose, so the anchor
    has to be a deployment input or provider calls cannot verify at all behind
    an inspecting proxy."""
    assert "LLM_CA_BUNDLE" in compose["services"]["api"]["environment"]


def test_verification_is_not_disabled_by_default(compose):
    value = compose["services"]["api"]["environment"]["LLM_INSECURE_SKIP_TLS_VERIFY"]
    assert "false" in str(value)


def test_the_images_install_corporate_anchors_before_pip():
    """pip cannot verify PyPI until the re-signing CA is trusted, so the order
    is the whole point - installing them afterwards fixes nothing."""
    root = COMPOSE.parent
    for dockerfile in ("api_service/Dockerfile", "analyst_ui/Dockerfile"):
        path = root / dockerfile
        if not path.exists():
            pytest.skip(f"{dockerfile} not present")
        text_ = path.read_text()
        assert "update-ca-certificates" in text_
        assert text_.index("ca-certificates/corporate") < text_.index("pip install")


def test_no_corporate_certificate_is_committed():
    """Trust anchors are environment-specific and not ours to distribute."""
    certs = COMPOSE.parent / "certs"
    if not certs.exists():
        pytest.skip("certs/ not present")
    leaked = [p.name for p in certs.iterdir() if p.suffix in (".crt", ".pem")]
    assert not leaked, f"certificates committed: {leaked}"

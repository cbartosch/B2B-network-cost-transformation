import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config, db, jobs, migrations
from .routers.api import router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("workbench")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Schema first. An unrecognised or newer schema stops the service rather
    # than producing a system that starts, runs and is quietly wrong.
    try:
        report = migrations.ensure(db.engine)
        _app.state.schema = report
    except (migrations.SchemaStateRefused, migrations.MigrationFailed) as exc:
        log.error("REFUSING TO START: %s", exc)
        raise
    # A pinning configuration that would degrade silently is refused here, for
    # the same reason a wrong schema is: a service that starts and is quietly
    # unprotected is worse than one that does not start.
    from .llm.providers import _transport
    try:
        for warning in _transport.startup_check():
            log.warning("TLS pinning: %s", warning)
    except _transport.PinConfigurationRefused as exc:
        log.error("REFUSING TO START: %s", exc)
        raise

    env = config.environment()
    avail = [n for n, c in config.PROVIDERS.items() if c["api_key"]]
    log.info("environment=%s providers_configured=%s", env, avail or "NONE")
    if not avail:
        log.warning("No provider configured. LIVE agent runs will FAIL CLOSED "
                    "rather than returning canned output (spec 7.2B).")
    # Refuse the one pinning combination that silently reverts to the
    # pre-C3-03 behaviour, and warn about the merely degraded one.
    from .llm.providers import _transport
    _transport.assert_pinning_supported()
    spki = _transport.spki_warning()
    if spki:
        log.warning("TLS pinning degraded: %s", spki["message"])

    if not config.API_TOKEN:
        log.warning("API_TOKEN is unset - every endpoint is unauthenticated. "
                    "Acceptable on a laptop, wrong anywhere else.")
    # Idempotent per table, so a table introduced by a later build is populated
    # even when others are already present. Reloading everything is `make seed`.
    try:
        from .seed import seed
        seed(force=False)
    except Exception as exc:                     # noqa: BLE001
        log.warning("reference seed skipped: %s", exc)
    # A process that died mid-simulation leaves rows nothing else would finish.
    # Best effort: a failure must not stop the service from serving, but it is
    # logged at ERROR rather than swallowed.
    try:
        report = jobs.reclaim_interrupted()
        _app.state.reclaimed = report
        if any(report.values()):
            log.info("reclaimed interrupted simulations: %s", report)
    except Exception:                            # noqa: BLE001
        log.exception("could not reclaim interrupted simulations")
        _app.state.reclaimed = {"error": "reclaim failed; see logs"}
    yield


# When a token is configured the interactive docs are switched off rather than
# left half-working: Swagger UI cannot attach the header, so leaving it enabled
# would publish the API surface unauthenticated while every call it makes fails.
_LOCKED = bool(config.API_TOKEN)

app = FastAPI(title="Enterprise Network Cost Transformation Workbench",
              version="4.7.4-scaffold", lifespan=lifespan,
              docs_url=None if _LOCKED else "/docs",
              redoc_url=None,
              openapi_url=None if _LOCKED else "/openapi.json",
              description="Stage 0 vertical slice. FastAPI is the sole control "
                          "plane; Streamlit holds no database, model or Internet "
                          "credentials.")


@app.exception_handler(LookupError)
async def _not_found(_request: Request, exc: LookupError):
    """A domain resolver that cannot find an identifier means the identifier is
    wrong, not that the server is broken. Handled once here rather than in every
    route that resolves one."""
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.middleware("http")
async def require_token(request: Request, call_next):
    """Optional shared secret, off by default so the bundle runs out of the box.

    Comparison is constant-time. `!=` on a secret leaks its length and prefix
    through response timing, which is cheap to avoid and awkward to retrofit.
    """
    if config.API_TOKEN and request.url.path not in config.AUTH_EXEMPT_PATHS:
        supplied = request.headers.get(config.AUTH_HEADER) or ""
        if not secrets.compare_digest(supplied, config.API_TOKEN):
            return JSONResponse(
                {"detail": f"invalid or missing {config.AUTH_HEADER}"},
                status_code=401)
    return await call_next(request)


app.include_router(router)

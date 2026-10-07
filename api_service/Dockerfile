# Patch level pinned, not just the minor. `python:3.12-slim` is a moving tag:
# 3.12.1 and 3.12.9 are both it, so two builds months apart get different
# interpreters and neither can say so. An external auditor's dependency skew
# came from running under 3.13 against a repo that believed it was 3.12, and
# the tag could not have told them otherwise.
#
# A digest would remove the last of the drift. This is the step that costs
# nothing and removes most of it.
FROM python:3.12.8-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Corporate proxy, if this network needs one. Passed as build args rather than
# read from the environment: an ambient proxy variable that silently reroutes
# egress is the same defect class the transport's trust_env=False exists to
# prevent. Empty by default, so a direct-egress network is unaffected.
#   docker compose build --build-arg HTTP_PROXY=http://proxy:8080 ...
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY="localhost,127.0.0.1,db,api,ui"
ENV HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY NO_PROXY=$NO_PROXY \
    http_proxy=$HTTP_PROXY https_proxy=$HTTPS_PROXY no_proxy=$NO_PROXY

# Corporate trust anchors first: an inspecting proxy re-signs HTTPS, so pip
# cannot verify PyPI until the re-signing CA is trusted. Empty by default.
COPY certs/ /usr/local/share/ca-certificates/corporate/
RUN set -eu; \
    if ls /usr/local/share/ca-certificates/corporate/*.crt >/dev/null 2>&1; then \
        update-ca-certificates; \
        echo "installed corporate CA(s):"; \
        ls -1 /usr/local/share/ca-certificates/corporate/*.crt; \
    else \
        echo "no corporate CA supplied - assuming direct egress"; \
    fi
# pip and the runtime both verify against the system bundle, which now contains
# the corporate anchor if one was supplied.
# An inspecting proxy adds a hop to every package download, and bootstrap-ca
# rebuilds without cache - so every wheel is fetched again on a link slower
# than the open internet. pip defaults to a 15-second read timeout and five
# retries, which a corporate link loses on the larger wheels: the build dies
# on ReadTimeoutError from files.pythonhosted.org partway through.
#
# Waiting longer rather than failing. A build that takes four minutes is
# better than one that has to be run three times.
#
# Set as its own ENV, outside the continuation above: a comment inside a
# backslash-continued instruction is handled differently by different Docker
# versions, and this file is the one thing that must build everywhere.
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    LLM_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Diagnostics, before pip: a missing trust anchor otherwise surfaces as twelve
# seconds of retries ending in CERTIFICATE_VERIFY_FAILED, which names a symptom.
COPY tools ./tools
RUN python tools/verify_tls_before_build.py

COPY api_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# The single source of release identity. _version.py read a hardcoded string
# kept in sync by hand, which drifted to 4.31.0 while VERSION said 4.198.0 -
# 167 releases, with /v1/health reporting the old one. Its own comment recorded
# that this had happened before and asked for a real fix rather than another
# patch.
COPY VERSION ./VERSION
COPY api_service/app ./app
# Tests live at the bundle root, beside the two services they exercise -
# test_compose.py and test_wiring.py read files from both.
COPY tests ./tests
# The second of those two services. The line above has always said the tests
# read files from both, and `make test` runs them from inside this image - but
# only api_service/app was ever copied, so roughly a hundred tests that read
# the Streamlit source died on FileNotFoundError before asserting anything.
# The suite's own documented entry point could not run them.
#
# Source only, and read only by the suite: the api process does not import it.
COPY analyst_ui ./analyst_ui
# The bundle-root files the suite reads, for the same reason. Without them
# test_backup_fallback died on FileNotFoundError for make.ps1 - five checks on
# whether `bundle-in` takes a pg_dump when the API is down, which is the one
# occasion that backup is most needed. test_compose.py skips itself when
# docker-compose.yml is absent, which is worse than failing: the guard reported
# nothing and ran nowhere, because this image is the only place the suite runs.
#
# Config and manifests, no secrets: docker-compose.yml names ${POSTGRES_PASSWORD}
# rather than holding it.
COPY docker-compose.yml ./docker-compose.yml
COPY make.ps1 ./make.ps1
# The bundle layout the tooling resolves against, as one symlink rather
# than fourteen edits. Every tool in tools/ locates the service the same
# way - `APP = ROOT / "api_service" / "app"`, or sys.path.insert of
# ROOT/"api_service" - because that is where the service lives in a
# checkout. This image flattens it to /app/app so the api process can
# `import app` from WORKDIR, and every one of those tools then died on
# FileNotFoundError for /app/api_service/app/... - including
# verify_domains.py, which is the end-to-end pass over all 17 agent
# domains and the only one that runs without a network.
#
# Pointing api_service/app at the same files satisfies both spellings
# without moving the package or touching the tools. requirements.txt is
# placed beside it for check_lockfile.py, which reads the per-service
# manifests at their repo-relative paths.
RUN mkdir -p api_service && ln -s /app/app /app/api_service/app
COPY api_service/requirements.txt ./api_service/requirements.txt
# Single definition of the API/UI auth contract, shared with the UI image.
COPY contract ./contract
# Non-root. An earlier revision ran both containers as root.
RUN useradd --create-home --uid 10001 workbench && chown -R workbench:workbench /app
USER workbench
EXPOSE 8000
# Readiness, not liveness: this drives `depends_on: service_healthy`, so it has
# to answer "can it serve?" rather than "is the process up?". /v1/ready makes one
# cheap database round-trip and is never cached.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/ready',timeout=2).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

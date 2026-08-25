FROM python:3.12-slim
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
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    LLM_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Diagnostics, before pip: a missing trust anchor otherwise surfaces as twelve
# seconds of retries ending in CERTIFICATE_VERIFY_FAILED, which names a symptom.
COPY tools ./tools
RUN python tools/verify_tls_before_build.py

COPY api_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api_service/app ./app
# Tests live at the bundle root, beside the two services they exercise -
# test_compose.py and test_wiring.py read files from both.
COPY tests ./tests
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

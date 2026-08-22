# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS runtime

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=60

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    PIP_PREFER_BINARY=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Optional corporate/interception CA support.
# Put one or more Base-64 PEM certificates with a .crt extension in ./certs.
# Certificates are appended before apt runs, then installed into Debian's
# managed CA store. This handles TLS-inspecting corporate proxies for both apt
# and pip without disabling certificate verification.
COPY certs/ /tmp/workbench-certs/
RUN set -eux; \
    mkdir -p /etc/ssl/certs; \
    touch /etc/ssl/certs/ca-certificates.crt; \
    for cert in /tmp/workbench-certs/*.crt; do \
        if [ -f "$cert" ] && [ -s "$cert" ]; then \
            cat "$cert" >> /etc/ssl/certs/ca-certificates.crt; \
            printf '\n' >> /etc/ssl/certs/ca-certificates.crt; \
        fi; \
    done; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    for cert in /tmp/workbench-certs/*.crt; do \
        if [ -f "$cert" ] && [ -s "$cert" ]; then \
            cp "$cert" "/usr/local/share/ca-certificates/$(basename "$cert")"; \
        fi; \
    done; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/* /tmp/workbench-certs

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY requirements-runtime.txt ./

# Install runtime dependencies directly. We deliberately do not run `pip install .`
# inside the container because PEP 517 build isolation would start a second pip
# process to download Hatchling. That extra bootstrap step is fragile behind
# TLS-inspecting corporate proxies and is unnecessary for this source-layout app.
RUN python -m pip install --no-cache-dir --prefer-binary \
    --requirement requirements-runtime.txt

COPY src ./src
COPY streamlit_app.py ./
RUN python -m compileall -q /app/src /app/streamlit_app.py

USER app

EXPOSE 8000 8501

CMD ["uvicorn", "network_cost_workbench.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

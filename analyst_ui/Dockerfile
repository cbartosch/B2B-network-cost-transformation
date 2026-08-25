FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
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

COPY analyst_ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY analyst_ui/streamlit_app ./streamlit_app
# Same contract file as the API image. Placed inside streamlit_app so it
# is importable: Streamlit puts the script's directory on sys.path.
COPY contract ./streamlit_app/contract
RUN useradd --create-home --uid 10002 analyst && chown -R analyst:analyst /app
USER analyst
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=2).status==200 else 1)"
CMD ["streamlit", "run", "streamlit_app/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]

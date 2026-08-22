# Enterprise Network Cost Transformation Workbench

Initial implementation scaffold for the evidence-gated network cost transformation workflow described in the v4.6 development specification.

## What is implemented

- V0-V5 evidence-stage policy and validation
- Deterministic coverage and savings calculations using `Decimal`
- FastAPI control plane with typed calculation endpoints
- Streamlit thin client that calls the API only
- Prefect outer workflow scaffold
- LangGraph/LangChain-ready agent runtime contract with explicit execution modes
- Fail-closed production controls: no synthetic fallback for LIVE agent runs
- PostgreSQL schema bootstrap for tenants, engagements, evidence, analyses, agents, market facts, and benchmark releases
- Docker bundle for PostgreSQL, FastAPI, and Streamlit
- Unit tests, linting, and a Docker smoke test in CI

## Architecture

```text
Streamlit (thin UI, no DB/model credentials)
    -> FastAPI control plane
        -> Prefect process workflows
        -> LangGraph bounded agent workflows
        -> deterministic domain services
            -> PostgreSQL (structured system of record)
            -> object storage (original evidence; adapter added later)
```

The initial commit intentionally does **not** include client data, benchmark observations, credentials, or model-provider configuration.

## Start the complete Docker bundle

```bash
cp .env.example .env
docker compose up -d --build
./scripts/docker_smoke.sh
```

Open:

- Streamlit: `http://localhost:8501`
- FastAPI docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/health`

Inspect or stop the stack:

```bash
docker compose ps
docker compose logs -f --tail=200
docker compose down
```

To remove the local PostgreSQL volume as well:

```bash
docker compose down -v
```

The default bundle is for local development. Credentials in `docker-compose.yml` are deliberately local-only placeholders and must be replaced before any shared or production deployment.

## Corporate TLS / SSL certificate errors

If the image build fails with `CERTIFICATE_VERIFY_FAILED`, Docker is not trusting
the CA used by the corporate proxy or security gateway. The image installs
Debian's CA bundle and supports local corporate-CA injection.

On Windows, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\export_windows_trusted_roots.ps1

docker compose down --remove-orphans
docker compose build --no-cache --progress=plain api ui
docker compose up -d
.\scripts\docker_smoke.ps1
```

For the smaller and preferred trust set, export only the corporate TLS-inspection
root as Base-64 X.509/PEM and save it as `certs/corporate-root-ca.crt`. See
`certs/README.md` for details.

If the organization uses an approved internal package mirror, set
`PIP_INDEX_URL` in `.env` to the mirror URL. Do not embed credentials in that URL
and do not permanently disable certificate verification.

The VS Code `Unknown channel: agentHostClientProxy` message is unrelated to the
Docker build failure.

### PEP 517 / build-dependency errors

If Docker reports `pip subprocess to install build dependencies did not run successfully`,
the project itself must not be installed with `pip install .` inside the image. The
container uses `requirements-runtime.txt` and `PYTHONPATH=/app/src` instead, so no
Hatchling/build-isolation download is required. Rebuild with no cache after updating:

```powershell
docker compose down --remove-orphans
docker compose build --no-cache --progress=plain api ui
docker compose up -d
.\scripts\docker_smoke.ps1
```

If a direct dependency download still fails with `CERTIFICATE_VERIFY_FAILED`, the
remaining issue is the corporate CA or package mirror rather than PEP 517. Export the
corporate root certificate as described above or configure the approved internal
`PIP_INDEX_URL`.

## Local Python development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

docker compose up -d postgres
uvicorn network_cost_workbench.api.main:app --reload
streamlit run streamlit_app.py
```

## Run tests

```bash
pytest
ruff check .
```

## Stage boundaries

| Version | Purpose | Highest permitted evidence class |
|---|---|---|
| V0 | Outside-in estimate | Public evidence and approved priors |
| V1 | Guided assessment | Management responses |
| V2 | Commercial baseline | Contracts, invoices, service orders, circuit inventory |
| V3 | Engineering validation | Topology, telemetry, incidents, utilization, serviceability evidence |
| V4 | Market tested | Quotes and bids |
| V5 | Realized | Post-implementation invoices and disconnect evidence |

Later versions replace earlier estimates; they are not additive savings pools.

## Security posture

- Production `MOCK` agent execution is disabled by default.
- A `LIVE` agent run must retain a genuine provider response ID.
- Agents receive typed tools, not arbitrary SQL or direct benchmark-vault access.
- Raw evidence belongs in governed object storage, not Git history.
- This repository must contain synthetic fixtures only.

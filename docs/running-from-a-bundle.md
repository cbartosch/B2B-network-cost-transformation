# Running this from a bundle

Work arrives as a `.bundle` file. This is how to get it into your repository and
the stack running, and what to do when a step does not behave.

Everything below is PowerShell on Windows, which is where this is developed. The
`docker compose` and `git` commands are identical on macOS and Linux; only the
`.\make.ps1` helper and the `$HOME\Downloads` paths differ.

---

## The short version

```powershell
cd "$HOME\Downloads\B2B-network-cost-transformation"

.\make.ps1 bundle-in "$HOME\Downloads\wb-fixed-4_132_0.bundle"
git merge incoming-docs/readme-as-introduction

docker compose up --build -d
docker compose exec api python -m app.seed --force
```

Then open **http://localhost:8501**.

The rest of this document is what each step does, and what to do when one of
them does not go that way.

---

## 1. Back up first, if you have work in the database

A bundle only carries code. Your cases, known facts, locations and estimates
live in a Docker volume, and nothing below touches it — but `docker compose
down -v` does, and that command sits one shell-history entry away from the ones
you are about to run.

```powershell
python tools\backup_cases.py backup --out .\case-backups
```

One readable JSON file per case: the case, its known facts, its dispositions and
any promoted footprint. Restore with `python tools\backup_cases.py restore --dir
.\case-backups`.

This exists because a maintenance instruction in this project's own notes
destroyed a real case's register. Cheap insurance; run it before anything that
mentions `-v`.

---

## 2. Load the bundle

```powershell
.\make.ps1 bundle-in "$HOME\Downloads\wb-fixed-4_132_0.bundle"
```

The helper verifies the file is a real bundle, lists the branches inside it, and
fetches into `incoming-<branch>` rather than onto the branch you are standing
on. Git refuses to overwrite a checked-out branch, and it refuses quietly enough
to look like nothing happened — hence the temporary ref.

Review, then take it:

```powershell
git log --oneline HEAD..incoming-docs/readme-as-introduction
git merge incoming-docs/readme-as-introduction
```

**Doing it by hand** is three commands and no helper:

```powershell
git remote add fixbundle "$HOME\Downloads\wb-fixed-4_132_0.bundle"
git fetch fixbundle
git merge fixbundle/docs/readme-as-introduction
git remote remove fixbundle
```

### When it does not work

**"does not look like a v2 bundle file"** — the download is truncated or the
browser renamed it. Check the size against what was sent and download it again.

**"refusing to fetch into current branch"** — you are on the branch the bundle
carries. Use `bundle-in`, which fetches into a temporary ref, or check out a
different branch first.

**The merge conflicts** — you have local commits on the same branch. The bundle
carries full history, so `git log --graph --oneline HEAD incoming-...` will show
where the two diverged.

---

## 3. Configure

```powershell
Copy-Item .env.example .env
```

Then edit `.env`. The only value the stack will not start sensibly without:

```ini
ANTHROPIC_API_KEY=sk-ant-...
```

Everything else has a working default. The ones worth knowing about:

| setting | default | when to change it |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | a different model |
| `WORKBENCH_ENVIRONMENT` | `DEV` | `PRODUCTION` hides exception detail in API errors |
| `LLM_SEARCH_TIMEOUT_SECONDS` | `480` | a searching call holds the connection for minutes |
| `LLM_EGRESS_PROXY` | empty | **only** if your network mandates a proxy for outbound HTTPS |
| `LLM_CA_BUNDLE` | empty | corporate TLS interception |
| `API_TOKEN` | empty | set it to require a token on every API call |

`.env` is gitignored and does not travel in a bundle. A new clone needs it
written again.

---

## 3a. Lock the dependencies, once

The direct dependencies are pinned. The **transitive** ones are not, so two
builds months apart can install different `starlette`, `anyio` or `numpy` — and
an external auditor's 113 test failures came from exactly that, with no way to
separate defects from the environment.

Run this once, after the first successful build:

```powershell
docker compose run --rm --no-deps api pip freeze > api_service\requirements.lock
docker compose run --rm --no-deps ui  pip freeze > analyst_ui\requirements.lock
python tools\check_lockfile.py
```

`make lock` does the same on macOS and Linux. **This cannot be generated
without a working container** — a lock is a record of what a resolver actually
installed, and inventing transitive versions produces a file that looks
authoritative and is fiction.

`python tools\check_lockfile.py` fails until both exist, and also fails if a
lock has no more packages than its requirements file, since that is a copy
rather than a freeze.

## 4. Start the stack

```powershell
docker compose up --build -d
```

Three containers: `db` (Postgres), `api` (FastAPI, port 8000) and `ui`
(Streamlit, port 8501). The API waits for the database to report healthy, and
runs its migrations on startup.

```powershell
docker compose ps
curl http://localhost:8000/v1/health
```

A healthy API reports its schema version and calculation version. If the schema
version is lower than the code expects, the migrations did not complete — read
`docker compose logs api` rather than continuing.

---

## 5. Seed the reference data

```powershell
docker compose exec api python -m app.seed --force
```

This fills the governed tables: price priors, archetypes, thresholds, research
briefs, regions, the topology template, bandwidth by industry. Without it the
estimate refuses to run rather than inventing values, so the failure is loud.

**`--force` is required after any bundle that changes seeded data.** The
release notes say when. It rewrites reference rows and does not touch your cases.

---

## 6. Use it

Open **http://localhost:8501**. The pages run in order:

| page | what it is for |
|---|---|
| 1 Intake | the entity, its aliases, the countries in scope, the industry |
| 2 Known facts | what the team already knows, and a sweep of what is public |
| 3 Pre-flight | the readiness gate — it will name what is missing |
| 4 Domain dispositions | research, and promoting findings into the estimate |
| 5 Simulation | the estate site by site, and the topology it implies |
| 6 Run V0 | the estimate, its confidence, and asking it questions |
| 7 Execution integrity | agent runs, incidents, attestation, TLS pins |
| 8 Savings recommendation | scenario selection and narrative |
| 9 V1 questionnaire | the stage gate beyond V0 |
| 10 Benchmark vault | steward screen: ingest sources, clear rights, derive bands |

Research on page 4 is slow by design — every domain is a live provider call
carrying a web search plus an independent fetch of each source it cites. Budget
90 to 300 seconds per domain, and expect a full 17-domain run to take twenty
minutes. Each result appears as it lands.

---

## When the stack misbehaves

**`docker compose up` builds and then the API restarts in a loop.** Almost
always a migration failing. `docker compose logs api --tail 50` names the step.

**Provider calls fail with `UNEXPECTED_EOF_WHILE_READING`.** The connection was
cut, not refused. If other calls in the same run succeeded, it is transient —
an intermediary dropping a long-lived request — and the retry now handles it;
re-run the domain. If *every* call fails identically, it is configuration:
`.\make.ps1 tls-doctor` will say whether you need `LLM_CA_BUNDLE` or
`LLM_EGRESS_PROXY`. Adding a CA does not fix a proxy problem and vice versa.

**"no approved prior" on every circuit.** The seed did not run, or did not run
with `--force` after a bundle that changed the priors.

**A page shows an empty list where you expect data.** Check the case selector on
the home page first. Facts, footprints and locations all belong to one case, and
every page operates on the one selected there.

**Starting completely fresh** — this destroys every case:

```powershell
python tools\backup_cases.py backup --out .\case-backups   # first
docker compose down -v
docker compose up --build -d
docker compose exec api python -m app.seed --force
```

`make reset` does the same and backs up first.

---

## Checks you can run without the stack

These need only Python and take seconds:

```powershell
python tools\check_duplication.py     # seven shapes duplication has taken here
python tools\validate_flow.py         # what each stage writes, the next reads
python tools\verify_domains.py        # all 17 research domains through the pipeline
```

The full suite needs the test dependencies:

```powershell
.\make.ps1 test-all
```

---

## Sending work back

```powershell
.\make.ps1 bundle-out
```

Produces a bundle carrying history, so a change returns as a commit whose parent
is genuinely yours and fast-forwards cleanly.

A bundle is an ordinary file containing your repository history. If that history
holds anything sensitive, it travels with it.

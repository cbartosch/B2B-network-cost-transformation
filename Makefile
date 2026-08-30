.PHONY: deck benchmarks reach tls-doctor tls-doctor-in-container check up down logs test seed reset psql doctor migrate pins attest

deck:          ## render a V0 snapshot as a PowerPoint (CASE=<case-id> OUT=v0.pptx)
	python tools/render_v0_deck.py --case $(CASE) -o $(or $(OUT),v0_estimate.pptx)

benchmarks:    ## ingest a folder of benchmark sources (BENCH=./folder RIGHTS=PUBLISHED)
	python tools/ingest_benchmarks.py $(BENCH) --rights $(RIGHTS) $(if $(ORG),--org "$(ORG)",)

reach:         ## prove the container is really on the internet (live, changing values)
	docker compose exec api python -c "import json; from app.domain import reachability; print(json.dumps(reachability.check(), indent=2))"

tls-doctor:    ## diagnose TLS on a corporate network (no Docker needed)
	@python tools/tls_doctor.py || python3 tools/tls_doctor.py

tls-doctor-in-container:  ## same check from inside the api container
	docker compose exec api python tools/tls_doctor.py

check:         ## validate build configuration before building (no Docker needed)
	@python tests/check_build_config.py || python3 tests/check_build_config.py

up: check      ## build and start the stack
	docker compose up --build -d
	@echo "UI  -> http://localhost:8501"
	@echo "API -> http://localhost:8000/docs"

down:
	docker compose down

reset:         ## destroy data and rebuild from scratch
	docker compose down -v
	docker compose up --build -d

logs:
	docker compose logs -f api ui

test:          ## run the integrity + DB control suites inside the api container
	@# DATABASE_URL is passed explicitly so the suite can never bind to Postgres,
	@# independently of anything conftest.py does.
	docker compose exec \
	  -e DATABASE_URL=sqlite:// \
	  -e WORKBENCH_ENVIRONMENT=TEST \
	  api python -m pytest /app/tests -v

seed:          ## top up reference data with any new/changed keys (safe: never touches existing rows unless --force)
	docker compose exec api python -m app.seed --force

pins:          ## show observed TLS pins for bootstrapping TLS_PINS
	docker compose exec api python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/integrity/tls-pins')), indent=2))"

attest:        ## provenance summary to compare against the provider console
	docker compose exec api python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/integrity/attestation')), indent=2))"

doctor:        ## report schema version and drift without changing anything
	docker compose exec api python -c "from app import migrations; print(migrations.status())"

migrate:       ## apply pending schema migrations (also runs at startup)
	docker compose exec api python -c "from app import db, migrations; print(migrations.ensure(db.engine))"

psql:
	docker compose exec db psql -U workbench -d workbench

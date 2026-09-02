.PHONY: audit-contract audit-identity check-duplication validate-flow verify-domains backup restore deck benchmarks reach tls-doctor tls-doctor-in-container check up down logs test seed reset psql doctor migrate pins attest

audit-contract: ## every input field's unit, period and currency
	python tools/audit_data_contract.py

audit-identity: ## what exactly is being audited: commit, versions, surface
	python tools/audit_identity.py

check-duplication: ## seven shapes duplication has taken here, in one pass
	python tools/check_duplication.py

validate-flow: ## check that what each stage writes is read by the next
	python tools/validate_flow.py

verify-domains: ## push a realistic reply for all 17 agent-routed domains through the pipeline
	python tools/verify_domains.py

backup:        ## save every case's hand-entered content to ./case-backups
	python tools/backup_cases.py backup --out ./case-backups

restore:       ## restore backed-up cases (DIR=./case-backups)
	python tools/backup_cases.py restore --dir $(or $(DIR),./case-backups)

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

reset:         ## DESTROYS EVERY CASE - backs up first, and tells you where
	@echo "This drops the database volume. Backing up every case first."
	python tools/backup_cases.py backup --out ./case-backups
	@echo ""
	@echo "Backups are in ./case-backups - restore with 'make restore' after."
	@echo "Press Ctrl-C now if that is not what you want."
	@sleep 5
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

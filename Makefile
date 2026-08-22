.PHONY: install test lint api ui db up down logs smoke

install:
	python -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check .

api:
	uvicorn network_cost_workbench.api.main:app --reload

ui:
	streamlit run streamlit_app.py

db:
	docker compose up -d postgres

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

smoke:
	docker compose up -d --build
	./scripts/docker_smoke.sh

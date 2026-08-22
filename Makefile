.PHONY: install test lint api ui db

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

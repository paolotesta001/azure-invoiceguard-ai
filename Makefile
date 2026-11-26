.PHONY: install install-azure lint format typecheck test check data demo demo-lite down tick record

install:            ## install with dev tools (mock mode)
	pip install -e ".[dev]"

install-azure:      ## add Azure SDKs (azure mode, make record)
	pip install -e ".[dev,azure]"

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .

typecheck:
	mypy

test:
	pytest

check: lint typecheck test   ## everything CI runs

data:               ## regenerate synthetic data (fixed seed)
	PYTHONPATH=src:. python scripts/generate_synthetic_data.py --seed 42 --out data

demo:               ## full mock-mode stack: Postgres + mock ERP + UI → http://localhost:8501
	docker compose up --build

down:
	docker compose down -v

demo-lite:          ## no Docker, no database: in-memory store
	INVOICEGUARD_STORAGE=memory PYTHONPATH=src:. streamlit run ui/app.py

tick:               ## send approval reminders (timeouts)
	PYTHONPATH=src:. python scripts/tick.py

record:             ## replace simulated DI recordings with LIVE ones (azure extras + az login)
	PYTHONPATH=src:. python scripts/record_responses.py

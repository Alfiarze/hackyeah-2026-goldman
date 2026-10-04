.PHONY: run up down logs ps test test-docker bench demo dashboard-dev landing venv db-shell clean sample-pdfs

ADMIN ?= dev-admin-key
GW ?= http://localhost:8000

run: up
	@echo "Dashboard: $(GW)/dashboard/   API docs: $(GW)/docs"

up:
	@test -f .env || cp .env.example .env
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f gateway

ps:
	docker compose ps

venv:
	uv venv -q -p 3.12 .venv && uv pip install -q -e ".[dev]" -p .venv/bin/python

# Test suite on the host against the dockerized Postgres (creates database goldman_test)
test:
	docker compose up -d db
	.venv/bin/pytest -q

# Same suite inside the image (no local Python needed)
test-docker:
	docker compose up -d db
	docker compose run --rm --no-deps -e TEST_DATABASE_URL_BASE=postgresql://goldman:goldman@db:5432 gateway pytest -q

# Performance telemetry on demand: p50/p95/p99 per workload and pipeline stage + throughput.
# Runs the real gateway in-process (mock model, heuristic semantic backend) and writes docs/bench-report.md.
bench:
	docker compose up -d db
	docker compose run --rm --no-deps -e TEST_DATABASE_URL_BASE=postgresql://goldman:goldman@db:5432 gateway python -m aegis.bench > docs/bench-report.md
	@echo "Report written to docs/bench-report.md"

# Run every scripted scenario against the running stack
demo:
	@for s in clean injection detector_miss cross_client expired_lease mcp_poison supply_chain budget_race; do \
		echo "== $$s"; curl -s -X POST -H "X-Admin-Key: $(ADMIN)" $(GW)/admin/demo/scenarios/$$s | python3 -m json.tool | head -40; done

# Landing page as its own container (nginx), http://localhost:8080
landing:
	docker compose --profile landing up -d --build landing
	@echo "Landing: http://localhost:$${LANDING_PORT:-8080}"

# Rebuild the sample contract PDFs (dashboard/public/samples) with headless Chromium in Docker
sample-pdfs:
	docker run --rm -v "$(CURDIR)":/work -w /tmp/pdfs mcr.microsoft.com/playwright:v1.56.1-noble \
		sh -c "npm init -y >/dev/null && npm i --silent playwright@1.56.1 && NODE_PATH=/tmp/pdfs/node_modules node /work/demo/samples/build-pdfs.cjs"
	docker run --rm -v "$(CURDIR)":/work -w /work python:3.12-slim \
		sh -c "pip install -q pypdf && python demo/samples/build_metadata_samples.py"

dashboard-dev:
	cd dashboard && npm install && npm run dev

db-shell:
	docker compose exec db psql -U $${POSTGRES_USER:-goldman} -d $${POSTGRES_DB:-goldman}

# Removes containers AND volumes (database data)
clean:
	docker compose down -v

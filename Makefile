.PHONY: run up down logs ps test test-docker bench redteam redteam-live demo dashboard-dev landing venv db-shell clean sample-pdfs

ADMIN ?= hackyeah
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
	docker compose run --rm --no-deps -v "$(CURDIR)/docs:/out" -e TEST_DATABASE_URL_BASE=postgresql://goldman:goldman@db:5432 gateway python -m aegis.bench --out /out/bench-report.md
	@echo "Report written to docs/bench-report.md"

# Red-team corpus: adversarial probes (OWASP LLM / agentic techniques) through the live pipeline.
# Deterministic (no model server needed) — runnable by the jury on any running stack.
redteam:
	docker compose up -d
	$(MAKE) redteam-live

# Same corpus against a stack already running (e.g. localhost) — for the live demo.
redteam-live:
	.venv/bin/python tests/redteam.py $(GW) $(ADMIN) 2>/dev/null || python tests/redteam.py $(GW) $(ADMIN)

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

# 60 s promo film (docs/pitch/aegis-film.mp4). Needs python3, ffmpeg, node and Playwright with Chromium
# (set CHROME_PATH to use an installed Chromium).
film:
	cd docs/pitch/video && python3 score.py && node render.cjs ../aegis-film.mp4 30

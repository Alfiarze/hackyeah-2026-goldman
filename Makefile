.PHONY: run up down logs ps test test-docker db-shell clean

run: up
	@echo "Gateway: http://localhost:$${GATEWAY_PORT:-8000}/health"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f gateway

ps:
	docker compose ps

# Tests on host against dockerized Postgres
test:
	docker compose up -d db
	pytest

# Tests inside the gateway image
test-docker:
	docker compose run --rm gateway pytest

db-shell:
	docker compose exec db psql -U $${POSTGRES_USER:-goldman} -d $${POSTGRES_DB:-goldman}

# Removes containers AND volumes (database data)
clean:
	docker compose down -v

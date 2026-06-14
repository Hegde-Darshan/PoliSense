# Load env vars
include .env
export

.DEFAULT_GOAL := help

.PHONY: help up down restart logs ps clean health

help: ## help: Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## up: Start Postgres Server
	docker compose up -d

down: ## down: Stop Postgres Server
	docker compose down

restart: ## restart: Restart Postgres Server
	docker compose down
	docker compose up -d

logs: ## logs: Tail Postgres logs (last 100 lines)
	docker compose logs --tail=100 postgres

ps: ## ps: Show running containers
	docker compose ps

health: ## health: Check Postgres container health
	@docker inspect --format='Docker health: {{.State.Health.Status}}' $$(docker compose ps -q postgres) 2>/dev/null || echo "Docker health: container not found"
	@docker compose exec -T postgres pg_isready -q && echo "pg_isready: OK" || echo "pg_isready: Postgres not reachable"

clean: ## clean: Stop and delete all data (DANGEROUS)
	docker compose down -v

# Load env vars
include .env
export

.DEFAULT_GOAL := help

.PHONY: help up down restart logs ps clean health

help: ## help: Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## up: Start ChromaD
	docker compose up -d

down: ## down: Stop ChromaDB
	docker compose down

restart: ## restart: Restart ChromaDB
	docker compose down
	docker compose up -d

logs: ## logs: Tail ChromaDB logs
	docker compose logs -f chromadb

ps: ## ps: Show running containers
	docker compose ps

health: ## health: Check Postgres container health
	@docker compose exec -T postgres pg_isready -q || echo "Postgres not reachable"

clean: ## clean: Stop and delete all data (DANGEROUS)
	docker compose down -v
	rm -rf $(CHROMA_DATA_DIR)

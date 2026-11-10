# PoliSense Makefile
# Works on: Windows (Git Bash / make from Git for Windows), Linux, macOS
#
# Usage: make help

ifeq ($(OS),Windows_NT)
    VENV_PYTHON := .venv/Scripts/python.exe
    VENV_PIP    := .venv/Scripts/pip.exe
else
    VENV_PYTHON := .venv/bin/python
    VENV_PIP    := .venv/bin/pip
endif

PG_USER := $(shell grep -E '^POSTGRES_USER=' .env.secrets 2>/dev/null | cut -d= -f2 | tr -d "\"'" | head -1)
PG_DB   := $(shell grep -E '^POSTGRES_DB='   .env          2>/dev/null | cut -d= -f2 | tr -d "\"'" | head -1)
PG_USER   := $(or $(PG_USER),postgres)
PG_DB     := $(or $(PG_DB),polisense_db_dev)
DUMP_FILE ?= exports/polisense_db.sql

.PHONY: help install db-up db-down db-schema db-export db-import run-ingestion run-retrieval run-server build-installer clean

.DEFAULT_GOAL := help

help:
	@echo ""
	@echo "  PoliSense — available targets"
	@echo "  ──────────────────────────────────────────────"
	@echo "  make install          Create .venv and install dependencies"
	@echo "  make db-up            Start PostgreSQL (Docker)"
	@echo "  make db-down          Stop PostgreSQL"
	@echo "  make db-schema        Re-apply db/schema.sql"
	@echo "  make db-export        Dump DB + state files → exports/"
	@echo "  make db-import        Load exports/ into running DB"
	@echo "  make run-ingestion    Run the ingestion pipeline"
	@echo "  make run-retrieval    Run the retrieval pipeline"
	@echo "  make run-server       Start the API server (port 8000)"
	@echo "  make build-installer  Build dist/PoliSense-Setup.exe"
	@echo "  make clean            Remove .venv, dist/, postgres_data/*"
	@echo ""

install:
	python -m venv .venv
	$(VENV_PIP) install --upgrade pip -q
	$(VENV_PIP) install -e .

db-up:
	docker compose up -d
	@echo "Waiting for PostgreSQL..."
	@until docker compose exec -T postgres pg_isready -U $(PG_USER) -d $(PG_DB) > /dev/null 2>&1; do \
	    printf '.'; sleep 2; \
	done
	@echo " ready."

db-down:
	docker compose down

db-schema:
	docker compose exec -T postgres psql -U $(PG_USER) -d $(PG_DB) < db/schema.sql

db-export:
	@mkdir -p exports
	docker compose exec -T postgres pg_dump -U $(PG_USER) -d $(PG_DB) \
	    --no-owner --no-acl --clean --if-exists > $(DUMP_FILE)
	cp documents/files_read.json    exports/files_read.json
	cp documents/files_skipped.json exports/files_skipped.json
	@echo ""
	@echo "  Export complete → exports/"
	@echo "  Transfer the exports/ directory to the new machine,"
	@echo "  then run: make db-import"
	@echo ""

db-import:
	@echo "Importing $(DUMP_FILE) into $(PG_DB)..."
	docker compose exec -T postgres psql -U $(PG_USER) -d $(PG_DB) < $(DUMP_FILE)
	@cp -f exports/files_read.json    documents/files_read.json    2>/dev/null || true
	@cp -f exports/files_skipped.json documents/files_skipped.json 2>/dev/null || true
	@echo ""
	@echo "  Import complete. documents/ state files restored."
	@echo ""

run-ingestion:
	$(VENV_PYTHON) polisense_core/ingestion_pipeline.py

run-retrieval:
	$(VENV_PYTHON) polisense_core/retrieval_pipeline.py

run-server:
	$(VENV_PYTHON) server.py

build-installer:
	pip install pyinstaller -q
	pyinstaller installer/polisense_setup.spec
	@echo ""
	@echo "  Installer built: dist/PoliSense-Setup.exe"
	@echo "  Place the .exe in the project root before running."
	@echo ""

clean:
	@read -p "Delete .venv, dist/, and postgres_data/* ? [y/N] " c && [ "$$c" = "y" ]
	rm -rf .venv dist build __pycache__
	rm -rf postgres_data/*
	@echo "Cleaned. Run 'make install' to reinstall."

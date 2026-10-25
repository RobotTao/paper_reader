.PHONY: help dev install import import-reset stats index-hashes colors test test-e2e lint backup screenshots docker-build docker-up docker-down docker-logs

PORT ?= 8080
DATA ?= local_data/data.json
BACKUP ?= backup/paper_reader_$(shell date +%Y%m%d_%H%M%S).tar.gz

help:
	@echo "make install        - create the python env and install dependencies (uv)"
	@echo "make dev            - run the app locally on http://127.0.0.1:$(PORT)"
	@echo "make import         - import the readpaper export ($(DATA))"
	@echo "make import-reset   - wipe the database and import again"
	@echo "make stats          - show row counts"
	@echo "make index-hashes   - hash every PDF so duplicates can be found"
	@echo "make colors         - show how many highlights would get their colour back"
	@echo "make test           - run the backend tests (pytest, on a throw-away library)"
	@echo "make test-e2e       - run the browser tests (needs Chrome with --remote-debugging-port=9333)"
	@echo "make lint           - run ruff over the backend and the tests"
	@echo "make screenshots    - take the pictures of the README (needs Chrome on 9333)"
	@echo "make backup         - pack the database + uploaded PDFs into $(BACKUP)"
	@echo "make docker-build   - build the docker image"
	@echo "make docker-up      - start the app with docker compose"
	@echo "make docker-logs    - follow the container logs"
	@echo "make docker-down    - stop the container"

install:
	cd backend && uv sync

dev:
	cd backend && PORT=$(PORT) uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $(PORT)

import:
	cd backend && uv run python -m app.cli import $(DATA)

import-reset:
	cd backend && uv run python -m app.cli import $(DATA) --reset

stats:
	cd backend && uv run python -m app.cli stats

# Hash every PDF in the library, so that uploading a file that is already
# there can be spotted. Only the hash column is written; nothing is deleted.
index-hashes:
	cd backend && uv run python -m app.cli index-hashes

# Give the imported highlights the colour they have in readpaper. Without
# --apply nothing is written - the command only says what it would do.
colors:
	cd backend && uv run python -m app.cli backfill-colors $(DATA)

# The backend tests. They run against a throw-away library in a temporary
# directory - the real one in local_data/ is never touched.
test:
	cd backend && uv run pytest -q

# The browser tests. They need a Chrome that listens on port 9333:
#   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
#     --remote-debugging-port=9333
# They run against a server of their own, with a library of their own.
# One case only: make test-e2e CASE=duplicate
test-e2e:
	cd backend && uv run python ../tests/e2e/run.py $(CASE)

# The linter: the backend keeps its own rules, the tests and the tools the
# ones in the ruff.toml at the top of the repository.
lint:
	cd backend && uv run ruff check . ../tests ../tools

# The pictures of the README. They are made of a library that is invented
# for the occasion, in a throw-away directory - the real one is never
# touched. Chrome has to listen on the debug port 9333, like for the tests.
screenshots:
	cd backend && uv run python ../tools/make_screenshots.py

# Pack the portable part of the library: the SQLite db + the PDFs you
# uploaded yourself. The imported PDFs (pdfs/<id>/...) are excluded (2.4 GB);
# they are restored with "make import" from data.json, or copied over
# separately. Uploaded PDFs sit flat in pdfs/, imported ones in sub-folders.
backup:
	@mkdir -p backup
	cd local_data && tar -czf ../$(BACKUP) db $$(find pdfs -maxdepth 1 -name '*.pdf')
	@echo "-> $(BACKUP)"
	@echo "restore on another machine: extract into local_data/, then 'make dev'"

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-logs:
	docker compose logs -f

docker-down:
	docker compose down

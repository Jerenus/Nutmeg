.PHONY: init install doctor test verify demo sync acceptance graph

init:
	bash ./init.sh

install:
	uv sync --extra dev

doctor:
	uv run nutmeg doctor

test:
	uv run pytest

verify:
	bash scripts/verify.sh

demo:
	uv run nutmeg fixtures --league epl --demo

sync:
	uv run nutmeg fixtures-sync

acceptance:
	bash scripts/acceptance.sh --dry-run

graph:
	python3 scripts/refresh_graph.py --project-root . --output-dir graphify-out

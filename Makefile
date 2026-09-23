.PHONY: init install doctor test verify

init:
	bash ./init.sh

install:
	uv sync --extra dev

doctor:
	uv run nutmeg ontology status

test:
	uv run pytest

verify:
	bash scripts/verify.sh

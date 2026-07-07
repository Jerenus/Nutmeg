.PHONY: init install doctor test verify demo sync

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

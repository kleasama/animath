BIN := .venv/bin
# pycairo: LGPL-2.1-only OR MPL-1.1, used under MPL-1.1 (SPEC N10)
LICENSE_EXEMPT := animath pycairo
.PHONY: setup lock check lint type test licenses
setup:
	uv venv -q && uv pip install -q -r requirements.lock && uv pip install -q --no-deps -e .
lock:
	uv lock -q && uv export -q --all-groups --no-hashes --no-emit-project --no-header --no-annotate -o requirements.lock && rm uv.lock
check: lint type test licenses
lint:
	$(BIN)/ruff check . && $(BIN)/ruff format --check .
type:
	$(BIN)/mypy
test:
	$(BIN)/pytest
licenses:
	$(BIN)/pip-licenses --partial-match --fail-on="GPL;AGPL" --ignore-packages $(LICENSE_EXEMPT)

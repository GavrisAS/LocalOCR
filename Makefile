.PHONY: check test run-gui
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run ty check
test:
	uv run pytest
run-gui:
	uv run localocr-gui

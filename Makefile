.PHONY: verify lint format type test gate-0 gate-1a gate-1 gate-2 gate-3 gate-4 gate-4.5 gate-5 gate-6 study-A study-B study-C study-D study-E study-F study-G clean

# Default target — full local verification (mirrors CI)
verify: lint type test

lint:
	uv run ruff check src/ tests/ scripts/ 2>/dev/null || uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

type:
	uv run mypy --strict src/

test:
	uv run pytest -q

# === Phase gates (each runs the matching gate script) ===
gate-0:
	@bash runbooks/gates/phase-0.sh
gate-1a:
	@bash runbooks/gates/phase-1a.sh
gate-1:
	@bash runbooks/gates/phase-1.sh
gate-2:
	@bash runbooks/gates/phase-2.sh
gate-3:
	@bash runbooks/gates/phase-3.sh
gate-4:
	@bash runbooks/gates/phase-4.sh
gate-4.5:
	@bash runbooks/gates/phase-4.5.sh
gate-5:
	@bash runbooks/gates/phase-5.sh
gate-6:
	@bash runbooks/gates/phase-6.sh

# === Bonereaper study gates ===
study-A:
	@bash runbooks/gates/study-A.sh
study-B:
	@bash runbooks/gates/study-B.sh
study-C:
	@bash runbooks/gates/study-C.sh
study-D:
	@bash runbooks/gates/study-D.sh
study-E:
	@bash runbooks/gates/study-E.sh
study-F:
	@bash runbooks/gates/study-F.sh
study-G:
	@bash runbooks/gates/study-G.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ src/**/__pycache__ tests/**/__pycache__

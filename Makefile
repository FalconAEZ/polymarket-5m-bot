.PHONY: verify verify-v3 lint format type test gate-0 gate-1a gate-1 gate-2 gate-3 gate-4 gate-4.5 gate-5 gate-6 dashboard dashboard-v2 dashboard-v3 dashboard-v3-build sync-staging dash-staging dash-staging-v2 dash-staging-v3 dash-tunnel study-A study-B study-C study-D study-E study-F study-G clean

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

# === Phase 4.5 dashboard ===
dashboard:
	@uv run streamlit run scripts/dashboard.py

# === Phase 5.5 staging dashboard (mirrors VPS state, then opens dashboard) ===
sync-staging:
	@bash runbooks/scripts/sync_staging.sh

dash-staging: sync-staging
	@PMB_DASH_STATE_DIR=state/staging uv run streamlit run scripts/dashboard.py

# === Phase 11.A.X — v2 dashboard (Bloomberg-terminal layout, feature-flagged) ===
dashboard-v2:
	@PMB_DASH_V2=1 uv run streamlit run scripts/dashboard.py

dash-staging-v2: sync-staging
	@PMB_DASH_V2=1 PMB_DASH_STATE_DIR=state/staging uv run streamlit run scripts/dashboard.py

# === Phase 11.A.X — open SSH tunnel from laptop to VPS dashboard ===
# After deploying dashboard-server.service on the VPS (per
# runbooks/staging/deploy-dashboard-v3.md), run `make dash-tunnel`
# from your laptop. Forwards both ports — v3 (8505) + v2.1 audit (8503).
# Browse to http://127.0.0.1:8505/.
dash-tunnel:
	@bash runbooks/operations/dashboard-tunnel.sh

# === Phase 11.A.X.B — v3 dashboard (FastAPI + React) ===
# Build the React frontend then run the FastAPI server locally against
# state/staging data. Open at http://127.0.0.1:8505/.
dashboard-v3-build:
	@cd apps/dashboard-v3 && npm ci && npm run build

dashboard-v3: dashboard-v3-build
	@PMB_DASH_STATE_DIR=state PMB_DASHBOARD_PORT=8505 \
		uv run python -m polymarket_bot.dashboard_server

dash-staging-v3: sync-staging dashboard-v3-build
	@PMB_DASH_STATE_DIR=state/staging PMB_DASHBOARD_PORT=8505 \
		uv run python -m polymarket_bot.dashboard_server

# === Combined verify for v3 (Python + TypeScript build) ===
verify-v3: verify
	@cd apps/dashboard-v3 && npm ci && npx tsc -b && npm run build

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

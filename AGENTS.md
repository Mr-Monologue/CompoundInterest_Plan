# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

智能定投系统 (Smart DCA System) — a Python/Streamlit single-application investment dashboard for Chinese mutual funds. Uses SQLite (embedded, auto-created at `data/trend.db`), AKShare and yfinance for market data (with graceful fallback to mock data).

### Running the app

```bash
source .venv/bin/activate
python run_gui.py
# or: streamlit run src/app/ui/gui.py --server.port 8501 --server.address 0.0.0.0
```

App listens on port 8501. The `.streamlit/config.toml` sets `headless = true`.

### Lint & format

```bash
source .venv/bin/activate
black --check src/ run_gui.py
flake8 src/ run_gui.py --max-line-length=120
```

Note: the existing codebase has some flake8 warnings (unused imports, f-strings without placeholders). These are pre-existing and not regressions.

### Tests

```bash
source .venv/bin/activate
pytest
```

No test files exist yet (`tests/` directory is absent); pytest will exit with code 5 (no tests collected). The `pyproject.toml` has coverage configured with `--cov=src`.

### Key gotchas

- `load_all_funds_config()` returns a **tuple** `(funds_list, raw_config)`, not a dict.
- The "采样并保存" (sample & save) action calls external APIs (AKShare, yfinance). These may fail in restricted network environments; the app falls back to mock data gracefully.
- `run_gui.py` sets `PYTHON_GIL=1` for Python 3.13 free-threading compatibility; this is fine on Python 3.12.
- The `pyproject.toml` lists `sqlite3` as a dependency, but that's a stdlib module — pip will skip it.
- The venv requires `python3.12-venv` system package on Ubuntu (already installed in this environment).

#!/bin/bash
# Start backend with clean Python environment
cd "F:/compound-interest-plan"
export COMPOUND_DB_PATH="F:/compound-interest-plan/invest.db"
unset PYTHONPATH
unset PYTHONHOME
"F:/compound-interest-plan/.venv/Scripts/python.exe" "F:/compound-interest-plan/backend/main.py"

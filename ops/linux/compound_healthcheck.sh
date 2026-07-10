#!/bin/bash
set -e
cd /home/pi/compound-interest-plan
PYTHON=.venv/bin/python
CTL=compoundctl.py
LOG=logs/operator_health.log
EVIDENCE=reports/handoff/operator_health.json

ts=$(date -Iseconds)
branch=$(git branch --show-current)
commit=$(git rev-parse --short HEAD)

doctor=$($PYTHON $CTL doctor 2>&1)
gate=$($PYTHON $CTL gate --target hermes 2>&1)

backend_ok=$(echo "$doctor" | python -c "import sys,json;print(json.load(sys.stdin)['backend']['health'])")
scheduler_ok=$(echo "$doctor" | python -c "import sys,json;print(json.load(sys.stdin)['scheduler']['heartbeat'])")
recovered=false

if [ "$backend_ok" != "True" ] || [ "$scheduler_ok" != "True" ]; then
    echo "$ts Recovery: backend=$backend_ok scheduler=$scheduler_ok" >> $LOG
    $PYTHON $CTL start --mode hermes-only 2>&1 >> $LOG
    recovered=true
fi

python -c "
import json, sys
evidence = {
    'timestamp': '$ts', 'branch': '$branch', 'commit': '$commit',
    'backend_running': '$backend_ok' == 'True',
    'scheduler_running': '$scheduler_ok' == 'True',
    'auto_recovery_attempted': $recovered,
    'auto_recovery_result': 'restarted' if $recovered else 'n/a',
    'safety': {'no_auto_trade': True, 'no_auto_confirm': True, 'no_pool_deduction': True}
}
json.dump(evidence, open('$EVIDENCE','w'), indent=2, ensure_ascii=False)
"
echo "$ts OK backend=$backend_ok scheduler=$scheduler_ok recovered=$recovered" >> $LOG

#!/bin/bash
set -e
SRV="$(dirname "$0")"
for f in compound-backend.service compound-scheduler.service compound-healthcheck.service compound-healthcheck.timer; do
    cp "$SRV/$f" /etc/systemd/system/
done
systemctl daemon-reload
for u in compound-backend.service compound-scheduler.service compound-healthcheck.timer; do
    systemctl enable "$u"
    systemctl start "$u" 2>/dev/null || true
done
echo "=== Operator Services ==="
systemctl status compound-backend.service compound-scheduler.service compound-healthcheck.timer --no-pager

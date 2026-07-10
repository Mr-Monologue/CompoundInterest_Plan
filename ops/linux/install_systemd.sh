#!/bin/bash
set -e
SERVICES_DIR="$(dirname "$0")"
cp "$SERVICES_DIR"/compound-backend.service /etc/systemd/system/
cp "$SERVICES_DIR"/compound-healthcheck.service /etc/systemd/system/
cp "$SERVICES_DIR"/compound-healthcheck.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable compound-backend.service
systemctl enable compound-healthcheck.timer
systemctl start compound-backend.service
systemctl start compound-healthcheck.timer
echo "Operator installed. Check: systemctl status compound-backend compound-healthcheck.timer"

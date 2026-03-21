#!/usr/bin/env bash
set -euo pipefail

# Minimal firewall setup for PZ dedicated server defaults.
sudo ufw allow 16261/udp
sudo ufw allow 16262/udp
sudo ufw reload

echo "Firewall rules applied for 16261/udp and 16262/udp"

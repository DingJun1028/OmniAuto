#!/usr/bin/env bash
# Read-only-ish diagnostic + open VPS-local firewall for 80/443.
# (Oracle Security List / DNS are console-side and NOT touched here.)
set +e
echo "=== ufw status ==="
sudo ufw status verbose 2>/dev/null || echo "ufw not installed"
echo "=== open 80/443 on VPS-local firewall ==="
sudo ufw allow 80/tcp 2>/dev/null
sudo ufw allow 443/tcp 2>/dev/null
echo "=== nginx listening? ==="
sudo ss -ltnp 2>/dev/null | grep -E ':80 |:443 |:8000 ' || echo "ss unavailable"
echo "=== nginx -t ==="
sudo nginx -t 2>&1 | tail -2
echo "=== local health (loopback) ==="
curl -fsS --max-time 8 http://127.0.0.1:8000/api/health && echo
echo "=== public IP (for DNS) ==="
curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || echo "(ipify unreachable)"

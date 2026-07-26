#!/usr/bin/env bash
# Deploy AI Station to the esggo VPS.
#
# Usage:
#   ./deploy/deploy.sh USER@HOST [DOMAIN]
# Example:
#   ./deploy/deploy.sh deploy@161.118.252.147 aistation.esggo.co
#
# What it does (idempotent, non-destructive):
#   1. rsync ./deploy  ->  ~/aistation/deploy  on the VPS
#   2. docker compose pull && up -d   (pulls docker.io/dingjunhong1028/aistation:latest)
#   3. installs the nginx site config + reloads nginx
#   4. prints the health endpoint
#
# Secrets: the container reads WEBHOOK_SECRET etc. from the VPS-side
# ~/aistation/deploy/.env (created once on the server). This script does NOT
# transmit secrets; it only ships the compose + nginx files.
set -euo pipefail

USERHOST="${1:?usage: deploy.sh USER@HOST [DOMAIN]}"
DOMAIN="${2:-aistation.esggo.co}"
REMOTE_DIR="~/aistation"

echo ">> deploying AI Station to $USERHOST (domain $DOMAIN)"

# 1. ship the deployment files
echo ">> rsync deploy/ -> $USERHOST:$REMOTE_DIR"
rsync -az --delete \
  --exclude '.env' \
  "$(dirname "$0")/" "$USERHOST:$REMOTE_DIR/deploy"

# 2. pull + run
echo ">> docker compose pull && up -d"
ssh "$USERHOST" "cd $REMOTE_DIR/deploy && docker compose pull && docker compose up -d"

# 3. install nginx site (the config is domain-agnostic except server_name)
echo ">> install nginx site for $DOMAIN"
ssh "$USERHOST" bash -c "'
  sudo cp $REMOTE_DIR/deploy/nginx/aistation.esggo.co.conf /etc/nginx/sites-available/$DOMAIN.conf
  sudo ln -sf /etc/nginx/sites-available/$DOMAIN.conf /etc/nginx/sites-enabled/$DOMAIN.conf
  sudo nginx -t && sudo systemctl reload nginx
'"

# 4. health check
echo ">> waiting for health endpoint"
sleep 5
ssh "$USERHOST" "curl -fsS http://127.0.0.1:8000/api/health && echo" || echo "!! health check failed — see logs: ssh $USERHOST 'cd $REMOTE_DIR/deploy && docker compose logs --tail=50'"

echo ">> done. Visit http://$DOMAIN (run certbot for HTTPS: sudo certbot --nginx -d $DOMAIN)"

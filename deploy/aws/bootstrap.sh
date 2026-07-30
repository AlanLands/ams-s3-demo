#!/usr/bin/env bash
# Provision a fresh Ubuntu 24.04 EC2 instance to run the AMS S3 demo.
#
# Ubuntu 24.04 is chosen deliberately: it ships Python 3.12, which is what the
# development venv already uses. Amazon Linux 2023 ships 3.11 and would need a
# separate Python build — avoidable risk before a live demo.
#
# Run as the `ubuntu` user on the instance:
#   sudo bash deploy/aws/bootstrap.sh
#
# This is idempotent — safe to re-run after a code update.
set -euo pipefail

APP_USER="${APP_USER:-ubuntu}"
APP_DIR="${APP_DIR:-/opt/ams-s3-demo}"

if [[ $EUID -ne 0 ]]; then
  echo "run with sudo: sudo bash $0" >&2
  exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "expected the repo at $APP_DIR — clone or rsync it there first" >&2
  exit 1
fi

echo "==> system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# git: the S3 pipeline shells out to it for diffs against the pre-CR baseline.
# nginx: single public entry point in front of the four app processes.
apt-get install -y -qq python3.12 python3.12-venv python3-pip git nginx curl

echo "==> python venv"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> frontend"
# apps/console/web/dist is gitignored, so it is NOT in the checkout. Build it locally and
# rsync it up (preferred — keeps Node off the instance entirely), or install Node
# here by setting BUILD_FRONTEND_ON_HOST=1.
if [[ -f "$APP_DIR/apps/console/web/dist/index.html" ]]; then
  echo "    dist present — nothing to do"
elif [[ "${BUILD_FRONTEND_ON_HOST:-0}" == "1" ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
  sudo -u "$APP_USER" bash -c "cd '$APP_DIR/apps/console/web' && npm ci && npm run build"
else
  echo "    !! apps/console/web/dist missing." >&2
  echo "    !! Build locally (cd apps/console/web && npm run build) and rsync apps/console/web/dist up," >&2
  echo "    !! or re-run with BUILD_FRONTEND_ON_HOST=1. Without it the console serves" >&2
  echo "    !! the API only and every page load 404s." >&2
  exit 1
fi

echo "==> ownership"
# The S3 pipeline writes generated .py files into the tree and runs pytest there,
# so the service user must own the whole checkout — not just a data subdirectory.
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> systemd units"
install -m 0644 "$APP_DIR/deploy/aws/ams-s3-console.service" /etc/systemd/system/
install -m 0644 "$APP_DIR/deploy/aws/ams-s3-policycore.service" /etc/systemd/system/
install -m 0644 "$APP_DIR/deploy/aws/ams-s3-policy-service.service" /etc/systemd/system/
install -m 0644 "$APP_DIR/deploy/aws/ams-s3-claims-service.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable ams-s3-console ams-s3-policycore ams-s3-policy-service ams-s3-claims-service

echo "==> nginx"
install -m 0644 "$APP_DIR/deploy/aws/nginx.conf" /etc/nginx/sites-available/ams-s3-demo
ln -sf /etc/nginx/sites-available/ams-s3-demo /etc/nginx/sites-enabled/ams-s3-demo
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

echo "==> starting services"
# policy-service before claims-service: claims-service calls it, and a claim
# submitted while policy-service is still coming up fails the lookup.
systemctl restart ams-s3-console ams-s3-policycore ams-s3-policy-service
sleep 1
systemctl restart ams-s3-claims-service
sleep 3
systemctl --no-pager --lines=0 status \
  ams-s3-console ams-s3-policycore ams-s3-policy-service ams-s3-claims-service || true

echo
echo "Bootstrap complete."
echo "Health check:  curl -fsS http://localhost/api/health"
echo
echo "Still to do before the demo (see deploy/aws/README.md):"
echo "  1. Create $APP_DIR/.env with LLM_PROVIDER=bedrock, AWS_REGION, BEDROCK_MODEL, GITLAB_MODE=replay"
echo "  2. Warm the unpinned LLM cache against Bedrock, or 8 beats will call live mid-demo"

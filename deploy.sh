#!/usr/bin/env bash
#
# One-shot deploy: pull the latest code and roll the containers.
# Run it on the server, from anywhere:  bash /path/to/shop/deploy.sh
#
#   bash deploy.sh              # deploy origin/main
#   bash deploy.sh some-branch  # deploy a different branch (for testing)
#
# What it does: hard-reset to origin/<ref>, rebuild the backend+frontend
# images, run migrations (one-off, before the new code starts), then
# `up -d`. `reset --hard` discards any uncommitted changes on the server —
# there normally aren't any; stash first if you have some to keep.

set -euo pipefail

REF="${1:-main}"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> repo: $(pwd)"
git fetch origin
git checkout "$REF"
git reset --hard "origin/$REF"
echo "==> now at: $(git log -1 --oneline)"

echo "==> building images"
docker compose build backend frontend

echo "==> migrating"
docker compose run --rm backend python manage.py migrate

echo "==> starting containers"
docker compose up -d

echo "==> smoke check"
docker compose exec -T backend python manage.py check
sleep 3
code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8082/api/guest/card/pulse/ || true)
echo "    /api/guest/card/pulse/ -> $code  (404 = routes up)"

echo "==> done."

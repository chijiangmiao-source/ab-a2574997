#!/bin/sh
# Runs once inside the compose `verify` service, then exits with a status code.
#   1. build/import check
#   2. unit + API test suite (valid equalities, expired scopes, conflict rollback)
#   3. HTTP smoke against the real running web service
set -eu

WEB_URL="${WEB_URL:-http://web:8000}"

echo "==> [1/3] backend import / build check"
python -c "import app.main; print('backend import OK')"

echo "==> [2/3] pytest suite"
cd /app
python -m pytest tests -q

echo "==> [3/3] HTTP smoke against ${WEB_URL}"
python /verify/smoke_http.py "${WEB_URL}"

echo "==> verify: ALL CHECKS PASSED"

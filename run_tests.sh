#!/bin/bash
set -e

cd "$(dirname "$0")"

# Use venv python if available
if [ -f venv/bin/python3 ]; then
    PYTHON="venv/bin/python3"
else
    PYTHON="python3"
fi

echo "=== Syntax check (py_compile) ==="
$PYTHON -m py_compile main.py
for f in modules/*.py memory/*.py personality.py; do
    $PYTHON -m py_compile "$f"
done
echo "Syntax: OK"

echo ""
echo "=== Smoke tests ==="
$PYTHON -m pytest tests/ -q 2>/dev/null || $PYTHON tests/test_smoke.py

echo ""
echo "=== ALL CHECKS PASSED ==="

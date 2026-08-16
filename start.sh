#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
echo "Accès local   : http://localhost:8000"
echo "Autres appareils :"
(hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null) | tr ' ' '\n' | grep -E '^(192|10|172)' | sed 's|^|  http://|; s|$|:8000|'
./.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000

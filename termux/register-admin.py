from __future__ import annotations

import json
import sys
from pathlib import Path


registry = Path(sys.argv[1]).expanduser()
port = int(sys.argv[2])
entry = {
    "id": "expenses",
    "name": "Expense Manager",
    "description": "Private spending, income and budget tracker",
    "service": "expense-manager",
    "port": port,
    "health_url": f"http://127.0.0.1:{port}/health",
    "open_url": f"http://127.0.0.1:{port}",
}
try:
    payload = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else {"apps": []}
except (json.JSONDecodeError, OSError):
    payload = {"apps": []}
apps = [app for app in payload.get("apps", []) if app.get("id") != entry["id"]]
apps.append(entry)
registry.parent.mkdir(parents=True, exist_ok=True)
registry.write_text(json.dumps({"apps": apps}, indent=2) + "\n", encoding="utf-8")
registry.chmod(0o600)

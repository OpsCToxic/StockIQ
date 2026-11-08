#!/usr/bin/env python3
"""Write the FastAPI OpenAPI spec for the frontend's typed client.

Run from `frontend/` via `npm run gen:api` (needs the Python environment and the .env settings
loaded, because importing the app reads them). The spec and the generated types are committed so
the frontend builds without a running backend.
"""

import json
import sys
from pathlib import Path

from stockiq.api.app import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "src/api/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")

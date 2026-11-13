"""Export the OpenAPI contract (ADR-012): `python -m app.openapi [output-path]`.

Generated with fixed settings so the file only changes when the API changes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "shared" / "api-contracts" / "openapi.json"


def generate() -> dict[str, Any]:
    settings = Settings(app_env="development", app_name="VpnHub")
    return create_app(settings).openapi()


def main(argv: list[str]) -> None:
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(generate(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv)

"""Provider process entry point with an explicit maintenance gate."""
from __future__ import annotations

import os

import uvicorn


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def main() -> None:
    maintenance = _truthy(os.getenv("RAG_MAINTENANCE_MODE"))
    app = "rag.maintenance_provider:app" if maintenance else "rag.openai_provider:app"
    host = os.getenv("PROVIDER_HOST", "127.0.0.1")
    port = int(os.getenv("PROVIDER_PORT", "8766"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

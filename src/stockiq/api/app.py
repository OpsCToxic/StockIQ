"""FastAPI app. Run locally: `uvicorn stockiq.api.app:app --host 127.0.0.1 --port 8000`.

Binds to localhost by default. There is no login: expose it only over Tailscale or behind an auth
proxy (docs/architecture.md, "Security"), never directly to the internet.
"""

from fastapi import FastAPI

from stockiq.api.portfolio import router as portfolio_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="StockIQ",
        version="0.1.0",
        description="Personal portfolio intelligence: look-through exposure and its evidence.",
    )
    app.include_router(portfolio_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

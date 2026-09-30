"""FastAPI application: orders, plans and negotiations APIs plus the A2A transport spike (three endpoints, one app)."""

from fastapi import FastAPI

from app.api import a2a, negotiations, orders, planning
from app.core.errors import install_error_handlers

app = FastAPI(title="Decentralized MRPII", version="0.2.0")
install_error_handlers(app)

app.include_router(orders.router)
app.include_router(planning.router)
app.include_router(negotiations.router)
a2a.install_a2a_spike(app)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}

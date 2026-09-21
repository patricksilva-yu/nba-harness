"""FastAPI application factory for the NBA analyst app."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router


FRONTEND_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]


def create_app() -> FastAPI:
    app = FastAPI(title="NBA Analyst Agent")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_origin_regex=r"http://(127\.0\.0\.1|localhost):30\d{2}",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    return app


app = create_app()

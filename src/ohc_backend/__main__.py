"""Entry point for running the application."""

import os

import uvicorn

if __name__ == "__main__":
    # Determine if we're in development mode
    debug_mode = os.getenv("ENVIRONMENT", "").lower() == "dev"

    uvicorn.run(
        "ohc_backend.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8000,
        reload=debug_mode
    )

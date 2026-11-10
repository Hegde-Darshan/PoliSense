"""API server entry point.

Usage:
    python server.py
    make run-server
"""
import os

from dotenv import load_dotenv

load_dotenv()

import uvicorn

uvicorn.run(
    "polisense_core.api.app:app",
    host="0.0.0.0",
    port=int(os.getenv("API_PORT", "8000")),
    reload=False,
)

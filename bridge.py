"""Compatibility entrypoint for the AMS Dashboard backend.

The FastAPI application is assembled in app.runtime to keep this file small and
stable for uvicorn, PyInstaller, and existing run scripts.
"""

from app.runtime import app, config_store


if __name__ == "__main__":
    import uvicorn

    port = int(config_store.get("server_port", 8000) or 8000)
    uvicorn.run("bridge:app", host="0.0.0.0", port=port, reload=False)


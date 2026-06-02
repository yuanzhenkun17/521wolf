from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


DIST_DIR = Path(__file__).with_name("dist")

app = FastAPI(title="521wolf 3D Match Frontend")
app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{path:path}")
async def spa_fallback(path: str):
    requested = DIST_DIR / path
    if path and requested.is_file():
        return FileResponse(requested)
    return FileResponse(DIST_DIR / "index.html")

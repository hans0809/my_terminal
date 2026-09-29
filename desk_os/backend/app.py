"""HTTP 应用。各功能的接口在 backend.routes。"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import feed_service, logbook
from backend.paths import FRONTEND_DIR
from backend.routes import api_router


def create_app() -> FastAPI:
    feed_service.init_db()
    logbook.boot()

    application = FastAPI(title="Desk OS", docs_url=None, redoc_url=None)
    application.include_router(api_router)

    @application.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    application.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    application.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
    application.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
    return application


app = create_app()

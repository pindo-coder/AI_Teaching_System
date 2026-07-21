from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as api_v1_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.init_db import init_db
from app.db.session import engine
from app.exceptions import register_exception_handlers
from app.services.material_import_service import recover_material_batches


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    recovered = recover_material_batches(engine)
    if recovered:
        logger.info("recovered material import batches count=%s", recovered)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    started_at = perf_counter()
    response = await call_next(request)
    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request method=%s path=%s status=%s duration_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

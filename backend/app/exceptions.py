import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder


logger = logging.getLogger(__name__)


def error_payload(*, message: str, error_code: str, request_id: str, detail: object | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "success": False,
        "message": message,
        "detail": message,
        "error_code": error_code,
        "request_id": request_id,
    }
    if detail is not None:
        payload["errors"] = detail
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                message=message,
                error_code=f"HTTP_{exc.status_code}",
                request_id=getattr(request.state, "request_id", "unknown"),
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                message="请求参数校验失败",
                error_code="VALIDATION_ERROR",
                request_id=getattr(request.state, "request_id", "unknown"),
                detail=jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("unhandled_error request_id=%s path=%s", request_id, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_payload(
                message="服务内部错误，请稍后重试",
                error_code="INTERNAL_SERVER_ERROR",
                request_id=request_id,
            ),
        )

import time
from logging import Logger

from fastapi import FastAPI, Request

REQUEST_EVENT = "request"


def install_request_logging(app: FastAPI, logger: Logger) -> None:
    @app.middleware("http")
    async def log_request(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                REQUEST_EVENT, extra=request_fields(request, 500, start)
            )
            raise
        logger.info(
            REQUEST_EVENT,
            extra=request_fields(request, response.status_code, start),
        )
        return response


def request_fields(request: Request, status: int, start: float) -> dict:
    return {
        "method": request.method,
        "path": request.url.path,
        "status": status,
        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
    }

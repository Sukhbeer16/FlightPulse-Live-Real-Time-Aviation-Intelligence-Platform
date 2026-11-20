"""Consistent, credential-safe JSON error responses for the HTTP API."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_error_handlers(app: FastAPI) -> None:
    """Register a small stable error envelope without echoing input values."""

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        del request
        detail = error.detail
        message = detail if isinstance(detail, str) else "Request failed."
        code = {
            404: "not_found",
            422: "validation_error",
            503: "service_unavailable",
        }.get(error.status_code, "http_error")
        body: dict[str, Any] = {
            "error": {"code": code, "message": message, "details": None}
        }
        if not isinstance(detail, str):
            body["error"]["details"] = detail
        return JSONResponse(
            status_code=error.status_code,
            content=body,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request
        details = [
            {
                "location": list(item.get("loc", ())),
                "message": item.get("msg", "Invalid value."),
                "type": item.get("type", "value_error"),
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, error: Exception
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected server error occurred.",
                    "details": None,
                }
            },
        )

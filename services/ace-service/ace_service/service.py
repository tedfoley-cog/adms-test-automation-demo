"""HTTP surface of the ACE service.

uvicorn ace_service.service:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import __version__
from .ace import dispatch
from .hdb_export import SavecaseError, parse_export, to_area_payload
from .schemas import AreaState, DispatchResult

MAX_SAVECASE_BYTES = 1_000_000

app = FastAPI(title="ACE service (RTGENACE)", version=__version__)


def _refusal(ierr: int, detail: object, line: int | None = None) -> JSONResponse:
    body: dict[str, object] = {"ierr": ierr, "detail": detail}
    if line is not None:
        body["line"] = line
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(RequestValidationError)
async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    # The default handler echoes the input back, which fails on NaN/Infinity (D-1).
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ace-service",
        "legacy_task": "RTGENACE",
        "version": __version__,
    }


@app.post("/v1/rtgenace/dispatch", response_model=DispatchResult)
def dispatch_area(area: AreaState) -> DispatchResult:
    return dispatch(area)


@app.post(
    "/v1/rtgenace/savecase",
    response_model=DispatchResult,
    openapi_extra={"requestBody": {"required": True, "content": {"text/plain": {"schema": {"type": "string"}}}}},
)
async def dispatch_savecase(request: Request) -> DispatchResult | JSONResponse:
    raw = await request.body()
    if len(raw) > MAX_SAVECASE_BYTES:
        return JSONResponse(status_code=413, content={"detail": "savecase export too large"})
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _refusal(2, "savecase export is not UTF-8 text")
    try:
        records = parse_export(text)
    except SavecaseError as exc:
        return _refusal(exc.ierr, exc.message, exc.line)
    try:
        area = AreaState.model_validate(to_area_payload(records))
    except ValidationError as exc:
        return _refusal(2, [error["msg"] for error in exc.errors()])
    return dispatch(area)

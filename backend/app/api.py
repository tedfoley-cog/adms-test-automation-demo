"""HTTP surface used by the control-room clients and the SCADA adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictFloat,
    StrictStr,
    field_validator,
    model_validator,
)

from . import __version__, agc, flisr, state_estimator
from .models import (
    AS_OF_MAX_LAG,
    AS_OF_MAX_LEAD,
    TIE_CAPACITY_GOOD_QUALITY,
    TIE_CAPACITY_MAX_AGE,
    TIE_CAPACITY_MAX_LEAD,
    TIE_CAPACITY_TOLERANCE_KW,
    BalancingState,
    Feeder,
    IsoAwareDatetime,
    Measurement,
    RestorationPlan,
    TieCapacity,
    Unit,
)
from .network import get_feeder, load_network

router = APIRouter()


class FlisrRequest(BaseModel):
    """Body of POST /flisr/plan. Types are strict and unknown fields are rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    feeder_mrid: StrictStr
    lockout_switch_mrid: StrictStr
    tie_capacity: dict[str, TieCapacity] | None = None
    tie_capacity_kw: dict[str, StrictFloat] | None = None  # deprecated, see the route text
    as_of: IsoAwareDatetime | None = None

    @field_validator("tie_capacity", "tie_capacity_kw", "as_of", mode="before")
    @classmethod
    def _no_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("omit the field instead of sending null")
        return value

    @model_validator(mode="after")
    def _mutually_exclusive(self) -> FlisrRequest:
        if self.tie_capacity is not None and self.tie_capacity_kw is not None:
            raise ValueError("tie_capacity and tie_capacity_kw are mutually exclusive")
        return self


class EstimationRequest(BaseModel):
    measurements: list[Measurement]


class AgcRequest(BaseModel):
    balancing_state: BalancingState
    units: list[Unit]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/feeders", response_model=list[Feeder])
def feeders() -> list[Feeder]:
    return load_network().feeders


def server_now() -> datetime:
    """Server UTC clock, read once per request; tests override it via dependency_overrides."""
    return datetime.now(UTC)


def _check_as_of_bound(as_of: datetime, now: datetime) -> None:
    """REQ-TIECAP-23: as_of must lie in [now - AS_OF_MAX_LAG, now + AS_OF_MAX_LEAD]."""
    if now - as_of > AS_OF_MAX_LAG or as_of - now > AS_OF_MAX_LEAD:
        raise RequestValidationError(
            [
                {
                    "type": "as_of_out_of_bounds",
                    "loc": ("body", "as_of"),
                    "msg": (
                        f"as_of must be within {AS_OF_MAX_LAG.total_seconds():g} s before and "
                        f"{AS_OF_MAX_LEAD.total_seconds():g} s after the server clock"
                    ),
                }
            ]
        )


def _flisr_plan_description() -> str:
    return (
        "Build an isolation and restoration plan for a feeder whose breaker or recloser is in "
        "lockout.\n\n"
        "Tie capacity: send `tie_capacity` (tie mRID -> `{kw, timestamp, quality}`). A tie "
        f"closes only when its capacity has quality {TIE_CAPACITY_GOOD_QUALITY}, is at most "
        f"{TIE_CAPACITY_MAX_AGE.total_seconds():g} s old and at most "
        f"{TIE_CAPACITY_MAX_LEAD.total_seconds():g} s ahead of `as_of`, and the load to "
        f"transfer is at most the capacity + {TIE_CAPACITY_TOLERANCE_KW:g} kW. Any other tie is "
        "listed in `blocked_ties` with its reason (HTTP 200). `as_of` defaults to the server "
        f"clock and must be within {AS_OF_MAX_LAG.total_seconds():g} s before and "
        f"{AS_OF_MAX_LEAD.total_seconds():g} s after the server clock (otherwise 422).\n\n"
        "**Deprecated:** `tie_capacity_kw` is deprecated and will be removed one release after "
        "this one. It is mutually exclusive with `tie_capacity`; sending both returns 422. "
        f"Legacy values are treated as quality {TIE_CAPACITY_GOOD_QUALITY} with timestamp = "
        "`as_of`, and the response lists `tie_capacity_kw` in `deprecations`."
    )


@router.post(
    "/flisr/plan", response_model=RestorationPlan, description=_flisr_plan_description()
)
def flisr_plan(
    request: FlisrRequest, now: Annotated[datetime, Depends(server_now)]
) -> RestorationPlan:
    as_of = request.as_of if request.as_of is not None else now
    _check_as_of_bound(as_of, now)
    network = load_network()
    try:
        feeder = get_feeder(network, request.feeder_mrid)
        return flisr.build_plan(
            feeder,
            request.lockout_switch_mrid,
            request.tie_capacity_kw,
            tie_capacity=request.tie_capacity,
            as_of=as_of,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except flisr.FlisrError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/state-estimator/run")
def run_estimator(request: EstimationRequest) -> dict[str, object]:
    result = state_estimator.estimate(request.measurements)
    return {
        "estimated": result.estimated,
        "residuals": result.residuals,
        "rejected": result.rejected,
        "observable": result.observable,
        "iterations": result.iterations,
        "rms_residual": state_estimator.convergence_metric(result),
    }


@router.post("/agc/dispatch")
def agc_dispatch(request: AgcRequest) -> dict[str, object]:
    ace = agc.reporting_ace(request.balancing_state)
    return {"ace_mw": ace, "setpoint_deltas_mw": agc.allocate_regulation(request.units, ace)}


async def _request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 without echoing the rejected input, which may be a non-finite float (F-QA-U2-1)."""
    detail = [
        {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


def create_app() -> FastAPI:
    app = FastAPI(title="Grid Control Services", version=__version__)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.include_router(router)
    return app


app = create_app()

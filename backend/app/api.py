"""HTTP surface used by the control-room clients and the SCADA adapter."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__, ace_client, flisr, state_estimator
from .models import BalancingState, Feeder, Measurement, RestorationPlan, Unit
from .network import get_feeder, load_network

router = APIRouter()


class FlisrRequest(BaseModel):
    feeder_mrid: str
    lockout_switch_mrid: str
    tie_capacity_kw: dict[str, float] = {}


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


@router.post("/flisr/plan", response_model=RestorationPlan)
def flisr_plan(request: FlisrRequest) -> RestorationPlan:
    network = load_network()
    try:
        feeder = get_feeder(network, request.feeder_mrid)
        return flisr.build_plan(feeder, request.lockout_switch_mrid, request.tie_capacity_kw)
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
    try:
        return ace_client.dispatch(request.balancing_state, request.units)
    except ace_client.AceServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def create_app() -> FastAPI:
    app = FastAPI(title="Grid Control Services", version=__version__)
    app.include_router(router)
    return app


app = create_app()

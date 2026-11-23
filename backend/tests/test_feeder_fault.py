from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.flisr import FlisrError, build_plan
from app.models import IsolationStep, RestorationPlan
from app.network import customers_out, get_feeder, load_network, switch_by_mrid

pytestmark = pytest.mark.characterization

BREAKER = "CB-1201"
TIE = "TIE-1201-1405"
UPSTREAM = IsolationStep(
    switch_mrid="SEC-SW-1201-1",
    action="open",
    reason="upstream isolation of Quarry Crossing",
)
DOWNSTREAM = IsolationStep(
    switch_mrid="REC-1201-2",
    action="open",
    reason="downstream isolation of Quarry Crossing",
)
RECLOSE = IsolationStep(
    switch_mrid=BREAKER,
    action="close",
    reason="re-energise healthy sections upstream of the fault",
)
BACKFEED = IsolationStep(
    switch_mrid=TIE,
    action="close",
    reason="back-feed 3 nodes from alternate source",
)


@pytest.fixture
def locked_out_network():
    network = load_network()
    switch_by_mrid(get_feeder(network, "FDR-1201"), BREAKER).open = True
    return network


@pytest.fixture
def feeder(locked_out_network):
    return get_feeder(locked_out_network, "FDR-1201")


@pytest.mark.parametrize(
    ("capacity", "customers_restored", "customers_remaining", "restoration", "notes"),
    [
        (
            None, 0, 437, [RECLOSE],
            ["Hollow Creek tie to 1405 skipped: 1490 kW exceeds 0 kW available capacity"],
        ),
        (
            1489, 0, 437, [RECLOSE],
            ["Hollow Creek tie to 1405 skipped: 1490 kW exceeds 1489 kW available capacity"],
        ),
        (1490, 341, 96, [RECLOSE, BACKFEED], []),
    ],
    ids=["default-zero-capacity", "one-kw-short", "exact-capacity"],
)
def test_restoration_capacity_and_operation_order(
    feeder, capacity, customers_restored, customers_remaining, restoration, notes
):
    before = feeder.model_copy(deep=True)
    plan = build_plan(feeder, BREAKER, {TIE: capacity} if capacity is not None else None)

    assert plan == RestorationPlan(
        feeder_mrid=feeder.mrid,
        faulted_section="SEC-1201-03",
        isolation=[UPSTREAM, DOWNSTREAM],
        restoration=restoration,
        customers_restored=customers_restored,
        customers_remaining=customers_remaining,
        transferred_load_kw=1490.0 if customers_restored else 0.0,
        notes=notes,
    )
    assert feeder == before


def test_no_fault_indication_leaves_all_downstream_customers_out(feeder):
    for section in feeder.sections:
        section.fault_indicator = False

    assert customers_out(feeder) == 1117
    assert build_plan(feeder, BREAKER) == RestorationPlan(
        feeder_mrid=feeder.mrid,
        faulted_section=None,
        customers_remaining=1117,
        notes=["no fault indication received; manual patrol required"],
    )


def test_final_indication_locates_tail_and_skips_non_remote_breaker(feeder):
    feeder.sections[-1].fault_indicator = True
    switch_by_mrid(feeder, BREAKER).scada_controllable = False
    switch_by_mrid(feeder, TIE).scada_controllable = False

    assert build_plan(feeder, BREAKER, {TIE: 2000}) == RestorationPlan(
        feeder_mrid=feeder.mrid,
        faulted_section="SEC-1201-04",
        isolation=[
            IsolationStep(
                switch_mrid="REC-1201-2",
                action="open",
                reason="upstream isolation of Hollow Creek tail",
            )
        ],
        customers_remaining=341,
    )


def test_refuses_fault_without_remote_isolation(feeder):
    for switch_mrid in (UPSTREAM.switch_mrid, DOWNSTREAM.switch_mrid):
        switch_by_mrid(feeder, switch_mrid).scada_controllable = False

    with pytest.raises(FlisrError, match="^no SCADA switch can isolate Quarry Crossing$"):
        build_plan(feeder, BREAKER, {TIE: 2000})


def test_tie_that_picks_up_no_new_nodes_is_not_closed(feeder):
    switch_by_mrid(feeder, TIE).from_node = feeder.source_node

    # Suspected defect: the still-unserved tail customers are not counted here.
    assert build_plan(feeder, BREAKER, {TIE: 2000}) == RestorationPlan(
        feeder_mrid=feeder.mrid,
        faulted_section="SEC-1201-03",
        isolation=[UPSTREAM, DOWNSTREAM],
        restoration=[RECLOSE],
        customers_remaining=96,
    )


def test_flisr_endpoint_returns_restoration_plan(locked_out_network):
    with patch("app.api.load_network", return_value=locked_out_network):
        response = TestClient(app).post(
            "/flisr/plan",
            json={
                "feeder_mrid": "FDR-1201",
                "lockout_switch_mrid": BREAKER,
                "tie_capacity_kw": {TIE: 1490},
            },
        )

    assert response.status_code == 200
    assert response.json() == RestorationPlan(
        feeder_mrid="FDR-1201",
        faulted_section="SEC-1201-03",
        isolation=[UPSTREAM, DOWNSTREAM],
        restoration=[RECLOSE, BACKFEED],
        customers_restored=341,
        customers_remaining=96,
        transferred_load_kw=1490.0,
    ).model_dump()


@pytest.mark.parametrize(
    ("feeder_mrid", "switch_mrid", "status", "detail"),
    [
        ("unknown", BREAKER, 404, "'unknown feeder unknown'"),
        ("FDR-1201", "unknown", 404, "'unknown switch unknown'"),
        ("FDR-1201", BREAKER, 409, "Cedar Ridge 1201 breaker is not in lockout"),
    ],
)
def test_flisr_endpoint_reports_unknown_assets_and_missing_lockout(
    feeder_mrid, switch_mrid, status, detail
):
    response = TestClient(app).post(
        "/flisr/plan", json={"feeder_mrid": feeder_mrid, "lockout_switch_mrid": switch_mrid}
    )

    assert response.status_code == status
    assert response.json() == {"detail": detail}

#include "test_harness.h"

#include "fault_detect.h"

static void assert_decision(trip_decision_t decision, trip_kind_t kind,
                            element_id_t element, double seconds, double amps)
{
    TH_ASSERT(decision.tripped == (kind != TRIP_NONE));
    TH_ASSERT(decision.kind == kind);
    TH_ASSERT(decision.element == element);
    TH_ASSERT_NEAR(decision.operate_time_s, seconds, 1e-9);
    TH_ASSERT_NEAR(decision.measured_amps, amps, 1e-9);
}

static void test_operate_time(void)
{
    oc_setting_t setting = {100.0, 0.5, CURVE_VERY_INVERSE, 0.25};

    TH_CASE("inverse and definite-time curves");
    TH_ASSERT_NEAR(oc_operate_time(&setting, 200.0), 6.75, 1e-9);
    setting.curve = CURVE_EXTREMELY_INVERSE;
    TH_ASSERT_NEAR(oc_operate_time(&setting, 300.0), 5.0, 1e-9);
    setting.curve = CURVE_DEFINITE_TIME;
    TH_ASSERT_NEAR(oc_operate_time(&setting, 101.0), 0.25, 1e-9);

    TH_CASE("pickup boundary and near-pickup denominator guard");
    TH_ASSERT(oc_operate_time(&setting, 100.0) == -1.0);
    setting.curve = CURVE_STANDARD_INVERSE;
    TH_ASSERT(oc_operate_time(&setting, nextafter(100.0, INFINITY)) == -1.0);
    TH_ASSERT(oc_operate_time(NULL, 200.0) == -1.0);
    setting.pickup_amps = 0.0;
    TH_ASSERT(oc_operate_time(&setting, 200.0) == -1.0);
}

static void test_instantaneous_selection(void)
{
    relay_settings_t settings = {
        .phase_inst = {.pickup_amps = 800.0, .definite_time_s = 0.04},
        .ground_inst = {.pickup_amps = 200.0, .definite_time_s = 0.02},
    };
    phasor_sample_t sample = {.ia_amps = 799.0, .ib_amps = 800.0, .in_amps = 200.0};

    TH_CASE("instantaneous pickup is strictly above threshold");
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_NONE, ELEMENT_NONE, 0.0, 0.0);

    TH_CASE("ground instantaneous trip with phase at pickup");
    sample.in_amps = 201.0;
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_INSTANTANEOUS, ELEMENT_50G, 0.02, 201.0);

    TH_CASE("phase instantaneous wins when both elements pick up");
    sample.ic_amps = 801.0;
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_INSTANTANEOUS, ELEMENT_50P, 0.04, 801.0);

    TH_CASE("nonpositive settings disable instantaneous elements");
    settings.phase_inst.pickup_amps = 0.0;
    settings.ground_inst.pickup_amps = -1.0;
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_NONE, ELEMENT_NONE, 0.0, 0.0);
}

static void test_time_delayed_selection(void)
{
    relay_settings_t settings = {
        .phase_toc = {.pickup_amps = 500.0, .curve = CURVE_DEFINITE_TIME,
                      .definite_time_s = 0.2},
        .ground_toc = {.pickup_amps = 100.0, .curve = CURVE_DEFINITE_TIME,
                       .definite_time_s = 0.1},
    };
    phasor_sample_t sample = {.ib_amps = 600.0, .in_amps = 120.0};

    TH_CASE("time-overcurrent prefers the shorter time and gives ties to phase");
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_TIME_DELAYED, ELEMENT_51G, 0.1, 120.0);
    settings.ground_toc.definite_time_s = 0.2;
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_TIME_DELAYED, ELEMENT_51P, 0.2, 600.0);
    sample.ib_amps = 500.0;
    assert_decision(fault_detect_evaluate(&settings, &sample),
                    TRIP_TIME_DELAYED, ELEMENT_51G, 0.2, 120.0);

    TH_CASE("missing input returns an empty trip decision");
    assert_decision(fault_detect_evaluate(NULL, &sample),
                    TRIP_NONE, ELEMENT_NONE, 0.0, 0.0);
    assert_decision(fault_detect_evaluate(&settings, NULL),
                    TRIP_NONE, ELEMENT_NONE, 0.0, 0.0);
}

static void test_fpi_latch_and_reset(void)
{
    TH_CASE("fault indicator holds until energised, reset delay elapsed, and below pickup");
    fpi_state_t fpi = {.asserted = true, .asserted_at_ms = 10U};
    fpi_init(NULL, 500.0, 20U);
    fpi_init(&fpi, 500.0, 20U);
    TH_ASSERT(!fpi.asserted && fpi.asserted_at_ms == 0U);
    TH_ASSERT(fpi.threshold_amps == 500.0 && fpi.reset_delay_ms == 20U);

    phasor_sample_t sample = {.ib_amps = 499.0, .timestamp_ms = UINT32_MAX - 9U};
    fpi_update(&fpi, &sample, false);
    TH_ASSERT(!fpi.asserted && fpi.asserted_at_ms == 0U);

    sample.ib_amps = 500.0;
    fpi_update(&fpi, &sample, false);
    TH_ASSERT(fpi.asserted && fpi.asserted_at_ms == UINT32_MAX - 9U);

    sample.ib_amps = 499.0;
    sample.timestamp_ms = 9U;
    fpi_update(&fpi, &sample, true);
    TH_ASSERT(fpi.asserted && fpi.asserted_at_ms == UINT32_MAX - 9U);

    sample.timestamp_ms = 10U;
    fpi_update(&fpi, &sample, false);
    TH_ASSERT(fpi.asserted && fpi.asserted_at_ms == UINT32_MAX - 9U);
    sample.ib_amps = 500.0;
    fpi_update(&fpi, &sample, true);
    TH_ASSERT(fpi.asserted && fpi.asserted_at_ms == UINT32_MAX - 9U);

    sample.ib_amps = 499.0;
    fpi_update(NULL, &sample, true);
    fpi_update(&fpi, NULL, true);
    TH_ASSERT(fpi.asserted && fpi.asserted_at_ms == UINT32_MAX - 9U);
    fpi_update(&fpi, &sample, true);
    TH_ASSERT(!fpi.asserted && fpi.asserted_at_ms == 0U);
}

int main(void)
{
    test_operate_time();
    test_instantaneous_selection();
    test_time_delayed_selection();
    test_fpi_latch_and_reset();
    return th_report("fault characterization");
}

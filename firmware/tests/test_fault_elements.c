/* Coverage for the parts of fault_detect.c the legacy suite never reached:
 * the ground elements, the instantaneous elements, the inverse-time curve
 * families and the fault passage indicator latch. */
#include "test_harness.h"

#include "fault_detect.h"

static relay_settings_t feeder_settings(void)
{
    relay_settings_t s;
    memset(&s, 0, sizeof(s));
    s.ct_ratio = 600.0 / 5.0;
    s.phase_inst.pickup_amps = 4800.0;
    s.phase_inst.curve = CURVE_DEFINITE_TIME;
    s.phase_inst.definite_time_s = 0.02;
    s.phase_toc.pickup_amps = 600.0;
    s.phase_toc.time_dial = 0.20;
    s.phase_toc.curve = CURVE_STANDARD_INVERSE;
    s.ground_inst.pickup_amps = 1200.0;
    s.ground_inst.curve = CURVE_DEFINITE_TIME;
    s.ground_inst.definite_time_s = 0.05;
    s.ground_toc.pickup_amps = 120.0;
    s.ground_toc.time_dial = 0.15;
    s.ground_toc.curve = CURVE_VERY_INVERSE;
    return s;
}

static void test_phase_instantaneous_trip(void)
{
    TH_CASE("phase instantaneous trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {5200.0, 410.0, 395.0, 60.0, 12.47, 3000U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_50P);
    TH_ASSERT(d.kind == TRIP_INSTANTANEOUS);
    TH_ASSERT_NEAR(d.operate_time_s, 0.02, 1e-9);
    TH_ASSERT_NEAR(d.measured_amps, 5200.0, 1e-9);
}

static void test_instantaneous_uses_the_largest_phase(void)
{
    TH_CASE("instantaneous element uses the largest phase current");
    relay_settings_t s = feeder_settings();
    phasor_sample_t on_b = {300.0, 5100.0, 310.0, 40.0, 12.47, 3100U};
    phasor_sample_t on_c = {300.0, 320.0, 4900.0, 40.0, 12.47, 3200U};

    trip_decision_t db = fault_detect_evaluate(&s, &on_b);
    trip_decision_t dc = fault_detect_evaluate(&s, &on_c);

    TH_ASSERT(db.element == ELEMENT_50P);
    TH_ASSERT_NEAR(db.measured_amps, 5100.0, 1e-9);
    TH_ASSERT(dc.element == ELEMENT_50P);
    TH_ASSERT_NEAR(dc.measured_amps, 4900.0, 1e-9);
}

static void test_ground_instantaneous_trip(void)
{
    TH_CASE("ground instantaneous trip on residual current");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {900.0, 280.0, 275.0, 1400.0, 12.47, 4000U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_50G);
    TH_ASSERT(d.kind == TRIP_INSTANTANEOUS);
    TH_ASSERT_NEAR(d.operate_time_s, 0.05, 1e-9);
    TH_ASSERT_NEAR(d.measured_amps, 1400.0, 1e-9);
}

static void test_ground_time_overcurrent_trip(void)
{
    TH_CASE("ground time overcurrent trip when no phase element picks up");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {300.0, 295.0, 290.0, 480.0, 12.47, 5000U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_51G);
    TH_ASSERT(d.kind == TRIP_TIME_DELAYED);
    /* very inverse: t = 0.15 * 13.5 / ((480/120) - 1) */
    TH_ASSERT_NEAR(d.operate_time_s, 0.675, 1e-4);
    TH_ASSERT_NEAR(d.measured_amps, 480.0, 1e-9);
}

static void test_faster_element_wins(void)
{
    TH_CASE("the faster of the two time elements is reported");
    relay_settings_t s = feeder_settings();
    /* Both 51P and 51G pick up; the ground curve is far faster here. */
    phasor_sample_t sample = {900.0, 320.0, 310.0, 900.0, 12.47, 5500U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);
    double t_phase = oc_operate_time(&s.phase_toc, 900.0);
    double t_ground = oc_operate_time(&s.ground_toc, 900.0);

    TH_ASSERT(t_phase > 0.0);
    TH_ASSERT(t_ground > 0.0);
    TH_ASSERT(t_ground < t_phase);
    TH_ASSERT(d.element == ELEMENT_51G);
    TH_ASSERT_NEAR(d.operate_time_s, t_ground, 1e-9);
}

static void test_null_inputs_do_not_trip(void)
{
    TH_CASE("null settings or sample never trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {5200.0, 410.0, 395.0, 60.0, 12.47, 3000U};

    trip_decision_t a = fault_detect_evaluate(NULL, &sample);
    trip_decision_t b = fault_detect_evaluate(&s, NULL);

    TH_ASSERT(a.tripped == false);
    TH_ASSERT(a.element == ELEMENT_NONE);
    TH_ASSERT(b.tripped == false);
    TH_ASSERT(b.element == ELEMENT_NONE);
}

static void test_operate_time_edge_cases(void)
{
    TH_CASE("operate time rejects disabled, unreached and marginal pickups");
    oc_setting_t disabled = {0.0, 0.2, CURVE_STANDARD_INVERSE, 0.0};
    oc_setting_t toc = {600.0, 0.2, CURVE_STANDARD_INVERSE, 0.0};
    oc_setting_t definite = {600.0, 0.0, CURVE_DEFINITE_TIME, 0.35};
    oc_setting_t extreme = {600.0, 0.5, CURVE_EXTREMELY_INVERSE, 0.0};

    TH_ASSERT(oc_operate_time(NULL, 1200.0) < 0.0);
    TH_ASSERT(oc_operate_time(&disabled, 1200.0) < 0.0);
    TH_ASSERT(oc_operate_time(&toc, 600.0) < 0.0);          /* at pickup, not above */
    TH_ASSERT(oc_operate_time(&toc, 600.0000001) < 0.0);    /* denominator underflows */
    TH_ASSERT_NEAR(oc_operate_time(&definite, 1200.0), 0.35, 1e-9);
    /* extremely inverse: t = 0.5 * 80 / ((1800/600)^2 - 1) */
    TH_ASSERT_NEAR(oc_operate_time(&extreme, 1800.0), 5.0, 1e-6);
}

static void test_fpi_latches_and_holds(void)
{
    TH_CASE("fault passage indicator latches on fault current and holds");
    fpi_state_t fpi;
    phasor_sample_t load = {300.0, 290.0, 285.0, 5.0, 12.47, 1000U};
    phasor_sample_t fault = {2500.0, 310.0, 300.0, 90.0, 12.47, 2000U};

    fpi_init(&fpi, 1000.0, 5000U);
    TH_ASSERT(fpi.asserted == false);
    TH_ASSERT_NEAR(fpi.threshold_amps, 1000.0, 1e-9);

    fpi_update(&fpi, &load, true);
    TH_ASSERT(fpi.asserted == false);

    fpi_update(&fpi, &fault, false);
    TH_ASSERT(fpi.asserted == true);
    TH_ASSERT(fpi.asserted_at_ms == 2000U);

    /* De-energised feeder: the latch holds no matter how long it has been. */
    load.timestamp_ms = 20000U;
    fpi_update(&fpi, &load, false);
    TH_ASSERT(fpi.asserted == true);
}

static void test_fpi_reset_requires_energised_feeder_and_delay(void)
{
    TH_CASE("fault passage indicator resets only after the delay on a healthy feeder");
    fpi_state_t fpi;
    phasor_sample_t fault = {2500.0, 310.0, 300.0, 90.0, 12.47, 2000U};
    phasor_sample_t healthy = {300.0, 290.0, 285.0, 5.0, 12.47, 4000U};

    fpi_init(&fpi, 1000.0, 5000U);
    fpi_update(&fpi, &fault, false);
    TH_ASSERT(fpi.asserted == true);

    fpi_update(&fpi, &healthy, true); /* only 2 s into a 5 s reset delay */
    TH_ASSERT(fpi.asserted == true);

    healthy.timestamp_ms = 7000U;
    fpi_update(&fpi, &healthy, true);
    TH_ASSERT(fpi.asserted == false);
    TH_ASSERT(fpi.asserted_at_ms == 0U);

    /* Re-latches on the next fault. */
    fault.timestamp_ms = 9000U;
    fpi_update(&fpi, &fault, true);
    TH_ASSERT(fpi.asserted == true);
    TH_ASSERT(fpi.asserted_at_ms == 9000U);
}

static void test_fpi_does_not_reset_while_current_persists(void)
{
    TH_CASE("fault passage indicator holds while fault current persists");
    fpi_state_t fpi;
    phasor_sample_t fault = {2500.0, 310.0, 300.0, 90.0, 12.47, 2000U};

    fpi_init(&fpi, 1000.0, 5000U);
    fpi_update(&fpi, &fault, true);
    TH_ASSERT(fpi.asserted == true);

    fault.timestamp_ms = 30000U;
    fpi_update(&fpi, &fault, true);
    TH_ASSERT(fpi.asserted == true);
}

static void test_fpi_null_arguments(void)
{
    TH_CASE("fault passage indicator ignores null arguments");
    fpi_state_t fpi;
    phasor_sample_t fault = {2500.0, 310.0, 300.0, 90.0, 12.47, 2000U};

    fpi_init(NULL, 1000.0, 5000U);
    fpi_init(&fpi, 1000.0, 5000U);
    fpi_update(NULL, &fault, true);
    fpi_update(&fpi, NULL, true);
    TH_ASSERT(fpi.asserted == false);
}

int main(void)
{
    test_phase_instantaneous_trip();
    test_instantaneous_uses_the_largest_phase();
    test_ground_instantaneous_trip();
    test_ground_time_overcurrent_trip();
    test_faster_element_wins();
    test_null_inputs_do_not_trip();
    test_operate_time_edge_cases();
    test_fpi_latches_and_holds();
    test_fpi_reset_requires_energised_feeder_and_delay();
    test_fpi_does_not_reset_while_current_persists();
    test_fpi_null_arguments();
    return th_report("fault_detect elements");
}

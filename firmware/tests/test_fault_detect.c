/* Overcurrent protection (50/51) and fault passage indication tests. */
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

static void test_no_trip_at_load_current(void)
{
    TH_CASE("no trip at load current");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {320.0, 310.0, 305.0, 8.0, 12.47, 1000U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == false);
    TH_ASSERT(d.element == ELEMENT_NONE);
}

static void test_phase_time_overcurrent_trip(void)
{
    TH_CASE("phase time overcurrent trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {2400.0, 380.0, 375.0, 15.0, 12.47, 2000U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_51P);
    TH_ASSERT(d.kind == TRIP_TIME_DELAYED);
    /* t = 0.2 * 0.14 / ((2400/600)^0.02 - 1) */
    TH_ASSERT_NEAR(d.operate_time_s, 0.9925, 0.01);
}

static void test_operate_time_rejects_missing_or_disabled_settings(void)
{
    TH_CASE("operate time is -1 without a usable setting");
    oc_setting_t disabled = {0.0, 1.0, CURVE_STANDARD_INVERSE, 0.0};
    oc_setting_t negative = {-10.0, 1.0, CURVE_STANDARD_INVERSE, 0.0};
    TH_ASSERT(oc_operate_time(NULL, 1000.0) == -1.0);
    TH_ASSERT(oc_operate_time(&disabled, 1000.0) == -1.0);
    TH_ASSERT(oc_operate_time(&negative, 1000.0) == -1.0);
}

static void test_operate_time_requires_current_above_pickup(void)
{
    TH_CASE("no operation at or below pickup");
    oc_setting_t si = {600.0, 1.0, CURVE_STANDARD_INVERSE, 0.0};
    TH_ASSERT(oc_operate_time(&si, 599.0) == -1.0);
    TH_ASSERT(oc_operate_time(&si, 600.0) == -1.0);
    /* Just above pickup the curve is asymptotic: guarded instead of returning ~1e12 s. */
    TH_ASSERT(oc_operate_time(&si, 600.0 * (1.0 + 1e-12)) == -1.0);
}

static void test_operate_time_iec_curves(void)
{
    TH_CASE("IEC 60255-151 curve constants");
    oc_setting_t si = {100.0, 1.0, CURVE_STANDARD_INVERSE, 0.0};
    oc_setting_t vi = {100.0, 1.0, CURVE_VERY_INVERSE, 0.0};
    oc_setting_t ei = {100.0, 1.0, CURVE_EXTREMELY_INVERSE, 0.0};
    oc_setting_t dt = {100.0, 1.0, CURVE_DEFINITE_TIME, 0.35};
    oc_setting_t unknown = {100.0, 1.0, (curve_type_t)99, 0.0};
    TH_ASSERT_NEAR(oc_operate_time(&si, 1000.0), 0.14 / (pow(10.0, 0.02) - 1.0), 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(&vi, 200.0), 13.5, 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(&ei, 200.0), 80.0 / 3.0, 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(&dt, 5000.0), 0.35, 1e-12);
    /* An out-of-range curve code falls back to standard inverse. */
    TH_ASSERT_NEAR(oc_operate_time(&unknown, 1000.0), oc_operate_time(&si, 1000.0), 1e-12);
    /* TMS scales operate time linearly. */
    vi.time_dial = 0.1;
    TH_ASSERT_NEAR(oc_operate_time(&vi, 200.0), 1.35, 1e-9);
}

static void test_null_inputs_never_trip(void)
{
    TH_CASE("null settings or sample never trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {9000.0, 9000.0, 9000.0, 9000.0, 12.47, 1U};
    trip_decision_t d = fault_detect_evaluate(NULL, &sample);
    TH_ASSERT(d.tripped == false && d.kind == TRIP_NONE && d.element == ELEMENT_NONE);
    d = fault_detect_evaluate(&s, NULL);
    TH_ASSERT(d.tripped == false && d.kind == TRIP_NONE);
}

static void test_phase_instantaneous_uses_highest_phase(void)
{
    TH_CASE("50P trips on the highest phase current");
    relay_settings_t s = feeder_settings();
    phasor_sample_t a = {5000.0, 300.0, 300.0, 1500.0, 12.47, 1U};
    phasor_sample_t b = {300.0, 5100.0, 300.0, 0.0, 12.47, 2U};
    phasor_sample_t c = {300.0, 2000.0, 5200.0, 0.0, 12.47, 3U};

    trip_decision_t d = fault_detect_evaluate(&s, &a);
    TH_ASSERT(d.tripped && d.kind == TRIP_INSTANTANEOUS && d.element == ELEMENT_50P);
    TH_ASSERT_NEAR(d.operate_time_s, 0.02, 1e-12);
    TH_ASSERT_NEAR(d.measured_amps, 5000.0, 1e-12); /* 50P outranks 50G */

    d = fault_detect_evaluate(&s, &b);
    TH_ASSERT(d.element == ELEMENT_50P);
    TH_ASSERT_NEAR(d.measured_amps, 5100.0, 1e-12);

    d = fault_detect_evaluate(&s, &c);
    TH_ASSERT(d.element == ELEMENT_50P);
    TH_ASSERT_NEAR(d.measured_amps, 5200.0, 1e-12);
}

static void test_ground_instantaneous_trip(void)
{
    TH_CASE("50G trips on residual current");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {400.0, 380.0, 390.0, 1500.0, 12.47, 1U};
    trip_decision_t d = fault_detect_evaluate(&s, &sample);
    TH_ASSERT(d.tripped && d.kind == TRIP_INSTANTANEOUS && d.element == ELEMENT_50G);
    TH_ASSERT_NEAR(d.operate_time_s, 0.05, 1e-12);
    TH_ASSERT_NEAR(d.measured_amps, 1500.0, 1e-12);
}

static void test_disabled_instantaneous_falls_through_to_time_overcurrent(void)
{
    TH_CASE("50P/50G with zero pickup are disabled");
    relay_settings_t s = feeder_settings();
    s.phase_inst.pickup_amps = 0.0;
    s.ground_inst.pickup_amps = 0.0;
    phasor_sample_t phase = {6000.0, 300.0, 300.0, 10.0, 12.47, 1U};
    phasor_sample_t ground = {300.0, 300.0, 300.0, 2000.0, 12.47, 2U};
    TH_ASSERT(fault_detect_evaluate(&s, &phase).element == ELEMENT_51P);
    TH_ASSERT(fault_detect_evaluate(&s, &ground).element == ELEMENT_51G);
}

static void test_ground_time_overcurrent_trip(void)
{
    TH_CASE("51G trips when only ground exceeds pickup");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {400.0, 410.0, 395.0, 240.0, 12.47, 1U};
    trip_decision_t d = fault_detect_evaluate(&s, &sample);
    TH_ASSERT(d.tripped && d.kind == TRIP_TIME_DELAYED && d.element == ELEMENT_51G);
    /* VI: 0.15 * 13.5 / (240/120 - 1) */
    TH_ASSERT_NEAR(d.operate_time_s, 2.025, 1e-9);
    TH_ASSERT_NEAR(d.measured_amps, 240.0, 1e-12);
}

static void test_fastest_time_overcurrent_element_wins(void)
{
    TH_CASE("51P vs 51G: the faster element trips, phase wins ties");
    relay_settings_t s = feeder_settings();
    phasor_sample_t phase_faster = {2400.0, 380.0, 375.0, 240.0, 12.47, 1U};
    phasor_sample_t ground_faster = {700.0, 380.0, 375.0, 600.0, 12.47, 2U};
    TH_ASSERT(fault_detect_evaluate(&s, &phase_faster).element == ELEMENT_51P);
    trip_decision_t d = fault_detect_evaluate(&s, &ground_faster);
    TH_ASSERT(d.element == ELEMENT_51G);
    TH_ASSERT_NEAR(d.operate_time_s, 0.15 * 13.5 / 4.0, 1e-9);

    s.phase_toc.curve = CURVE_DEFINITE_TIME;
    s.phase_toc.definite_time_s = 0.3;
    s.ground_toc.curve = CURVE_DEFINITE_TIME;
    s.ground_toc.definite_time_s = 0.3;
    d = fault_detect_evaluate(&s, &ground_faster);
    TH_ASSERT(d.element == ELEMENT_51P);
    TH_ASSERT_NEAR(d.operate_time_s, 0.3, 1e-12);
}

static void test_fpi_init(void)
{
    TH_CASE("FPI init clears the latch and stores settings");
    fpi_state_t fpi;
    memset(&fpi, 0xFF, sizeof(fpi));
    fpi_init(NULL, 1.0, 1U);
    fpi_init(&fpi, 900.0, 60000U);
    TH_ASSERT(fpi.asserted == false);
    TH_ASSERT(fpi.asserted_at_ms == 0U);
    TH_ASSERT(fpi.reset_delay_ms == 60000U);
    TH_ASSERT_NEAR(fpi.threshold_amps, 900.0, 1e-12);
}

static void test_fpi_latches_and_resets(void)
{
    TH_CASE("FPI asserts on fault current and resets only when safe");
    fpi_state_t fpi;
    fpi_init(&fpi, 900.0, 60000U);
    phasor_sample_t load = {300.0, 310.0, 305.0, 5.0, 12.47, 1000U};
    phasor_sample_t fault = {300.0, 300.0, 900.0, 600.0, 12.47, 2000U};

    fpi_update(NULL, &fault, false);
    fpi_update(&fpi, NULL, false);
    fpi_update(&fpi, &load, true);
    TH_ASSERT(fpi.asserted == false);

    fpi_update(&fpi, &fault, false); /* threshold is inclusive, any phase */
    TH_ASSERT(fpi.asserted == true);
    TH_ASSERT(fpi.asserted_at_ms == 2000U);

    load.timestamp_ms = 2000U + 60000U;
    fpi_update(&fpi, &load, false); /* feeder still dead */
    TH_ASSERT(fpi.asserted == true);

    load.timestamp_ms = 2000U + 59999U;
    fpi_update(&fpi, &load, true); /* reset delay not yet expired */
    TH_ASSERT(fpi.asserted == true);

    fault.timestamp_ms = 2000U + 60000U;
    fpi_update(&fpi, &fault, true); /* fault current still flowing */
    TH_ASSERT(fpi.asserted == true);
    TH_ASSERT(fpi.asserted_at_ms == 2000U); /* re-seeing fault does not restart timer */

    load.timestamp_ms = 2000U + 60000U;
    fpi_update(&fpi, &load, true);
    TH_ASSERT(fpi.asserted == false);
    TH_ASSERT(fpi.asserted_at_ms == 0U);
}

int main(void)
{
    test_no_trip_at_load_current();
    test_phase_time_overcurrent_trip();
    test_operate_time_rejects_missing_or_disabled_settings();
    test_operate_time_requires_current_above_pickup();
    test_operate_time_iec_curves();
    test_null_inputs_never_trip();
    test_phase_instantaneous_uses_highest_phase();
    test_ground_instantaneous_trip();
    test_disabled_instantaneous_falls_through_to_time_overcurrent();
    test_ground_time_overcurrent_trip();
    test_fastest_time_overcurrent_element_wins();
    test_fpi_init();
    test_fpi_latches_and_resets();
    return th_report("fault_detect");
}

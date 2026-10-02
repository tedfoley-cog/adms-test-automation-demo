/* Coverage for the protection paths the legacy suite never exercised:
 * the ground elements, the instantaneous (50) elements, the inverse-time
 * curve families of IEC 60255-151, and the fault passage indicator latch. */
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
    TH_CASE("phase instantaneous (50P) trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {5200.0, 4900.0, 420.0, 60.0, 12.47, 3000U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_50P);
    TH_ASSERT(d.kind == TRIP_INSTANTANEOUS);
    TH_ASSERT_NEAR(d.operate_time_s, 0.02, 1e-9);
    TH_ASSERT_NEAR(d.measured_amps, 5200.0, 1e-9);
}

static void test_phase_instantaneous_uses_worst_phase(void)
{
    TH_CASE("instantaneous element picks the largest phase current");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {300.0, 310.0, 5100.0, 20.0, 12.47, 3100U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.element == ELEMENT_50P);
    TH_ASSERT_NEAR(d.measured_amps, 5100.0, 1e-9);
}

static void test_ground_instantaneous_trip(void)
{
    TH_CASE("ground instantaneous (50G) trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {400.0, 380.0, 360.0, 1500.0, 12.47, 3200U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_50G);
    TH_ASSERT(d.kind == TRIP_INSTANTANEOUS);
    TH_ASSERT_NEAR(d.operate_time_s, 0.05, 1e-9);
    TH_ASSERT_NEAR(d.measured_amps, 1500.0, 1e-9);
}

static void test_ground_time_overcurrent_trip(void)
{
    TH_CASE("ground time overcurrent (51G) trip on the very inverse curve");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {300.0, 295.0, 290.0, 400.0, 12.47, 3300U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_51G);
    TH_ASSERT(d.kind == TRIP_TIME_DELAYED);
    /* t = 0.15 * 13.5 / ((400/120)^1 - 1) */
    TH_ASSERT_NEAR(d.operate_time_s, 0.86786, 1e-4);
    TH_ASSERT_NEAR(d.measured_amps, 400.0, 1e-9);
}

static void test_phase_wins_when_both_time_elements_pick_up(void)
{
    TH_CASE("faster phase element wins over the ground element");
    relay_settings_t s = feeder_settings();
    s.ground_toc.time_dial = 5.0;
    phasor_sample_t sample = {2400.0, 380.0, 375.0, 400.0, 12.47, 3400U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.element == ELEMENT_51P);
    TH_ASSERT_NEAR(d.measured_amps, 2400.0, 1e-9);
}

static void test_ground_wins_when_faster(void)
{
    TH_CASE("faster ground element wins over the phase element");
    relay_settings_t s = feeder_settings();
    s.phase_toc.time_dial = 5.0;
    phasor_sample_t sample = {700.0, 380.0, 375.0, 900.0, 12.47, 3500U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.element == ELEMENT_51G);
}

static void test_disabled_instantaneous_elements(void)
{
    TH_CASE("instantaneous elements disabled by a zero pickup");
    relay_settings_t s = feeder_settings();
    s.phase_inst.pickup_amps = 0.0;
    s.ground_inst.pickup_amps = 0.0;
    phasor_sample_t sample = {6000.0, 400.0, 400.0, 30.0, 12.47, 3600U};

    trip_decision_t d = fault_detect_evaluate(&s, &sample);

    TH_ASSERT(d.tripped == true);
    TH_ASSERT(d.element == ELEMENT_51P);
    TH_ASSERT(d.kind == TRIP_TIME_DELAYED);
}

static void test_null_inputs(void)
{
    TH_CASE("null settings or sample yield no trip");
    relay_settings_t s = feeder_settings();
    phasor_sample_t sample = {6000.0, 400.0, 400.0, 30.0, 12.47, 3700U};

    trip_decision_t a = fault_detect_evaluate(NULL, &sample);
    trip_decision_t b = fault_detect_evaluate(&s, NULL);

    TH_ASSERT(a.tripped == false);
    TH_ASSERT(a.element == ELEMENT_NONE);
    TH_ASSERT(b.tripped == false);
}

static void test_operate_time_curve_families(void)
{
    TH_CASE("IEC 60255-151 curve families and definite time");
    oc_setting_t setting;
    memset(&setting, 0, sizeof(setting));
    setting.pickup_amps = 600.0;
    setting.time_dial = 0.20;

    setting.curve = CURVE_VERY_INVERSE;
    /* t = 0.2 * 13.5 / ((1200/600)^1 - 1) */
    TH_ASSERT_NEAR(oc_operate_time(&setting, 1200.0), 2.7, 1e-6);

    setting.curve = CURVE_EXTREMELY_INVERSE;
    /* t = 0.2 * 80 / ((1200/600)^2 - 1) */
    TH_ASSERT_NEAR(oc_operate_time(&setting, 1200.0), 5.333333, 1e-5);

    setting.curve = CURVE_STANDARD_INVERSE;
    /* t = 0.2 * 0.14 / ((1200/600)^0.02 - 1) */
    TH_ASSERT_NEAR(oc_operate_time(&setting, 1200.0), 2.005805, 1e-4);

    setting.curve = CURVE_DEFINITE_TIME;
    setting.definite_time_s = 0.35;
    TH_ASSERT_NEAR(oc_operate_time(&setting, 1200.0), 0.35, 1e-9);
}

static void test_operate_time_no_pickup(void)
{
    TH_CASE("operate time is -1 below pickup or with an invalid setting");
    oc_setting_t setting;
    memset(&setting, 0, sizeof(setting));
    setting.pickup_amps = 600.0;
    setting.time_dial = 0.20;
    setting.curve = CURVE_STANDARD_INVERSE;

    TH_ASSERT_NEAR(oc_operate_time(&setting, 600.0), -1.0, 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(&setting, 10.0), -1.0, 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(NULL, 1200.0), -1.0, 1e-9);

    setting.pickup_amps = 0.0;
    TH_ASSERT_NEAR(oc_operate_time(&setting, 1200.0), -1.0, 1e-9);
}

static void test_operate_time_just_above_pickup(void)
{
    TH_CASE("operate time is refused when the curve denominator vanishes");
    oc_setting_t setting;
    memset(&setting, 0, sizeof(setting));
    setting.pickup_amps = 600.0;
    setting.time_dial = 0.20;
    setting.curve = CURVE_STANDARD_INVERSE;

    TH_ASSERT_NEAR(oc_operate_time(&setting, 600.0 * (1.0 + 1e-12)), -1.0, 1e-9);
}

static void test_fpi_latches_and_holds(void)
{
    TH_CASE("fault passage indicator latches on fault current and holds");
    fpi_state_t fpi;
    fpi_init(&fpi, 1000.0, 5000U);
    TH_ASSERT(fpi.asserted == false);

    phasor_sample_t load = {300.0, 290.0, 280.0, 5.0, 12.47, 1000U};
    fpi_update(&fpi, &load, true);
    TH_ASSERT(fpi.asserted == false);

    phasor_sample_t fault = {2400.0, 310.0, 305.0, 80.0, 12.47, 2000U};
    fpi_update(&fpi, &fault, false);
    TH_ASSERT(fpi.asserted == true);
    TH_ASSERT(fpi.asserted_at_ms == 2000U);

    /* de-energised feeder never clears the latch */
    phasor_sample_t dead = {0.0, 0.0, 0.0, 0.0, 0.0, 9000U};
    fpi_update(&fpi, &dead, false);
    TH_ASSERT(fpi.asserted == true);

    /* re-energised but the reset delay has not expired */
    phasor_sample_t restored_early = {320.0, 300.0, 295.0, 6.0, 12.47, 5000U};
    fpi_update(&fpi, &restored_early, true);
    TH_ASSERT(fpi.asserted == true);

    /* re-energised, delay expired, but fault current still present */
    phasor_sample_t still_faulted = {2400.0, 300.0, 295.0, 6.0, 12.47, 12000U};
    fpi_update(&fpi, &still_faulted, true);
    TH_ASSERT(fpi.asserted == true);
}

static void test_fpi_resets_after_delay(void)
{
    TH_CASE("fault passage indicator resets once healthy for the reset delay");
    fpi_state_t fpi;
    fpi_init(&fpi, 1000.0, 5000U);

    phasor_sample_t fault = {2400.0, 310.0, 305.0, 80.0, 12.47, 2000U};
    fpi_update(&fpi, &fault, true);
    TH_ASSERT(fpi.asserted == true);

    phasor_sample_t restored = {320.0, 300.0, 295.0, 6.0, 12.47, 7000U};
    fpi_update(&fpi, &restored, true);

    TH_ASSERT(fpi.asserted == false);
    TH_ASSERT(fpi.asserted_at_ms == 0U);
}

static void test_fpi_null_inputs(void)
{
    TH_CASE("fault passage indicator ignores null inputs");
    fpi_state_t fpi;
    fpi_init(&fpi, 1000.0, 5000U);
    phasor_sample_t fault = {2400.0, 310.0, 305.0, 80.0, 12.47, 2000U};

    fpi_init(NULL, 1000.0, 5000U);
    fpi_update(NULL, &fault, true);
    fpi_update(&fpi, NULL, true);

    TH_ASSERT(fpi.asserted == false);
}

int main(void)
{
    test_phase_instantaneous_trip();
    test_phase_instantaneous_uses_worst_phase();
    test_ground_instantaneous_trip();
    test_ground_time_overcurrent_trip();
    test_phase_wins_when_both_time_elements_pick_up();
    test_ground_wins_when_faster();
    test_disabled_instantaneous_elements();
    test_null_inputs();
    test_operate_time_curve_families();
    test_operate_time_no_pickup();
    test_operate_time_just_above_pickup();
    test_fpi_latches_and_holds();
    test_fpi_resets_after_delay();
    test_fpi_null_inputs();
    return th_report("fault_detect_elements");
}

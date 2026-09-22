/* Protection unit tests carried over from the previous relay platform.
 * Coverage here is thin: only the phase time-overcurrent path is exercised. */
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

int main(void)
{
    test_no_trip_at_load_current();
    test_phase_time_overcurrent_trip();
    return th_report("fault_detect");
}

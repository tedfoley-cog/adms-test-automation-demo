/* Element-level tests for 50/51 phase and ground protection and the fault passage
 * indicator (IEC 60255-151). Complements test_fault_detect.c. */
#include "test_harness.h"

#include <stdint.h>

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

static phasor_sample_t sample_of(double ia, double ib, double ic, double in, uint32_t t)
{
    phasor_sample_t p;
    memset(&p, 0, sizeof(p));
    p.ia_amps = ia;
    p.ib_amps = ib;
    p.ic_amps = ic;
    p.in_amps = in;
    p.timestamp_ms = t;
    return p;
}

static oc_setting_t curve(curve_type_t type, double pickup, double tms)
{
    oc_setting_t o;
    memset(&o, 0, sizeof(o));
    o.curve = type;
    o.pickup_amps = pickup;
    o.time_dial = tms;
    o.definite_time_s = 0.3;
    return o;
}

static void test_operate_time_guards(void)
{
    TH_CASE("operate time is -1 for NULL, disabled, at-pickup and near-unity ratios");
    oc_setting_t si = curve(CURVE_STANDARD_INVERSE, 100.0, 0.1);
    oc_setting_t off = curve(CURVE_STANDARD_INVERSE, 0.0, 0.1);
    TH_ASSERT(oc_operate_time(NULL, 500.0) == -1.0);
    TH_ASSERT(oc_operate_time(&off, 500.0) == -1.0);
    TH_ASSERT(oc_operate_time(&si, 100.0) == -1.0);
    TH_ASSERT(oc_operate_time(&si, 99.0) == -1.0);
    TH_ASSERT(oc_operate_time(&si, 100.0 * (1.0 + 1e-12)) == -1.0);
}

static void test_operate_time_curves(void)
{
    TH_CASE("IEC SI, VI, EI and definite time at 10x pickup");
    oc_setting_t dt = curve(CURVE_DEFINITE_TIME, 100.0, 0.1);
    oc_setting_t si = curve(CURVE_STANDARD_INVERSE, 100.0, 0.1);
    oc_setting_t vi = curve(CURVE_VERY_INVERSE, 100.0, 0.1);
    oc_setting_t ei = curve(CURVE_EXTREMELY_INVERSE, 100.0, 0.1);
    TH_ASSERT_NEAR(oc_operate_time(&dt, 1000.0), 0.3, 1e-12);
    TH_ASSERT_NEAR(oc_operate_time(&si, 1000.0), 0.1 * 0.14 / (pow(10.0, 0.02) - 1.0), 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(&vi, 1000.0), 0.1 * 13.5 / 9.0, 1e-9);
    TH_ASSERT_NEAR(oc_operate_time(&ei, 1000.0), 0.1 * 80.0 / 99.0, 1e-9);
}

static void test_inverse_curves_are_monotonic(void)
{
    TH_CASE("more current never means a slower inverse-time trip");
    curve_type_t types[] = {CURVE_STANDARD_INVERSE, CURVE_VERY_INVERSE, CURVE_EXTREMELY_INVERSE};
    for (int k = 0; k < 3; k++) {
        oc_setting_t o = curve(types[k], 100.0, 0.2);
        double previous = oc_operate_time(&o, 101.0);
        for (double amps = 110.0; amps < 5000.0; amps += 37.0) {
            double t = oc_operate_time(&o, amps);
            TH_ASSERT(t > 0.0 && t <= previous);
            previous = t;
        }
    }
}

static void test_evaluate_null_inputs(void)
{
    TH_CASE("NULL settings or sample never trips");
    relay_settings_t s = feeder_settings();
    phasor_sample_t p = sample_of(9000.0, 0.0, 0.0, 0.0, 1U);
    TH_ASSERT(fault_detect_evaluate(NULL, &p).tripped == false);
    trip_decision_t d = fault_detect_evaluate(&s, NULL);
    TH_ASSERT(d.tripped == false && d.kind == TRIP_NONE && d.element == ELEMENT_NONE);
}

static void test_phase_instantaneous_uses_worst_phase(void)
{
    TH_CASE("50P trips on the highest phase, whichever phase it is");
    relay_settings_t s = feeder_settings();
    phasor_sample_t on_b = sample_of(300.0, 5200.0, 310.0, 10.0, 1U);
    phasor_sample_t on_c = sample_of(300.0, 310.0, 6100.0, 10.0, 2U);

    trip_decision_t b = fault_detect_evaluate(&s, &on_b);
    trip_decision_t c = fault_detect_evaluate(&s, &on_c);

    TH_ASSERT(b.tripped && b.kind == TRIP_INSTANTANEOUS && b.element == ELEMENT_50P);
    TH_ASSERT_NEAR(b.measured_amps, 5200.0, 1e-9);
    TH_ASSERT_NEAR(b.operate_time_s, 0.02, 1e-12);
    TH_ASSERT(c.element == ELEMENT_50P);
    TH_ASSERT_NEAR(c.measured_amps, 6100.0, 1e-9);
}

static void test_phase_instantaneous_disabled_falls_to_51p(void)
{
    TH_CASE("50P with zero pickup is disabled and 51P picks the fault up");
    relay_settings_t s = feeder_settings();
    s.phase_inst.pickup_amps = 0.0;
    phasor_sample_t p = sample_of(6000.0, 300.0, 300.0, 10.0, 1U);

    trip_decision_t d = fault_detect_evaluate(&s, &p);

    TH_ASSERT(d.tripped && d.element == ELEMENT_51P && d.kind == TRIP_TIME_DELAYED);
}

static void test_ground_instantaneous(void)
{
    TH_CASE("50G trips on residual current above ground instantaneous pickup");
    relay_settings_t s = feeder_settings();
    phasor_sample_t p = sample_of(500.0, 480.0, 470.0, 1500.0, 1U);

    trip_decision_t d = fault_detect_evaluate(&s, &p);

    TH_ASSERT(d.tripped && d.kind == TRIP_INSTANTANEOUS && d.element == ELEMENT_50G);
    TH_ASSERT_NEAR(d.measured_amps, 1500.0, 1e-9);
    TH_ASSERT_NEAR(d.operate_time_s, 0.05, 1e-12);

    s.ground_inst.pickup_amps = 0.0;
    d = fault_detect_evaluate(&s, &p);
    TH_ASSERT(d.element == ELEMENT_51G);
}

static void test_ground_time_overcurrent_only(void)
{
    TH_CASE("51G trips a high-impedance ground fault with phases at load");
    relay_settings_t s = feeder_settings();
    phasor_sample_t p = sample_of(320.0, 310.0, 305.0, 300.0, 1U);

    trip_decision_t d = fault_detect_evaluate(&s, &p);

    TH_ASSERT(d.tripped && d.element == ELEMENT_51G && d.kind == TRIP_TIME_DELAYED);
    TH_ASSERT_NEAR(d.operate_time_s, 0.15 * 13.5 / (300.0 / 120.0 - 1.0), 1e-9);
    TH_ASSERT_NEAR(d.measured_amps, 300.0, 1e-9);
}

static void test_faster_time_element_wins(void)
{
    TH_CASE("when 51P and 51G both pick up, the faster one is reported; ties go to 51P");
    relay_settings_t s = feeder_settings();
    phasor_sample_t ground_faster = sample_of(700.0, 300.0, 300.0, 1000.0, 1U);
    phasor_sample_t phase_faster = sample_of(4000.0, 300.0, 300.0, 130.0, 2U);

    TH_ASSERT(fault_detect_evaluate(&s, &ground_faster).element == ELEMENT_51G);
    TH_ASSERT(fault_detect_evaluate(&s, &phase_faster).element == ELEMENT_51P);

    s.ground_toc = s.phase_toc;
    phasor_sample_t tie = sample_of(1200.0, 0.0, 0.0, 1200.0, 3U);
    TH_ASSERT(fault_detect_evaluate(&s, &tie).element == ELEMENT_51P);
}

static void test_fpi_latch(void)
{
    TH_CASE("FPI asserts at threshold and resets only when energised, delayed and quiet");
    fpi_state_t f;
    fpi_init(NULL, 400.0, 1000U);
    fpi_init(&f, 400.0, 1000U);
    TH_ASSERT(!f.asserted && f.reset_delay_ms == 1000U);

    phasor_sample_t quiet = sample_of(399.0, 100.0, 100.0, 0.0, 100U);
    fpi_update(&f, &quiet, true);
    fpi_update(NULL, &quiet, true);
    fpi_update(&f, NULL, true);
    TH_ASSERT(!f.asserted);

    phasor_sample_t fault = sample_of(100.0, 400.0, 100.0, 0.0, 200U);
    fpi_update(&f, &fault, false);
    TH_ASSERT(f.asserted && f.asserted_at_ms == 200U);

    phasor_sample_t later = sample_of(100.0, 100.0, 100.0, 0.0, 1500U);
    fpi_update(&f, &later, false);
    TH_ASSERT(f.asserted);

    phasor_sample_t too_soon = sample_of(100.0, 100.0, 100.0, 0.0, 1199U);
    fpi_update(&f, &too_soon, true);
    TH_ASSERT(f.asserted);

    phasor_sample_t still_faulted = sample_of(450.0, 100.0, 100.0, 0.0, 1300U);
    fpi_update(&f, &still_faulted, true);
    TH_ASSERT(f.asserted);

    phasor_sample_t reset = sample_of(100.0, 100.0, 100.0, 0.0, 1200U);
    fpi_update(&f, &reset, true);
    TH_ASSERT(!f.asserted && f.asserted_at_ms == 0U);
}

static double unit_draw(uint32_t *seed)
{
    *seed = *seed * 1664525U + 1013904223U;
    return (double)(*seed >> 8) / 16777216.0;
}

static void test_trip_invariants_over_seeded_samples(void)
{
    TH_CASE("seeded samples: trips are justified by pickup and instantaneous always wins");
    relay_settings_t s = feeder_settings();
    uint32_t seed = 60255U;
    for (int i = 0; i < 2000; i++) {
        phasor_sample_t p = sample_of(unit_draw(&seed) * 7000.0, unit_draw(&seed) * 7000.0,
                                      unit_draw(&seed) * 7000.0, unit_draw(&seed) * 2000.0, (uint32_t)i);
        double iphase = fmax(p.ia_amps, fmax(p.ib_amps, p.ic_amps));
        trip_decision_t d = fault_detect_evaluate(&s, &p);

        if (iphase > s.phase_inst.pickup_amps) {
            TH_ASSERT(d.element == ELEMENT_50P);
        } else if (p.in_amps > s.ground_inst.pickup_amps) {
            TH_ASSERT(d.element == ELEMENT_50G);
        }
        TH_ASSERT(d.tripped == (iphase > s.phase_toc.pickup_amps || p.in_amps > s.ground_toc.pickup_amps));
        if (d.tripped) {
            TH_ASSERT(d.operate_time_s >= 0.0);
        }
    }
}

int main(void)
{
    test_operate_time_guards();
    test_operate_time_curves();
    test_inverse_curves_are_monotonic();
    test_evaluate_null_inputs();
    test_phase_instantaneous_uses_worst_phase();
    test_phase_instantaneous_disabled_falls_to_51p();
    test_ground_instantaneous();
    test_ground_time_overcurrent_only();
    test_faster_time_element_wins();
    test_fpi_latch();
    test_trip_invariants_over_seeded_samples();
    return th_report("fault_detect_elements");
}

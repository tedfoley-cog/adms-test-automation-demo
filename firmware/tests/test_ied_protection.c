/* Feeder IED protection: curve shapes and a steady-state soak on a freshly
 * booted relay. Fault scenarios run closed-loop on the emulated STM32F407
 * (tools/run_renode.py), not in this suite. */
#include "test_harness.h"

#include "ied_loop.h"
#include "oc_element.h"
#include "trip_matrix.h"

static void test_ieee_very_inverse_operate_time(void)
{
    TH_CASE("IEEE very inverse operate time at 5x pickup");
    toc_settings_t s = {600.0f, 2.0f, TOC_IEEE_VI, 0.0f};
    /* C37.112: t = TD * (19.61 / (M^2 - 1) + 0.491) */
    TH_ASSERT_NEAR(toc_operate_time(&s, 5.0f), 2.0 * (19.61 / 24.0 + 0.491), 1e-3);
}

static void test_iec_standard_inverse_operate_time(void)
{
    TH_CASE("IEC standard inverse operate time at 10x pickup");
    toc_settings_t s = {600.0f, 0.1f, TOC_IEC_SI, 0.0f};
    /* IEC 60255-151: t = TMS * 0.14 / (M^0.02 - 1) */
    TH_ASSERT_NEAR(toc_operate_time(&s, 10.0f), 0.1 * 0.14 / (pow(10.0, 0.02) - 1.0), 1e-3);
}

static void test_no_trip_under_load(void)
{
    TH_CASE("balanced load does not trip");
    const ied_status_t *st = loop_run(testset_find("steady_load"), 0u);
    TH_ASSERT(!st->trip1);
    TH_ASSERT(!st->tripb);
    TH_ASSERT(st->target == 0u);
    TH_ASSERT(st->ring_overruns == 0u);
}

int main(void)
{
    test_ieee_very_inverse_operate_time();
    test_iec_standard_inverse_operate_time();
    test_no_trip_under_load();
    return th_report("ied_protection");
}

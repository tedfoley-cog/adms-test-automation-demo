/* Autoreclose sequence tests: shot counting through to lockout, reclaim-time
 * reset of the shot counter, and operator lockout reset (IEEE C37.60). */
#include "test_harness.h"

#include "recloser.h"

static recloser_config_t feeder_recloser(void)
{
    recloser_config_t c;
    memset(&c, 0, sizeof(c));
    c.shots_to_lockout = 3U;
    c.dead_time_ms[0] = 500U;
    c.dead_time_ms[1] = 2000U;
    c.dead_time_ms[2] = 5000U;
    c.dead_time_ms[3] = 5000U;
    c.reclaim_time_ms = 30000U;
    c.cold_load_pickup_enabled = false;
    return c;
}

/* Drive one trip-and-reclose cycle starting from CLOSED; returns the clock
 * after the reclose. */
static uint32_t trip_and_reclose(const recloser_config_t *config,
                                 recloser_status_t *status,
                                 uint32_t now_ms)
{
    uint32_t dead_ms = config->dead_time_ms[status->shot_count];

    recloser_step(config, status, true, now_ms);      /* CLOSED -> TRIPPED */
    recloser_step(config, status, false, now_ms + 1U); /* TRIPPED -> RECLOSE_WAIT */
    recloser_step(config, status, false, now_ms + 1U + dead_ms);
    return now_ms + 1U + dead_ms;
}

static void test_init_state(void)
{
    TH_CASE("init leaves the recloser closed with no shots");
    recloser_status_t s;
    memset(&s, 0xFF, sizeof(s));

    recloser_init(&s);

    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.trip_command == false);
}

static void test_first_trip_issues_trip_command(void)
{
    TH_CASE("first trip issues a trip command and opens");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);

    TH_ASSERT(s.trip_command == true);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.state == RECLOSER_TRIPPED);
    TH_ASSERT(s.last_trip_ms == 1000U);
    TH_ASSERT(s.shot_count == 0U);
}

static void test_dead_time_must_expire_before_reclose(void)
{
    TH_CASE("reclose waits for the shot dead time");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    recloser_step(&c, &s, false, 1001U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);

    recloser_step(&c, &s, false, 1001U + 499U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.shot_count == 0U);

    recloser_step(&c, &s, false, 1001U + 500U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.close_command == true);
    TH_ASSERT(s.shot_count == 1U);
}

static void test_shot_counting_to_lockout(void)
{
    TH_CASE("three shots then a fourth trip drives lockout");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t now = 1000U;

    now = trip_and_reclose(&c, &s, now);
    TH_ASSERT(s.shot_count == 1U);
    now = trip_and_reclose(&c, &s, now);
    TH_ASSERT(s.shot_count == 2U);
    now = trip_and_reclose(&c, &s, now);
    TH_ASSERT(s.shot_count == 3U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);

    recloser_step(&c, &s, true, now + 10U);

    TH_ASSERT(s.trip_command == true);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.shot_count == 3U);
}

static void test_lockout_is_terminal_until_reset(void)
{
    TH_CASE("lockout ignores further scans");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);
    s.state = RECLOSER_LOCKOUT;
    s.shot_count = 3U;

    recloser_step(&c, &s, false, 90000U);
    recloser_step(&c, &s, true, 91000U);

    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.trip_command == false);
}

static void test_fault_during_dead_time_locks_out(void)
{
    TH_CASE("fault still present while open goes straight to lockout");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    recloser_step(&c, &s, false, 1001U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);

    recloser_step(&c, &s, true, 1200U);

    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.last_trip_ms == 1200U);
    TH_ASSERT(s.shot_count == 0U);
}

static void test_reclaim_time_resets_shot_count(void)
{
    TH_CASE("reclaim time resets the shot counter");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);

    uint32_t now = trip_and_reclose(&c, &s, 1000U);
    TH_ASSERT(s.shot_count == 1U);

    recloser_step(&c, &s, false, now + c.reclaim_time_ms - 1U);
    TH_ASSERT(s.shot_count == 1U);

    recloser_step(&c, &s, false, now + c.reclaim_time_ms);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
}

static void test_dead_time_saturates_at_last_shot(void)
{
    TH_CASE("shot index beyond the table uses the last dead time");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);
    s.state = RECLOSER_RECLOSE_WAIT;
    s.shot_count = RECLOSER_MAX_SHOTS;
    s.state_entered_ms = 0U;

    recloser_step(&c, &s, false, c.dead_time_ms[RECLOSER_MAX_SHOTS - 1] - 1U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);

    recloser_step(&c, &s, false, c.dead_time_ms[RECLOSER_MAX_SHOTS - 1]);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == (uint8_t)(RECLOSER_MAX_SHOTS + 1));
}

static void test_operator_reset_from_lockout(void)
{
    TH_CASE("operator reset closes from lockout and clears shots");
    recloser_status_t s;
    recloser_init(&s);
    s.state = RECLOSER_LOCKOUT;
    s.shot_count = 3U;

    bool accepted = recloser_reset_lockout(&s, false);

    TH_ASSERT(accepted == true);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.close_command == true);
}

static void test_operator_reset_refused(void)
{
    TH_CASE("operator reset refused while tripping or not in lockout");
    recloser_status_t s;
    recloser_init(&s);
    s.state = RECLOSER_LOCKOUT;

    TH_ASSERT(recloser_reset_lockout(&s, true) == false);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);

    s.state = RECLOSER_CLOSED;
    TH_ASSERT(recloser_reset_lockout(&s, false) == false);

    TH_ASSERT(recloser_reset_lockout(NULL, false) == false);
}

static void test_null_arguments_are_ignored(void)
{
    TH_CASE("null arguments are ignored");
    recloser_config_t c = feeder_recloser();
    recloser_status_t s;
    recloser_init(&s);
    recloser_init(NULL);

    recloser_step(NULL, &s, true, 10U);
    recloser_step(&c, NULL, true, 10U);

    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.trip_command == false);
}

static void test_zero_shot_configuration_locks_out_immediately(void)
{
    TH_CASE("zero shots configured locks out on the first trip");
    recloser_config_t c = feeder_recloser();
    c.shots_to_lockout = 0U;
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 500U);

    TH_ASSERT(s.trip_command == true);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
}

int main(void)
{
    test_init_state();
    test_first_trip_issues_trip_command();
    test_dead_time_must_expire_before_reclose();
    test_shot_counting_to_lockout();
    test_lockout_is_terminal_until_reset();
    test_fault_during_dead_time_locks_out();
    test_reclaim_time_resets_shot_count();
    test_dead_time_saturates_at_last_shot();
    test_operator_reset_from_lockout();
    test_operator_reset_refused();
    test_null_arguments_are_ignored();
    test_zero_shot_configuration_locks_out_immediately();
    return th_report("recloser");
}

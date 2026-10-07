/* Autoreclose sequence tests (IEEE C37.60 operating sequence). */
#include "test_harness.h"

#include "recloser.h"

/* Typical 3-shot sequence: 0.5 s instantaneous reclose, then 2 s, 5 s, 15 s dead times. */
static recloser_config_t feeder_config(void)
{
    recloser_config_t c;
    memset(&c, 0, sizeof(c));
    c.shots_to_lockout = 3U;
    c.dead_time_ms[0] = 500U;
    c.dead_time_ms[1] = 2000U;
    c.dead_time_ms[2] = 5000U;
    c.dead_time_ms[3] = 15000U;
    c.reclaim_time_ms = 30000U;
    return c;
}

/* Trip from CLOSED, open (TRIPPED), then wait out the dead time for the current shot. */
static uint32_t trip_and_reclose(const recloser_config_t *c, recloser_status_t *s, uint32_t now)
{
    recloser_step(c, s, true, now);
    recloser_step(c, s, false, now + 50U);
    uint32_t wait_entered = now + 50U;
    uint32_t dead = c->dead_time_ms[s->shot_count < RECLOSER_MAX_SHOTS ? s->shot_count
                                                                        : RECLOSER_MAX_SHOTS - 1];
    recloser_step(c, s, false, wait_entered + dead);
    return wait_entered + dead;
}

static void test_init_starts_closed_and_idle(void)
{
    TH_CASE("init starts closed with no commands");
    recloser_status_t s;
    memset(&s, 0xA5, sizeof(s));
    recloser_init(&s);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.state_entered_ms == 0U);
    TH_ASSERT(s.last_trip_ms == 0U);
    TH_ASSERT(!s.close_command && !s.trip_command);
}

static void test_null_arguments_are_ignored(void)
{
    TH_CASE("null arguments are ignored");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(NULL);
    recloser_init(&s);
    recloser_step(NULL, &s, true, 10U);
    TH_ASSERT(s.state == RECLOSER_CLOSED && !s.trip_command);
    recloser_step(&c, NULL, true, 10U);
    TH_ASSERT(recloser_reset_lockout(NULL, false) == false);
}

static void test_closed_without_trip_stays_closed(void)
{
    TH_CASE("closed with no trip stays closed");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    recloser_step(&c, &s, false, 1000U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(!s.trip_command && !s.close_command);
}

static void test_trip_opens_then_waits_dead_time(void)
{
    TH_CASE("trip opens, then dead time elapses before reclose");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    TH_ASSERT(s.state == RECLOSER_TRIPPED);
    TH_ASSERT(s.trip_command && !s.close_command);
    TH_ASSERT(s.last_trip_ms == 1000U);

    recloser_step(&c, &s, false, 1020U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    TH_ASSERT(!s.trip_command); /* commands are one-scan pulses */

    recloser_step(&c, &s, false, 1020U + 499U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT && !s.close_command);

    recloser_step(&c, &s, false, 1020U + 500U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.close_command);
    TH_ASSERT(s.shot_count == 1U);
    TH_ASSERT(s.state_entered_ms == 1520U);

    recloser_step(&c, &s, false, 1540U);
    TH_ASSERT(!s.close_command);
}

static void test_dead_time_follows_shot_number(void)
{
    TH_CASE("each shot uses its own dead time");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    uint32_t t = trip_and_reclose(&c, &s, 0U);
    TH_ASSERT(s.shot_count == 1U);
    recloser_step(&c, &s, true, t + 10U);
    recloser_step(&c, &s, false, t + 20U);
    recloser_step(&c, &s, false, t + 20U + 1999U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    recloser_step(&c, &s, false, t + 20U + 2000U);
    TH_ASSERT(s.state == RECLOSER_CLOSED && s.shot_count == 2U);
}

static void test_permanent_fault_locks_out_after_configured_shots(void)
{
    TH_CASE("permanent fault locks out after shots_to_lockout recloses");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    uint32_t t = 0U;
    for (int shot = 0; shot < 3; ++shot) {
        t = trip_and_reclose(&c, &s, t + 100U);
        TH_ASSERT(s.state == RECLOSER_CLOSED);
    }
    TH_ASSERT(s.shot_count == 3U);

    recloser_step(&c, &s, true, t + 100U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.trip_command && !s.close_command);
    TH_ASSERT(s.last_trip_ms == t + 100U);

    /* Lockout is terminal for the automatic sequence. */
    recloser_step(&c, &s, false, t + 100000U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT && !s.close_command && !s.trip_command);
    recloser_step(&c, &s, true, t + 200000U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT && !s.trip_command);
}

static void test_zero_shots_locks_out_on_first_trip(void)
{
    TH_CASE("reclosing disabled: first trip goes straight to lockout");
    recloser_config_t c = feeder_config();
    c.shots_to_lockout = 0U;
    recloser_status_t s;
    recloser_init(&s);
    recloser_step(&c, &s, true, 10U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT && s.trip_command);
}

static void test_trip_during_dead_time_locks_out(void)
{
    TH_CASE("trip asserted while open in dead time locks out");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    recloser_step(&c, &s, true, 0U);
    recloser_step(&c, &s, false, 10U);
    recloser_step(&c, &s, true, 200U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.last_trip_ms == 200U);
    TH_ASSERT(!s.close_command && !s.trip_command);
    TH_ASSERT(s.shot_count == 0U);
}

static void test_reclaim_resets_shot_counter(void)
{
    TH_CASE("healthy for reclaim time resets the shot counter");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    uint32_t closed_at = trip_and_reclose(&c, &s, 0U);
    TH_ASSERT(s.shot_count == 1U);
    recloser_step(&c, &s, false, closed_at + 29999U);
    TH_ASSERT(s.shot_count == 1U);
    recloser_step(&c, &s, false, closed_at + 30000U);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);

    /* A new fault after reclaim gets the full sequence again (shot 0 dead time). */
    recloser_step(&c, &s, true, closed_at + 40000U);
    TH_ASSERT(s.state == RECLOSER_TRIPPED);
}

static void test_timers_survive_scan_clock_wraparound(void)
{
    TH_CASE("dead time and reclaim are correct across uint32 clock wrap");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t near_wrap = 0xFFFFFF00U;
    recloser_step(&c, &s, true, near_wrap);
    recloser_step(&c, &s, false, near_wrap + 10U);
    recloser_step(&c, &s, false, near_wrap + 10U + 499U); /* wraps past zero */
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    recloser_step(&c, &s, false, near_wrap + 10U + 500U);
    TH_ASSERT(s.state == RECLOSER_CLOSED && s.shot_count == 1U);
}

static void test_shots_beyond_table_reuse_last_dead_time(void)
{
    TH_CASE("shots beyond the dead-time table reuse the last entry");
    recloser_config_t c = feeder_config();
    c.shots_to_lockout = 6U;
    recloser_status_t s;
    recloser_init(&s);
    uint32_t t = 0U;
    for (int shot = 0; shot < RECLOSER_MAX_SHOTS; ++shot) {
        t = trip_and_reclose(&c, &s, t + 100U);
    }
    TH_ASSERT(s.shot_count == RECLOSER_MAX_SHOTS);

    recloser_step(&c, &s, true, t + 100U);
    recloser_step(&c, &s, false, t + 150U);
    recloser_step(&c, &s, false, t + 150U + 14999U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    recloser_step(&c, &s, false, t + 150U + 15000U);
    TH_ASSERT(s.state == RECLOSER_CLOSED && s.shot_count == RECLOSER_MAX_SHOTS + 1);
}

static void test_lockout_reset_rules(void)
{
    TH_CASE("lockout reset is refused unless locked out with trip clear");
    recloser_config_t c = feeder_config();
    c.shots_to_lockout = 0U;
    recloser_status_t s;
    recloser_init(&s);

    TH_ASSERT(recloser_reset_lockout(&s, false) == false); /* not locked out */
    TH_ASSERT(s.state == RECLOSER_CLOSED && !s.close_command);

    recloser_step(&c, &s, true, 10U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(recloser_reset_lockout(&s, true) == false); /* fault still asserted */
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);

    TH_ASSERT(recloser_reset_lockout(&s, false) == true);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.close_command);
}

static void test_unknown_state_is_inert(void)
{
    TH_CASE("corrupt state value issues no commands");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    s.state = (recloser_state_t)42;
    recloser_step(&c, &s, true, 10U);
    TH_ASSERT(!s.trip_command && !s.close_command);
    TH_ASSERT(s.state == (recloser_state_t)42);
}

int main(void)
{
    test_init_starts_closed_and_idle();
    test_null_arguments_are_ignored();
    test_closed_without_trip_stays_closed();
    test_trip_opens_then_waits_dead_time();
    test_dead_time_follows_shot_number();
    test_permanent_fault_locks_out_after_configured_shots();
    test_zero_shots_locks_out_on_first_trip();
    test_trip_during_dead_time_locks_out();
    test_reclaim_resets_shot_counter();
    test_timers_survive_scan_clock_wraparound();
    test_shots_beyond_table_reuse_last_dead_time();
    test_lockout_reset_rules();
    test_unknown_state_is_inert();
    return th_report("recloser");
}

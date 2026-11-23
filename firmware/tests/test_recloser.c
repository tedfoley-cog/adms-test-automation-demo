#include "test_harness.h"

#include "recloser.h"

static const recloser_config_t config = {
    .shots_to_lockout = 2U,
    .dead_time_ms = {10U, 20U, 30U, 40U},
    .reclaim_time_ms = 100U,
};

static void assert_status(recloser_status_t s, recloser_state_t state,
                          unsigned shots, uint32_t entered_ms, uint32_t trip_ms,
                          bool close, bool trip)
{
    TH_ASSERT(s.state == state);
    TH_ASSERT(s.shot_count == shots);
    TH_ASSERT(s.state_entered_ms == entered_ms);
    TH_ASSERT(s.last_trip_ms == trip_ms);
    TH_ASSERT(s.close_command == close);
    TH_ASSERT(s.trip_command == trip);
}

static void test_shot_sequence(void)
{
    TH_CASE("two timed reclose attempts, then lockout and guarded manual reset");
    recloser_status_t s;
    recloser_init(&s);
    assert_status(s, RECLOSER_CLOSED, 0U, 0U, 0U, false, false);
    TH_ASSERT(!recloser_reset_lockout(&s, false));

    recloser_step(&config, &s, true, 10U);
    assert_status(s, RECLOSER_TRIPPED, 0U, 10U, 10U, false, true);
    recloser_step(&config, &s, false, 11U);
    assert_status(s, RECLOSER_RECLOSE_WAIT, 0U, 11U, 10U, false, false);
    recloser_step(&config, &s, false, 20U);
    assert_status(s, RECLOSER_RECLOSE_WAIT, 0U, 11U, 10U, false, false);
    recloser_step(&config, &s, false, 21U);
    assert_status(s, RECLOSER_CLOSED, 1U, 21U, 10U, true, false);
    recloser_step(&config, &s, false, 22U);
    assert_status(s, RECLOSER_CLOSED, 1U, 21U, 10U, false, false);

    recloser_step(&config, &s, true, 30U);
    assert_status(s, RECLOSER_TRIPPED, 1U, 30U, 30U, false, true);
    recloser_step(&config, &s, false, 31U);
    recloser_step(&config, &s, false, 50U);
    assert_status(s, RECLOSER_RECLOSE_WAIT, 1U, 31U, 30U, false, false);
    recloser_step(&config, &s, false, 51U);
    assert_status(s, RECLOSER_CLOSED, 2U, 51U, 30U, true, false);

    recloser_step(&config, &s, true, 60U);
    assert_status(s, RECLOSER_LOCKOUT, 2U, 60U, 60U, false, true);
    TH_ASSERT(!recloser_reset_lockout(&s, true));
    recloser_step(&config, &s, false, 500U);
    assert_status(s, RECLOSER_LOCKOUT, 2U, 60U, 60U, false, false);
    TH_ASSERT(recloser_reset_lockout(&s, false));
    assert_status(s, RECLOSER_CLOSED, 0U, 60U, 60U, true, false);
}

static void test_trip_during_dead_time(void)
{
    TH_CASE("trip takes priority over closing at the dead-time boundary");
    recloser_status_t s;
    recloser_init(&s);
    recloser_step(&config, &s, true, 10U);
    recloser_step(&config, &s, false, 11U);
    recloser_step(&config, &s, true, 21U);
    assert_status(s, RECLOSER_LOCKOUT, 0U, 21U, 21U, false, false);
}

static void test_reclaim_time(void)
{
    TH_CASE("shot count reclaims at exactly the full healthy interval");
    recloser_status_t s;
    recloser_init(&s);
    recloser_step(&config, &s, true, 10U);
    recloser_step(&config, &s, false, 11U);
    recloser_step(&config, &s, false, 21U);
    recloser_step(&config, &s, false, 120U);
    assert_status(s, RECLOSER_CLOSED, 1U, 21U, 10U, false, false);
    recloser_step(&config, &s, false, 121U);
    assert_status(s, RECLOSER_CLOSED, 0U, 21U, 10U, false, false);
}

static void test_zero_shot_lockout(void)
{
    TH_CASE("zero configured shots lock out on the first trip");
    recloser_config_t no_retry = config;
    no_retry.shots_to_lockout = 0U;
    recloser_status_t s;
    recloser_init(&s);
    recloser_step(&no_retry, &s, true, 10U);
    assert_status(s, RECLOSER_LOCKOUT, 0U, 10U, 10U, false, true);

    /* Suspected defect: reset before another scan leaves both commands set. */
    TH_ASSERT(recloser_reset_lockout(&s, false));
    assert_status(s, RECLOSER_CLOSED, 0U, 10U, 10U, true, true);
}

static void test_extended_shot_count_and_missing_inputs(void)
{
    TH_CASE("shot counts beyond the dead-time table reuse its last entry");
    recloser_config_t extended = config;
    extended.shots_to_lockout = RECLOSER_MAX_SHOTS + 1U;
    recloser_status_t s = {
        .state = RECLOSER_RECLOSE_WAIT,
        .shot_count = RECLOSER_MAX_SHOTS,
        .state_entered_ms = 20U,
        .last_trip_ms = 19U,
    };
    recloser_step(&extended, &s, false, 59U);
    assert_status(s, RECLOSER_RECLOSE_WAIT, RECLOSER_MAX_SHOTS, 20U, 19U, false, false);
    recloser_step(&extended, &s, false, 60U);
    assert_status(s, RECLOSER_CLOSED, RECLOSER_MAX_SHOTS + 1U, 60U, 19U, true, false);

    TH_CASE("missing configuration or status is ignored");
    recloser_init(NULL);
    recloser_step(&config, NULL, true, 61U);
    recloser_step(NULL, &s, true, 61U);
    TH_ASSERT(!recloser_reset_lockout(NULL, false));
    assert_status(s, RECLOSER_CLOSED, RECLOSER_MAX_SHOTS + 1U, 60U, 19U, true, false);
}

int main(void)
{
    test_shot_sequence();
    test_trip_during_dead_time();
    test_reclaim_time();
    test_zero_shot_lockout();
    test_extended_shot_count_and_missing_inputs();
    return th_report("recloser");
}

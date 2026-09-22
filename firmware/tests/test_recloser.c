/* Autoreclose sequence tests: shot counting through to lockout, the reclaim
 * timer, the reclose-onto-fault path and the operator lockout reset. */
#include "test_harness.h"

#include "recloser.h"

static recloser_config_t feeder_config(void)
{
    recloser_config_t c;
    memset(&c, 0, sizeof(c));
    c.shots_to_lockout = 2U;
    c.dead_time_ms[0] = 500U;
    c.dead_time_ms[1] = 1000U;
    c.dead_time_ms[2] = 2000U;
    c.dead_time_ms[3] = 2000U;
    c.reclaim_time_ms = 10000U;
    c.cold_load_pickup_enabled = false;
    return c;
}

/* Trip, pass through TRIPPED into RECLOSE_WAIT, then let the dead time expire. */
static void run_one_shot(const recloser_config_t *config,
                         recloser_status_t *status,
                         uint32_t trip_ms,
                         uint32_t dead_time_ms)
{
    recloser_step(config, status, true, trip_ms);
    recloser_step(config, status, false, trip_ms + 50U);
    recloser_step(config, status, false, trip_ms + 50U + dead_time_ms);
}

static void test_init_starts_closed(void)
{
    TH_CASE("init starts closed with no shots");
    recloser_status_t s;
    recloser_init(&s);

    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.trip_command == false);
}

static void test_first_trip_opens_and_waits(void)
{
    TH_CASE("first trip opens then enters reclose wait");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    TH_ASSERT(s.trip_command == true);
    TH_ASSERT(s.state == RECLOSER_TRIPPED);
    TH_ASSERT(s.last_trip_ms == 1000U);
    TH_ASSERT(s.shot_count == 0U);

    recloser_step(&c, &s, false, 1050U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    TH_ASSERT(s.trip_command == false);
}

static void test_dead_time_must_expire_before_reclose(void)
{
    TH_CASE("reclose waits for the per-shot dead time");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    recloser_step(&c, &s, false, 1050U);

    recloser_step(&c, &s, false, 1500U); /* 450 ms into a 500 ms dead time */
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.shot_count == 0U);

    recloser_step(&c, &s, false, 1550U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.close_command == true);
    TH_ASSERT(s.shot_count == 1U);
}

static void test_shot_count_reaches_lockout(void)
{
    TH_CASE("shot count reaches lockout on the configured attempt");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    run_one_shot(&c, &s, 1000U, c.dead_time_ms[0]);
    TH_ASSERT(s.shot_count == 1U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);

    run_one_shot(&c, &s, 3000U, c.dead_time_ms[1]);
    TH_ASSERT(s.shot_count == 2U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);

    /* Third fault: the shot budget is spent, so the trip goes straight to lockout. */
    recloser_step(&c, &s, true, 6000U);
    TH_ASSERT(s.trip_command == true);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.last_trip_ms == 6000U);
}

static void test_lockout_ignores_further_scans(void)
{
    TH_CASE("lockout is terminal without an operator reset");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    run_one_shot(&c, &s, 1000U, c.dead_time_ms[0]);
    run_one_shot(&c, &s, 3000U, c.dead_time_ms[1]);
    recloser_step(&c, &s, true, 6000U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);

    recloser_step(&c, &s, false, 60000U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.close_command == false);
    TH_ASSERT(s.trip_command == false);
    TH_ASSERT(s.shot_count == 2U);
}

static void test_reclose_onto_fault_locks_out(void)
{
    TH_CASE("fault still present during the dead time locks out");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    recloser_step(&c, &s, false, 1050U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);

    recloser_step(&c, &s, true, 1200U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.last_trip_ms == 1200U);
    TH_ASSERT(s.shot_count == 0U);
}

static void test_reclaim_timer_clears_shot_count(void)
{
    TH_CASE("reclaim timer clears the shot count after a healthy interval");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    run_one_shot(&c, &s, 1000U, c.dead_time_ms[0]);
    TH_ASSERT(s.shot_count == 1U);

    recloser_step(&c, &s, false, 1550U + 9000U); /* still inside the reclaim time */
    TH_ASSERT(s.shot_count == 1U);

    recloser_step(&c, &s, false, 1550U + c.reclaim_time_ms);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
}

static void test_dead_time_saturates_beyond_the_shot_table(void)
{
    TH_CASE("shots past the table reuse the last dead time");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    uint32_t now = 1000U;
    int shot;

    c.shots_to_lockout = 6U; /* more shots than RECLOSER_MAX_SHOTS entries */
    recloser_init(&s);

    for (shot = 0; shot < RECLOSER_MAX_SHOTS; shot++) {
        run_one_shot(&c, &s, now, c.dead_time_ms[shot]);
        now += 10000U;
    }
    TH_ASSERT(s.shot_count == RECLOSER_MAX_SHOTS);

    /* Shot index 4 has no table entry; the last configured dead time applies. */
    recloser_step(&c, &s, true, now);
    recloser_step(&c, &s, false, now + 50U);
    recloser_step(&c, &s, false, now + 50U + c.dead_time_ms[RECLOSER_MAX_SHOTS - 1] - 1U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);

    recloser_step(&c, &s, false, now + 50U + c.dead_time_ms[RECLOSER_MAX_SHOTS - 1]);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == RECLOSER_MAX_SHOTS + 1);
}

static void test_operator_reset_of_lockout(void)
{
    TH_CASE("operator reset clears lockout only with the trip removed");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    run_one_shot(&c, &s, 1000U, c.dead_time_ms[0]);
    run_one_shot(&c, &s, 3000U, c.dead_time_ms[1]);
    recloser_step(&c, &s, true, 6000U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);

    TH_ASSERT(recloser_reset_lockout(&s, true) == false);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);

    TH_ASSERT(recloser_reset_lockout(&s, false) == true);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U);
    TH_ASSERT(s.close_command == true);

    /* A second reset is refused: the device is no longer locked out. */
    TH_ASSERT(recloser_reset_lockout(&s, false) == false);
}

static void test_null_arguments_are_ignored(void)
{
    TH_CASE("null arguments are ignored");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    recloser_init(NULL);
    recloser_step(NULL, &s, true, 1000U);
    recloser_step(&c, NULL, true, 1000U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(recloser_reset_lockout(NULL, false) == false);
}

int main(void)
{
    test_init_starts_closed();
    test_first_trip_opens_and_waits();
    test_dead_time_must_expire_before_reclose();
    test_shot_count_reaches_lockout();
    test_lockout_ignores_further_scans();
    test_reclose_onto_fault_locks_out();
    test_reclaim_timer_clears_shot_count();
    test_dead_time_saturates_beyond_the_shot_table();
    test_operator_reset_of_lockout();
    test_null_arguments_are_ignored();
    return th_report("recloser");
}

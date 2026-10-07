/* Autoreclose sequence tests (IEEE C37.60). Pins the current state machine,
 * including the behaviours flagged in the comments, before any change to it. */
#include "test_harness.h"

#include <stdint.h>

#include "recloser.h"

static recloser_config_t feeder_config(void)
{
    recloser_config_t c;
    memset(&c, 0, sizeof(c));
    c.shots_to_lockout = 3U;
    c.dead_time_ms[0] = 500U;
    c.dead_time_ms[1] = 2000U;
    c.dead_time_ms[2] = 5000U;
    c.dead_time_ms[3] = 7000U;
    c.reclaim_time_ms = 10000U;
    return c;
}

/* Trip at `t`, open on the next scan, and return the time the reclose wait began. */
static uint32_t trip_and_open(const recloser_config_t *c, recloser_status_t *s, uint32_t t)
{
    recloser_step(c, s, true, t);
    recloser_step(c, s, false, t + 10U);
    return t + 10U;
}

static void test_init_and_null_safety(void)
{
    TH_CASE("init clears status and NULL arguments are ignored");
    recloser_status_t s;
    memset(&s, 0xAB, sizeof(s));
    recloser_init(&s);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.shot_count == 0U && s.state_entered_ms == 0U && s.last_trip_ms == 0U);
    TH_ASSERT(!s.close_command && !s.trip_command);

    recloser_config_t c = feeder_config();
    recloser_init(NULL);
    recloser_step(NULL, &s, true, 5U);
    recloser_step(&c, NULL, true, 5U);
    TH_ASSERT(s.state == RECLOSER_CLOSED && !s.trip_command);
    TH_ASSERT(recloser_reset_lockout(NULL, false) == false);
}

static void test_healthy_feeder_stays_closed(void)
{
    TH_CASE("no trip keeps the recloser closed with no commands");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    for (uint32_t t = 0U; t < 50000U; t += 1000U) {
        recloser_step(&c, &s, false, t);
        TH_ASSERT(s.state == RECLOSER_CLOSED && !s.trip_command && !s.close_command);
    }
}

static void test_trip_opens_then_waits(void)
{
    TH_CASE("trip issues one trip command, then the next scan enters reclose wait");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 1000U);
    TH_ASSERT(s.state == RECLOSER_TRIPPED);
    TH_ASSERT(s.trip_command && !s.close_command);
    TH_ASSERT(s.last_trip_ms == 1000U && s.state_entered_ms == 1000U);

    recloser_step(&c, &s, false, 1010U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    TH_ASSERT(!s.trip_command && !s.close_command);
    TH_ASSERT(s.state_entered_ms == 1010U);
}

static void test_dead_time_boundary(void)
{
    TH_CASE("first reclose fires exactly when dead time 0 has elapsed");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t wait = trip_and_open(&c, &s, 1000U);

    recloser_step(&c, &s, false, wait + 499U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT && !s.close_command);

    recloser_step(&c, &s, false, wait + 500U);
    TH_ASSERT(s.state == RECLOSER_CLOSED);
    TH_ASSERT(s.close_command && s.shot_count == 1U);

    recloser_step(&c, &s, false, wait + 510U);
    TH_ASSERT(!s.close_command);
}

static void test_per_shot_dead_times_and_lockout(void)
{
    TH_CASE("each shot uses its own dead time; the trip after the last shot locks out");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t t = 1000U;

    for (uint8_t shot = 0U; shot < c.shots_to_lockout; shot++) {
        uint32_t wait = trip_and_open(&c, &s, t);
        recloser_step(&c, &s, false, wait + c.dead_time_ms[shot] - 1U);
        TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
        recloser_step(&c, &s, false, wait + c.dead_time_ms[shot]);
        TH_ASSERT(s.state == RECLOSER_CLOSED && s.shot_count == shot + 1U);
        t = wait + c.dead_time_ms[shot] + 100U;
    }

    recloser_step(&c, &s, true, t);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.trip_command && s.last_trip_ms == t);
}

static void test_reclaim_resets_shot_count(void)
{
    TH_CASE("shot count resets only after the full reclaim time healthy");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t wait = trip_and_open(&c, &s, 1000U);
    recloser_step(&c, &s, false, wait + 500U);
    uint32_t closed_at = wait + 500U;
    TH_ASSERT(s.shot_count == 1U);

    recloser_step(&c, &s, false, closed_at + c.reclaim_time_ms - 1U);
    TH_ASSERT(s.shot_count == 1U);
    recloser_step(&c, &s, false, closed_at + c.reclaim_time_ms);
    TH_ASSERT(s.shot_count == 0U && s.state == RECLOSER_CLOSED);
}

static void test_trip_during_dead_time_locks_out(void)
{
    /* Pinned: a trip while open goes straight to lockout even with shots remaining. */
    TH_CASE("trip asserted during the dead time locks out immediately");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t wait = trip_and_open(&c, &s, 1000U);

    recloser_step(&c, &s, true, wait + 100U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(s.shot_count == 0U && s.last_trip_ms == wait + 100U);
    TH_ASSERT(!s.trip_command && !s.close_command);
}

static void test_lockout_is_absorbing_until_reset(void)
{
    TH_CASE("lockout ignores trips and time; reset is refused while trip is asserted");
    recloser_config_t c = feeder_config();
    c.shots_to_lockout = 0U;
    recloser_status_t s;
    recloser_init(&s);

    recloser_step(&c, &s, true, 100U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT && s.trip_command);
    recloser_step(&c, &s, true, 200U);
    recloser_step(&c, &s, false, 900000U);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT && !s.trip_command && !s.close_command);

    TH_ASSERT(recloser_reset_lockout(&s, true) == false);
    TH_ASSERT(s.state == RECLOSER_LOCKOUT);
    TH_ASSERT(recloser_reset_lockout(&s, false) == true);
    TH_ASSERT(s.state == RECLOSER_CLOSED && s.shot_count == 0U && s.close_command);

    TH_ASSERT(recloser_reset_lockout(&s, false) == false);
}

static void test_shots_beyond_table_reuse_last_dead_time(void)
{
    TH_CASE("shots past RECLOSER_MAX_SHOTS reuse the last configured dead time");
    recloser_config_t c = feeder_config();
    c.shots_to_lockout = 6U;
    recloser_status_t s;
    recloser_init(&s);
    uint32_t t = 0U;
    for (uint8_t shot = 0U; shot < 6U; shot++) {
        uint32_t dead = shot < RECLOSER_MAX_SHOTS ? c.dead_time_ms[shot] : c.dead_time_ms[3];
        uint32_t wait = trip_and_open(&c, &s, t);
        recloser_step(&c, &s, false, wait + dead - 1U);
        TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
        recloser_step(&c, &s, false, wait + dead);
        TH_ASSERT(s.state == RECLOSER_CLOSED);
        t = wait + dead + 1U;
    }
    TH_ASSERT(s.shot_count == 6U);
}

static void test_scan_clock_wraparound(void)
{
    TH_CASE("dead time is measured correctly across a uint32 clock wrap");
    recloser_config_t c = feeder_config();
    recloser_status_t s;
    recloser_init(&s);
    uint32_t wait = trip_and_open(&c, &s, UINT32_MAX - 300U);

    recloser_step(&c, &s, false, wait + 499U);
    TH_ASSERT(s.state == RECLOSER_RECLOSE_WAIT);
    recloser_step(&c, &s, false, wait + 500U);
    TH_ASSERT(s.state == RECLOSER_CLOSED && s.close_command);
}

static uint32_t lcg(uint32_t *seed)
{
    *seed = *seed * 1664525U + 1013904223U;
    return *seed >> 8;
}

static void test_invariants_over_seeded_sequences(void)
{
    TH_CASE("seeded scan sequences never exceed the shot budget or issue both commands");
    for (uint32_t run = 0U; run < 500U; run++) {
        uint32_t seed = run * 2654435761U + 1U;
        recloser_config_t c = feeder_config();
        c.shots_to_lockout = (uint8_t)(lcg(&seed) % 6U);
        for (int i = 0; i < RECLOSER_MAX_SHOTS; i++) {
            c.dead_time_ms[i] = 100U + lcg(&seed) % 3000U;
        }
        c.reclaim_time_ms = 1000U + lcg(&seed) % 20000U;

        recloser_status_t s;
        recloser_init(&s);
        uint32_t now = lcg(&seed);
        unsigned closes_since_reset = 0U;
        for (int scan = 0; scan < 400; scan++) {
            now += 10U + lcg(&seed) % 400U;
            recloser_state_t before = s.state;
            uint8_t shots_before = s.shot_count;
            recloser_step(&c, &s, lcg(&seed) % 7U == 0U, now);

            TH_ASSERT(!(s.trip_command && s.close_command));
            TH_ASSERT(!s.close_command || (before == RECLOSER_RECLOSE_WAIT && s.state == RECLOSER_CLOSED));
            TH_ASSERT(!s.trip_command || before == RECLOSER_CLOSED);
            TH_ASSERT(s.shot_count <= c.shots_to_lockout);
            if (before == RECLOSER_LOCKOUT) {
                TH_ASSERT(s.state == RECLOSER_LOCKOUT && !s.close_command);
            }
            if (s.shot_count < shots_before) {
                closes_since_reset = 0U;
            }
            if (s.close_command) {
                closes_since_reset++;
            }
            TH_ASSERT(closes_since_reset <= c.shots_to_lockout);
        }
    }
}

int main(void)
{
    test_init_and_null_safety();
    test_healthy_feeder_stays_closed();
    test_trip_opens_then_waits();
    test_dead_time_boundary();
    test_per_shot_dead_times_and_lockout();
    test_reclaim_resets_shot_count();
    test_trip_during_dead_time_locks_out();
    test_lockout_is_absorbing_until_reset();
    test_shots_beyond_table_reuse_last_dead_time();
    test_scan_clock_wraparound();
    test_invariants_over_seeded_sequences();
    return th_report("recloser");
}

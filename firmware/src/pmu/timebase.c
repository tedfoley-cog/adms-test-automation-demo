#include "ied_config.h"

#include "timebase.h"

#include <stddef.h>

void timebase_init(timebase_t *tb, uint32_t soc_at_boot)
{
    tb->uptime_s = 0u;
    tb->sample_in_second = 0u;
    tb->tick = 0u;
    tb->soc = soc_at_boot;
    tb->pps_locked = false;
    tb->pps_good_count = 0u;
    tb->seconds_since_pps = 0u;
    tb->pps_rejected = 0u;
    tb->slips = 0u;
    tb->reload_q16 = TIMEBASE_NOMINAL_RELOAD_Q16;
    tb->reload_frac_acc = 0u;
    tb->freq_error_ppb = 0;
}

uint32_t timebase_on_sample(timebase_t *tb)
{
    tb->tick++;
    tb->sample_in_second++;
    if (tb->sample_in_second >= IED_SAMPLE_RATE_HZ) {
        /* Free-running rollover; a PPS edge re-aligns this when present. */
        tb->sample_in_second = 0u;
        tb->uptime_s++;
        tb->soc++;
        timebase_holdover_tick(tb);
    }

    tb->reload_frac_acc += tb->reload_q16 & 0xFFFFu;
    uint32_t reload = tb->reload_q16 >> 16;
    if (tb->reload_frac_acc >= 0x10000u) {
        tb->reload_frac_acc -= 0x10000u;
        reload++;
    }
    return reload;
}

void timebase_on_pps(timebase_t *tb, uint32_t counts_since_last_pps)
{
    int32_t error = (int32_t)(counts_since_last_pps - TIMEBASE_TIMER_HZ);
    int32_t mag = error < 0 ? -error : error;

    if (mag > (int32_t)TIMEBASE_PPS_TOLERANCE_COUNTS) {
        /* Glitch or a missing edge: ignore it and stay on the current trim. */
        tb->pps_rejected++;
        tb->pps_good_count = 0u;
        return;
    }

    /* Oscillator error in ppb: counts error over 84e6 counts. */
    tb->freq_error_ppb = (int32_t)(((int64_t)error * 1000000000LL) / (int64_t)TIMEBASE_TIMER_HZ);

    /* Frequency correction: reload = measured counts per second / 1920. */
    tb->reload_q16 = (uint32_t)(((uint64_t)counts_since_last_pps << 16) / IED_SAMPLE_RATE_HZ);

    /* Phase alignment: sample 0 belongs to the PPS edge. */
    if (tb->sample_in_second != 0u) {
        if (tb->sample_in_second > IED_SAMPLE_RATE_HZ / 2u) {
            tb->uptime_s++;
            tb->soc++;
        }
        tb->slips++;
        tb->sample_in_second = 0u;
    }

    tb->seconds_since_pps = 0u;
    if (tb->pps_good_count < TIMEBASE_PPS_LOCK_COUNT) {
        tb->pps_good_count++;
    }
    tb->pps_locked = tb->pps_good_count >= TIMEBASE_PPS_LOCK_COUNT;
}

void timebase_holdover_tick(timebase_t *tb)
{
    if (tb->seconds_since_pps < UINT32_MAX) {
        tb->seconds_since_pps++;
    }
    if (tb->seconds_since_pps > 1u) {
        tb->pps_locked = false;
        tb->pps_good_count = 0u;
    }
}

float timebase_seconds(uint32_t uptime_s, uint32_t sample_in_second)
{
    return (float)uptime_s + (float)sample_in_second * IED_SAMPLE_PERIOD_S;
}

float timebase_now_s(const timebase_t *tb)
{
    return timebase_seconds(tb->uptime_s, tb->sample_in_second);
}

uint32_t timebase_fracsec(uint32_t sample_in_second, uint32_t time_base)
{
    return (uint32_t)(((uint64_t)sample_in_second * time_base) / IED_SAMPLE_RATE_HZ);
}

/* Holdover error estimate: a TCXO held at its last trim drifts ~1 us/s. */
static uint32_t holdover_error_ns(const timebase_t *tb)
{
    uint64_t ns = (uint64_t)tb->seconds_since_pps * 1000u;
    return ns > UINT32_MAX ? UINT32_MAX : (uint32_t)ns;
}

uint8_t timebase_time_quality(const timebase_t *tb)
{
    if (tb->pps_locked) {
        return 0x0u;
    }
    if (tb->pps_good_count == 0u && tb->seconds_since_pps == 0u) {
        return 0xFu; /* never locked: clock failure, time not reliable */
    }
    uint32_t ns = holdover_error_ns(tb);
    if (ns < 1000u) {
        return 0x4u;
    }
    if (ns < 10000u) {
        return 0x5u;
    }
    if (ns < 100000u) {
        return 0x6u;
    }
    if (ns < 1000000u) {
        return 0x7u;
    }
    if (ns < 10000000u) {
        return 0x8u;
    }
    return 0xBu;
}

uint16_t timebase_stat_bits(const timebase_t *tb)
{
    uint16_t unlocked;
    if (tb->pps_locked || tb->seconds_since_pps < 10u) {
        unlocked = 0u;
    } else if (tb->seconds_since_pps < 100u) {
        unlocked = 1u;
    } else if (tb->seconds_since_pps < 1000u) {
        unlocked = 2u;
    } else {
        unlocked = 3u;
    }

    uint16_t pmu_tq;
    if (tb->pps_locked) {
        pmu_tq = 2u; /* < 1 us */
    } else {
        uint32_t ns = holdover_error_ns(tb);
        if (ns < 10000u) {
            pmu_tq = 3u;
        } else if (ns < 100000u) {
            pmu_tq = 4u;
        } else if (ns < 1000000u) {
            pmu_tq = 5u;
        } else if (ns < 10000000u) {
            pmu_tq = 6u;
        } else {
            pmu_tq = 7u;
        }
    }
    return (uint16_t)((pmu_tq << 6) | (unlocked << 4));
}

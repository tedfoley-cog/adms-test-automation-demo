/* Relay timebase: sample counter, UTC alignment and PPS discipline.
 *
 * The sample timer free-runs from the 84 MHz APB1 timer clock. The station
 * clock's 1PPS edge is captured on a second timer channel; at each edge the
 * discipline loop compares the timer counts elapsed over the last second with
 * the nominal 84 000 000 and trims the fractional reload so 1920 samples land
 * exactly inside each UTC second. Sample 0 of every second is aligned to the
 * PPS edge, which is what lets synchrophasors from different substations be
 * compared directly.
 *
 * If PPS disappears the timebase keeps running in holdover on the last trim
 * and degrades the C37.118 time-quality fields as the estimated error grows.
 */
#ifndef TIMEBASE_H
#define TIMEBASE_H

#include <stdbool.h>
#include <stdint.h>

#define TIMEBASE_TIMER_HZ        84000000u
#define TIMEBASE_NOMINAL_RELOAD_Q16 \
    ((uint32_t)(((uint64_t)TIMEBASE_TIMER_HZ << 16) / IED_SAMPLE_RATE_HZ))
#define TIMEBASE_PPS_LOCK_COUNT  3u   /* consecutive good PPS edges to declare lock */
#define TIMEBASE_PPS_TOLERANCE_COUNTS 840u  /* +/-10 ppm window on the PPS interval */

typedef struct {
    uint32_t uptime_s;            /* whole seconds since power-up */
    uint32_t sample_in_second;    /* 0..IED_SAMPLE_RATE_HZ-1, aligned to PPS */
    uint32_t tick;                /* free-running sample counter */
    uint32_t soc;                 /* UTC second-of-century (C37.118, 1970 epoch) */

    bool pps_locked;
    uint32_t pps_good_count;
    uint32_t seconds_since_pps;
    uint32_t pps_rejected;
    uint32_t slips;               /* PPS arrived with the sample count off by >= 1 */

    uint32_t reload_q16;          /* timer counts per sample, Q16.16 */
    uint32_t reload_frac_acc;     /* fractional-reload accumulator */
    int32_t freq_error_ppb;       /* last measured oscillator error */
} timebase_t;

void timebase_init(timebase_t *tb, uint32_t soc_at_boot);

/* Called from the sample ISR. Returns the timer reload to program for the
 * next sample period (integer counts, dithered to the Q16 average). */
uint32_t timebase_on_sample(timebase_t *tb);

/* Called on the PPS capture interrupt with the number of sample-timer counts
 * elapsed since the previous PPS edge and the sample index at which the edge
 * landed. */
void timebase_on_pps(timebase_t *tb, uint32_t counts_since_last_pps);

/* Called once per second while no PPS has been seen. */
void timebase_holdover_tick(timebase_t *tb);

/* Relay time in seconds since power-up, for setting-sheet timers. */
float timebase_now_s(const timebase_t *tb);
float timebase_seconds(uint32_t uptime_s, uint32_t sample_in_second);

/* C37.118 FRACSEC count for a sample index within the current second. */
uint32_t timebase_fracsec(uint32_t sample_in_second, uint32_t time_base);

/* C37.118 time-quality nibble (FRACSEC bits 27..24). */
uint8_t timebase_time_quality(const timebase_t *tb);

/* C37.118 STAT bits 5..4 (unlocked time) and 8..6 (PMU time quality). */
uint16_t timebase_stat_bits(const timebase_t *tb);

#endif /* TIMEBASE_H */

/* Per-channel history of scaled samples, shared by the protection DFT
 * (one cycle, 32 samples) and the synchrophasor estimator (63-tap window).
 *
 * The buffer is 128 samples deep: the PMU pass reads a 63-sample window while
 * the protection task may preempt it and keep appending, so the extra 65
 * samples (34 ms) are the guaranteed slack before a window sample can be
 * overwritten. Indexing is by free-running sample tick.
 */
#ifndef SAMPLE_HISTORY_H
#define SAMPLE_HISTORY_H

#include "ied_config.h"

#include <stdint.h>

#define SAMPLE_HISTORY_LEN 128u

typedef struct {
    float x[IED_NUM_CHANNELS][SAMPLE_HISTORY_LEN];
    uint32_t sis[SAMPLE_HISTORY_LEN];  /* sample-in-second at each slot */
    uint32_t newest_tick;
    uint32_t count;                    /* saturates at SAMPLE_HISTORY_LEN */
} sample_history_t;

void sample_history_init(sample_history_t *h);
void sample_history_push(sample_history_t *h, uint32_t tick, uint32_t sample_in_second,
                         const float value[IED_NUM_CHANNELS]);

static inline float sample_history_at(const sample_history_t *h, ied_channel_t ch, uint32_t tick)
{
    return h->x[ch][tick & (SAMPLE_HISTORY_LEN - 1u)];
}

static inline uint32_t sample_history_sis(const sample_history_t *h, uint32_t tick)
{
    return h->sis[tick & (SAMPLE_HISTORY_LEN - 1u)];
}

#endif /* SAMPLE_HISTORY_H */

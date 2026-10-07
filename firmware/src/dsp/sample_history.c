#include "sample_history.h"

#include <stddef.h>
#include <string.h>

_Static_assert((SAMPLE_HISTORY_LEN & (SAMPLE_HISTORY_LEN - 1u)) == 0u,
               "SAMPLE_HISTORY_LEN must be a power of two");

void sample_history_init(sample_history_t *h)
{
    if (h == NULL) {
        return;
    }
    memset(h, 0, sizeof(*h));
}

void sample_history_push(sample_history_t *h, uint32_t tick, uint32_t sample_in_second,
                         const float value[IED_NUM_CHANNELS])
{
    uint32_t slot = tick & (SAMPLE_HISTORY_LEN - 1u);
    for (uint32_t ch = 0; ch < (uint32_t)IED_NUM_CHANNELS; ch++) {
        h->x[ch][slot] = value[ch];
    }
    h->sis[slot] = sample_in_second;
    h->newest_tick = tick;
    if (h->count < SAMPLE_HISTORY_LEN) {
        h->count++;
    }
}

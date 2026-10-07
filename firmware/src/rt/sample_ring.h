/* Single-producer / single-consumer ring between the acquisition ISR and the
 * protection task.
 *
 * The ISR is the only writer of `head`, the task the only writer of `tail`;
 * acquire/release ordering on those two indices is the whole synchronisation
 * contract, so neither side ever masks interrupts. Indices are free-running
 * 32-bit counters and are reduced modulo the (power-of-two) capacity on use,
 * which keeps `head - tail` correct across wrap.
 */
#ifndef SAMPLE_RING_H
#define SAMPLE_RING_H

#include "ied_config.h"

#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>

#define SAMPLE_RING_CAPACITY 64u /* 2 cycles of headroom; must be a power of two */

typedef struct {
    uint32_t tick;                        /* sample index since boot */
    uint32_t uptime_s;                    /* timebase snapshot taken in the ISR */
    uint32_t soc;
    uint16_t sample_in_second;
    int16_t raw[IED_NUM_CHANNELS];        /* simultaneous ADC counts */
} sample_frame_t;

typedef struct {
    sample_frame_t slot[SAMPLE_RING_CAPACITY];
    atomic_uint_fast32_t head;            /* written by the ISR only */
    atomic_uint_fast32_t tail;            /* written by the task only */
    uint32_t overruns;                    /* frames dropped because the task fell behind */
    uint32_t high_water;                  /* deepest backlog observed */
} sample_ring_t;

void sample_ring_init(sample_ring_t *ring);

/* ISR side. Returns false (and counts an overrun) when the ring is full; the
 * newest frame is dropped so frames already queued keep their timing. */
bool sample_ring_push(sample_ring_t *ring, const sample_frame_t *frame);

/* Task side. Returns false when the ring is empty. */
bool sample_ring_pop(sample_ring_t *ring, sample_frame_t *out);

uint32_t sample_ring_depth(const sample_ring_t *ring);

#endif /* SAMPLE_RING_H */

#include "sample_ring.h"

#include <stddef.h>
#include <string.h>

_Static_assert((SAMPLE_RING_CAPACITY & (SAMPLE_RING_CAPACITY - 1u)) == 0u,
               "SAMPLE_RING_CAPACITY must be a power of two");

void sample_ring_init(sample_ring_t *ring)
{
    if (ring == NULL) {
        return;
    }
    memset(ring->slot, 0, sizeof(ring->slot));
    atomic_store_explicit(&ring->head, 0u, memory_order_relaxed);
    atomic_store_explicit(&ring->tail, 0u, memory_order_relaxed);
    ring->overruns = 0u;
    ring->high_water = 0u;
}

bool sample_ring_push(sample_ring_t *ring, const sample_frame_t *frame)
{
    uint32_t head = (uint32_t)atomic_load_explicit(&ring->head, memory_order_relaxed);
    uint32_t tail = (uint32_t)atomic_load_explicit(&ring->tail, memory_order_acquire);
    uint32_t depth = head - tail;

    if (depth >= SAMPLE_RING_CAPACITY) {
        ring->overruns++;
        return false;
    }
    ring->slot[head & (SAMPLE_RING_CAPACITY - 1u)] = *frame;
    atomic_store_explicit(&ring->head, head + 1u, memory_order_release);

    if (depth + 1u > ring->high_water) {
        ring->high_water = depth + 1u;
    }
    return true;
}

bool sample_ring_pop(sample_ring_t *ring, sample_frame_t *out)
{
    uint32_t tail = (uint32_t)atomic_load_explicit(&ring->tail, memory_order_relaxed);
    uint32_t head = (uint32_t)atomic_load_explicit(&ring->head, memory_order_acquire);

    if (head == tail) {
        return false;
    }
    *out = ring->slot[tail & (SAMPLE_RING_CAPACITY - 1u)];
    atomic_store_explicit(&ring->tail, tail + 1u, memory_order_release);
    return true;
}

uint32_t sample_ring_depth(const sample_ring_t *ring)
{
    uint32_t head = (uint32_t)atomic_load_explicit(&ring->head, memory_order_acquire);
    uint32_t tail = (uint32_t)atomic_load_explicit(&ring->tail, memory_order_acquire);
    return head - tail;
}

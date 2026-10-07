/* Frequency protection: under/over-frequency (81U / 81O) and rate of change
 * of frequency (81R). Evaluated once per synchrophasor frame (60 Hz) on the
 * PMU's positive-sequence frequency and ROCOF, so protection and the
 * measurement streamed to the control centre can never disagree.
 *
 * All stages are blocked when positive-sequence voltage is below the
 * undervoltage inhibit, because frequency is undefined on a dead bus.
 */
#ifndef FREQ_ELEMENT_H
#define FREQ_ELEMENT_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    float uf_pickup_hz;       /* 81U, e.g. 59.3 */
    uint16_t uf_frames;       /* 81U delay in frames */
    float of_pickup_hz;       /* 81O, e.g. 60.5 */
    uint16_t of_frames;
    float rocof_pickup_hz_s;  /* 81R magnitude, e.g. 1.5 Hz/s */
    uint16_t rocof_frames;    /* consecutive frames above pickup */
    float uv_inhibit_pu;      /* block below this V1, e.g. 0.5 */
} freq_settings_t;

typedef struct {
    uint16_t uf_count;
    uint16_t of_count;
    uint16_t rocof_count;
    bool uf_operated;
    bool of_operated;
    bool rocof_operated;
    bool inhibited;
    bool blocked;
} freq_state_t;

void freq_init(freq_state_t *st);
/* `fault_block` is asserted by the protection task while a fault is detected
 * and for a hold-off afterwards: the positive-sequence angle jumps at fault
 * inception and clearing, which is a phase step, not a frequency change. */
void freq_step(const freq_settings_t *s, freq_state_t *st, float freq_hz, float rocof_hz_s,
               float v1_pu, bool fault_block);

#endif /* FREQ_ELEMENT_H */

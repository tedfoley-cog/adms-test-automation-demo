/* Protection-grade phasor estimation.
 *
 * Full-cycle Fourier (32-point DFT) over the most recent nominal cycle, with
 * the angle referenced to the PPS-aligned sample-in-second index so that a
 * steady 60 Hz signal produces a stationary phasor. Current channels pass
 * through a digital mimic filter first to remove the decaying DC offset that
 * accompanies an asymmetrical fault.
 *
 * Magnitudes are RMS, angles in radians.
 */
#ifndef PHASOR_H
#define PHASOR_H

#include "cplx.h"
#include "ied_config.h"
#include "sample_history.h"

#include <stdint.h>

typedef struct {
    float tau;      /* mimic time constant in samples (X/R / omega / Ts) */
    float k_gain;   /* normalises the mimic gain to 1.0 at 60 Hz */
    float prev;     /* previous raw sample */
    float y;        /* filtered output */
    cplx_t phase_comp; /* undoes the mimic's phase lead at 60 Hz */
    uint8_t primed;
} mimic_filter_t;

void phasor_tables_init(void);

/* Configure a mimic filter for a source with the given X/R ratio. */
void mimic_init(mimic_filter_t *f, float x_over_r);
float mimic_step(mimic_filter_t *f, float x);

/* Rotate a phasor computed from mimic-filtered samples back onto the
 * unfiltered signal's angle (the filter leads by ~70 deg at X/R = 4). */
static inline cplx_t mimic_compensate(const mimic_filter_t *f, cplx_t phasor)
{
    return cplx_mul(phasor, f->phase_comp);
}

/* Full-cycle DFT of channel `ch` ending at `newest_tick`. The history must
 * hold at least IED_SAMPLES_PER_CYCLE samples. */
cplx_t phasor_full_cycle(const sample_history_t *h, ied_channel_t ch, uint32_t newest_tick);

/* Reference rotation for sample-in-second index n: exp(-j*2*pi*n/32). */
cplx_t phasor_ref(uint32_t sample_in_second);

#endif /* PHASOR_H */

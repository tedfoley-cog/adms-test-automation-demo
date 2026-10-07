#include "phasor.h"

#include <stddef.h>

static float s_cos[IED_SAMPLES_PER_CYCLE];
static float s_sin[IED_SAMPLES_PER_CYCLE];
static uint8_t s_tables_ready;

void phasor_tables_init(void)
{
    for (uint32_t n = 0; n < IED_SAMPLES_PER_CYCLE; n++) {
        float w = CPLX_TWO_PI * (float)n / (float)IED_SAMPLES_PER_CYCLE;
        s_cos[n] = cosf(w);
        s_sin[n] = sinf(w);
    }
    s_tables_ready = 1u;
}

cplx_t phasor_ref(uint32_t sample_in_second)
{
    uint32_t n = sample_in_second & (IED_SAMPLES_PER_CYCLE - 1u);
    return cplx(s_cos[n], -s_sin[n]);
}

void mimic_init(mimic_filter_t *f, float x_over_r)
{
    if (f == NULL) {
        return;
    }
    /* tau in samples: L/R = (X/R) / omega0, divided by the sample period. */
    float omega0 = CPLX_TWO_PI * IED_F_NOMINAL_HZ;
    f->tau = (x_over_r / omega0) * (float)IED_SAMPLE_RATE_HZ;

    /* H(z) = K * ((1 + tau) - tau * z^-1); choose K so |H(e^jw0)| = 1. */
    float w = CPLX_TWO_PI / (float)IED_SAMPLES_PER_CYCLE;
    float re = (1.0f + f->tau) - f->tau * cosf(w);
    float im = f->tau * sinf(w);
    float mag = sqrtf(re * re + im * im);
    f->k_gain = 1.0f / mag;
    f->phase_comp = cplx(re / mag, -im / mag);
    f->prev = 0.0f;
    f->y = 0.0f;
    f->primed = 0u;
}

float mimic_step(mimic_filter_t *f, float x)
{
    if (!f->primed) {
        f->prev = x;
        f->primed = 1u;
    }
    f->y = f->k_gain * ((1.0f + f->tau) * x - f->tau * f->prev);
    f->prev = x;
    return f->y;
}

cplx_t phasor_full_cycle(const sample_history_t *h, ied_channel_t ch, uint32_t newest_tick)
{
    if (!s_tables_ready) {
        phasor_tables_init();
    }
    float re = 0.0f;
    float im = 0.0f;
    for (uint32_t m = 0; m < IED_SAMPLES_PER_CYCLE; m++) {
        uint32_t tick = newest_tick - m;
        float x = sample_history_at(h, ch, tick);
        uint32_t n = sample_history_sis(h, tick) & (IED_SAMPLES_PER_CYCLE - 1u);
        re += x * s_cos[n];
        im -= x * s_sin[n];
    }
    const float k = CPLX_SQRT2 / (float)IED_SAMPLES_PER_CYCLE;
    return cplx(re * k, im * k);
}

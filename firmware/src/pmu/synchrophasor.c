#include "synchrophasor.h"

#include "phasor.h"
#include "symcomp.h"

#include <stddef.h>

static float s_weight[PMU_WINDOW_TAPS];
static float s_gain;
static bool s_ready;

static void tables_init(void)
{
    float sum = 0.0f;
    for (uint32_t k = 0; k < PMU_WINDOW_TAPS; k++) {
        int32_t offset = (int32_t)k - (int32_t)PMU_HALF_WINDOW;
        int32_t mag = offset < 0 ? -offset : offset;
        s_weight[k] = 1.0f - (float)mag / (float)(PMU_HALF_WINDOW + 1u);
        sum += s_weight[k];
    }
    s_gain = CPLX_SQRT2 / sum;
    s_ready = true;
}

void pmu_estimator_init(pmu_estimator_t *est)
{
    if (!s_ready) {
        tables_init();
    }
    phasor_tables_init();
    est->prev_angle = 0.0f;
    est->prev_freq = IED_F_NOMINAL_HZ;
    est->frames = 0u;
    est->last.valid = false;
    est->last.freq_hz = IED_F_NOMINAL_HZ;
    est->last.rocof_hz_s = 0.0f;
    est->last.sample_in_second = 0u;
}

float pmu_wrap_angle(float rad)
{
    float r = fmodf(rad + CPLX_PI, CPLX_TWO_PI);
    return r - CPLX_PI;
}

float pmu_tve(cplx_t estimated, cplx_t reference)
{
    float ref = cplx_abs(reference);
    if (ref <= 0.0f) {
        return 0.0f;
    }
    return cplx_abs(cplx_sub(estimated, reference)) / ref;
}

pmu_measurement_t *pmu_estimate(pmu_estimator_t *est, const sample_history_t *h,
                                      uint32_t newest_tick)
{
    if (!s_ready) {
        tables_init();
    }
    pmu_measurement_t *m = &est->last;
    uint32_t first_tick = newest_tick - (PMU_WINDOW_TAPS - 1u);
    uint32_t centre_tick = newest_tick - PMU_HALF_WINDOW;

    for (uint32_t ch = 0; ch < (uint32_t)IED_NUM_CHANNELS; ch++) {
        float re = 0.0f;
        float im = 0.0f;
        for (uint32_t k = 0; k < PMU_WINDOW_TAPS; k++) {
            uint32_t tick = first_tick + k;
            float x = sample_history_at(h, (ied_channel_t)ch, tick) * s_weight[k];
            cplx_t ref = phasor_ref(sample_history_sis(h, tick));
            re += x * ref.re;
            im += x * ref.im;
        }
        m->phasor[ch] = cplx(re * s_gain, im * s_gain);
    }

    symcomp_t vs = symcomp_from_abc(m->phasor[IED_CH_VA], m->phasor[IED_CH_VB],
                                    m->phasor[IED_CH_VC]);
    symcomp_t is = symcomp_from_abc(m->phasor[IED_CH_IA], m->phasor[IED_CH_IB],
                                    m->phasor[IED_CH_IC]);
    m->v1 = vs.pos;
    m->i1 = is.pos;
    m->sample_in_second = sample_history_sis(h, centre_tick);

    /* Frequency from the positive-sequence angle slip over one reporting
     * interval: below f0 the phasor lags by 2*pi*(f0 - f)/Fs per frame. */
    float angle = cplx_arg(m->v1);
    const float frame_s = 1.0f / (float)IED_PMU_RATE_HZ;
    if (est->frames == 0u) {
        m->freq_hz = IED_F_NOMINAL_HZ;
        m->rocof_hz_s = 0.0f;
        m->valid = false;
    } else {
        float slip = pmu_wrap_angle(est->prev_angle - angle);
        m->freq_hz = IED_F_NOMINAL_HZ - slip / (CPLX_TWO_PI * frame_s);
        m->rocof_hz_s = est->frames >= 2u ? (m->freq_hz - est->prev_freq) / frame_s : 0.0f;
        m->valid = est->frames >= 2u;
    }
    est->prev_angle = angle;
    est->prev_freq = m->freq_hz;
    if (est->frames < UINT32_MAX) {
        est->frames++;
    }
    return m;
}

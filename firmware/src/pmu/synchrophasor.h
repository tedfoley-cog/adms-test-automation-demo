/* Synchrophasor estimation, IEEE C37.118.1 P-class.
 *
 * Implements the reference P-class algorithm of C37.118.1 Annex C: a
 * two-cycle triangular-weighted quadrature demodulation centred on the
 * reporting instant, followed by positive-sequence extraction and frequency /
 * ROCOF from the rate of change of the positive-sequence angle.
 *
 * Reporting rate is 60 frames/s. Frame k is time-stamped at sample
 * 32k of the UTC second, so the window needs the 31 samples after the
 * timestamp: measurement latency is 31 samples (16.1 ms) plus compute.
 */
#ifndef SYNCHROPHASOR_H
#define SYNCHROPHASOR_H

#include "cplx.h"
#include "ied_config.h"
#include "sample_history.h"

#include <stdbool.h>
#include <stdint.h>

#define PMU_WINDOW_TAPS   63u   /* 2 * 32 - 1 */
#define PMU_HALF_WINDOW   31u

typedef struct {
    cplx_t phasor[IED_NUM_CHANNELS];   /* RMS, primary units */
    cplx_t v1;                         /* positive-sequence voltage */
    cplx_t i1;                         /* positive-sequence current */
    float freq_hz;
    float rocof_hz_s;
    uint32_t sample_in_second;         /* timestamp sample index */
    bool valid;                        /* false until two frames are available */
} pmu_measurement_t;

typedef struct {
    float prev_angle;
    float prev_freq;
    uint32_t frames;
    pmu_measurement_t last;
} pmu_estimator_t;

void pmu_estimator_init(pmu_estimator_t *est);

/* True when the newest sample completes the window for a reporting instant. */
static inline bool pmu_frame_due(uint32_t sample_in_second)
{
    return (sample_in_second % IED_PMU_DECIMATION) == PMU_HALF_WINDOW;
}

/* Run the estimator for the window whose newest sample is `newest_tick`. */
pmu_measurement_t *pmu_estimate(pmu_estimator_t *est, const sample_history_t *h,
                                      uint32_t newest_tick);

/* Wrap an angle into [-pi, pi). */
float pmu_wrap_angle(float rad);

/* Total vector error, frequency error and ROCOF error per C37.118.1 5.3. */
float pmu_tve(cplx_t estimated, cplx_t reference);

#endif /* SYNCHROPHASOR_H */

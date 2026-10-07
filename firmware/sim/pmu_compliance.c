/* Synchrophasor compliance harness (IEEE C37.118.1-2011 + 1a-2014, P class).
 *
 * Feeds the production estimator with ideal three-phase test signals
 * quantised through the same 16-bit ADC scaling as the relay, and measures
 * total vector error (TVE), frequency error (FE) and ROCOF error (RFE)
 * against the analytically known synchrophasor at every reporting instant.
 *
 *   pmu_compliance --suite magnitude|phase    (JSON on stdout)
 *   pmu_compliance --list
 */
#include "ied_app.h"
#include "phasor.h"
#include "sample_history.h"
#include "synchrophasor.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#define LIMIT_TVE_PCT   1.0
#define LIMIT_FE_HZ     0.005
#define LIMIT_RFE_HZ_S  0.4
#define SETTLE_FRAMES   4u
#define PI_D            3.14159265358979323846
#define MEASURE_FRAMES  60u

typedef struct {
    double mag_pu;
    double phase_deg;
    double freq_hz;
    double rocof_hz_s;
} test_point_t;

typedef struct {
    double tve_pct;
    double fe_hz;
    double rfe_hz_s;
} point_result_t;

static double ref_angle(const test_point_t *p, double t)
{
    /* Phase of the input relative to the nominal-frequency reference. */
    double df = p->freq_hz - IED_F_NOMINAL_HZ;
    return 2.0 * PI_D * (df * t + 0.5 * p->rocof_hz_s * t * t) + p->phase_deg * PI_D / 180.0;
}

static point_result_t run_point(const test_point_t *p)
{
    static sample_history_t hist;
    pmu_estimator_t est;
    const ied_settings_t *s = ied_default_settings();
    const double vnom = s->v_ln_nominal;
    const double inom = 600.0;
    const double ts = 1.0 / IED_SAMPLE_RATE_HZ;

    sample_history_init(&hist);
    pmu_estimator_init(&est);

    point_result_t r = {0.0, 0.0, 0.0};
    uint32_t frames = 0u;
    uint32_t total = (SETTLE_FRAMES + MEASURE_FRAMES + 2u) * IED_PMU_DECIMATION + PMU_WINDOW_TAPS;

    for (uint32_t n = 0; n < total; n++) {
        double t = (double)n * ts;
        double theta0 = 2.0 * PI_D * IED_F_NOMINAL_HZ * t + ref_angle(p, t);
        float value[IED_NUM_CHANNELS];
        for (int ph = 0; ph < 3; ph++) {
            double th = theta0 - ph * 2.0 * PI_D / 3.0;
            double v = sqrt(2.0) * vnom * p->mag_pu * cos(th);
            double i = sqrt(2.0) * inom * p->mag_pu * cos(th - 0.3);
            value[IED_CH_VA + ph] = (float)lrint(v / s->scale[IED_CH_VA + ph]) *
                                    s->scale[IED_CH_VA + ph];
            value[IED_CH_IA + ph] = (float)lrint(i / s->scale[IED_CH_IA + ph]) *
                                    s->scale[IED_CH_IA + ph];
        }
        value[IED_CH_IN] = 0.0f;
        sample_history_push(&hist, n, n % IED_SAMPLE_RATE_HZ, value);

        uint32_t sis = n % IED_SAMPLE_RATE_HZ;
        if (n + 1u < PMU_WINDOW_TAPS || !pmu_frame_due(sis)) {
            continue;
        }
        const pmu_measurement_t *m = pmu_estimate(&est, &hist, n);
        frames++;
        if (frames <= SETTLE_FRAMES || !m->valid) {
            continue;
        }
        double tc = (double)(n - PMU_HALF_WINDOW) * ts;
        double ang = ref_angle(p, tc);
        cplx_t ref = cplx_polar((float)(vnom * p->mag_pu), (float)ang);
        double tve = (double)pmu_tve(m->v1, ref) * 100.0;
        double f_true = p->freq_hz + p->rocof_hz_s * tc;
        double fe = fabs((double)m->freq_hz - f_true);
        double rfe = fabs((double)m->rocof_hz_s - p->rocof_hz_s);
        r.tve_pct = fmax(r.tve_pct, tve);
        r.fe_hz = fmax(r.fe_hz, fe);
        r.rfe_hz_s = fmax(r.rfe_hz_s, rfe);
        if (frames >= SETTLE_FRAMES + MEASURE_FRAMES) {
            break;
        }
    }
    return r;
}

static int suite_points(const char *suite, test_point_t *pts, char labels[][32], int max)
{
    int n = 0;
    if (strcmp(suite, "magnitude") == 0) {
        static const double mags[] = {0.1, 0.5, 0.8, 1.0, 1.2};
        for (size_t k = 0; k < sizeof(mags) / sizeof(mags[0]) && n < max; k++, n++) {
            pts[n] = (test_point_t){mags[k], 0.0, IED_F_NOMINAL_HZ, 0.0};
            snprintf(labels[n], 32, "%.0f%% Vnom", mags[k] * 100.0);
        }
    } else if (strcmp(suite, "phase") == 0) {
        for (int deg = -180; deg < 180 && n < max; deg += 30, n++) {
            pts[n] = (test_point_t){1.0, (double)deg, IED_F_NOMINAL_HZ, 0.0};
            snprintf(labels[n], 32, "%+d deg", deg);
        }
    }
    return n;
}

int main(int argc, char **argv)
{
    const char *suite = NULL;
    for (int k = 1; k < argc; k++) {
        if (strcmp(argv[k], "--list") == 0) {
            printf("magnitude\nphase\n");
            return 0;
        }
        if (strcmp(argv[k], "--suite") == 0 && k + 1 < argc) {
            suite = argv[++k];
        }
    }
    if (suite == NULL) {
        fprintf(stderr, "usage: pmu_compliance --suite magnitude|phase | --list\n");
        return 2;
    }

    phasor_tables_init();
    test_point_t pts[64];
    char labels[64][32];
    int n = suite_points(suite, pts, labels, 64);
    if (n == 0) {
        fprintf(stderr, "unknown suite '%s'\n", suite);
        return 2;
    }

    int failed = 0;
    printf("{\"suite\": \"%s\", \"limits\": {\"tve_pct\": %.3f, \"fe_hz\": %.4f, "
           "\"rfe_hz_s\": %.2f}, \"points\": [",
           suite, LIMIT_TVE_PCT, LIMIT_FE_HZ, LIMIT_RFE_HZ_S);
    for (int k = 0; k < n; k++) {
        point_result_t r = run_point(&pts[k]);
        bool pass = r.tve_pct <= LIMIT_TVE_PCT && r.fe_hz <= LIMIT_FE_HZ &&
                    r.rfe_hz_s <= LIMIT_RFE_HZ_S;
        failed += pass ? 0 : 1;
        printf("%s{\"label\": \"%s\", \"freq_hz\": %.3f, \"tve_pct\": %.4f, \"fe_hz\": %.5f, "
               "\"rfe_hz_s\": %.4f, \"pass\": %s}",
               k == 0 ? "" : ", ", labels[k], pts[k].freq_hz, r.tve_pct, r.fe_hz, r.rfe_hz_s,
               pass ? "true" : "false");
    }
    printf("], \"failed\": %d}\n", failed);
    return failed == 0 ? 0 : 1;
}

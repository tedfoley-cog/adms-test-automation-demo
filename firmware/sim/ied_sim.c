/* Host closed-loop simulation: test set -> IED -> breaker model.
 *
 * Runs the exact production code paths in the order the target executes
 * them (acq ISR, PPS, protection, PMU, comms) one sample at a time.
 *
 *   ied_sim --list
 *   ied_sim --scenario fault_ag_zone1
 *   ied_sim --scenario steady_load --freq 59.5 --duration 4
 *   ied_sim --scenario fault_ag_zone1 --uptime-s 2246400
 *   ied_sim --scenario steady_load --pmu-csv pmu.csv
 */
#include "ied_app.h"
#include "testset.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PREROLL_S       3u
#define SOC_AT_BOOT     1790000000u

typedef struct {
    FILE *csv;
    uint32_t frames;
    float f_min;
    float f_max;
    float rocof_abs_max;
    uint32_t not_sync_frames;
    bool started;
    double t0;
} sim_ctx_t;

static double s_scenario_t;

static void on_pmu(const uint8_t *frame, size_t len, const pmu_measurement_t *m, uint32_t soc,
                   uint32_t fracsec, void *ctx)
{
    sim_ctx_t *c = (sim_ctx_t *)ctx;
    (void)frame;
    (void)len;
    if (s_scenario_t < 0.0) {
        return;
    }
    uint16_t stat = (uint16_t)((frame[14] << 8) | frame[15]);
    c->frames++;
    if (m->valid) {
        c->f_min = fminf(c->f_min, m->freq_hz);
        c->f_max = fmaxf(c->f_max, m->freq_hz);
        c->rocof_abs_max = fmaxf(c->rocof_abs_max, fabsf(m->rocof_hz_s));
    }
    if ((stat & 0x2000u) != 0u) {
        c->not_sync_frames++;
    }
    if (c->csv != NULL) {
        fprintf(c->csv, "%u,%06u,%.4f,%.4f,%.1f,%.2f,0x%04x\n", (unsigned)soc,
                (unsigned)(fracsec & 0xFFFFFFu), (double)m->freq_hz, (double)m->rocof_hz_s,
                (double)cplx_abs(m->v1), (double)(cplx_arg(m->v1) * 57.2957795f),
                (unsigned)stat);
    }
}

static void on_event(const soe_event_t *ev, void *ctx)
{
    (void)ctx;
    if (s_scenario_t < 0.0 && ev->code == SOE_PPS_LOCK) {
        return;
    }
    double t_ms = s_scenario_t * 1000.0;
    printf("SOE t=%8.2fms soc=%u.%06u %-12s", t_ms, (unsigned)ev->soc, (unsigned)ev->usec,
           soe_code_name(ev->code));
    if (ev->code == SOE_ELEMENT_OPERATE) {
        elem_id_t e = (elem_id_t)(ev->detail & 0xFFu);
        printf(" %-8s", elem_name(e));
        uint8_t loops = (uint8_t)(ev->detail >> 8);
        for (int l = 0; l < DIST_LOOP_COUNT; l++) {
            if ((loops & (1u << l)) != 0u) {
                printf(" %s", distance_loop_name((distance_loop_t)l));
            }
        }
        printf(" value=%.3f", (double)ev->value);
    } else if (ev->code == SOE_TRIP1_ON) {
        printf(" target=0x%04x I=%.0fA", ev->detail, (double)ev->value);
    } else if (ev->code == SOE_TRIPB_ON) {
        printf(" bf_timer=%.3fs", (double)ev->value);
    }
    printf("\n");
}

static void usage(void)
{
    fprintf(stderr,
            "usage: ied_sim --scenario NAME [--freq HZ] [--rocof HZ_S --freq-end HZ "
            "--ramp-start S] [--duration S] [--uptime-s N] [--pmu-csv FILE]\n"
            "       ied_sim --list\n");
}

int main(int argc, char **argv)
{
    const char *name = NULL;
    const char *csv_path = NULL;
    float freq = -1.0f;
    float rocof = 0.0f;
    float freq_end = -1.0f;
    float ramp_start = 0.0f;
    float duration = -1.0f;
    unsigned long uptime = 0ul;

    for (int k = 1; k < argc; k++) {
        if (strcmp(argv[k], "--list") == 0) {
            for (int s = 0; s < testset_scenario_count(); s++) {
                const scenario_t *sc = testset_scenario(s);
                printf("%-26s %s\n", sc->name, sc->description);
            }
            return 0;
        } else if (strcmp(argv[k], "--scenario") == 0 && k + 1 < argc) {
            name = argv[++k];
        } else if (strcmp(argv[k], "--freq") == 0 && k + 1 < argc) {
            freq = strtof(argv[++k], NULL);
        } else if (strcmp(argv[k], "--rocof") == 0 && k + 1 < argc) {
            rocof = strtof(argv[++k], NULL);
        } else if (strcmp(argv[k], "--freq-end") == 0 && k + 1 < argc) {
            freq_end = strtof(argv[++k], NULL);
        } else if (strcmp(argv[k], "--ramp-start") == 0 && k + 1 < argc) {
            ramp_start = strtof(argv[++k], NULL);
        } else if (strcmp(argv[k], "--duration") == 0 && k + 1 < argc) {
            duration = strtof(argv[++k], NULL);
        } else if (strcmp(argv[k], "--uptime-s") == 0 && k + 1 < argc) {
            uptime = strtoul(argv[++k], NULL, 10);
        } else if (strcmp(argv[k], "--pmu-csv") == 0 && k + 1 < argc) {
            csv_path = argv[++k];
        } else {
            usage();
            return 2;
        }
    }
    const scenario_t *base = name != NULL ? testset_find(name) : NULL;
    if (base == NULL) {
        usage();
        return 2;
    }

    scenario_t sc = *base;
    if (freq > 0.0f) {
        sc.freq_hz = freq;
        sc.freq_end_hz = freq;
    }
    if (rocof != 0.0f) {
        sc.rocof_hz_s = rocof;
        sc.ramp_start_s = ramp_start;
        sc.freq_end_hz = freq_end > 0.0f ? freq_end : sc.freq_hz;
    }
    if (duration > 0.0f) {
        sc.duration_s = duration;
    }

    sim_ctx_t ctx = {0};
    ctx.f_min = 1e9f;
    ctx.f_max = -1e9f;
    if (csv_path != NULL) {
        ctx.csv = fopen(csv_path, "w");
        if (ctx.csv == NULL) {
            perror(csv_path);
            return 1;
        }
        fprintf(ctx.csv, "soc,fracsec_us,freq_hz,rocof_hz_s,v1_mag,v1_ang_deg,stat\n");
    }

    const ied_settings_t *settings = ied_default_settings();
    ied_hooks_t hooks = {on_pmu, on_event, &ctx};
    ied_init(settings, SOC_AT_BOOT, &hooks);
    g_timebase.uptime_s = (uint32_t)uptime;

    testset_t ts;
    testset_init(&ts, &sc, settings->scale);
    testset_set_preroll(&ts, PREROLL_S * IED_SAMPLE_RATE_HZ);

    printf("SCENARIO %s: %s\n", sc.name, sc.description);
    if (uptime != 0ul) {
        printf("UPTIME   %lu s (%.2f days) at power-up of the scenario\n", uptime,
               (double)uptime / 86400.0);
    }

    int16_t raw[IED_NUM_CHANNELS];
    const ied_status_t *st = ied_status();
    while (!testset_done(&ts)) {
        s_scenario_t = (double)testset_time_s(&ts);
        testset_step(&ts, st->trip1, st->tripb, raw);
        ied_set_breaker_open(ts.breaker_open || ts.bus_dead);
        (void)ied_acq_isr(raw);
        if (g_timebase.sample_in_second == 0u) {
            ied_pps_isr(TIMEBASE_TIMER_HZ);
        }
        if (ied_protection_task()) {
            ied_pmu_task();
        }
        if ((g_timebase.tick % IED_COMMS_DECIMATION) == 0u) {
            ied_comms_task();
        }
    }
    for (int k = 0; k < 8; k++) {
        ied_comms_task();
    }

    printf("RESULT   trip1=%d 86B=%d breaker_open=%d bus_dead=%d target=0x%04x\n", st->trip1,
           st->tripb, ts.breaker_open, ts.bus_dead, st->target);
    printf("PMU      frames=%u f_min=%.4f f_max=%.4f max|rocof|=%.3f not_sync=%u\n",
           (unsigned)ctx.frames, (double)ctx.f_min, (double)ctx.f_max,
           (double)ctx.rocof_abs_max, (unsigned)ctx.not_sync_frames);
    if (ctx.csv != NULL) {
        fclose(ctx.csv);
    }
    return 0;
}

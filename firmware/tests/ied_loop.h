/* Closed-loop harness shared by the IED host tests: drives the production
 * acquisition / protection / PMU / comms entry points from the secondary-
 * injection test set exactly as firmware/sim/ied_sim.c does. */
#ifndef IED_LOOP_H
#define IED_LOOP_H

#include "ied_app.h"
#include "testset.h"

#include <string.h>

#define LOOP_MAX_EVENTS 64
#define LOOP_MAX_FRAMES 512
#define LOOP_PREROLL_S  3u

typedef struct {
    soe_event_t events[LOOP_MAX_EVENTS];
    int num_events;
    pmu_measurement_t frames[LOOP_MAX_FRAMES];
    int num_frames;
    testset_t ts;
} loop_result_t;

static loop_result_t loop_res;

static inline void loop_on_event(const soe_event_t *ev, void *ctx)
{
    (void)ctx;
    if (loop_res.num_events < LOOP_MAX_EVENTS) {
        loop_res.events[loop_res.num_events++] = *ev;
    }
}

static inline void loop_on_pmu(const uint8_t *frame, size_t len, const pmu_measurement_t *m,
                        uint32_t soc, uint32_t fracsec, void *ctx)
{
    (void)frame;
    (void)len;
    (void)soc;
    (void)fracsec;
    (void)ctx;
    if (loop_res.num_frames < LOOP_MAX_FRAMES) {
        loop_res.frames[loop_res.num_frames++] = *m;
    }
}

/* Runs `sc` after a steady-state preroll; frames/events from the preroll are
 * discarded so assertions see only the scenario. */
static inline const ied_status_t *loop_run(const scenario_t *sc, uint32_t uptime_s)
{
    memset(&loop_res, 0, sizeof(loop_res));
    ied_hooks_t hooks = {loop_on_pmu, loop_on_event, NULL};
    const ied_settings_t *s = ied_default_settings();
    ied_init(s, 1790000000u, &hooks);
    g_timebase.uptime_s = uptime_s;
    testset_init(&loop_res.ts, sc, s->scale);
    testset_set_preroll(&loop_res.ts, LOOP_PREROLL_S * IED_SAMPLE_RATE_HZ);

    int16_t raw[IED_NUM_CHANNELS];
    while (!testset_done(&loop_res.ts)) {
        const ied_status_t *st = ied_status();
        testset_step(&loop_res.ts, st->trip1, st->tripb, raw);
        ied_set_breaker_open(loop_res.ts.breaker_open || loop_res.ts.bus_dead);
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
        if (loop_res.ts.n == loop_res.ts.preroll_n) {
            loop_res.num_events = 0;
            loop_res.num_frames = 0;
        }
    }
    for (int k = 0; k < 4; k++) {
        ied_comms_task();
    }
    return ied_status();
}

static inline const soe_event_t *loop_find(uint16_t code, int nth)
{
    for (int k = 0; k < loop_res.num_events; k++) {
        if (loop_res.events[k].code == code && nth-- == 0) {
            return &loop_res.events[k];
        }
    }
    return NULL;
}

#endif /* IED_LOOP_H */

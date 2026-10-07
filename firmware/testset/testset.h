/* Secondary-injection test set.
 *
 * Generates the seven analog channels an IED would see from its VTs and CTs
 * for a 12.47 kV radial feeder: a Thevenin source behind the substation bus,
 * a 5 km 336 ACSR line, and faults solved with the symmetrical-component
 * networks (SLG, LL, 3PH) at any point along it. Fault current includes the
 * decaying DC offset set by the point on wave of inception and the X/R of
 * the fault loop. A breaker model responds to the IED's trip outputs.
 *
 * The same code runs on the host (sim/) and inside the target firmware under
 * Renode, standing in for the ADC DMA buffer, so both see identical samples.
 */
#ifndef TESTSET_H
#define TESTSET_H

#include "cplx.h"
#include "ied_config.h"

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    FAULT_NONE = 0,
    FAULT_AG,
    FAULT_BG,
    FAULT_CG,
    FAULT_AB,
    FAULT_BC,
    FAULT_CA,
    FAULT_ABC
} fault_type_t;

typedef struct {
    const char *name;
    const char *description;
    float duration_s;
    float freq_hz;            /* system frequency at t = 0 */
    float rocof_hz_s;         /* ramp rate applied from ramp_start_s */
    float ramp_start_s;
    float freq_end_hz;        /* ramp stops here */
    float load_a;
    float load_pf;
    fault_type_t fault;
    float fault_start_s;
    float fault_location_pct; /* % of line length from the relay */
    float fault_r_ohm;
    bool breaker_stuck;
} scenario_t;

typedef struct {
    const scenario_t *sc;
    float scale[IED_NUM_CHANNELS];
    uint32_t n;               /* samples generated */
    uint32_t preroll_n;       /* steady-state samples before scenario time 0 */
    uint32_t phase_acc;       /* DDS phase of the system voltage, 2^32 = 2 pi */
    float freq_hz;

    cplx_t v_pre[3], i_pre[3];
    cplx_t v_flt[3], i_flt[3];
    float fault_tau_samples;
    float dc_offset[3];       /* instantaneous current at inception, per phase */
    uint32_t fault_n;
    bool fault_active;

    bool breaker_open;
    bool bus_dead;
    int32_t breaker_timer;    /* samples until the feeder breaker opens */
    int32_t bus_timer;
    uint32_t lcg;
} testset_t;

#define TESTSET_BREAKER_SAMPLES   96   /* 3-cycle breaker: 50 ms */
#define TESTSET_BUS_SAMPLES       154  /* 5-cycle upstream breakers: 80 ms */

int testset_scenario_count(void);
const scenario_t *testset_scenario(int index);
const scenario_t *testset_find(const char *name);

void testset_init(testset_t *ts, const scenario_t *sc, const float scale[IED_NUM_CHANNELS]);

/* Produce the next simultaneous sample. trip1/tripb are the IED outputs from
 * the previous sample period. */
void testset_step(testset_t *ts, bool trip1, bool tripb, int16_t raw[IED_NUM_CHANNELS]);

/* Hold the pre-fault steady state for `samples` before scenario time 0 (the
 * IED needs three PPS edges to declare time lock). */
void testset_set_preroll(testset_t *ts, uint32_t samples);

bool testset_done(const testset_t *ts);
float testset_time_s(const testset_t *ts);

/* Steady-state phasor solution, exposed for tests (RMS, primary units). */
void testset_solve_fault(fault_type_t type, float location_pct, float rf_ohm, cplx_t v[3],
                         cplx_t i[3], float *x_over_r);

#endif /* TESTSET_H */

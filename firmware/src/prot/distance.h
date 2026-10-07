/* Mho distance protection (ANSI 21), two forward zones.
 *
 * Six measuring loops (AG, BG, CG, AB, BC, CA) are evaluated every pass with
 * a phase comparator:
 *
 *     operate  <=>  Re{ (I_loop * Zr - V_loop) * conj(V_pol) } > 0
 *
 * which is a circle through the origin with diameter Zr at the line angle.
 * Ground loops use residual compensation I_loop = I_ph + k0 * 3 * I0 with
 * k0 = (Z0 - Z1) / (3 * Z1). The polarising voltage is positive-sequence
 * memory, so a close-in three-phase fault that collapses the voltage still
 * has a stable reference for several cycles.
 */
#ifndef DISTANCE_H
#define DISTANCE_H

#include "cplx.h"

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    DIST_LOOP_AG = 0,
    DIST_LOOP_BG,
    DIST_LOOP_CG,
    DIST_LOOP_AB,
    DIST_LOOP_BC,
    DIST_LOOP_CA,
    DIST_LOOP_COUNT
} distance_loop_t;

typedef struct {
    cplx_t z1_line;          /* positive-sequence line impedance, primary ohms */
    cplx_t k0;               /* residual compensation factor */
    float z1_reach_pct;      /* zone 1 reach, % of line (typically 80) */
    float z2_reach_pct;      /* zone 2 reach, % of line (typically 120) */
    uint32_t z2_delay_ticks; /* zone 2 time delay, in samples */
    float min_loop_a;        /* loop current supervision */
    float min_residual_a;    /* 3I0 supervision for ground loops */
    uint8_t z1_security;     /* consecutive passes before zone 1 operates */
    float memory_alpha;      /* positive-sequence memory filter coefficient */
} distance_settings_t;

typedef struct {
    cplx_t v1_mem;
    bool mem_valid;
    uint8_t z1_count[DIST_LOOP_COUNT];
    bool z2_timing[DIST_LOOP_COUNT];
    uint32_t z2_start_tick[DIST_LOOP_COUNT];
    cplx_t z_apparent[DIST_LOOP_COUNT];
    uint8_t z1_loops;        /* bitmask of loops in zone 1 this pass */
    uint8_t z2_loops;
    bool z1_operated;
    bool z2_operated;
} distance_state_t;

void distance_init(distance_state_t *st);

/* One protection pass. v and i are RMS phasors in primary units, phase order
 * A, B, C. `v1_nominal` is the nominal positive-sequence voltage (RMS, LN). */
void distance_step(const distance_settings_t *s, distance_state_t *st, const cplx_t v[3],
                   const cplx_t i[3], float v1_nominal, uint32_t tick);

const char *distance_loop_name(distance_loop_t loop);

#endif /* DISTANCE_H */

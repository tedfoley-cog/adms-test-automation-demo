#include "distance.h"

#include "symcomp.h"

#include <stddef.h>

#define MEM_UPDATE_MIN_PU 0.70f  /* only refresh memory from a healthy voltage */

static const char *const k_loop_names[DIST_LOOP_COUNT] = {"AG", "BG", "CG", "AB", "BC", "CA"};

const char *distance_loop_name(distance_loop_t loop)
{
    if ((unsigned)loop >= (unsigned)DIST_LOOP_COUNT) {
        return "--";
    }
    return k_loop_names[loop];
}

void distance_init(distance_state_t *st)
{
    st->v1_mem = cplx(0.0f, 0.0f);
    st->mem_valid = false;
    for (int l = 0; l < DIST_LOOP_COUNT; l++) {
        st->z1_count[l] = 0u;
        st->z2_timing[l] = false;
        st->z2_start_tick[l] = 0u;
        st->z_apparent[l] = cplx(0.0f, 0.0f);
    }
    st->z1_loops = 0u;
    st->z2_loops = 0u;
    st->z1_operated = false;
    st->z2_operated = false;
}

static bool mho_operates(cplx_t v_loop, cplx_t i_loop, cplx_t z_reach, cplx_t v_pol)
{
    cplx_t s1 = cplx_sub(cplx_mul(i_loop, z_reach), v_loop);
    cplx_t torque = cplx_mul(s1, cplx_conj(v_pol));
    return torque.re > 0.0f;
}

void distance_step(const distance_settings_t *s, distance_state_t *st, const cplx_t v[3],
                   const cplx_t i[3], float v1_nominal, uint32_t tick)
{
    if (s == NULL || st == NULL) {
        return;
    }

    symcomp_t vs = symcomp_from_abc(v[0], v[1], v[2]);
    cplx_t i_res = cplx_add(cplx_add(i[0], i[1]), i[2]); /* 3 * I0 */

    /* Positive-sequence memory: track a healthy voltage, freeze during a dip. */
    if (cplx_abs(vs.pos) >= MEM_UPDATE_MIN_PU * v1_nominal) {
        if (!st->mem_valid) {
            st->v1_mem = vs.pos;
            st->mem_valid = true;
        } else {
            st->v1_mem = cplx_add(st->v1_mem,
                                  cplx_scale(cplx_sub(vs.pos, st->v1_mem), s->memory_alpha));
        }
    }
    if (!st->mem_valid) {
        st->z1_loops = 0u;
        st->z2_loops = 0u;
        st->z1_operated = false;
        st->z2_operated = false;
        return;
    }

    cplx_t a = symcomp_a();
    cplx_t a2 = symcomp_a2();
    cplx_t pol_a = st->v1_mem;
    cplx_t pol_b = cplx_mul(st->v1_mem, a2);
    cplx_t pol_c = cplx_mul(st->v1_mem, a);

    cplx_t v_loop[DIST_LOOP_COUNT];
    cplx_t i_loop[DIST_LOOP_COUNT];
    cplx_t v_pol[DIST_LOOP_COUNT];
    bool supervised[DIST_LOOP_COUNT];

    cplx_t k0_ires = cplx_mul(s->k0, i_res);
    float ires_mag = cplx_abs(i_res);
    for (int ph = 0; ph < 3; ph++) {
        v_loop[ph] = v[ph];
        i_loop[ph] = cplx_add(i[ph], k0_ires);
        supervised[ph] = ires_mag >= s->min_residual_a && cplx_abs(i[ph]) >= s->min_loop_a;
    }
    v_pol[DIST_LOOP_AG] = pol_a;
    v_pol[DIST_LOOP_BG] = pol_b;
    v_pol[DIST_LOOP_CG] = pol_c;

    static const int pp_from[3] = {0, 1, 2};
    static const int pp_to[3] = {1, 2, 0};
    cplx_t pp_pol[3] = {cplx_sub(pol_a, pol_b), cplx_sub(pol_b, pol_c), cplx_sub(pol_c, pol_a)};
    for (int k = 0; k < 3; k++) {
        int l = DIST_LOOP_AB + k;
        v_loop[l] = cplx_sub(v[pp_from[k]], v[pp_to[k]]);
        i_loop[l] = cplx_sub(i[pp_from[k]], i[pp_to[k]]);
        v_pol[l] = pp_pol[k];
        supervised[l] = cplx_abs(i_loop[l]) >= s->min_loop_a;
    }

    cplx_t zr1 = cplx_scale(s->z1_line, s->z1_reach_pct / 100.0f);
    cplx_t zr2 = cplx_scale(s->z1_line, s->z2_reach_pct / 100.0f);

    st->z1_loops = 0u;
    st->z2_loops = 0u;
    bool z1_any = false;
    bool z2_any = false;

    for (int l = 0; l < DIST_LOOP_COUNT; l++) {
        st->z_apparent[l] = cplx_div_safe(v_loop[l], i_loop[l], 1e-3f);

        bool in_z1 = supervised[l] && mho_operates(v_loop[l], i_loop[l], zr1, v_pol[l]);
        bool in_z2 = supervised[l] && mho_operates(v_loop[l], i_loop[l], zr2, v_pol[l]);

        if (in_z1) {
            st->z1_loops |= (uint8_t)(1u << l);
            if (st->z1_count[l] < UINT8_MAX) {
                st->z1_count[l]++;
            }
            if (st->z1_count[l] >= s->z1_security) {
                z1_any = true;
            }
        } else {
            st->z1_count[l] = 0u;
        }

        if (in_z2) {
            st->z2_loops |= (uint8_t)(1u << l);
            if (!st->z2_timing[l]) {
                st->z2_timing[l] = true;
                st->z2_start_tick[l] = tick;
            }
            if ((uint32_t)(tick - st->z2_start_tick[l]) >= s->z2_delay_ticks) {
                z2_any = true;
            }
        } else {
            st->z2_timing[l] = false;
        }
    }

    st->z1_operated = z1_any;
    st->z2_operated = z2_any;
}

#include "oc_element.h"

#include <math.h>
#include <stddef.h>

typedef struct {
    float a;      /* IEC k, IEEE A */
    float b;      /* IEEE B (0 for IEC) */
    float p;      /* exponent */
    float tr;     /* IEEE reset constant (0: instantaneous reset) */
} curve_def_t;

static curve_def_t curve_def(toc_curve_t curve)
{
    switch (curve) {
    case TOC_IEC_VI:
        return (curve_def_t){13.5f, 0.0f, 1.0f, 0.0f};
    case TOC_IEC_EI:
        return (curve_def_t){80.0f, 0.0f, 2.0f, 0.0f};
    case TOC_IEC_LTI:
        return (curve_def_t){120.0f, 0.0f, 1.0f, 0.0f};
    case TOC_IEEE_MI:
        return (curve_def_t){0.0515f, 0.1140f, 0.02f, 4.85f};
    case TOC_IEEE_VI:
        return (curve_def_t){19.61f, 0.491f, 2.0f, 21.6f};
    case TOC_IEEE_EI:
        return (curve_def_t){28.2f, 0.1217f, 2.0f, 29.1f};
    case TOC_IEC_SI:
    case TOC_DEFINITE:
    default:
        return (curve_def_t){0.14f, 0.0f, 0.02f, 0.0f};
    }
}

float toc_operate_time(const toc_settings_t *s, float multiple)
{
    if (s == NULL || multiple <= 1.0f) {
        return -1.0f;
    }
    if (s->curve == TOC_DEFINITE) {
        return s->definite_s;
    }
    float m = multiple > TOC_MAX_MULTIPLE ? TOC_MAX_MULTIPLE : multiple;
    curve_def_t c = curve_def(s->curve);
    float denom = powf(m, c.p) - 1.0f;
    if (denom <= 1e-6f) {
        return -1.0f;
    }
    return s->tms * (c.a / denom + c.b);
}

float toc_reset_time(const toc_settings_t *s, float multiple)
{
    if (s == NULL || s->curve == TOC_DEFINITE) {
        return 0.0f;
    }
    curve_def_t c = curve_def(s->curve);
    if (c.tr <= 0.0f || multiple >= 1.0f) {
        return 0.0f;
    }
    return s->tms * c.tr / (1.0f - multiple * multiple);
}

void toc_init(toc_state_t *st)
{
    st->accum = 0.0f;
    st->picked_up = false;
    st->operated = false;
}

bool toc_step(const toc_settings_t *s, toc_state_t *st, float i_mag, float dt_s)
{
    if (s == NULL || st == NULL || s->pickup_a <= 0.0f) {
        return false;
    }
    float m = i_mag / s->pickup_a;

    if (m > 1.0f) {
        st->picked_up = true;
        float t_op = toc_operate_time(s, m);
        if (t_op > 0.0f) {
            st->accum += dt_s / t_op;
        }
        if (st->accum >= 1.0f) {
            st->accum = 1.0f;
            st->operated = true;
        }
        return st->operated;
    }

    if (m >= TOC_DROPOUT_RATIO && st->picked_up) {
        /* Between dropout and pickup: hold the accumulator. */
        return st->operated;
    }

    st->picked_up = false;
    st->operated = false;
    float t_reset = toc_reset_time(s, m);
    if (t_reset > 0.0f) {
        st->accum -= dt_s / t_reset;
        if (st->accum < 0.0f) {
            st->accum = 0.0f;
        }
    } else {
        st->accum = 0.0f;
    }
    return false;
}

void ioc_init(ioc_state_t *st)
{
    st->count = 0u;
    st->operated = false;
}

bool ioc_step(const ioc_settings_t *s, ioc_state_t *st, float i_mag)
{
    if (s == NULL || st == NULL || s->pickup_a <= 0.0f) {
        return false;
    }
    if (i_mag > s->pickup_a) {
        if (st->count < UINT8_MAX) {
            st->count++;
        }
        if (st->count >= s->security_passes) {
            st->operated = true;
        }
    } else if (i_mag < s->pickup_a * TOC_DROPOUT_RATIO) {
        st->count = 0u;
        st->operated = false;
    }
    return st->operated;
}

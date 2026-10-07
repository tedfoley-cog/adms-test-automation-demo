/* Single-precision complex arithmetic for phasor work on the Cortex-M4F FPU.
 * Header-only and branch-free so every call has a fixed instruction count. */
#ifndef CPLX_H
#define CPLX_H

#include <math.h>

typedef struct {
    float re;
    float im;
} cplx_t;

#define CPLX_PI      3.14159265358979f
#define CPLX_TWO_PI  6.28318530717959f
#define CPLX_SQRT2   1.41421356237310f

static inline cplx_t cplx(float re, float im)
{
    cplx_t z = {re, im};
    return z;
}

static inline cplx_t cplx_polar(float mag, float ang)
{
    return cplx(mag * cosf(ang), mag * sinf(ang));
}

static inline cplx_t cplx_add(cplx_t a, cplx_t b) { return cplx(a.re + b.re, a.im + b.im); }
static inline cplx_t cplx_sub(cplx_t a, cplx_t b) { return cplx(a.re - b.re, a.im - b.im); }
static inline cplx_t cplx_scale(cplx_t a, float k) { return cplx(a.re * k, a.im * k); }
static inline cplx_t cplx_conj(cplx_t a) { return cplx(a.re, -a.im); }

static inline cplx_t cplx_mul(cplx_t a, cplx_t b)
{
    return cplx(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
}

static inline float cplx_abs2(cplx_t a) { return a.re * a.re + a.im * a.im; }
static inline float cplx_abs(cplx_t a) { return sqrtf(cplx_abs2(a)); }
static inline float cplx_arg(cplx_t a) { return atan2f(a.im, a.re); }

/* a / b; returns 0 when |b| is below `eps` instead of producing inf/NaN. */
static inline cplx_t cplx_div_safe(cplx_t a, cplx_t b, float eps)
{
    float d = cplx_abs2(b);
    if (d < eps * eps) {
        return cplx(0.0f, 0.0f);
    }
    cplx_t n = cplx_mul(a, cplx_conj(b));
    return cplx(n.re / d, n.im / d);
}

#endif /* CPLX_H */

#include "symcomp.h"

#define HALF        0.5f
#define SQRT3_OVER2 0.866025403784439f

cplx_t symcomp_a(void) { return cplx(-HALF, SQRT3_OVER2); }
cplx_t symcomp_a2(void) { return cplx(-HALF, -SQRT3_OVER2); }

symcomp_t symcomp_from_abc(cplx_t a, cplx_t b, cplx_t c)
{
    const float third = 1.0f / 3.0f;
    cplx_t op_a = symcomp_a();
    cplx_t op_a2 = symcomp_a2();
    symcomp_t s;

    s.zero = cplx_scale(cplx_add(cplx_add(a, b), c), third);
    s.pos = cplx_scale(cplx_add(cplx_add(a, cplx_mul(op_a, b)), cplx_mul(op_a2, c)), third);
    s.neg = cplx_scale(cplx_add(cplx_add(a, cplx_mul(op_a2, b)), cplx_mul(op_a, c)), third);
    return s;
}

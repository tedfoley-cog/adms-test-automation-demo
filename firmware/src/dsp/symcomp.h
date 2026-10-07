/* Symmetrical components (Fortescue), phase A reference. */
#ifndef SYMCOMP_H
#define SYMCOMP_H

#include "cplx.h"

typedef struct {
    cplx_t zero;
    cplx_t pos;
    cplx_t neg;
} symcomp_t;

/* The rotation operator a = 1 /_ 120 deg and a^2 = 1 /_ 240 deg. */
cplx_t symcomp_a(void);
cplx_t symcomp_a2(void);

symcomp_t symcomp_from_abc(cplx_t a, cplx_t b, cplx_t c);

#endif /* SYMCOMP_H */

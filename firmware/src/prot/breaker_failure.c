#include "breaker_failure.h"

#include <stddef.h>

void bf_init(bf_state_t *st)
{
    st->initiated = false;
    st->start_s = 0.0f;
    st->retrip = false;
    st->bus_trip = false;
    st->elapsed_s = 0.0f;
}

static bool current_detected(const bf_settings_t *s, const float iph[3])
{
    return iph[0] > s->pickup_a || iph[1] > s->pickup_a || iph[2] > s->pickup_a;
}

void bf_step(const bf_settings_t *s, bf_state_t *st, bool bfi, const float iph[3], float now_s)
{
    if (s == NULL || st == NULL || iph == NULL) {
        return;
    }

    bool current = current_detected(s, iph);

    if (bfi && current && !st->initiated) {
        st->initiated = true;
        st->start_s = now_s;
        st->elapsed_s = 0.0f;
    }

    if (!st->initiated) {
        return;
    }

    if (!current) {
        /* Breaker has interrupted: BF drops out; the bus trip stays latched. */
        st->initiated = false;
        st->retrip = false;
        return;
    }

    st->elapsed_s = now_s - st->start_s;
    if (st->elapsed_s >= s->retrip_delay_s) {
        st->retrip = true;
    }
    if (st->elapsed_s >= s->bf_delay_s) {
        st->bus_trip = true;
    }
}

void bf_reset(bf_state_t *st)
{
    if (st != NULL) {
        bf_init(st);
    }
}

#include "trip_matrix.h"

#include <stddef.h>

static const char *const k_elem_names[ELEM_COUNT] = {
    "50P", "50G", "51P", "51G", "21Z1", "21Z2", "81U", "81O", "81R", "50BF-RT", "50BF-86B",
};

const char *elem_name(elem_id_t e)
{
    if ((unsigned)e >= (unsigned)ELEM_COUNT) {
        return "?";
    }
    return k_elem_names[e];
}

void trip_matrix_init(trip_matrix_state_t *st)
{
    st->operated = 0u;
    st->rising = 0u;
    st->target = 0u;
    st->trip1 = false;
    st->tripb = false;
    st->trip1_count = 0u;
}

void trip_matrix_step(const trip_matrix_settings_t *s, trip_matrix_state_t *st,
                      elem_mask_t operated, bool breaker_open, bool current_present)
{
    if (s == NULL || st == NULL) {
        return;
    }
    st->rising = (elem_mask_t)(operated & (elem_mask_t)~st->operated);
    st->operated = operated;

    bool trip1_request = (operated & s->trip1_mask) != 0u;
    if (trip1_request && !st->trip1) {
        st->trip1 = true;
        st->trip1_count++;
        if (st->target == 0u) {
            st->target = (elem_mask_t)(operated & s->trip1_mask);
        }
    } else if (!trip1_request && st->trip1 && breaker_open && !current_present) {
        st->trip1 = false;
    }

    if ((operated & s->tripb_mask) != 0u && !st->tripb) {
        st->tripb = true;
        st->target |= (elem_mask_t)(operated & s->tripb_mask);
    }
}

void trip_matrix_reset_lockout(trip_matrix_state_t *st)
{
    if (st != NULL) {
        st->tripb = false;
        st->target = 0u;
    }
}

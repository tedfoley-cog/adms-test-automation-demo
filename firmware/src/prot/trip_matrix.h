/* Trip matrix and output logic.
 *
 * Maps element operate signals onto the two trip outputs of the IED:
 *   TRIP1  feeder breaker (52) trip coil, sealed in until the breaker opens
 *          and current has gone, then released;
 *   TRIPB  bus lockout (86B), driven by breaker failure only, latched until
 *          a deliberate reset.
 * Also latches the first-operated element as the front-panel target and
 * reports rising edges so the event recorder can time-tag them.
 */
#ifndef TRIP_MATRIX_H
#define TRIP_MATRIX_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    ELEM_50P = 0,
    ELEM_50G,
    ELEM_51P,
    ELEM_51G,
    ELEM_21Z1,
    ELEM_21Z2,
    ELEM_81U,
    ELEM_81O,
    ELEM_81R,
    ELEM_50BF_RETRIP,
    ELEM_50BF_BUS,
    ELEM_COUNT
} elem_id_t;

typedef uint16_t elem_mask_t;

#define ELEM_BIT(e) ((elem_mask_t)(1u << (e)))

typedef struct {
    elem_mask_t trip1_mask;   /* elements routed to TRIP1 */
    elem_mask_t tripb_mask;   /* elements routed to the 86B bus lockout */
} trip_matrix_settings_t;

typedef struct {
    elem_mask_t operated;     /* this pass */
    elem_mask_t rising;       /* edges since the previous pass */
    elem_mask_t target;       /* latched first-trip target(s) */
    bool trip1;
    bool tripb;               /* 86B latched */
    uint32_t trip1_count;
} trip_matrix_state_t;

void trip_matrix_init(trip_matrix_state_t *st);

/* `breaker_open` is 52b; `current_present` is the BF current detector. */
void trip_matrix_step(const trip_matrix_settings_t *s, trip_matrix_state_t *st,
                      elem_mask_t operated, bool breaker_open, bool current_present);

void trip_matrix_reset_lockout(trip_matrix_state_t *st);

const char *elem_name(elem_id_t e);

#endif /* TRIP_MATRIX_H */

/* Autoreclose sequence control for a feeder recloser. */
#ifndef RECLOSER_H
#define RECLOSER_H

#include "relay_types.h"

#define RECLOSER_MAX_SHOTS 4

typedef enum {
    RECLOSER_CLOSED = 0,
    RECLOSER_TRIPPED,
    RECLOSER_RECLOSE_WAIT,
    RECLOSER_LOCKOUT
} recloser_state_t;

typedef struct {
    uint8_t shots_to_lockout;                 /* number of reclose attempts */
    uint32_t dead_time_ms[RECLOSER_MAX_SHOTS];/* per-shot dead time */
    uint32_t reclaim_time_ms;                 /* healthy time before reset */
    bool cold_load_pickup_enabled;
} recloser_config_t;

typedef struct {
    recloser_state_t state;
    uint8_t shot_count;
    uint32_t state_entered_ms;
    uint32_t last_trip_ms;
    bool close_command;
    bool trip_command;
} recloser_status_t;

void recloser_init(recloser_status_t *status);

/* Advance the sequence by one scan.
 * `trip` is the protection trip signal for this scan, `now_ms` the scan clock. */
void recloser_step(const recloser_config_t *config,
                   recloser_status_t *status,
                   bool trip,
                   uint32_t now_ms);

/* Operator-initiated lockout reset; refused while a trip is asserted. */
bool recloser_reset_lockout(recloser_status_t *status, bool trip_asserted);

#endif /* RECLOSER_H */

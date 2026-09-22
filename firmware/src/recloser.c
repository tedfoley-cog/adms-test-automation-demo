#include "recloser.h"

#include <stddef.h>

static void enter_state(recloser_status_t *status, recloser_state_t next, uint32_t now_ms)
{
    status->state = next;
    status->state_entered_ms = now_ms;
}

void recloser_init(recloser_status_t *status)
{
    if (status == NULL) {
        return;
    }
    status->state = RECLOSER_CLOSED;
    status->shot_count = 0U;
    status->state_entered_ms = 0U;
    status->last_trip_ms = 0U;
    status->close_command = false;
    status->trip_command = false;
}

static uint32_t dead_time_for_shot(const recloser_config_t *config, uint8_t shot)
{
    if (shot >= RECLOSER_MAX_SHOTS) {
        return config->dead_time_ms[RECLOSER_MAX_SHOTS - 1];
    }
    return config->dead_time_ms[shot];
}

void recloser_step(const recloser_config_t *config,
                   recloser_status_t *status,
                   bool trip,
                   uint32_t now_ms)
{
    if (config == NULL || status == NULL) {
        return;
    }

    status->trip_command = false;
    status->close_command = false;

    switch (status->state) {
    case RECLOSER_CLOSED:
        if (trip) {
            status->trip_command = true;
            status->last_trip_ms = now_ms;
            if (status->shot_count >= config->shots_to_lockout) {
                enter_state(status, RECLOSER_LOCKOUT, now_ms);
            } else {
                enter_state(status, RECLOSER_TRIPPED, now_ms);
            }
        } else if (status->shot_count > 0U &&
                   (now_ms - status->state_entered_ms) >= config->reclaim_time_ms) {
            status->shot_count = 0U;
        }
        break;

    case RECLOSER_TRIPPED:
        enter_state(status, RECLOSER_RECLOSE_WAIT, now_ms);
        break;

    case RECLOSER_RECLOSE_WAIT:
        if (trip) {
            /* Fault still present while open: treat as an additional operation. */
            status->last_trip_ms = now_ms;
            enter_state(status, RECLOSER_LOCKOUT, now_ms);
        } else if ((now_ms - status->state_entered_ms) >=
                   dead_time_for_shot(config, status->shot_count)) {
            status->shot_count++;
            status->close_command = true;
            enter_state(status, RECLOSER_CLOSED, now_ms);
        }
        break;

    case RECLOSER_LOCKOUT:
    default:
        break;
    }
}

bool recloser_reset_lockout(recloser_status_t *status, bool trip_asserted)
{
    if (status == NULL || status->state != RECLOSER_LOCKOUT || trip_asserted) {
        return false;
    }
    status->state = RECLOSER_CLOSED;
    status->shot_count = 0U;
    status->close_command = true;
    return true;
}

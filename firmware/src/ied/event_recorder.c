#include "event_recorder.h"

#include <stddef.h>

void soe_init(soe_ring_t *r)
{
    r->head = 0u;
    r->tail = 0u;
    r->lost = 0u;
}

void soe_record(soe_ring_t *r, const soe_event_t *ev)
{
    if (r->head - r->tail >= SOE_CAPACITY) {
        r->lost++;
        return;
    }
    r->slot[r->head % SOE_CAPACITY] = *ev;
    r->head++;
}

bool soe_pop(soe_ring_t *r, soe_event_t *out)
{
    if (r->head == r->tail) {
        return false;
    }
    *out = r->slot[r->tail % SOE_CAPACITY];
    r->tail++;
    return true;
}

const char *soe_code_name(uint16_t code)
{
    switch ((soe_code_t)code) {
    case SOE_ELEMENT_OPERATE:
        return "OPERATE";
    case SOE_ELEMENT_RESET:
        return "RESET";
    case SOE_TRIP1_ON:
        return "TRIP1";
    case SOE_TRIP1_OFF:
        return "TRIP1_OFF";
    case SOE_TRIPB_ON:
        return "86B_BUS_TRIP";
    case SOE_BREAKER_OPEN:
        return "52_OPEN";
    case SOE_BREAKER_CLOSED:
        return "52_CLOSED";
    case SOE_PPS_LOCK:
        return "PPS_LOCK";
    case SOE_PPS_LOST:
        return "PPS_LOST";
    case SOE_TASK_OVERRUN:
        return "TASK_OVERRUN";
    default:
        return "?";
    }
}

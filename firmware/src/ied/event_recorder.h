/* Sequence-of-events recorder: time-tagged element and output transitions,
 * held in a fixed ring until the comms task drains them. */
#ifndef EVENT_RECORDER_H
#define EVENT_RECORDER_H

#include <stdbool.h>
#include <stdint.h>

#define SOE_CAPACITY 64u

typedef enum {
    SOE_ELEMENT_OPERATE = 1,
    SOE_ELEMENT_RESET,
    SOE_TRIP1_ON,
    SOE_TRIP1_OFF,
    SOE_TRIPB_ON,
    SOE_BREAKER_OPEN,
    SOE_BREAKER_CLOSED,
    SOE_PPS_LOCK,
    SOE_PPS_LOST,
    SOE_TASK_OVERRUN
} soe_code_t;

typedef struct {
    uint32_t soc;
    uint32_t usec;             /* microseconds into the UTC second */
    uint32_t tick;
    uint16_t code;             /* soe_code_t */
    uint16_t detail;           /* element id / loop mask / task id */
    float value;               /* measured quantity at the event */
} soe_event_t;

typedef struct {
    soe_event_t slot[SOE_CAPACITY];
    uint32_t head;
    uint32_t tail;
    uint32_t lost;
} soe_ring_t;

void soe_init(soe_ring_t *r);
void soe_record(soe_ring_t *r, const soe_event_t *ev);
bool soe_pop(soe_ring_t *r, soe_event_t *out);
const char *soe_code_name(uint16_t code);

#endif /* EVENT_RECORDER_H */

/* Host implementation of the platform cycle counter: nanoseconds from the
 * monotonic clock. Only the Cortex-M target (DWT->CYCCNT) produces numbers
 * that are compared against the cycle budgets. */
#define _POSIX_C_SOURCE 199309L

#include "cycle_stats.h"

#include <time.h>

uint32_t rt_cycles(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec);
}

/* Per-task execution-time accounting against a fixed cycle budget.
 *
 * The platform supplies `rt_cycles()`: DWT->CYCCNT on the Cortex-M target, a
 * monotonic counter on the host. Statistics are integer-only so recording a
 * sample costs a handful of cycles and never touches the FPU context.
 */
#ifndef CYCLE_STATS_H
#define CYCLE_STATS_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    RT_TASK_ACQ = 0,   /* sample acquisition ISR, 1920 Hz */
    RT_TASK_PROT,      /* protection pass, 480 Hz */
    RT_TASK_PMU,       /* synchrophasor estimation and framing, 60 Hz */
    RT_TASK_COMMS,     /* DNP3 point refresh and diagnostics, 120 Hz */
    RT_NUM_TASKS
} rt_task_id_t;

typedef struct {
    const char *name;
    uint32_t rate_hz;
    uint32_t budget_cycles;
    uint32_t runs;
    uint32_t min_cycles;
    uint32_t max_cycles;
    uint64_t total_cycles;
    uint32_t budget_overruns;  /* runs that exceeded budget_cycles */
} rt_task_stats_t;

/* Platform hook: free-running 32-bit cycle counter. */
uint32_t rt_cycles(void);

void cycle_stats_init(void);
rt_task_stats_t *cycle_stats_task(rt_task_id_t id);

/* Record one execution of `id` that started at `start` (an rt_cycles() value).
 * Wrap of the 32-bit counter is handled by unsigned subtraction. */
uint32_t cycle_stats_record(rt_task_id_t id, uint32_t start);

uint32_t cycle_stats_mean(const rt_task_stats_t *stats);

/* Worst-case CPU utilisation in parts per million: sum over tasks of
 * max_cycles * rate_hz / cpu_hz. */
uint32_t cycle_stats_worst_case_util_ppm(uint32_t cpu_hz);

bool cycle_stats_within_budget(void);

#endif /* CYCLE_STATS_H */

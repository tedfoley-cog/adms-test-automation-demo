#include "cycle_stats.h"

#include "ied_config.h"

#include <stddef.h>

static rt_task_stats_t s_tasks[RT_NUM_TASKS];

void cycle_stats_init(void)
{
    static const struct {
        const char *name;
        uint32_t rate_hz;
        uint32_t budget;
    } table[RT_NUM_TASKS] = {
        [RT_TASK_ACQ] = {"acq_isr", IED_SAMPLE_RATE_HZ, IED_BUDGET_ACQ_CYCLES},
        [RT_TASK_PROT] = {"protection", IED_PROT_RATE_HZ, IED_BUDGET_PROT_CYCLES},
        [RT_TASK_PMU] = {"pmu", IED_PMU_RATE_HZ, IED_BUDGET_PMU_CYCLES},
        [RT_TASK_COMMS] = {"comms", IED_SAMPLE_RATE_HZ / IED_COMMS_DECIMATION,
                           IED_BUDGET_COMMS_CYCLES},
    };

    for (size_t i = 0; i < RT_NUM_TASKS; i++) {
        s_tasks[i].name = table[i].name;
        s_tasks[i].rate_hz = table[i].rate_hz;
        s_tasks[i].budget_cycles = table[i].budget;
        s_tasks[i].runs = 0u;
        s_tasks[i].min_cycles = UINT32_MAX;
        s_tasks[i].max_cycles = 0u;
        s_tasks[i].total_cycles = 0u;
        s_tasks[i].budget_overruns = 0u;
    }
}

rt_task_stats_t *cycle_stats_task(rt_task_id_t id)
{
    if ((unsigned)id >= (unsigned)RT_NUM_TASKS) {
        return NULL;
    }
    return &s_tasks[id];
}

uint32_t cycle_stats_record(rt_task_id_t id, uint32_t start)
{
    uint32_t elapsed = rt_cycles() - start;
    rt_task_stats_t *t = cycle_stats_task(id);
    if (t == NULL) {
        return elapsed;
    }
    t->runs++;
    t->total_cycles += elapsed;
    if (elapsed < t->min_cycles) {
        t->min_cycles = elapsed;
    }
    if (elapsed > t->max_cycles) {
        t->max_cycles = elapsed;
    }
    if (elapsed > t->budget_cycles) {
        t->budget_overruns++;
    }
    return elapsed;
}

uint32_t cycle_stats_mean(const rt_task_stats_t *stats)
{
    if (stats == NULL || stats->runs == 0u) {
        return 0u;
    }
    return (uint32_t)(stats->total_cycles / stats->runs);
}

uint32_t cycle_stats_worst_case_util_ppm(uint32_t cpu_hz)
{
    uint64_t acc = 0u;
    for (size_t i = 0; i < RT_NUM_TASKS; i++) {
        acc += (uint64_t)s_tasks[i].max_cycles * s_tasks[i].rate_hz;
    }
    return (uint32_t)((acc * 1000000u) / cpu_hz);
}

bool cycle_stats_within_budget(void)
{
    for (size_t i = 0; i < RT_NUM_TASKS; i++) {
        if (s_tasks[i].budget_overruns != 0u) {
            return false;
        }
    }
    return true;
}

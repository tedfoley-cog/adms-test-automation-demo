/* STM32F407 target for the feeder IED.
 *
 * TIM2 is the sample clock (1920 Hz, reload trimmed every period by the PPS
 * discipline loop). Its ISR stands in for the end-of-conversion DMA interrupt
 * of the simultaneous-sampling ADC: the on-chip test set produces the seven
 * channel samples and the IED acquisition ISR consumes them. Protection and
 * PMU work runs in two lower-priority software interrupts so the sample ISR
 * always preempts them; DNP3 / SOE / UART reporting runs in thread mode.
 *
 * Under Renode the harness selects a scenario by writing g_harness before the
 * core starts (tools/run_renode.py). Every task's execution time is measured
 * with DWT->CYCCNT from scenario time 0 (after the warm-up preroll) and
 * printed as TIMING lines when the scenario ends.
 */
#include "c37118.h"
#include "cycle_stats.h"
#include "ied_app.h"
#include "stm32f4_regs.h"
#include "testset.h"

#include <stdio.h>
#include <string.h>

#define HARNESS_MAGIC  0x49454421u /* "IED!" */
#define PREROLL_S      3u
#define SOC_AT_BOOT    1790000000u
#define PRIO_SAMPLE    0x00u
#define PRIO_PROT      0x40u
#define PRIO_PMU       0x80u

typedef struct {
    uint32_t magic;
    uint32_t scenario;      /* index into the test-set scenario table */
    uint32_t uptime_s;      /* relay uptime preset (fast-forward) */
    int32_t freq_mhz;       /* system frequency override, 0 = scenario default */
    uint32_t duration_ms;   /* scenario duration override, 0 = default */
} harness_t;

__attribute__((section(".noinit"))) volatile harness_t g_harness;

static testset_t s_ts;
static scenario_t s_sc;
static volatile bool s_done;
static uint32_t s_testset_max_cycles;

/* PMU summaries handed from the PMU interrupt to the thread-mode printer. */
typedef struct {
    uint32_t soc;
    uint32_t fracsec;
    float freq;
    float rocof;
    float v1;
    uint16_t stat;
    uint16_t len;
} pmu_line_t;

#define PMU_Q 16u
static pmu_line_t s_pmu_q[PMU_Q];
static volatile uint32_t s_pmu_head;
static uint32_t s_pmu_tail;
static uint32_t s_pmu_dropped;

uint32_t rt_cycles(void)
{
    return DWT_CYCCNT;
}

/* ------------------------------------------------------------- uart */

static void uart_init(void)
{
    RCC_AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_GPIODEN;
    RCC_APB1ENR |= RCC_APB1ENR_USART2EN;
    /* PA2 = USART2_TX, AF7 */
    GPIOA_MODER = (GPIOA_MODER & ~(3u << 4)) | (2u << 4);
    GPIOA_AFRL = (GPIOA_AFRL & ~(0xFu << 8)) | (7u << 8);
    USART2_BRR = (22u << 4) | 13u; /* 115200 baud from 42 MHz */
    USART2_CR1 = (1u << 13) | (1u << 3); /* UE | TE */
}

static void uart_puts(const char *s)
{
    while (*s != '\0') {
        while ((USART2_SR & USART_SR_TXE) == 0u) {
        }
        USART2_DR = (uint32_t)(uint8_t)*s++;
    }
}

static void uart_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

#include <stdarg.h>
static void uart_printf(const char *fmt, ...)
{
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    uart_puts(line);
}

/* fixed-point float formatting: newlib-nano printf has no %f */
static const char *fx(char *buf, size_t n, float v, int decimals)
{
    int32_t scale = 1;
    for (int k = 0; k < decimals; k++) {
        scale *= 10;
    }
    int64_t q = (int64_t)(v * (float)scale + (v < 0.0f ? -0.5f : 0.5f));
    const char *sign = q < 0 ? "-" : "";
    if (q < 0) {
        q = -q;
    }
    if (decimals == 0) {
        snprintf(buf, n, "%s%ld", sign, (long)q);
    } else {
        snprintf(buf, n, "%s%ld.%0*ld", sign, (long)(q / scale), decimals, (long)(q % scale));
    }
    return buf;
}

/* ------------------------------------------------------------- hooks */

static void on_pmu(const uint8_t *frame, size_t len, const pmu_measurement_t *m, uint32_t soc,
                   uint32_t fracsec, void *ctx)
{
    (void)ctx;
    uint32_t head = s_pmu_head;
    if (head - s_pmu_tail >= PMU_Q) {
        s_pmu_dropped++;
        return;
    }
    pmu_line_t *l = &s_pmu_q[head % PMU_Q];
    l->soc = soc;
    l->fracsec = fracsec;
    l->freq = m->freq_hz;
    l->rocof = m->rocof_hz_s;
    l->v1 = cplx_abs(m->v1);
    l->stat = (uint16_t)((frame[14] << 8) | frame[15]);
    l->len = (uint16_t)len;
    s_pmu_head = head + 1u;
}

static void on_event(const soe_event_t *ev, void *ctx)
{
    (void)ctx;
    char v[24];
    uart_printf("SOE %lu.%06lu tick=%lu %s", (unsigned long)ev->soc, (unsigned long)ev->usec,
                (unsigned long)ev->tick, soe_code_name(ev->code));
    if (ev->code == SOE_ELEMENT_OPERATE) {
        uart_printf(" %s", elem_name((elem_id_t)(ev->detail & 0xFFu)));
        uint8_t loops = (uint8_t)(ev->detail >> 8);
        for (int l = 0; l < DIST_LOOP_COUNT; l++) {
            if ((loops & (1u << l)) != 0u) {
                uart_printf(" %s", distance_loop_name((distance_loop_t)l));
            }
        }
    } else if (ev->code == SOE_TRIP1_ON) {
        uart_printf(" target=0x%04x", ev->detail);
    }
    uart_printf(" value=%s\r\n", fx(v, sizeof(v), ev->value, 3));
}

static void drain_pmu(void)
{
    while (s_pmu_tail != s_pmu_head) {
        const pmu_line_t *l = &s_pmu_q[s_pmu_tail % PMU_Q];
        char f[24];
        char r[24];
        char v[24];
        uart_printf("PMU %lu.%06lu f=%s rocof=%s v1=%s stat=0x%04x len=%u\r\n",
                    (unsigned long)l->soc, (unsigned long)(l->fracsec & 0xFFFFFFu),
                    fx(f, sizeof(f), l->freq, 4), fx(r, sizeof(r), l->rocof, 3),
                    fx(v, sizeof(v), l->v1, 1), l->stat, l->len);
        s_pmu_tail++;
    }
}

/* ------------------------------------------------------------- isrs */

void TIM2_IRQHandler(void)
{
    TIM2_SR = 0u;
    if (s_done) {
        return;
    }

    /* Stand-in for the ADC DMA buffer: the test set's sample for this period. */
    uint32_t t0 = DWT_CYCCNT;
    int16_t raw[IED_NUM_CHANNELS];
    const ied_status_t *st = ied_status();
    testset_step(&s_ts, st->trip1, st->tripb, raw);
    ied_set_breaker_open(s_ts.breaker_open || s_ts.bus_dead);
    uint32_t ts_cycles = DWT_CYCCNT - t0;
    if (ts_cycles > s_testset_max_cycles) {
        s_testset_max_cycles = ts_cycles;
    }

    if (s_ts.n == s_ts.preroll_n) {
        /* Scenario time 0: measure only the scenario, not the warm-up. */
        cycle_stats_init();
        s_testset_max_cycles = 0u;
    }

    uint32_t reload = ied_acq_isr(raw);
    TIM2_ARR = reload - 1u;

    if (g_timebase.sample_in_second == 0u) {
        /* Station clock PPS edge, captured on the same timer. */
        ied_pps_isr(TIMEBASE_TIMER_HZ);
    }
    NVIC_ISPR(0) = 1u << IRQ_EXTI1;

    if (testset_done(&s_ts)) {
        s_done = true;
    }
}

void EXTI1_IRQHandler(void)
{
    if (ied_protection_task()) {
        NVIC_ISPR(0) = 1u << IRQ_EXTI2;
    }
}

void EXTI2_IRQHandler(void)
{
    ied_pmu_task();
}

/* ------------------------------------------------------------- init */

static void clock_init(void)
{
    /* HSE 8 MHz -> PLL: M=8, N=336, P=2 -> 168 MHz SYSCLK; Q=7 -> 48 MHz.
     * AHB /1, APB1 /4 (42 MHz, timers 84 MHz), APB2 /2. Bounded waits so an
     * emulator without an RCC model still boots. */
    RCC_CR |= RCC_CR_HSEON;
    for (uint32_t n = 0; n < 100000u && (RCC_CR & RCC_CR_HSERDY) == 0u; n++) {
    }
    RCC_PLLCFGR = 8u | (336u << 6) | (0u << 16) | (1u << 22) | (7u << 24);
    FLASH_ACR = (1u << 8) | (1u << 9) | (1u << 10) | 5u; /* prefetch, I/D cache, 5 WS */
    RCC_CFGR = (5u << 10) | (4u << 13);
    RCC_CR |= RCC_CR_PLLON;
    for (uint32_t n = 0; n < 100000u && (RCC_CR & RCC_CR_PLLRDY) == 0u; n++) {
    }
    RCC_CFGR = (RCC_CFGR & ~3u) | 2u; /* SYSCLK = PLL */
}

static void dwt_init(void)
{
    SCB_DEMCR |= DEMCR_TRCENA;
    DWT_CYCCNT = 0u;
    DWT_CTRL |= DWT_CYCCNTENA;
}

static void sample_timer_init(void)
{
    RCC_APB1ENR |= RCC_APB1ENR_TIM2EN;
    TIM2_PSC = 0u;
    TIM2_ARR = (TIMEBASE_NOMINAL_RELOAD_Q16 >> 16) - 1u;
    TIM2_EGR = 1u;
    TIM2_SR = 0u;
    TIM2_DIER = 1u;

    SCB_AIRCR = (0x05FAu << 16) | (3u << 8); /* 4 bits of preemption priority */
    NVIC_IPR_BYTE(IRQ_TIM2) = PRIO_SAMPLE;
    NVIC_IPR_BYTE(IRQ_EXTI1) = PRIO_PROT;
    NVIC_IPR_BYTE(IRQ_EXTI2) = PRIO_PMU;
    NVIC_ISER(0) = (1u << IRQ_TIM2) | (1u << IRQ_EXTI1) | (1u << IRQ_EXTI2);
    TIM2_CR1 = 1u;
}

static void print_timing(void)
{
    uart_printf("TIMING task=testset rate_hz=%u runs=0 min=0 mean=0 max=%lu budget=0 "
                "overruns=0\r\n",
                IED_SAMPLE_RATE_HZ, (unsigned long)s_testset_max_cycles);
    for (int k = 0; k < RT_NUM_TASKS; k++) {
        const rt_task_stats_t *t = cycle_stats_task((rt_task_id_t)k);
        uart_printf("TIMING task=%s rate_hz=%lu runs=%lu min=%lu mean=%lu max=%lu budget=%lu "
                    "overruns=%lu\r\n",
                    t->name, (unsigned long)t->rate_hz, (unsigned long)t->runs,
                    (unsigned long)(t->runs != 0u ? t->min_cycles : 0u),
                    (unsigned long)cycle_stats_mean(t), (unsigned long)t->max_cycles,
                    (unsigned long)t->budget_cycles, (unsigned long)t->budget_overruns);
    }
    const ied_status_t *st = ied_status();
    uart_printf("UTIL worst_case_ppm=%lu ring_overruns=%lu pmu_overruns=%lu pmu_dropped=%lu\r\n",
                (unsigned long)cycle_stats_worst_case_util_ppm(IED_CPU_HZ),
                (unsigned long)st->ring_overruns, (unsigned long)st->pmu_overruns,
                (unsigned long)s_pmu_dropped);
    uart_printf("RESULT trip1=%d 86B=%d breaker_open=%d bus_dead=%d target=0x%04x\r\n",
                st->trip1, st->tripb, s_ts.breaker_open, s_ts.bus_dead, st->target);
}

int main(void)
{
    clock_init();
    dwt_init();
    uart_init();

    uint32_t idx = 0u;
    uint32_t uptime = 0u;
    if (g_harness.magic == HARNESS_MAGIC) {
        idx = g_harness.scenario;
        uptime = g_harness.uptime_s;
    }
    const scenario_t *base = testset_scenario((int)idx);
    if (base == NULL) {
        base = testset_scenario(0);
    }
    s_sc = *base;
    if (g_harness.magic == HARNESS_MAGIC && g_harness.freq_mhz != 0) {
        s_sc.freq_hz = (float)g_harness.freq_mhz / 1000.0f;
        s_sc.freq_end_hz = s_sc.freq_hz;
    }
    if (g_harness.magic == HARNESS_MAGIC && g_harness.duration_ms != 0u) {
        s_sc.duration_s = (float)g_harness.duration_ms / 1000.0f;
    }

    ied_hooks_t hooks = {on_pmu, on_event, NULL};
    const ied_settings_t *settings = ied_default_settings();
    ied_init(settings, SOC_AT_BOOT, &hooks);
    g_timebase.uptime_s = uptime;
    testset_init(&s_ts, &s_sc, settings->scale);
    testset_set_preroll(&s_ts, PREROLL_S * IED_SAMPLE_RATE_HZ);

    uint8_t cfg[C37118_MAX_CFG];
    size_t cfg_len = ied_pmu_config_frame(cfg, sizeof(cfg));
    uart_printf("BOOT ied stm32f407 cpu_hz=%lu fs=%u scenario=%s uptime_s=%lu cfg2_len=%u\r\n",
                (unsigned long)IED_CPU_HZ, IED_SAMPLE_RATE_HZ, s_sc.name, (unsigned long)uptime,
                (unsigned)cfg_len);

    sample_timer_init();

    uint32_t last_comms_tick = 0u;
    while (!s_done) {
        uint32_t tick = g_timebase.tick;
        if (tick - last_comms_tick >= IED_COMMS_DECIMATION) {
            last_comms_tick = tick;
            ied_comms_task();
        }
        drain_pmu();
    }
    TIM2_CR1 = 0u;
    for (int k = 0; k < 8; k++) {
        ied_comms_task();
    }
    drain_pmu();
    print_timing();
    uart_puts("DONE\r\n");
    for (;;) {
        __asm volatile("wfi");
    }
}

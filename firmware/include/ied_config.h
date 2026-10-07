/* Compile-time configuration of the feeder IED real-time core.
 *
 * Sampling is fixed-rate and disciplined to the station PPS: 32 samples per
 * nominal 60 Hz cycle, 1920 samples per UTC second. Every rate below is an
 * integer divisor of the sample rate so the cyclic schedule repeats exactly
 * once per second and no task ever sees a fractional period.
 */
#ifndef IED_CONFIG_H
#define IED_CONFIG_H

#include <stdint.h>

#define IED_F_NOMINAL_HZ        60.0f
#define IED_SAMPLES_PER_CYCLE   32u
#define IED_SAMPLE_RATE_HZ      1920u
#define IED_SAMPLE_PERIOD_S     (1.0f / (float)IED_SAMPLE_RATE_HZ)

/* Protection pass every 4 samples: 8 passes per cycle, 2.083 ms period. */
#define IED_PROT_DECIMATION     4u
#define IED_PROT_RATE_HZ        (IED_SAMPLE_RATE_HZ / IED_PROT_DECIMATION)
#define IED_PROT_PERIOD_S       ((float)IED_PROT_DECIMATION / (float)IED_SAMPLE_RATE_HZ)

/* Synchrophasor reporting: 60 frames/s, one per nominal cycle. */
#define IED_PMU_RATE_HZ         60u
#define IED_PMU_DECIMATION      (IED_SAMPLE_RATE_HZ / IED_PMU_RATE_HZ)

/* Communications / housekeeping slot: 100 Hz is not a divisor of 1920, so the
 * background slot runs every 16 samples (120 Hz). */
#define IED_COMMS_DECIMATION    16u

/* Target CPU: STM32F407VG, Cortex-M4F at 168 MHz. */
#define IED_CPU_HZ              168000000u
#define IED_CYCLES_PER_SAMPLE   (IED_CPU_HZ / IED_SAMPLE_RATE_HZ)

/* Analog channels, in ADC scan order. */
typedef enum {
    IED_CH_VA = 0,
    IED_CH_VB,
    IED_CH_VC,
    IED_CH_IA,
    IED_CH_IB,
    IED_CH_IC,
    IED_CH_IN,
    IED_NUM_CHANNELS
} ied_channel_t;

/* 16-bit simultaneous-sampling ADC (bipolar, +/-32767 counts full scale). */
#define IED_ADC_FULL_SCALE      32767

/* Worst-case execution budgets in CPU cycles, enforced by the Renode timing
 * run (tools/build_realtime_report.py) and by CI. A task that exceeds its
 * budget fails the build even if every functional test passes. */
#define IED_BUDGET_ACQ_CYCLES       2000u
#define IED_BUDGET_PROT_CYCLES      12000u
#define IED_BUDGET_PMU_CYCLES       30000u
#define IED_BUDGET_COMMS_CYCLES     40000u

#endif /* IED_CONFIG_H */

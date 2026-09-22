/* Overcurrent fault detection and fault passage indication. */
#ifndef FAULT_DETECT_H
#define FAULT_DETECT_H

#include "relay_types.h"

/* Operate time of an IEC 60255-151 inverse-time element.
 * Returns -1.0 when the measured current does not exceed pickup. */
double oc_operate_time(const oc_setting_t *setting, double measured_amps);

/* Evaluate phase and ground overcurrent elements against one sample. */
trip_decision_t fault_detect_evaluate(const relay_settings_t *settings,
                                      const phasor_sample_t *sample);

/* Fault passage indicator latch: asserts once fault current is seen and
 * holds until the feeder is re-energised and the reset timer expires. */
typedef struct {
    bool asserted;
    uint32_t asserted_at_ms;
    uint32_t reset_delay_ms;
    double threshold_amps;
} fpi_state_t;

void fpi_init(fpi_state_t *fpi, double threshold_amps, uint32_t reset_delay_ms);
void fpi_update(fpi_state_t *fpi, const phasor_sample_t *sample, bool feeder_energised);

#endif /* FAULT_DETECT_H */

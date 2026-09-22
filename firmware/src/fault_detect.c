#include "fault_detect.h"

#include <math.h>
#include <stddef.h>

/* IEC 60255-151 curve constants: t = TMS * k / ((I/Is)^alpha - 1) */
typedef struct {
    double k;
    double alpha;
} curve_constants_t;

static curve_constants_t curve_constants(curve_type_t curve)
{
    curve_constants_t c;
    switch (curve) {
    case CURVE_VERY_INVERSE:
        c.k = 13.5;
        c.alpha = 1.0;
        break;
    case CURVE_EXTREMELY_INVERSE:
        c.k = 80.0;
        c.alpha = 2.0;
        break;
    case CURVE_STANDARD_INVERSE:
    default:
        c.k = 0.14;
        c.alpha = 0.02;
        break;
    }
    return c;
}

double oc_operate_time(const oc_setting_t *setting, double measured_amps)
{
    if (setting == NULL || setting->pickup_amps <= 0.0) {
        return -1.0;
    }
    if (measured_amps <= setting->pickup_amps) {
        return -1.0;
    }
    if (setting->curve == CURVE_DEFINITE_TIME) {
        return setting->definite_time_s;
    }

    curve_constants_t c = curve_constants(setting->curve);
    double ratio = measured_amps / setting->pickup_amps;
    double denominator = pow(ratio, c.alpha) - 1.0;
    if (denominator <= 1e-9) {
        return -1.0;
    }
    return setting->time_dial * c.k / denominator;
}

static double max_phase_current(const phasor_sample_t *sample)
{
    double m = sample->ia_amps;
    if (sample->ib_amps > m) {
        m = sample->ib_amps;
    }
    if (sample->ic_amps > m) {
        m = sample->ic_amps;
    }
    return m;
}

trip_decision_t fault_detect_evaluate(const relay_settings_t *settings,
                                      const phasor_sample_t *sample)
{
    trip_decision_t decision = {false, TRIP_NONE, ELEMENT_NONE, 0.0, 0.0};
    if (settings == NULL || sample == NULL) {
        return decision;
    }

    double iphase = max_phase_current(sample);
    double iground = sample->in_amps;

    if (iphase > settings->phase_inst.pickup_amps &&
        settings->phase_inst.pickup_amps > 0.0) {
        decision.tripped = true;
        decision.kind = TRIP_INSTANTANEOUS;
        decision.element = ELEMENT_50P;
        decision.operate_time_s = settings->phase_inst.definite_time_s;
        decision.measured_amps = iphase;
        return decision;
    }

    if (iground > settings->ground_inst.pickup_amps &&
        settings->ground_inst.pickup_amps > 0.0) {
        decision.tripped = true;
        decision.kind = TRIP_INSTANTANEOUS;
        decision.element = ELEMENT_50G;
        decision.operate_time_s = settings->ground_inst.definite_time_s;
        decision.measured_amps = iground;
        return decision;
    }

    double t_phase = oc_operate_time(&settings->phase_toc, iphase);
    double t_ground = oc_operate_time(&settings->ground_toc, iground);

    if (t_phase >= 0.0 && (t_ground < 0.0 || t_phase <= t_ground)) {
        decision.tripped = true;
        decision.kind = TRIP_TIME_DELAYED;
        decision.element = ELEMENT_51P;
        decision.operate_time_s = t_phase;
        decision.measured_amps = iphase;
    } else if (t_ground >= 0.0) {
        decision.tripped = true;
        decision.kind = TRIP_TIME_DELAYED;
        decision.element = ELEMENT_51G;
        decision.operate_time_s = t_ground;
        decision.measured_amps = iground;
    }

    return decision;
}

void fpi_init(fpi_state_t *fpi, double threshold_amps, uint32_t reset_delay_ms)
{
    if (fpi == NULL) {
        return;
    }
    fpi->asserted = false;
    fpi->asserted_at_ms = 0U;
    fpi->reset_delay_ms = reset_delay_ms;
    fpi->threshold_amps = threshold_amps;
}

void fpi_update(fpi_state_t *fpi, const phasor_sample_t *sample, bool feeder_energised)
{
    if (fpi == NULL || sample == NULL) {
        return;
    }

    double iphase = max_phase_current(sample);
    if (!fpi->asserted) {
        if (iphase >= fpi->threshold_amps) {
            fpi->asserted = true;
            fpi->asserted_at_ms = sample->timestamp_ms;
        }
        return;
    }

    if (feeder_energised &&
        (sample->timestamp_ms - fpi->asserted_at_ms) >= fpi->reset_delay_ms &&
        iphase < fpi->threshold_amps) {
        fpi->asserted = false;
        fpi->asserted_at_ms = 0U;
    }
}

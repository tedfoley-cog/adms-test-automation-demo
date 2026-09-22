/* Shared types for the feeder protection relay application.
 *
 * Application code targets a software-defined protection & control platform:
 * the protection core runs on a real-time partition, the DNP3 outstation and
 * diagnostics run on a separate platform partition.
 */
#ifndef RELAY_TYPES_H
#define RELAY_TYPES_H

#include <stdbool.h>
#include <stdint.h>

#define RELAY_MAX_ANALOG_POINTS 16
#define RELAY_MAX_BINARY_POINTS 16

/* IEC 60255-151 inverse-time characteristic families. */
typedef enum {
    CURVE_STANDARD_INVERSE = 0,
    CURVE_VERY_INVERSE = 1,
    CURVE_EXTREMELY_INVERSE = 2,
    CURVE_DEFINITE_TIME = 3
} curve_type_t;

/* Protection element identifiers use ANSI device numbers. */
typedef enum {
    ELEMENT_NONE = 0,
    ELEMENT_50P = 50,  /* instantaneous phase overcurrent */
    ELEMENT_51P = 51,  /* time overcurrent, phase */
    ELEMENT_50G = 150, /* instantaneous ground overcurrent */
    ELEMENT_51G = 151  /* time overcurrent, ground */
} element_id_t;

typedef struct {
    double pickup_amps;   /* Is, primary amps */
    double time_dial;     /* TMS */
    curve_type_t curve;
    double definite_time_s;
} oc_setting_t;

typedef struct {
    oc_setting_t phase_inst;
    oc_setting_t phase_toc;
    oc_setting_t ground_inst;
    oc_setting_t ground_toc;
    double ct_ratio;
} relay_settings_t;

typedef struct {
    double ia_amps;
    double ib_amps;
    double ic_amps;
    double in_amps;      /* residual / neutral current */
    double vll_kv;
    uint32_t timestamp_ms;
} phasor_sample_t;

typedef enum {
    TRIP_NONE = 0,
    TRIP_INSTANTANEOUS,
    TRIP_TIME_DELAYED
} trip_kind_t;

typedef struct {
    bool tripped;
    trip_kind_t kind;
    element_id_t element;
    double operate_time_s;
    double measured_amps;
} trip_decision_t;

#endif /* RELAY_TYPES_H */

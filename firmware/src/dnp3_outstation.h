/* Minimal DNP3 outstation point map and static (class 0) response encoding.
 *
 * Object groups follow IEEE 1815: group 1 variation 1 (single-bit binary input),
 * group 1 variation 2 (binary input with flags), group 30 variation 1 (32-bit
 * analog input with flags).
 */
#ifndef DNP3_OUTSTATION_H
#define DNP3_OUTSTATION_H

#include "relay_types.h"

#include <stddef.h>

/* IEEE 1815 quality flag bits shared by binary and analog inputs. */
#define DNP3_FLAG_ONLINE 0x01u
#define DNP3_FLAG_RESTART 0x02u
#define DNP3_FLAG_COMM_LOST 0x04u
#define DNP3_FLAG_OVER_RANGE 0x20u
#define DNP3_FLAG_STATE 0x80u

typedef struct {
    bool value;
    uint8_t flags;
    bool assigned_class1;
} dnp3_binary_point_t;

typedef struct {
    int32_t value;
    uint8_t flags;
    double scale; /* engineering units per count */
} dnp3_analog_point_t;

typedef struct {
    dnp3_binary_point_t binary[RELAY_MAX_BINARY_POINTS];
    dnp3_analog_point_t analog[RELAY_MAX_ANALOG_POINTS];
    size_t binary_count;
    size_t analog_count;
    bool restart_pending;
} dnp3_outstation_t;

void dnp3_init(dnp3_outstation_t *out, size_t binary_count, size_t analog_count);

/* Update a binary input; returns false when the index is out of range. */
bool dnp3_set_binary(dnp3_outstation_t *out, size_t index, bool value, bool online);

/* Update an analog input from an engineering value, applying the point scale
 * and setting the over-range flag when the value clips. */
bool dnp3_set_analog(dnp3_outstation_t *out, size_t index, double engineering_value, bool online);

/* Encode a class 0 (static) read response body into `buffer`.
 * Layout: g1v2 objects for all binary points, then g30v1 for all analog points.
 * Returns the number of bytes written, or 0 when the buffer is too small. */
size_t dnp3_encode_class0(const dnp3_outstation_t *out, uint8_t *buffer, size_t buffer_len);

#endif /* DNP3_OUTSTATION_H */

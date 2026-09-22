#include "dnp3_outstation.h"

#include <math.h>
#include <string.h>

#define ANALOG_MAX 2147483647.0
#define ANALOG_MIN (-2147483648.0)

void dnp3_init(dnp3_outstation_t *out, size_t binary_count, size_t analog_count)
{
    if (out == NULL) {
        return;
    }
    memset(out, 0, sizeof(*out));
    out->binary_count = binary_count > RELAY_MAX_BINARY_POINTS ? RELAY_MAX_BINARY_POINTS
                                                               : binary_count;
    out->analog_count = analog_count > RELAY_MAX_ANALOG_POINTS ? RELAY_MAX_ANALOG_POINTS
                                                               : analog_count;
    out->restart_pending = true;

    for (size_t i = 0; i < out->binary_count; i++) {
        out->binary[i].flags = DNP3_FLAG_ONLINE | DNP3_FLAG_RESTART;
        out->binary[i].assigned_class1 = true;
    }
    for (size_t i = 0; i < out->analog_count; i++) {
        out->analog[i].flags = DNP3_FLAG_ONLINE | DNP3_FLAG_RESTART;
        out->analog[i].scale = 1.0;
    }
}

bool dnp3_set_binary(dnp3_outstation_t *out, size_t index, bool value, bool online)
{
    if (out == NULL || index >= out->binary_count) {
        return false;
    }
    dnp3_binary_point_t *point = &out->binary[index];
    point->value = value;
    point->flags = online ? DNP3_FLAG_ONLINE : DNP3_FLAG_COMM_LOST;
    if (value) {
        point->flags |= DNP3_FLAG_STATE;
    }
    out->restart_pending = false;
    return true;
}

bool dnp3_set_analog(dnp3_outstation_t *out, size_t index, double engineering_value, bool online)
{
    if (out == NULL || index >= out->analog_count) {
        return false;
    }
    dnp3_analog_point_t *point = &out->analog[index];
    double scale = point->scale > 0.0 ? point->scale : 1.0;
    double counts = engineering_value / scale;
    uint8_t flags = online ? DNP3_FLAG_ONLINE : DNP3_FLAG_COMM_LOST;

    if (counts > ANALOG_MAX) {
        counts = ANALOG_MAX;
        flags |= DNP3_FLAG_OVER_RANGE;
    } else if (counts < ANALOG_MIN) {
        counts = ANALOG_MIN;
        flags |= DNP3_FLAG_OVER_RANGE;
    }

    point->value = (int32_t)llround(counts);
    point->flags = flags;
    out->restart_pending = false;
    return true;
}

static void put_u32_le(uint8_t *buffer, int32_t value)
{
    uint32_t raw = (uint32_t)value;
    buffer[0] = (uint8_t)(raw & 0xFFu);
    buffer[1] = (uint8_t)((raw >> 8) & 0xFFu);
    buffer[2] = (uint8_t)((raw >> 16) & 0xFFu);
    buffer[3] = (uint8_t)((raw >> 24) & 0xFFu);
}

size_t dnp3_encode_class0(const dnp3_outstation_t *out, uint8_t *buffer, size_t buffer_len)
{
    if (out == NULL || buffer == NULL) {
        return 0;
    }

    size_t required = 0;
    if (out->binary_count > 0) {
        required += 4 + out->binary_count;            /* header + 1 byte per g1v2 object */
    }
    if (out->analog_count > 0) {
        required += 4 + (out->analog_count * 5);      /* header + flags + int32 per g30v1 */
    }
    if (required == 0 || required > buffer_len) {
        return 0;
    }

    size_t offset = 0;

    if (out->binary_count > 0) {
        buffer[offset++] = 1;    /* group 1: binary input */
        buffer[offset++] = 2;    /* variation 2: with flags */
        buffer[offset++] = 0x00; /* qualifier 0x00: 8-bit start/stop range */
        buffer[offset++] = (uint8_t)(out->binary_count - 1);
        for (size_t i = 0; i < out->binary_count; i++) {
            buffer[offset++] = out->binary[i].flags;
        }
    }

    if (out->analog_count > 0) {
        buffer[offset++] = 30;   /* group 30: analog input */
        buffer[offset++] = 1;    /* variation 1: 32-bit with flags */
        buffer[offset++] = 0x00;
        buffer[offset++] = (uint8_t)(out->analog_count - 1);
        for (size_t i = 0; i < out->analog_count; i++) {
            buffer[offset++] = out->analog[i].flags;
            put_u32_le(&buffer[offset], out->analog[i].value);
            offset += 4;
        }
    }

    return offset;
}

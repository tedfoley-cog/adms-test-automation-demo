#include "test_harness.h"

#include "dnp3_outstation.h"

static void test_point_initialization(void)
{
    TH_CASE("point counts clamp to capacity and points start online with restart");
    dnp3_outstation_t out;
    dnp3_init(NULL, 1U, 1U);
    dnp3_init(&out, RELAY_MAX_BINARY_POINTS + 1U, RELAY_MAX_ANALOG_POINTS + 1U);
    TH_ASSERT(out.binary_count == RELAY_MAX_BINARY_POINTS);
    TH_ASSERT(out.analog_count == RELAY_MAX_ANALOG_POINTS);
    TH_ASSERT(out.restart_pending);
    for (size_t i = 0; i < out.binary_count; i++) {
        TH_ASSERT(!out.binary[i].value && out.binary[i].assigned_class1);
        TH_ASSERT(out.binary[i].flags == (DNP3_FLAG_ONLINE | DNP3_FLAG_RESTART));
    }
    for (size_t i = 0; i < out.analog_count; i++) {
        TH_ASSERT(out.analog[i].value == 0 && out.analog[i].scale == 1.0);
        TH_ASSERT(out.analog[i].flags == (DNP3_FLAG_ONLINE | DNP3_FLAG_RESTART));
    }
}

static void test_updates(void)
{
    TH_CASE("invalid indices and null outstation reject updates");
    dnp3_outstation_t out;
    dnp3_init(&out, 1U, 1U);
    TH_ASSERT(!dnp3_set_binary(NULL, 0U, true, true));
    TH_ASSERT(!dnp3_set_binary(&out, 1U, true, true));
    TH_ASSERT(!dnp3_set_analog(NULL, 0U, 12.0, true));
    TH_ASSERT(!dnp3_set_analog(&out, 1U, 12.0, true));
    TH_ASSERT(out.restart_pending);

    TH_CASE("point updates replace quality and state flags");
    TH_ASSERT(dnp3_set_binary(&out, 0U, true, false));
    TH_ASSERT(out.binary[0].value);
    TH_ASSERT(out.binary[0].flags == (DNP3_FLAG_STATE | DNP3_FLAG_COMM_LOST));
    TH_ASSERT(!out.restart_pending);
    TH_ASSERT(dnp3_set_binary(&out, 0U, false, true));
    TH_ASSERT(!out.binary[0].value && out.binary[0].flags == DNP3_FLAG_ONLINE);

    TH_CASE("analog counts round and clip with explicit quality");
    dnp3_init(&out, 0U, 1U);
    out.analog[0].scale = 2.0;
    TH_ASSERT(dnp3_set_analog(&out, 0U, -5.0, true));
    TH_ASSERT(out.analog[0].value == -3 && out.analog[0].flags == DNP3_FLAG_ONLINE);
    TH_ASSERT(!out.restart_pending);
    out.analog[0].scale = 0.0;
    TH_ASSERT(dnp3_set_analog(&out, 0U, 9.0, true));
    TH_ASSERT(out.analog[0].value == 9 && out.analog[0].flags == DNP3_FLAG_ONLINE);
    TH_ASSERT(dnp3_set_analog(&out, 0U, 2147483648.0, false));
    TH_ASSERT(out.analog[0].value == INT32_MAX);
    TH_ASSERT(out.analog[0].flags == (DNP3_FLAG_OVER_RANGE | DNP3_FLAG_COMM_LOST));
    TH_ASSERT(dnp3_set_analog(&out, 0U, -2147483649.0, true));
    TH_ASSERT(out.analog[0].value == INT32_MIN);
    TH_ASSERT(out.analog[0].flags == (DNP3_FLAG_OVER_RANGE | DNP3_FLAG_ONLINE));
}

static void test_static_response(void)
{
    TH_CASE("empty response and short buffer leave destination untouched");
    dnp3_outstation_t out;
    uint8_t buffer[15];
    uint8_t untouched[sizeof(buffer)];
    memset(buffer, 0xA5, sizeof(buffer));
    memset(untouched, 0xA5, sizeof(untouched));
    dnp3_init(&out, 0U, 0U);
    TH_ASSERT(dnp3_encode_class0(NULL, buffer, sizeof(buffer)) == 0U);
    TH_ASSERT(dnp3_encode_class0(&out, NULL, sizeof(buffer)) == 0U);
    TH_ASSERT(dnp3_encode_class0(&out, buffer, sizeof(buffer)) == 0U);

    dnp3_init(&out, 1U, 1U);
    TH_ASSERT(dnp3_set_binary(&out, 0U, true, true));
    TH_ASSERT(dnp3_set_analog(&out, 0U, -258.0, false));
    TH_ASSERT(dnp3_encode_class0(&out, buffer, 13U) == 0U);
    TH_ASSERT(memcmp(buffer, untouched, sizeof(buffer)) == 0);

    TH_CASE("class-0 emits current binary flags followed by little-endian analog");
    /* Suspected defect: qualifier 0x00 currently has a stop byte but no start byte. */
    const uint8_t binary[] = {1U, 2U, 0U, 0U, DNP3_FLAG_ONLINE | DNP3_FLAG_STATE};
    const uint8_t analog[] = {30U, 1U, 0U, 0U, DNP3_FLAG_COMM_LOST,
                              0xFEU, 0xFEU, 0xFFU, 0xFFU};
    TH_ASSERT(dnp3_encode_class0(&out, buffer, 14U) == 14U);
    TH_ASSERT(memcmp(buffer, binary, sizeof(binary)) == 0);
    TH_ASSERT(memcmp(buffer + sizeof(binary), analog, sizeof(analog)) == 0);
    TH_ASSERT(buffer[14] == 0xA5U);

    out.binary_count = 0U;
    TH_ASSERT(dnp3_encode_class0(&out, buffer, sizeof(analog)) == sizeof(analog));
    TH_ASSERT(memcmp(buffer, analog, sizeof(analog)) == 0);
}

int main(void)
{
    test_point_initialization();
    test_updates();
    test_static_response();
    return th_report("DNP3 outstation");
}

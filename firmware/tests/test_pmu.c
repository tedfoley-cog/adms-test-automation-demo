/* Synchrophasor measurement and C37.118 framing. */
#include "test_harness.h"

#include "c37118.h"
#include "ied_loop.h"

static void test_crc_ccitt_check_value(void)
{
    TH_CASE("CRC-CCITT (0xFFFF) of \"123456789\" is 0x29B1");
    const uint8_t msg[] = "123456789";
    TH_ASSERT(c37118_crc(msg, 9) == 0x29B1u);
}

static void test_data_frame_round_trip(void)
{
    TH_CASE("data frame encodes, validates and decodes");
    c37118_data_t d;
    memset(&d, 0, sizeof(d));
    d.idcode = 4107u;
    d.soc = 1790000000u;
    d.fracsec = 500000u;
    d.stat = 0u;
    d.num_phasors = 2u;
    d.phasor[0] = cplx_polar(7200.0f, 0.5f);
    d.phasor[1] = cplx_polar(320.0f, -0.2f);
    d.freq_hz = 60.01f;
    d.rocof_hz_s = -0.05f;

    uint8_t buf[C37118_MAX_FRAME];
    size_t len = c37118_encode_data(&d, buf, sizeof(buf));
    TH_ASSERT(len > 0u);
    TH_ASSERT(c37118_check(buf, len) == 0);

    c37118_data_t out;
    TH_ASSERT(c37118_decode_data(buf, len, 2u, &out));
    TH_ASSERT(out.soc == d.soc && out.fracsec == d.fracsec);
    TH_ASSERT_NEAR(cplx_abs(out.phasor[0]), 7200.0, 0.01);
    TH_ASSERT_NEAR(out.freq_hz, 60.01, 1e-4);

    buf[20] ^= 0x01u;
    TH_ASSERT(c37118_check(buf, len) != 0);
}

static void test_nominal_frequency(void)
{
    TH_CASE("60 Hz steady state: FE < 5 mHz, ROCOF ~ 0, frames synchronised");
    const ied_status_t *st = loop_run(testset_find("steady_load"), 0u);
    TH_ASSERT(st->pps_locked);
    TH_ASSERT(loop_res.num_frames >= 55);
    for (int k = 0; k < loop_res.num_frames; k++) {
        TH_ASSERT_NEAR(loop_res.frames[k].freq_hz, 60.0, 0.005);
        TH_ASSERT_NEAR(loop_res.frames[k].rocof_hz_s, 0.0, 0.4);
    }
}

int main(void)
{
    test_crc_ccitt_check_value();
    test_data_frame_round_trip();
    test_nominal_frequency();
    return th_report("pmu");
}

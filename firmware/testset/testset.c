#include "testset.h"

#include <string.h>

#define E_LN_V        7200.0f
#define SQRT3_OVER2   0.866025403784439f

/* Source behind the substation bus (20 MVA transformer, solidly grounded). */
static const cplx_t k_zs1 = {0.35f, 1.90f};
static const cplx_t k_zs0 = {0.30f, 1.70f};
/* 5 km of 336 ACSR. */
static const cplx_t k_zl1 = {1.53f, 3.14f};
static const cplx_t k_zl0 = {3.85f, 10.0f};

static const scenario_t k_scenarios[] = {
    {
        .name = "steady_load",
        .description = "Balanced 320 A load at 0.95 pf, 60 Hz, PPS locked",
        .duration_s = 1.0f, .freq_hz = 60.0f, .freq_end_hz = 60.0f,
        .load_a = 320.0f, .load_pf = 0.95f,
    },
    {
        .name = "fault_ag_zone1",
        .description = "A-G fault at 40% of the line, 0.5 ohm; cleared by 21 zone 1",
        .duration_s = 0.8f, .freq_hz = 60.0f, .freq_end_hz = 60.0f,
        .load_a = 320.0f, .load_pf = 0.95f,
        .fault = FAULT_AG, .fault_start_s = 0.30f, .fault_location_pct = 40.0f,
        .fault_r_ohm = 0.5f,
    },
    {
        .name = "fault_bc_zone2",
        .description = "B-C fault at 110% of the line; cleared by time-delayed 21 zone 2",
        .duration_s = 1.0f, .freq_hz = 60.0f, .freq_end_hz = 60.0f,
        .load_a = 320.0f, .load_pf = 0.95f,
        .fault = FAULT_BC, .fault_start_s = 0.30f, .fault_location_pct = 110.0f,
        .fault_r_ohm = 0.1f,
    },
    {
        .name = "fault_ag_high_resistance",
        .description = "A-G fault through 10 ohm at 50%; outside the mho, cleared by 51G",
        .duration_s = 2.2f, .freq_hz = 60.0f, .freq_end_hz = 60.0f,
        .load_a = 320.0f, .load_pf = 0.95f,
        .fault = FAULT_AG, .fault_start_s = 0.30f, .fault_location_pct = 50.0f,
        .fault_r_ohm = 10.0f,
    },
    {
        .name = "breaker_failure",
        .description = "A-G zone 1 fault with the feeder breaker stuck closed; 50BF trips the bus",
        .duration_s = 0.8f, .freq_hz = 60.0f, .freq_end_hz = 60.0f,
        .load_a = 320.0f, .load_pf = 0.95f,
        .fault = FAULT_AG, .fault_start_s = 0.30f, .fault_location_pct = 40.0f,
        .fault_r_ohm = 0.5f, .breaker_stuck = true,
    },
};

int testset_scenario_count(void)
{
    return (int)(sizeof(k_scenarios) / sizeof(k_scenarios[0]));
}

const scenario_t *testset_scenario(int index)
{
    if (index < 0 || index >= testset_scenario_count()) {
        return NULL;
    }
    return &k_scenarios[index];
}

const scenario_t *testset_find(const char *name)
{
    for (int k = 0; k < testset_scenario_count(); k++) {
        if (strcmp(k_scenarios[k].name, name) == 0) {
            return &k_scenarios[k];
        }
    }
    return NULL;
}

static cplx_t op_a(void) { return cplx(-0.5f, SQRT3_OVER2); }
static cplx_t op_a2(void) { return cplx(-0.5f, -SQRT3_OVER2); }

/* Phase quantities from sequence components with `ref` as the reference
 * phase; result written so that out[ref] = X0 + X1 + X2. */
static void seq_to_phase(cplx_t x0, cplx_t x1, cplx_t x2, int ref, cplx_t out[3])
{
    cplx_t a = op_a();
    cplx_t a2 = op_a2();
    cplx_t p0 = cplx_add(cplx_add(x0, x1), x2);
    cplx_t p1 = cplx_add(cplx_add(x0, cplx_mul(a2, x1)), cplx_mul(a, x2));
    cplx_t p2 = cplx_add(cplx_add(x0, cplx_mul(a, x1)), cplx_mul(a2, x2));
    /* Rotate so the reference phase sits at its own angle in the ABC frame. */
    cplx_t rot = ref == 0 ? cplx(1.0f, 0.0f) : (ref == 1 ? a2 : a);
    out[ref] = cplx_mul(p0, rot);
    out[(ref + 1) % 3] = cplx_mul(p1, rot);
    out[(ref + 2) % 3] = cplx_mul(p2, rot);
}

void testset_solve_fault(fault_type_t type, float location_pct, float rf_ohm, cplx_t v[3],
                         cplx_t i[3], float *x_over_r)
{
    float d = location_pct / 100.0f;
    cplx_t z1 = cplx_add(k_zs1, cplx_scale(k_zl1, d));
    cplx_t z0 = cplx_add(k_zs0, cplx_scale(k_zl0, d));
    cplx_t e = cplx(E_LN_V, 0.0f);
    cplx_t rf = cplx(rf_ohm, 0.0f);
    cplx_t zero = cplx(0.0f, 0.0f);
    cplx_t i0 = zero;
    cplx_t i1 = zero;
    cplx_t i2 = zero;
    int ref = 0;
    cplx_t loop = z1;

    switch (type) {
    case FAULT_AG:
    case FAULT_BG:
    case FAULT_CG: {
        ref = (int)(type - FAULT_AG);
        cplx_t zt = cplx_add(cplx_add(cplx_scale(z1, 2.0f), z0), cplx_scale(rf, 3.0f));
        i1 = cplx_div_safe(e, zt, 1e-6f);
        i2 = i1;
        i0 = i1;
        loop = cplx_add(cplx_scale(z1, 2.0f), z0);
        break;
    }
    case FAULT_AB:
    case FAULT_BC:
    case FAULT_CA: {
        /* Phase-phase fault: the unfaulted phase is the reference. */
        static const int unfaulted[3] = {2, 0, 1};
        ref = unfaulted[type - FAULT_AB];
        cplx_t zt = cplx_add(cplx_scale(z1, 2.0f), rf);
        i1 = cplx_div_safe(e, zt, 1e-6f);
        i2 = cplx_scale(i1, -1.0f);
        loop = cplx_scale(z1, 2.0f);
        break;
    }
    case FAULT_ABC:
        i1 = cplx_div_safe(e, cplx_add(z1, rf), 1e-6f);
        break;
    case FAULT_NONE:
    default:
        break;
    }

    /* Bus voltages: source EMF minus the drop across the source impedance. */
    cplx_t v1 = cplx_sub(e, cplx_mul(k_zs1, i1));
    cplx_t v2 = cplx_scale(cplx_mul(k_zs1, i2), -1.0f);
    cplx_t v0 = cplx_scale(cplx_mul(k_zs0, i0), -1.0f);

    /* The reference-phase EMF is at angle 0 in its own frame, so rotate the
     * source EMF consistently with seq_to_phase. */
    seq_to_phase(v0, v1, v2, ref, v);
    seq_to_phase(i0, i1, i2, ref, i);
    if (x_over_r != NULL) {
        *x_over_r = loop.re > 1e-6f ? loop.im / loop.re : 10.0f;
    }
}

static void load_flow(const scenario_t *sc, cplx_t v[3], cplx_t i[3])
{
    cplx_t a = op_a();
    cplx_t a2 = op_a2();
    float phi = acosf(sc->load_pf > 0.0f ? sc->load_pf : 1.0f);
    cplx_t ia = cplx_polar(sc->load_a, -phi);
    cplx_t va = cplx_sub(cplx(E_LN_V, 0.0f), cplx_mul(k_zs1, ia));
    v[0] = va;
    v[1] = cplx_mul(va, a2);
    v[2] = cplx_mul(va, a);
    i[0] = ia;
    i[1] = cplx_mul(ia, a2);
    i[2] = cplx_mul(ia, a);
}

void testset_init(testset_t *ts, const scenario_t *sc, const float scale[IED_NUM_CHANNELS])
{
    memset(ts, 0, sizeof(*ts));
    ts->sc = sc;
    for (int ch = 0; ch < IED_NUM_CHANNELS; ch++) {
        ts->scale[ch] = scale[ch];
    }
    ts->freq_hz = sc->freq_hz;
    ts->lcg = 0x2545F491u;
    ts->breaker_timer = -1;
    ts->bus_timer = -1;
    load_flow(sc, ts->v_pre, ts->i_pre);
    if (sc->fault != FAULT_NONE) {
        float xr = 1.0f;
        testset_solve_fault(sc->fault, sc->fault_location_pct, sc->fault_r_ohm, ts->v_flt,
                            ts->i_flt, &xr);
        ts->fault_tau_samples = (xr / (CPLX_TWO_PI * IED_F_NOMINAL_HZ)) * (float)IED_SAMPLE_RATE_HZ;
    }
}

void testset_set_preroll(testset_t *ts, uint32_t samples)
{
    ts->preroll_n = samples;
}

float testset_time_s(const testset_t *ts)
{
    return ((float)ts->n - (float)ts->preroll_n) / (float)IED_SAMPLE_RATE_HZ;
}

bool testset_done(const testset_t *ts)
{
    return testset_time_s(ts) >= ts->sc->duration_s;
}

static float inst(cplx_t phasor, float theta)
{
    /* Instantaneous value of an RMS phasor at system angle theta. */
    return CPLX_SQRT2 * (phasor.re * cosf(theta) - phasor.im * sinf(theta));
}

static int16_t adc(float value, float scale, uint32_t *lcg)
{
    *lcg = *lcg * 1664525u + 1013904223u;
    float dither = (float)((int32_t)(*lcg >> 30) - 1); /* -1, 0, +1, +2 LSB -> centred */
    float counts = value / scale + dither * 0.5f;
    if (counts > (float)IED_ADC_FULL_SCALE) {
        counts = (float)IED_ADC_FULL_SCALE;
    } else if (counts < -(float)IED_ADC_FULL_SCALE) {
        counts = -(float)IED_ADC_FULL_SCALE;
    }
    return (int16_t)lrintf(counts);
}

void testset_step(testset_t *ts, bool trip1, bool tripb, int16_t raw[IED_NUM_CHANNELS])
{
    const scenario_t *sc = ts->sc;
    float t = testset_time_s(ts);

    /* Frequency ramp. */
    if (sc->rocof_hz_s != 0.0f && t >= sc->ramp_start_s && t >= 0.0f) {
        float f = sc->freq_hz + sc->rocof_hz_s * (t - sc->ramp_start_s);
        if ((sc->rocof_hz_s < 0.0f && f < sc->freq_end_hz) ||
            (sc->rocof_hz_s > 0.0f && f > sc->freq_end_hz)) {
            f = sc->freq_end_hz;
        }
        ts->freq_hz = f;
    }
    float theta = (float)ts->phase_acc * (CPLX_TWO_PI / 4294967296.0f);

    /* Fault inception. */
    if (sc->fault != FAULT_NONE && !ts->fault_active && t >= sc->fault_start_s && t >= 0.0f &&
        !ts->breaker_open) {
        ts->fault_active = true;
        ts->fault_n = ts->n;
        for (int ph = 0; ph < 3; ph++) {
            ts->dc_offset[ph] = inst(ts->i_flt[ph], theta) - inst(ts->i_pre[ph], theta);
        }
    }

    /* Breaker models. */
    if (trip1 && !ts->breaker_open && ts->breaker_timer < 0 && !sc->breaker_stuck) {
        ts->breaker_timer = TESTSET_BREAKER_SAMPLES;
    }
    if (tripb && !ts->bus_dead && ts->bus_timer < 0) {
        ts->bus_timer = TESTSET_BUS_SAMPLES;
    }
    if (ts->breaker_timer > 0 && --ts->breaker_timer == 0) {
        ts->breaker_open = true;
        ts->fault_active = false;
    }
    if (ts->bus_timer > 0 && --ts->bus_timer == 0) {
        ts->bus_dead = true;
        ts->fault_active = false;
    }

    const cplx_t *v = ts->fault_active ? ts->v_flt : ts->v_pre;
    const cplx_t *i = ts->fault_active ? ts->i_flt : ts->i_pre;
    float decay = 0.0f;
    if (ts->fault_active && ts->fault_tau_samples > 0.0f) {
        decay = expf(-(float)(ts->n - ts->fault_n) / ts->fault_tau_samples);
    }

    float sum_i = 0.0f;
    for (int ph = 0; ph < 3; ph++) {
        float vv = ts->bus_dead ? 0.0f : inst(v[ph], theta);
        float ii = 0.0f;
        if (!ts->breaker_open && !ts->bus_dead) {
            ii = inst(i[ph], theta);
            if (ts->fault_active) {
                /* Current cannot change instantaneously at inception. */
                ii -= ts->dc_offset[ph] * decay;
            }
        }
        raw[IED_CH_VA + ph] = adc(vv, ts->scale[IED_CH_VA + ph], &ts->lcg);
        raw[IED_CH_IA + ph] = adc(ii, ts->scale[IED_CH_IA + ph], &ts->lcg);
        sum_i += ii;
    }
    raw[IED_CH_IN] = adc(sum_i, ts->scale[IED_CH_IN], &ts->lcg);

    ts->phase_acc += (uint32_t)((ts->freq_hz / (float)IED_SAMPLE_RATE_HZ) * 4294967296.0f);
    ts->n++;
}

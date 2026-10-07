#include "c37118.h"

#include <string.h>

uint16_t c37118_crc(const uint8_t *buf, size_t len)
{
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < len; i++) {
        uint16_t temp = (uint16_t)(((crc >> 8) ^ buf[i]) & 0xFFu);
        crc = (uint16_t)(crc << 8);
        uint16_t quick = (uint16_t)(temp ^ (temp >> 4));
        crc ^= quick;
        quick = (uint16_t)(quick << 5);
        crc ^= quick;
        quick = (uint16_t)(quick << 7);
        crc ^= quick;
    }
    return crc;
}

typedef struct {
    uint8_t *buf;
    size_t len;
    size_t pos;
    bool overflow;
} writer_t;

static void put_u8(writer_t *w, uint8_t v)
{
    if (w->pos >= w->len) {
        w->overflow = true;
        return;
    }
    w->buf[w->pos++] = v;
}

static void put_u16(writer_t *w, uint16_t v)
{
    put_u8(w, (uint8_t)(v >> 8));
    put_u8(w, (uint8_t)v);
}

static void put_u32(writer_t *w, uint32_t v)
{
    put_u16(w, (uint16_t)(v >> 16));
    put_u16(w, (uint16_t)v);
}

static void put_f32(writer_t *w, float f)
{
    uint32_t v;
    memcpy(&v, &f, sizeof(v));
    put_u32(w, v);
}

static void put_name(writer_t *w, const char *name)
{
    size_t n = name != NULL ? strlen(name) : 0u;
    for (size_t i = 0; i < 16u; i++) {
        put_u8(w, (uint8_t)(i < n ? name[i] : ' '));
    }
}

static size_t finish(writer_t *w)
{
    if (w->overflow || w->pos + 2u > w->len) {
        return 0u;
    }
    size_t total = w->pos + 2u;
    w->buf[2] = (uint8_t)(total >> 8);
    w->buf[3] = (uint8_t)total;
    uint16_t crc = c37118_crc(w->buf, w->pos);
    put_u16(w, crc);
    return w->overflow ? 0u : total;
}

size_t c37118_encode_data(const c37118_data_t *d, uint8_t *buf, size_t buf_len)
{
    if (d == NULL || buf == NULL || d->num_phasors > C37118_MAX_PHASORS) {
        return 0u;
    }
    writer_t w = {buf, buf_len, 0u, false};
    put_u16(&w, C37118_SYNC_DATA);
    put_u16(&w, 0u); /* FRAMESIZE, patched in finish() */
    put_u16(&w, d->idcode);
    put_u32(&w, d->soc);
    put_u32(&w, d->fracsec);
    put_u16(&w, d->stat);
    for (uint8_t i = 0; i < d->num_phasors; i++) {
        put_f32(&w, cplx_abs(d->phasor[i]));
        put_f32(&w, cplx_arg(d->phasor[i]));
    }
    put_f32(&w, d->freq_hz);
    put_f32(&w, d->rocof_hz_s);
    put_u16(&w, d->digital);
    return finish(&w);
}

size_t c37118_encode_cfg2(const c37118_cfg_t *c, uint8_t *buf, size_t buf_len)
{
    if (c == NULL || buf == NULL || c->num_phasors > C37118_MAX_PHASORS) {
        return 0u;
    }
    writer_t w = {buf, buf_len, 0u, false};
    put_u16(&w, C37118_SYNC_CFG2);
    put_u16(&w, 0u);
    put_u16(&w, c->idcode);
    put_u32(&w, c->soc);
    put_u32(&w, 0u);
    put_u32(&w, C37118_TIME_BASE);
    put_u16(&w, 1u); /* NUM_PMU */
    put_name(&w, c->station);
    put_u16(&w, c->idcode);
    put_u16(&w, C37118_FMT_POLAR | C37118_FMT_PH_FLOAT | C37118_FMT_AN_FLOAT |
                    C37118_FMT_FREQ_FLOAT);
    put_u16(&w, c->num_phasors);
    put_u16(&w, 0u); /* ANNMR */
    put_u16(&w, 1u); /* DGNMR */
    for (uint8_t i = 0; i < c->num_phasors; i++) {
        put_name(&w, c->phasor_names[i]);
    }
    for (uint8_t i = 0; i < 16u; i++) {
        put_name(&w, c->digital_names != NULL ? c->digital_names[i] : "");
    }
    for (uint8_t i = 0; i < c->num_phasors; i++) {
        /* PHUNIT: byte 0 = 0 voltage / 1 current; scale ignored for float data. */
        uint32_t unit = (uint32_t)(c->phasor_is_current[i] ? 1u : 0u) << 24;
        put_u32(&w, unit);
    }
    put_u32(&w, 0x0000FFFFu); /* DIGUNIT: all inputs valid, normal state 0 */
    put_u16(&w, 0u);          /* FNOM: 60 Hz */
    put_u16(&w, c->cfgcnt);
    put_u16(&w, (uint16_t)c->data_rate);
    return finish(&w);
}

int c37118_check(const uint8_t *buf, size_t len)
{
    if (buf == NULL || len < 16u || buf[0] != 0xAAu) {
        return -1;
    }
    size_t size = ((size_t)buf[2] << 8) | buf[3];
    if (size != len) {
        return -1;
    }
    uint16_t crc = (uint16_t)(((uint16_t)buf[len - 2u] << 8) | buf[len - 1u]);
    if (crc != c37118_crc(buf, len - 2u)) {
        return -1;
    }
    return (buf[1] >> 4) & 0x7;
}

static uint16_t get_u16(const uint8_t *p) { return (uint16_t)(((uint16_t)p[0] << 8) | p[1]); }

static uint32_t get_u32(const uint8_t *p)
{
    return ((uint32_t)get_u16(p) << 16) | get_u16(p + 2);
}

static float get_f32(const uint8_t *p)
{
    uint32_t v = get_u32(p);
    float f;
    memcpy(&f, &v, sizeof(f));
    return f;
}

bool c37118_decode_data(const uint8_t *buf, size_t len, uint8_t num_phasors, c37118_data_t *out)
{
    if (out == NULL || num_phasors > C37118_MAX_PHASORS || c37118_check(buf, len) != 0) {
        return false;
    }
    size_t expected = 16u + 8u * num_phasors + 8u + 2u + 2u;
    if (len != expected) {
        return false;
    }
    out->idcode = get_u16(buf + 4);
    out->soc = get_u32(buf + 6);
    out->fracsec = get_u32(buf + 10);
    out->stat = get_u16(buf + 14);
    out->num_phasors = num_phasors;
    const uint8_t *p = buf + 16;
    for (uint8_t i = 0; i < num_phasors; i++) {
        out->phasor[i] = cplx_polar(get_f32(p), get_f32(p + 4));
        p += 8;
    }
    out->freq_hz = get_f32(p);
    out->rocof_hz_s = get_f32(p + 4);
    out->digital = get_u16(p + 8);
    return true;
}

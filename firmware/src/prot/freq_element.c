#include "freq_element.h"

#include <math.h>
#include <stddef.h>

void freq_init(freq_state_t *st)
{
    st->uf_count = 0u;
    st->of_count = 0u;
    st->rocof_count = 0u;
    st->uf_operated = false;
    st->of_operated = false;
    st->rocof_operated = false;
    st->inhibited = true;
    st->blocked = false;
}

static bool stage(bool condition, uint16_t *count, uint16_t frames)
{
    if (!condition) {
        *count = 0u;
        return false;
    }
    if (*count < UINT16_MAX) {
        (*count)++;
    }
    return *count >= frames;
}

void freq_step(const freq_settings_t *s, freq_state_t *st, float freq_hz, float rocof_hz_s,
               float v1_pu, bool fault_block)
{
    if (s == NULL || st == NULL) {
        return;
    }
    st->inhibited = v1_pu < s->uv_inhibit_pu || isnan(freq_hz) || isnan(rocof_hz_s);
    if (st->inhibited) {
        freq_init(st);
        st->inhibited = true;
        return;
    }
    st->blocked = fault_block;
    if (fault_block) {
        st->uf_count = 0u;
        st->of_count = 0u;
        st->rocof_count = 0u;
        st->uf_operated = false;
        st->of_operated = false;
        st->rocof_operated = false;
        return;
    }
    st->uf_operated = stage(freq_hz < s->uf_pickup_hz, &st->uf_count, s->uf_frames);
    st->of_operated = stage(freq_hz > s->of_pickup_hz, &st->of_count, s->of_frames);
    st->rocof_operated = stage(fabsf(rocof_hz_s) > s->rocof_pickup_hz_s, &st->rocof_count,
                               s->rocof_frames);
}

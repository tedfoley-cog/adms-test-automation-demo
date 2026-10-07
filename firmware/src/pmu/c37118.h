/* IEEE C37.118.2-2011 frame encoding: data frames and configuration frame 2.
 *
 * Phasors are sent as IEEE-754 float, polar (magnitude RMS, angle radians);
 * FREQ / DFREQ as float Hz and Hz/s. All multi-byte fields are big-endian
 * and every frame ends with CRC-CCITT (poly 0x1021, init 0xFFFF).
 */
#ifndef C37118_H
#define C37118_H

#include "cplx.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define C37118_SYNC_DATA   0xAA02u
#define C37118_SYNC_CFG2   0xAA32u
#define C37118_TIME_BASE   1000000u   /* FRACSEC resolution: 1 us */

#define C37118_MAX_PHASORS 9u
#define C37118_MAX_FRAME   128u
#define C37118_MAX_CFG     512u

/* FORMAT word */
#define C37118_FMT_POLAR       0x0001u
#define C37118_FMT_PH_FLOAT    0x0002u
#define C37118_FMT_AN_FLOAT    0x0004u
#define C37118_FMT_FREQ_FLOAT  0x0008u

/* STAT word */
#define C37118_STAT_DATA_INVALID   0x8000u
#define C37118_STAT_PMU_ERROR      0x4000u
#define C37118_STAT_NOT_SYNC       0x2000u
#define C37118_STAT_TRIGGER        0x0800u
#define C37118_STAT_CFG_CHANGE     0x0400u
#define C37118_TRIG_FREQ           0x0004u
#define C37118_TRIG_DFDT           0x0005u
#define C37118_TRIG_DIGITAL        0x0007u

typedef struct {
    uint16_t idcode;
    uint32_t soc;
    uint32_t fracsec;          /* time quality in bits 31..24, count in 23..0 */
    uint16_t stat;
    uint8_t num_phasors;
    cplx_t phasor[C37118_MAX_PHASORS];
    float freq_hz;
    float rocof_hz_s;
    uint16_t digital;
} c37118_data_t;

typedef struct {
    uint16_t idcode;
    const char *station;       /* up to 16 characters */
    uint8_t num_phasors;
    const char *const *phasor_names;
    const uint8_t *phasor_is_current;
    const float *phasor_scale; /* informational; float frames ignore PHUNIT scaling */
    const char *const *digital_names; /* 16 names */
    uint16_t cfgcnt;
    int16_t data_rate;
    uint32_t soc;
} c37118_cfg_t;

uint16_t c37118_crc(const uint8_t *buf, size_t len);

size_t c37118_encode_data(const c37118_data_t *d, uint8_t *buf, size_t buf_len);
size_t c37118_encode_cfg2(const c37118_cfg_t *c, uint8_t *buf, size_t buf_len);

/* Validate SYNC byte, FRAMESIZE and CRC. Returns the frame type (0..7) or -1. */
int c37118_check(const uint8_t *buf, size_t len);

/* Decode a data frame previously produced by c37118_encode_data. */
bool c37118_decode_data(const uint8_t *buf, size_t len, uint8_t num_phasors, c37118_data_t *out);

#endif /* C37118_H */

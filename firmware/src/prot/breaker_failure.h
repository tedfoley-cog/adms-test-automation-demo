/* Breaker failure protection (ANSI 50BF).
 *
 * Started by any trip issued to the feeder breaker (BFI). If phase current is
 * still flowing when the retrip timer expires, the trip is repeated on the
 * second trip coil; if it is still flowing when the BF timer expires the
 * breaker is declared failed and every breaker on the bus is tripped through
 * the 86B lockout.
 *
 * Timers are kept in seconds so they read straight across from the setting
 * sheet (retrip 20 ms, BF 150 ms are typical).
 */
#ifndef BREAKER_FAILURE_H
#define BREAKER_FAILURE_H

#include <stdbool.h>

typedef struct {
    float pickup_a;        /* phase current detector, primary amps */
    float retrip_delay_s;
    float bf_delay_s;
} bf_settings_t;

typedef struct {
    bool initiated;
    float start_s;
    bool retrip;
    bool bus_trip;         /* latched until bf_reset() */
    float elapsed_s;       /* diagnostic: timer value at the last pass */
} bf_state_t;

void bf_init(bf_state_t *st);

/* One protection pass. `iph` holds RMS phase-current magnitudes (A, B, C);
 * `now_s` is relay time in seconds (timebase_now_s()). */
void bf_step(const bf_settings_t *s, bf_state_t *st, bool bfi, const float iph[3], float now_s);

void bf_reset(bf_state_t *st);

#endif /* BREAKER_FAILURE_H */

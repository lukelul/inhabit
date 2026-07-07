/* Inhabit ENUM protocol — chain-index assignment via ENUM_IN / ENUM_OUT GPIOs.
 *
 * Protocol (root CLAUDE.md):
 *   1. All pods power on un-indexed (ST_NOT_ENUMERATED set).
 *   2. A pod whose ENUM_IN (PA1) is asserted (HIGH) claims chain_index =
 *      max(peer indexes heard on CAN) + 1, or 0 if none heard (host seeds).
 *   3. After a brief delay it asserts ENUM_OUT (PA2), waking the next pod.
 *
 * GPIO abstraction: enum_step() takes the current ENUM_IN pin level as a bool
 * and exposes the desired ENUM_OUT level in ctx->enum_out. The caller (main.c)
 * reads/writes the physical pins. This keeps the module host-testable.
 *
 * ISR safety: enum_notify_peer() is the only entry point safe to call from the
 * CAN RX path (which may be interrupt-driven). It performs single-word stores
 * only — it latches the observed peer index and raises a pending flag; it does
 * NOT read-modify-write the FSM's max_peer_index. The main loop's enum_step()
 * folds the latched value in, so the snapshot-and-assign handoff cannot race an
 * ISR update (root CLAUDE.md: "ISRs set flags, main loop acts").
 */
#ifndef INHABIT_ENUM_H
#define INHABIT_ENUM_H

#include <stdint.h>
#include <stdbool.h>
#include "can_frame.h"

/* Debounce ENUM_IN for this many consecutive calls before accepting. */
#define ENUM_DEBOUNCE_TICKS  10u
/* Delay between index assignment and ENUM_OUT assertion (let CAN TX propagate). */
#define ENUM_OUT_DELAY_TICKS  5u
/* Highest assignable chain index. 0xFF is reserved as the "none heard"
 * sentinel, so a pod that would have to claim 0xFF instead faults
 * (ST_NOT_ENUMERATED stays set) rather than wrapping silently back to 0. */
#define ENUM_MAX_CHAIN_INDEX  0xFEu
/* Sentinel: no peer index heard yet. Never a valid chain index. */
#define ENUM_PEER_NONE        0xFFu

typedef enum {
    ENUM_WAIT,      /* waiting for ENUM_IN HIGH                         */
    ENUM_DEBOUNCE,  /* ENUM_IN seen HIGH, counting stable ticks         */
    ENUM_ASSIGNED,  /* chain_index set, delaying before ENUM_OUT assert */
    ENUM_DONE       /* fully enumerated, ENUM_OUT driven HIGH           */
} enum_phase_t;

typedef struct {
    enum_phase_t phase;
    uint8_t      debounce_count;
    uint8_t      out_delay_count;
    uint8_t      max_peer_index;  /* highest peer chain_index folded in by enum_step;
                                     ENUM_PEER_NONE (0xFF) = none. Main-loop owned. */
    /* ISR->loop latch (written by enum_notify_peer, consumed by enum_step). Kept
     * to single-word stores so a CAN-RX interrupt cannot corrupt max_peer_index
     * mid-snapshot. */
    volatile uint8_t pending_peer_index; /* last peer index observed on the bus   */
    volatile bool    peer_pending;       /* a new pending_peer_index is waiting    */
    bool         enum_out;        /* caller drives PA2 from this field              */
} enum_ctx_t;

/* Initialise the enum context. Call once at startup. */
void enum_init(enum_ctx_t *ctx);

/* Advance the state machine by one tick.
 *   ctx        — enum context (caller owns storage)
 *   state      — inhabit_state_t whose chain_index / status_flags are updated
 *   enum_in    — current level of the ENUM_IN pin (true = asserted / HIGH)
 * After the call, read ctx->enum_out and drive PA2 accordingly. */
void enum_step(enum_ctx_t *ctx, inhabit_state_t *state, bool enum_in);

/* Inform the enum engine of a peer's chain_index observed on CAN. Safe to call
 * from the (possibly interrupt-driven) RX path: it only latches the value via
 * single-word stores, never read-modify-writes the FSM state. enum_step() folds
 * the latch in on the next main-loop tick. The reserved sentinel
 * ENUM_PEER_NONE (0xFF) is rejected here (it can never be a real chain index),
 * so a corrupt frame cannot reset this pod back to index 0. */
void enum_notify_peer(enum_ctx_t *ctx, uint8_t peer_chain_index);

#endif

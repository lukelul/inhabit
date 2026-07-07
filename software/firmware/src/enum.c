/* Inhabit ENUM protocol — implementation (see enum.h for the contract). */
#include "enum.h"

void enum_init(enum_ctx_t *ctx) {
    ctx->phase              = ENUM_WAIT;
    ctx->debounce_count     = 0;
    ctx->out_delay_count    = 0;
    ctx->max_peer_index     = ENUM_PEER_NONE;   /* none heard yet */
    ctx->pending_peer_index = ENUM_PEER_NONE;
    ctx->peer_pending       = false;
    ctx->enum_out           = false;
}

void enum_notify_peer(enum_ctx_t *ctx, uint8_t peer_chain_index) {
    /* Once enumerated, peer traffic is a no-op: a late/duplicate frame must not
     * change our committed chain_index. */
    if (ctx->phase == ENUM_DONE) return;
    /* Reject the reserved sentinel so a corrupt frame reporting 0xFF cannot
     * later be read as "no peers" and reset this pod to index 0. */
    if (peer_chain_index == ENUM_PEER_NONE) return;
    /* ISR-safe: single-word stores only. Take max so a lower index arriving
     * after a higher one cannot clobber the pending value before enum_step()
     * consumes it. */
    if (!ctx->peer_pending || peer_chain_index > ctx->pending_peer_index) {
        ctx->pending_peer_index = peer_chain_index;
    }
    ctx->peer_pending = true;
}

void enum_step(enum_ctx_t *ctx, inhabit_state_t *state, bool enum_in) {
    /* Fold any latched peer observation into the main-loop-owned max.
     * Skip if already done — post-enumeration CAN traffic is irrelevant. */
    if (ctx->peer_pending && ctx->phase != ENUM_DONE) {
        uint8_t peer = ctx->pending_peer_index;
        ctx->peer_pending = false;
        if (ctx->max_peer_index == ENUM_PEER_NONE || peer > ctx->max_peer_index) {
            ctx->max_peer_index = peer;
        }
    }

    switch (ctx->phase) {

    case ENUM_WAIT:
        if (enum_in) {
            ctx->debounce_count = 1;
            ctx->phase = ENUM_DEBOUNCE;
        }
        break;

    case ENUM_DEBOUNCE:
        if (!enum_in) {
            /* glitch — reset */
            ctx->debounce_count = 0;
            ctx->phase = ENUM_WAIT;
        } else {
            ++ctx->debounce_count;
            if (ctx->debounce_count >= ENUM_DEBOUNCE_TICKS) {
                /* ENUM_IN stable: claim chain_index = max peer + 1 (or 0 if none).
                 * Guard the top of the range: claiming 0xFF would be read by the
                 * next pod as "no peers" and wrap the chain back to 0. If we would
                 * exceed ENUM_MAX_CHAIN_INDEX, fail loud (leave ST_NOT_ENUMERATED
                 * set) instead of assigning a colliding index. */
                if (ctx->max_peer_index == ENUM_PEER_NONE) {
                    state->chain_index   = 0u;
                    state->status_flags &= (uint8_t)~ST_NOT_ENUMERATED;
                    ctx->out_delay_count = 0;
                    ctx->phase = ENUM_ASSIGNED;
                } else if (ctx->max_peer_index < ENUM_MAX_CHAIN_INDEX) {
                    state->chain_index   = (uint8_t)(ctx->max_peer_index + 1u);
                    state->status_flags &= (uint8_t)~ST_NOT_ENUMERATED;
                    ctx->out_delay_count = 0;
                    ctx->phase = ENUM_ASSIGNED;
                } else {
                    /* Chain is full: cannot assign a valid index. Stay
                     * un-enumerated, fault loud, do NOT assert ENUM_OUT. */
                    state->status_flags |= ST_NOT_ENUMERATED;
                    ctx->phase = ENUM_WAIT;
                    ctx->debounce_count = 0;
                }
            }
        }
        break;

    case ENUM_ASSIGNED:
        ++ctx->out_delay_count;
        if (ctx->out_delay_count >= ENUM_OUT_DELAY_TICKS) {
            ctx->enum_out = true;
            ctx->phase = ENUM_DONE;
        }
        break;

    case ENUM_DONE:
        /* nothing to do */
        break;
    }
}

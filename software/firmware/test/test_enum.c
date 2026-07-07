/* Host-side unit test for the ENUM state machine.
 *   cc -I../inc test_enum.c ../src/enum.c ../src/can_frame.c -o t && ./t
 */
#include "enum.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* Helper: tick the FSM N times with a fixed enum_in level. */
static void tick_n(enum_ctx_t *ctx, inhabit_state_t *st, bool pin, unsigned n) {
    for (unsigned i = 0; i < n; ++i) enum_step(ctx, st, pin);
}

static void test_single_pod_enumerates_to_zero(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    /* ENUM_IN low — nothing happens */
    tick_n(&ctx, &st, false, 20);
    assert(ctx.phase == ENUM_WAIT);
    assert(st.status_flags & ST_NOT_ENUMERATED);

    /* ENUM_IN goes HIGH — debounce */
    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS - 1);
    assert(ctx.phase == ENUM_DEBOUNCE);
    assert(st.status_flags & ST_NOT_ENUMERATED);

    /* One more tick completes debounce → ASSIGNED, index 0 */
    enum_step(&ctx, &st, true);
    assert(ctx.phase == ENUM_ASSIGNED);
    assert(st.chain_index == 0);
    assert(!(st.status_flags & ST_NOT_ENUMERATED));
    assert(!ctx.enum_out);

    /* Wait for ENUM_OUT delay */
    tick_n(&ctx, &st, true, ENUM_OUT_DELAY_TICKS - 1);
    assert(ctx.phase == ENUM_ASSIGNED);
    assert(!ctx.enum_out);

    tick_n(&ctx, &st, true, 1);
    assert(ctx.phase == ENUM_DONE);
    assert(ctx.enum_out);
}

static void test_debounce_rejects_glitch(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    /* Partial high then low — must reset */
    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS - 2);
    assert(ctx.phase == ENUM_DEBOUNCE);

    enum_step(&ctx, &st, false);  /* glitch */
    assert(ctx.phase == ENUM_WAIT);
    assert(st.status_flags & ST_NOT_ENUMERATED);

    /* Full stable assertion after the glitch succeeds */
    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS);
    assert(ctx.phase == ENUM_ASSIGNED);
    assert(st.chain_index == 0);
}

static void test_peer_index_increments(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    /* Hear peers with indexes 0 and 2 before our ENUM_IN fires */
    enum_notify_peer(&ctx, 0);
    enum_notify_peer(&ctx, 2);

    /* Enumerate — should claim index 3 */
    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS);
    assert(st.chain_index == 3);

    /* After DONE, notify_peer is a no-op */
    tick_n(&ctx, &st, true, ENUM_OUT_DELAY_TICKS);
    assert(ctx.phase == ENUM_DONE);
    enum_notify_peer(&ctx, 99);
    assert(ctx.max_peer_index == 2);  /* unchanged */
}

static void test_two_pod_chain(void) {
    enum_ctx_t a, b;
    inhabit_state_t sa = {0}, sb = {0};
    sa.status_flags = ST_NOT_ENUMERATED;
    sb.status_flags = ST_NOT_ENUMERATED;
    enum_init(&a);
    enum_init(&b);

    /* Pod A: ENUM_IN from host (always HIGH). Pod B: ENUM_IN = A's ENUM_OUT. */
    for (unsigned t = 0; t < 100; ++t) {
        bool a_in  = true;        /* host drives A's ENUM_IN */
        bool b_in  = a.enum_out;  /* A's ENUM_OUT → B's ENUM_IN */
        enum_step(&a, &sa, a_in);
        /* Once A is transmitting, B hears A's chain_index on CAN */
        if (a.phase >= ENUM_ASSIGNED) enum_notify_peer(&b, sa.chain_index);
        enum_step(&b, &sb, b_in);
    }

    assert(a.phase == ENUM_DONE);
    assert(b.phase == ENUM_DONE);
    assert(sa.chain_index == 0);
    assert(sb.chain_index == 1);
    assert(a.enum_out);
    assert(b.enum_out);
    assert(!(sa.status_flags & ST_NOT_ENUMERATED));
    assert(!(sb.status_flags & ST_NOT_ENUMERATED));
}

static void test_status_flags_preserved(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED | ST_ADC_FAULT | ST_SPI_FAULT;
    enum_init(&ctx);

    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS);
    /* ST_NOT_ENUMERATED cleared; other bits untouched */
    assert(!(st.status_flags & ST_NOT_ENUMERATED));
    assert(st.status_flags & ST_ADC_FAULT);
    assert(st.status_flags & ST_SPI_FAULT);
}

/* Data-integrity guard: a peer reporting the reserved 0xFF sentinel (corrupt
 * frame, or a chain that wrapped) must NOT reset us to index 0. We must still
 * claim max_peer+1 from the real peers we heard. */
static void test_peer_sentinel_0xff_rejected(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    enum_notify_peer(&ctx, 3);            /* real peer */
    enum_notify_peer(&ctx, ENUM_PEER_NONE); /* bogus 0xFF — must be ignored */
    /* fold the latch with one step (pin low: no phase change) */
    enum_step(&ctx, &st, false);
    assert(ctx.max_peer_index == 3);

    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS);
    assert(st.chain_index == 4);          /* 3 + 1, NOT wrapped to 0 */
    assert(!(st.status_flags & ST_NOT_ENUMERATED));
}

/* Data-integrity guard: a full chain (peer at 0xFE = ENUM_MAX_CHAIN_INDEX) must
 * fault loud rather than claim 0xFF (which the next pod reads as "no peers"). */
static void test_chain_full_faults(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    enum_notify_peer(&ctx, ENUM_MAX_CHAIN_INDEX);  /* 0xFE: last valid index */
    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS + ENUM_OUT_DELAY_TICKS);

    /* Must NOT enumerate: no valid index left. Fault stays set, ENUM_OUT low. */
    assert(st.status_flags & ST_NOT_ENUMERATED);
    assert(!ctx.enum_out);
    assert(ctx.phase != ENUM_DONE);
}

/* The ISR->loop latch only takes effect once enum_step() folds it: max_peer_index
 * is unchanged immediately after notify, then updated on the next step. */
static void test_notify_latches_until_step(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    enum_notify_peer(&ctx, 5);
    assert(ctx.peer_pending);
    assert(ctx.max_peer_index == ENUM_PEER_NONE); /* not folded yet */

    enum_step(&ctx, &st, false);                  /* main loop folds it in */
    assert(!ctx.peer_pending);
    assert(ctx.max_peer_index == 5);
}

/* Monotonic pending: a lower peer index must not clobber a higher one
 * that hasn't been consumed by enum_step() yet. */
static void test_pending_keeps_max(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    enum_notify_peer(&ctx, 7);
    enum_notify_peer(&ctx, 3);  /* lower — must not clobber 7 */
    enum_notify_peer(&ctx, 5);  /* still lower than 7 */
    assert(ctx.pending_peer_index == 7);

    enum_step(&ctx, &st, false);  /* fold */
    assert(ctx.max_peer_index == 7);
}

/* Data-integrity guard: after ENUM_DONE, peer traffic is a no-op. A late or
 * duplicate frame must not latch, must not change max_peer_index, and (even
 * after stepping) must not change the committed chain_index. */
static void test_notify_after_done_is_noop(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    enum_notify_peer(&ctx, 2);
    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS + ENUM_OUT_DELAY_TICKS);
    assert(ctx.phase == ENUM_DONE);
    uint8_t idx       = st.chain_index;       /* should be 3 (2 + 1) */
    uint8_t max_after = ctx.max_peer_index;   /* should be 2 */
    assert(idx == 3);
    assert(max_after == 2);

    /* Late peer frames after enumeration: dropped, nothing latched. */
    enum_notify_peer(&ctx, 99);
    assert(!ctx.peer_pending);
    assert(ctx.max_peer_index == max_after);

    /* Stepping after the late frame still changes nothing. */
    tick_n(&ctx, &st, true, 5);
    assert(ctx.max_peer_index == max_after);
    assert(st.chain_index == idx);
    assert(ctx.phase == ENUM_DONE);
}

/* Manufacturing scale: 7-pod passive arm (P4 roadmap target). Each pod must
 * enumerate to its ordinal position in the chain. */
static void test_seven_pod_chain(void) {
    #define N_PODS 7
    enum_ctx_t ctxs[N_PODS];
    inhabit_state_t states[N_PODS];
    for (int i = 0; i < N_PODS; ++i) {
        enum_init(&ctxs[i]);
        memset(&states[i], 0, sizeof(inhabit_state_t));
        states[i].status_flags = ST_NOT_ENUMERATED;
    }

    for (unsigned t = 0; t < 500; ++t) {
        enum_step(&ctxs[0], &states[0], true); /* host seeds pod 0 */
        for (int i = 1; i < N_PODS; ++i) {
            for (int j = 0; j < i; ++j) {
                if (ctxs[j].phase >= ENUM_ASSIGNED)
                    enum_notify_peer(&ctxs[i], states[j].chain_index);
            }
            enum_step(&ctxs[i], &states[i], ctxs[i - 1].enum_out);
        }
    }

    for (int i = 0; i < N_PODS; ++i) {
        assert(ctxs[i].phase == ENUM_DONE);
        assert(states[i].chain_index == (uint8_t)i);
        assert(!(states[i].status_flags & ST_NOT_ENUMERATED));
        assert(ctxs[i].enum_out);
    }
    #undef N_PODS
}

static void test_done_is_idempotent(void) {
    enum_ctx_t ctx;  inhabit_state_t st = {0};
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    tick_n(&ctx, &st, true, ENUM_DEBOUNCE_TICKS + ENUM_OUT_DELAY_TICKS);
    assert(ctx.phase == ENUM_DONE);

    /* Many more ticks — nothing changes */
    uint8_t idx = st.chain_index;
    uint8_t flags = st.status_flags;
    tick_n(&ctx, &st, true, 100);
    assert(st.chain_index == idx);
    assert(st.status_flags == flags);
    assert(ctx.phase == ENUM_DONE);
}

int main(void) {
    test_single_pod_enumerates_to_zero();
    test_debounce_rejects_glitch();
    test_peer_index_increments();
    test_two_pod_chain();
    test_status_flags_preserved();
    test_peer_sentinel_0xff_rejected();
    test_chain_full_faults();
    test_notify_latches_until_step();
    test_pending_keeps_max();
    test_notify_after_done_is_noop();
    test_seven_pod_chain();
    test_done_is_idempotent();
    printf("firmware enum: 12 tests passed\n");
    return 0;
}

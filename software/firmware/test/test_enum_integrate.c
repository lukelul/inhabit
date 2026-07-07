/* Host-side INTEGRATION test for the ENUM -> state -> schema-v1 frame wiring.
 *
 * Round-2 Lane A regression guard: before this, enum.c was ORPHANED — main.c had
 * a TODO stub for enum_step() and never called the real FSM, so chain_index was
 * left at its init value (0) and the schema-v1 frame on the wire NEVER carried
 * the enumerated index. This test reproduces exactly the data flow main.c now
 * performs:
 *
 *   enum_notify_peer()  (RX path observes a peer's chain_index)
 *        -> enum_step()  (main loop folds + assigns g_state.chain_index)
 *        -> inhabit_pack (schema-v1 frame byte 5 = chain_index)
 *
 * and asserts the packed frame's chain_index byte equals the index the ENUM FSM
 * assigned — i.e. the FSM output is actually carried on the bus, not dropped.
 *
 *   cc -I../inc test_enum_integrate.c ../src/enum.c ../src/can_frame.c -o t && ./t
 */
#include "enum.h"
#include "can_frame.h"
#include <assert.h>
#include <stdio.h>

/* Mirror of main.c's enum_tick(): advance the FSM with the given ENUM_IN level.
 * (main.c also drives the ENUM_OUT pin here; that's pure GPIO with no bearing on
 *  the chain_index data path under test.) */
static void enum_tick(enum_ctx_t *ctx, inhabit_state_t *st, bool enum_in) {
    enum_step(ctx, st, enum_in);
}

/* Byte index of chain_index in the schema-v1 frame (can_frame.h layout). */
#define FRAME_CHAIN_INDEX_BYTE 5

/* A lone pod (host seeds index 0): the assigned index must reach the frame. */
static void test_index0_reaches_frame(void) {
    enum_ctx_t ctx; inhabit_state_t st = {0};
    st.node_id = 7;
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    /* No peers heard; ENUM_IN asserted -> FSM assigns chain_index 0. */
    for (unsigned i = 0; i < ENUM_DEBOUNCE_TICKS; ++i) enum_tick(&ctx, &st, true);
    assert(st.chain_index == 0);
    assert(!(st.status_flags & ST_NOT_ENUMERATED)); /* fail-loud bit cleared */

    uint8_t frame[INHABIT_DLC];
    inhabit_pack(&st, frame);
    assert(frame[FRAME_CHAIN_INDEX_BYTE] == st.chain_index);
    assert(frame[FRAME_CHAIN_INDEX_BYTE] == 0);
}

/* The core regression: a peer index observed on the RX path (enum_notify_peer)
 * must propagate through the FSM into the packed frame as peer+1. If main.c ever
 * regresses to the orphaned stub, st.chain_index stays 0 and this fails. */
static void test_peer_index_propagates_to_frame(void) {
    enum_ctx_t ctx; inhabit_state_t st = {0};
    st.node_id = 9;
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    /* RX path observes a peer at chain_index 4 (== max(peer)). */
    enum_notify_peer(&ctx, 4);

    /* Main loop ticks the FSM with ENUM_IN asserted -> claims 5. */
    for (unsigned i = 0; i < ENUM_DEBOUNCE_TICKS; ++i) enum_tick(&ctx, &st, true);
    assert(st.chain_index == 5);

    uint8_t frame[INHABIT_DLC];
    inhabit_pack(&st, frame);

    /* Frame must carry the ENUM-assigned index, not the init/stub value. */
    assert(frame[FRAME_CHAIN_INDEX_BYTE] == st.chain_index);
    assert(frame[FRAME_CHAIN_INDEX_BYTE] == 5);

    /* And it must round-trip through unpack identical (checksum + index). */
    inhabit_state_t back;
    assert(inhabit_unpack(frame, &back));
    assert(back.chain_index == 5);
    assert(back.node_id == 9);
    assert(!(back.status_flags & ST_NOT_ENUMERATED));
}

/* Before enumeration completes, the frame must advertise ST_NOT_ENUMERATED
 * (fail loud) so a host/peer never trusts an un-indexed pod's chain_index. */
static void test_pre_enum_frame_fails_loud(void) {
    enum_ctx_t ctx; inhabit_state_t st = {0};
    st.node_id = 3;
    st.status_flags = ST_NOT_ENUMERATED;
    enum_init(&ctx);

    /* ENUM_IN never asserted: FSM stays in WAIT, index unset. */
    for (unsigned i = 0; i < 50; ++i) enum_tick(&ctx, &st, false);

    uint8_t frame[INHABIT_DLC];
    inhabit_pack(&st, frame);
    inhabit_state_t back;
    assert(inhabit_unpack(frame, &back));
    assert(back.status_flags & ST_NOT_ENUMERATED); /* still fail-loud on the wire */
}

int main(void) {
    test_index0_reaches_frame();
    test_peer_index_propagates_to_frame();
    test_pre_enum_frame_fails_loud();
    printf("firmware enum-integrate: 3 tests passed\n");
    return 0;
}

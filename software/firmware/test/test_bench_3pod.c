/* 3-pod bench harness — deterministic simulation of a 3-pod ENUM chain.
 *
 * Produces the exact schema-v1 CAN frames expected on the bus when three pods
 * enumerate via the ENUM daisy chain. This is the host-side golden reference
 * for bench verification: compare candump / logic-analyzer captures against
 * the byte sequences printed here.
 *
 * CANONICAL HARNESS: this file is the source of truth for the 3-pod golden
 * frames — it compiles the frozen codec, drives the real ENUM FSM, and asserts
 * its golden bytes at runtime. The table in BENCH_TESTS.md §4 is only an
 * ILLUSTRATIVE wire-format reference with rounder numbers and a different
 * scenario (node_id == chain_index, IDs 0x100..0x102); here node_id ==
 * chain_index + 1 and IDs are 0x101..0x103. If the two ever disagree, trust
 * this compiled harness.
 *
 *   cc -I../inc test_bench_3pod.c ../src/enum.c ../src/can_frame.c -o t && ./t
 */
#include "enum.h"
#include "can_frame.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define NUM_PODS 3

/* Per-pod simulation state. */
typedef struct {
    enum_ctx_t    ectx;
    inhabit_state_t st;
} pod_t;

/* Helper: tick all pods one step. Pod 0's ENUM_IN is always HIGH (host seeds).
 * Pod N's ENUM_IN = Pod N-1's enum_out. After each pod's ENUM_ASSIGNED, it
 * broadcasts its chain_index to all downstream pods (simulates CAN RX). */
static void tick_all(pod_t pods[NUM_PODS]) {
    for (int i = 0; i < NUM_PODS; ++i) {
        bool ein = (i == 0) ? true : pods[i - 1].ectx.enum_out;
        /* Before stepping, feed upstream peers' chain_index via CAN. */
        for (int j = 0; j < i; ++j) {
            if (pods[j].ectx.phase >= ENUM_ASSIGNED) {
                enum_notify_peer(&pods[i].ectx, pods[j].st.chain_index);
            }
        }
        enum_step(&pods[i].ectx, &pods[i].st, ein);
    }
}

static void print_frame(const char *label, uint8_t node_id, const uint8_t frame[INHABIT_DLC]) {
    uint32_t can_id = inhabit_can_id(node_id);
    printf("  %s  CAN ID 0x%03X  [", label, can_id);
    for (unsigned i = 0; i < INHABIT_DLC; ++i) {
        printf("%02X%s", frame[i], (i < INHABIT_DLC - 1) ? " " : "");
    }
    printf("]\n");
}

/* Core test: 3 pods enumerate to chain_index 0, 1, 2. Each produces a valid
 * schema-v1 frame with the correct chain_index byte and checksum. */
static void test_3pod_chain_frames(void) {
    pod_t pods[NUM_PODS];
    memset(pods, 0, sizeof(pods));

    /* Assign unique node_ids (in a real system these are hard-coded or from
     * board strapping — here we just use 1, 2, 3 for clarity). */
    for (int i = 0; i < NUM_PODS; ++i) {
        enum_init(&pods[i].ectx);
        pods[i].st.node_id       = (uint8_t)(i + 1);
        pods[i].st.status_flags  = ST_NOT_ENUMERATED;
        pods[i].st.angle_raw_adc = (uint16_t)(1000 + i * 500); /* synthetic */
        pods[i].st.angle_millideg = (int16_t)(i * 12000);       /* synthetic */
    }

    /* Run enough ticks for the full chain to enumerate. Worst case:
     * DEBOUNCE + OUT_DELAY per pod, cascaded. 200 ticks is plenty. */
    for (int t = 0; t < 200; ++t) tick_all(pods);

    /* Verify all pods reached DONE with correct chain_index. */
    for (int i = 0; i < NUM_PODS; ++i) {
        assert(pods[i].ectx.phase == ENUM_DONE);
        assert(pods[i].st.chain_index == (uint8_t)i);
        assert(!(pods[i].st.status_flags & ST_NOT_ENUMERATED));
        assert(pods[i].ectx.enum_out);
    }

    /* Pack each pod's state and verify against hardcoded golden bytes.
     * These pin the wire format independently of inhabit_pack/unpack — a
     * schema regression changes the expected bytes and breaks this test. */
    printf("\n=== Expected 3-pod CAN frames (bench golden reference) ===\n");
    printf("  Schema v1: [angle_adc_lo, angle_adc_hi, mdeg_lo, mdeg_hi, "
           "node_id, chain_index, status, checksum]\n\n");

    /* Golden frames computed by hand from the init values above:
     *   Pod 0: adc=1000(0x03E8) mdeg=0(0x0000) nid=1 ci=0 sf=0x00
     *   Pod 1: adc=1500(0x05DC) mdeg=12000(0x2EE0) nid=2 ci=1 sf=0x00
     *   Pod 2: adc=2000(0x07D0) mdeg=24000(0x5DC0) nid=3 ci=2 sf=0x00
     *   checksum = XOR of bytes 0..6 */
    static const uint8_t golden[NUM_PODS][INHABIT_DLC] = {
        { 0xE8, 0x03, 0x00, 0x00, 0x01, 0x00, 0x00, 0xEA },
        { 0xDC, 0x05, 0xE0, 0x2E, 0x02, 0x01, 0x00, 0x14 },
        { 0xD0, 0x07, 0xC0, 0x5D, 0x03, 0x02, 0x00, 0x4B },
    };
    static const uint32_t golden_ids[NUM_PODS] = { 0x101, 0x102, 0x103 };

    for (int i = 0; i < NUM_PODS; ++i) {
        uint8_t frame[INHABIT_DLC];
        inhabit_pack(&pods[i].st, frame);

        char label[16];
        snprintf(label, sizeof(label), "Pod %d:", i);
        print_frame(label, pods[i].st.node_id, frame);

        /* Assert packed frame matches golden bytes exactly. */
        assert(memcmp(frame, golden[i], INHABIT_DLC) == 0);

        /* Verify CAN ID against hardcoded expected value. */
        assert(inhabit_can_id(pods[i].st.node_id) == golden_ids[i]);

        /* Manually verify byte-7 XOR checksum (independent of unpack). */
        uint8_t xor = 0;
        for (unsigned b = 0; b < 7; ++b) xor ^= frame[b];
        assert(frame[7] == xor);

        /* Verify key byte positions match schema v1 contract:
         *   [0:1] = angle_raw_adc LE, [2:3] = angle_millideg LE,
         *   [4] = node_id, [5] = chain_index, [6] = status_flags */
        assert(frame[4] == pods[i].st.node_id);
        assert(frame[5] == (uint8_t)i);  /* chain_index */
        assert(frame[6] == 0x00);        /* no faults, enumerated */

        /* Round-trip still works. */
        inhabit_state_t back;
        assert(inhabit_unpack(frame, &back));
        assert(back.chain_index == (uint8_t)i);
        assert(back.node_id == pods[i].st.node_id);
    }
}

/* Pre-enumeration: all 3 pods must advertise ST_NOT_ENUMERATED. A host/peer
 * must never trust chain_index from a frame with this flag set. */
static void test_pre_enum_all_fail_loud(void) {
    pod_t pods[NUM_PODS];
    memset(pods, 0, sizeof(pods));
    for (int i = 0; i < NUM_PODS; ++i) {
        enum_init(&pods[i].ectx);
        pods[i].st.node_id = (uint8_t)(i + 1);
        pods[i].st.status_flags = ST_NOT_ENUMERATED;
    }

    /* Zero ticks: no ENUM_IN seen yet. */
    for (int i = 0; i < NUM_PODS; ++i) {
        uint8_t frame[INHABIT_DLC];
        inhabit_pack(&pods[i].st, frame);
        assert(frame[6] & ST_NOT_ENUMERATED);
    }
}

/* Partial chain: only 2 of 3 pods get ENUM_IN. Pod 2 must stay fail-loud. */
static void test_partial_chain_fault(void) {
    pod_t pods[NUM_PODS];
    memset(pods, 0, sizeof(pods));
    for (int i = 0; i < NUM_PODS; ++i) {
        enum_init(&pods[i].ectx);
        pods[i].st.node_id = (uint8_t)(i + 1);
        pods[i].st.status_flags = ST_NOT_ENUMERATED;
    }

    /* Only tick pods 0 and 1 with their ENUM_IN driven. Pod 2 never gets
     * ENUM_IN because we won't connect pod 1's ENUM_OUT to pod 2. */
    for (int t = 0; t < 200; ++t) {
        enum_step(&pods[0].ectx, &pods[0].st, true); /* host seeds */
        bool p1_in = pods[0].ectx.enum_out;
        if (pods[0].ectx.phase >= ENUM_ASSIGNED)
            enum_notify_peer(&pods[1].ectx, pods[0].st.chain_index);
        enum_step(&pods[1].ectx, &pods[1].st, p1_in);
        /* Pod 2: ENUM_IN stays LOW (disconnected). */
        enum_step(&pods[2].ectx, &pods[2].st, false);
    }

    assert(pods[0].ectx.phase == ENUM_DONE);
    assert(pods[0].st.chain_index == 0);
    assert(pods[1].ectx.phase == ENUM_DONE);
    assert(pods[1].st.chain_index == 1);
    /* Pod 2: still un-enumerated — fail loud on the bus. */
    assert(pods[2].ectx.phase == ENUM_WAIT);
    assert(pods[2].st.status_flags & ST_NOT_ENUMERATED);
}

int main(void) {
    test_3pod_chain_frames();
    test_pre_enum_all_fail_loud();
    test_partial_chain_fault();
    printf("\nfirmware bench-3pod: 3 tests passed\n");
    return 0;
}

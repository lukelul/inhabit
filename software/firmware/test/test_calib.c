#include "calib.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void test_adc_validation(void) {
    assert(inhabit_calib_adc_valid(0u));
    assert(inhabit_calib_adc_valid(2048u));
    assert(inhabit_calib_adc_valid(4095u));
    assert(!inhabit_calib_adc_valid(4096u));
    assert(!inhabit_calib_adc_valid(0xFFFFu));
}

static void test_conversion_basic(void) {
    inhabit_calib_params_t params = { 1.5f, -1500.0f };
    assert(inhabit_calib_adc_to_millideg(1000u, &params) == 0);
    assert(inhabit_calib_adc_to_millideg(2000u, &params) == 1500);
    assert(inhabit_calib_adc_to_millideg(3000u, &params) == 3000);
}

static void test_conversion_null_params(void) {
    assert(inhabit_calib_adc_to_millideg(1000u, 0) == 0);
}

static void test_conversion_zero_adc(void) {
    inhabit_calib_params_t params = { 1.5f, -1500.0f };
    assert(inhabit_calib_adc_to_millideg(0u, &params) == -1500);
}

static void test_conversion_max_adc(void) {
    inhabit_calib_params_t params = { 1.5f, -1500.0f };
    int32_t result = inhabit_calib_adc_to_millideg(4095u, &params);
    assert(result > 0);  /* sanity: max ADC should produce positive angle */
}

static void test_fit_linear(void) {
    inhabit_calib_sample_t samples[] = {
        { 1000u, 0 },
        { 2000u, 1500 },
        { 3000u, 3000 },
    };
    inhabit_calib_params_t fitted = { 0.0f, 0.0f };
    assert(inhabit_calib_fit_linear(samples, 3u, &fitted));
    assert(inhabit_calib_adc_to_millideg(1000u, &fitted) == 0);
    assert(inhabit_calib_adc_to_millideg(3000u, &fitted) == 3000);
}

static void test_fit_rejects_insufficient(void) {
    inhabit_calib_sample_t one = { 1000u, 0 };
    inhabit_calib_params_t p = { 0.0f, 0.0f };
    assert(!inhabit_calib_fit_linear(&one, 1u, &p));
    assert(!inhabit_calib_fit_linear(&one, 0u, &p));
    assert(!inhabit_calib_fit_linear(0, 3u, &p));
    assert(!inhabit_calib_fit_linear(&one, 2u, 0));
}

static void test_fit_rejects_degenerate(void) {
    /* Exact-zero denominator: all x identical → denom == 0 → must reject. */
    inhabit_calib_sample_t degen[] = {
        { 2000u, 100 },
        { 2000u, 200 },
        { 2000u, 300 },
    };
    inhabit_calib_params_t p = { 0.0f, 0.0f };
    assert(!inhabit_calib_fit_linear(degen, 3u, &p));

    /* Scale-aware rejection at HIGH magnitude. The old fixed `1e-9f` epsilon was
       meaningless against accumulators of order n*adc^2 (~1.3e10 here): a fixed
       absolute floor neither scales with the operands nor proves the new guard.
       This all-identical large-x set drives denominator to 0; the scale-aware
       test `fabs(denom) <= DBL_EPSILON*(fabs(lhs)+fabs(rhs))` must still reject
       it regardless of magnitude. (With uint16 ADC inputs, distinct integers
       differ by >=1 LSB and yield a denominator far above the threshold at any
       practical sample_count — see the accept case below — so an all-identical
       set is the only integer-reachable rejection.) */
    inhabit_calib_sample_t degen_hi[] = {
        { 65535u, 100 },
        { 65535u, 200 },
        { 65535u, 300 },
        { 65535u, 400 },
    };
    assert(!inhabit_calib_fit_linear(degen_hi, 4u, &p));

    /* Near-degenerate but VALID at high magnitude: ADC clustered at the top of
       the uint16 range (65530..65535) with a genuine 1-LSB-grid spread. The true
       denominator is small relative to lhs/rhs (~1e10) yet well above the
       scale-aware threshold, so this must be ACCEPTED and resolve a correct,
       finite slope. This is exactly the float-precision regime that commit
       5f7e32b fixed: float accumulators lose the slope here; double recovers it.
       The original test (1-LSB spread at mid-range) did not exercise this. */
    inhabit_calib_sample_t near_degen[] = {
        { 65530u, 0 },
        { 65531u, 2 },
        { 65532u, 4 },
        { 65533u, 6 },
        { 65534u, 8 },
        { 65535u, 10 },
    };
    p.slope = 0.0f;
    p.intercept = 0.0f;
    assert(inhabit_calib_fit_linear(near_degen, 6u, &p));
    assert(p.slope == p.slope);          /* finite: NaN != NaN */
    assert(p.intercept == p.intercept);  /* finite */
    /* true line is millideg = 2*(adc - 65530); slope ~= 2.0 within float eps */
    assert(p.slope > 1.99f && p.slope < 2.01f);
    assert(inhabit_calib_adc_to_millideg(65530u, &p) >= -1 &&
           inhabit_calib_adc_to_millideg(65530u, &p) <= 1);
    assert(inhabit_calib_adc_to_millideg(65535u, &p) >= 9 &&
           inhabit_calib_adc_to_millideg(65535u, &p) <= 11);
}

static void test_fit_two_points(void) {
    /* int16_t millideg range: -32768..32767; use realistic sub-range */
    inhabit_calib_sample_t two[] = {
        { 0u, -10000 },
        { 4095u, 10000 },
    };
    inhabit_calib_params_t p = { 0.0f, 0.0f };
    assert(inhabit_calib_fit_linear(two, 2u, &p));
    assert(inhabit_calib_adc_to_millideg(0u, &p) == -10000);
    int32_t full = inhabit_calib_adc_to_millideg(4095u, &p);
    assert(full >= 9999 && full <= 10001);
}

static void test_calib_id(void) {
    assert(inhabit_calib_id(0u) == INHABIT_CALIB_BASE_ID);
    assert(inhabit_calib_id(3u) == 0x303u);
    assert(inhabit_calib_id(255u) == INHABIT_CALIB_BASE_ID + 255u);
}

static void test_pack_unpack_roundtrip(void) {
    uint8_t frame[INHABIT_CALIB_DLC];
    inhabit_calib_telemetry_t tx = { 2048u, 1234, 3u, 1u, 0u };
    inhabit_calib_pack(&tx, frame);

    inhabit_calib_telemetry_t rx;
    assert(inhabit_calib_unpack(frame, &rx));
    assert(rx.raw_adc == tx.raw_adc);
    assert(rx.calibrated_millideg == tx.calibrated_millideg);
    assert(rx.node_id == tx.node_id);
    assert(rx.chain_index == tx.chain_index);
    assert(rx.status_flags == tx.status_flags);
}

static void test_pack_unpack_extremes(void) {
    /* max values */
    uint8_t frame[INHABIT_CALIB_DLC];
    inhabit_calib_telemetry_t tx = { 4095u, 32767, 255u, 255u, 0xFFu };
    inhabit_calib_pack(&tx, frame);
    inhabit_calib_telemetry_t rx;
    assert(inhabit_calib_unpack(frame, &rx));
    assert(rx.raw_adc == 4095u);
    assert(rx.calibrated_millideg == 32767);
    assert(rx.status_flags == 0xFFu);

    /* negative millideg */
    inhabit_calib_telemetry_t neg = { 0u, -1500, 0u, 0u, 0u };
    inhabit_calib_pack(&neg, frame);
    assert(inhabit_calib_unpack(frame, &rx));
    assert(rx.calibrated_millideg == -1500);
    assert(rx.raw_adc == 0u);
}

static void test_corrupt_checksum_rejected(void) {
    uint8_t frame[INHABIT_CALIB_DLC];
    inhabit_calib_telemetry_t tx = { 2048u, 1234, 3u, 1u, 0u };
    inhabit_calib_pack(&tx, frame);

    /* flip one bit in the checksum */
    frame[7] ^= 0x01u;
    inhabit_calib_telemetry_t rx;
    assert(!inhabit_calib_unpack(frame, &rx));
}

static void test_corrupt_payload_rejected(void) {
    uint8_t frame[INHABIT_CALIB_DLC];
    inhabit_calib_telemetry_t tx = { 2048u, 1234, 3u, 1u, 0u };
    inhabit_calib_pack(&tx, frame);

    /* corrupt a payload byte */
    frame[0] ^= 0xFFu;
    inhabit_calib_telemetry_t rx;
    assert(!inhabit_calib_unpack(frame, &rx));
}

/* Golden bytes for C↔Python parity: tx = {2048, 1234, 3, 1, 0} */
static void test_golden_frame_bytes(void) {
    uint8_t frame[INHABIT_CALIB_DLC];
    inhabit_calib_telemetry_t tx = { 2048u, 1234, 3u, 1u, 0u };
    inhabit_calib_pack(&tx, frame);

    /* LE: 2048=0x0800, 1234=0x04D2, node=3, chain=1, flags=0 */
    assert(frame[0] == 0x00u);  /* raw_adc low */
    assert(frame[1] == 0x08u);  /* raw_adc high */
    assert(frame[2] == 0xD2u);  /* millideg low */
    assert(frame[3] == 0x04u);  /* millideg high */
    assert(frame[4] == 0x03u);  /* node_id */
    assert(frame[5] == 0x01u);  /* chain_index */
    assert(frame[6] == 0x00u);  /* status_flags */
    /* checksum = XOR of bytes 0..6 = 0x00^0x08^0xD2^0x04^0x03^0x01^0x00 */
    uint8_t expected_cksum = 0x00u ^ 0x08u ^ 0xD2u ^ 0x04u ^ 0x03u ^ 0x01u ^ 0x00u;
    assert(frame[7] == expected_cksum);
}

int main(void) {
    test_adc_validation();
    test_conversion_basic();
    test_conversion_null_params();
    test_conversion_zero_adc();
    test_conversion_max_adc();
    test_fit_linear();
    test_fit_rejects_insufficient();
    test_fit_rejects_degenerate();
    test_fit_two_points();
    test_calib_id();
    test_pack_unpack_roundtrip();
    test_pack_unpack_extremes();
    test_corrupt_checksum_rejected();
    test_corrupt_payload_rejected();
    test_golden_frame_bytes();

    printf("firmware calib: 15 tests passed\n");
    return 0;
}

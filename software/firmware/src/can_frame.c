#include "can_frame.h"

static uint8_t xor7(const uint8_t *b) {
    uint8_t c = 0;
    for (int i = 0; i < 7; ++i) c ^= b[i];
    return c;
}

uint32_t inhabit_can_id(uint8_t node_id) { return INHABIT_CAN_BASE_ID + node_id; }

void inhabit_pack(const inhabit_state_t *s, uint8_t out[INHABIT_DLC]) {
    out[0] = (uint8_t)(s->angle_raw_adc & 0xFF);
    out[1] = (uint8_t)(s->angle_raw_adc >> 8);
    out[2] = (uint8_t)((uint16_t)s->angle_millideg & 0xFF);
    out[3] = (uint8_t)((uint16_t)s->angle_millideg >> 8);
    out[4] = s->node_id;
    out[5] = s->chain_index;
    out[6] = s->status_flags;
    out[7] = xor7(out);
}

bool inhabit_unpack(const uint8_t in[INHABIT_DLC], inhabit_state_t *s) {
    s->angle_raw_adc  = (uint16_t)(in[0] | (in[1] << 8));
    s->angle_millideg = (int16_t)(in[2] | (in[3] << 8));
    s->node_id        = in[4];
    s->chain_index    = in[5];
    s->status_flags   = in[6];
    return xor7(in) == in[7];
}

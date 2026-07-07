/* Inhabit CAN schema v1 — single source of truth (mirrors host/inhabit_can/codec.py).
 * Frame: ID = 0x100 + node_id, DLC 8.
 *   [0:1] angle_raw_adc  u16 LE
 *   [2:3] angle_millideg i16 LE
 *   [4]   node_id        u8
 *   [5]   chain_index    u8
 *   [6]   status_flags   u8
 *   [7]   checksum       u8 (XOR of bytes 0..6)
 */
#ifndef INHABIT_CAN_FRAME_H
#define INHABIT_CAN_FRAME_H
#include <stdint.h>
#include <stdbool.h>

#define INHABIT_CAN_BASE_ID 0x100u
#define INHABIT_DLC         8u

/* status_flags bits */
#define ST_ADC_FAULT       (1u<<0)
#define ST_SPI_FAULT       (1u<<1)
#define ST_CAN_FAULT       (1u<<2)
#define ST_MAGNET_OOB      (1u<<3)
#define ST_NOT_ENUMERATED  (1u<<4)
#define ST_CALIB_INVALID   (1u<<5)

typedef struct {
    uint16_t angle_raw_adc;
    int16_t  angle_millideg;
    uint8_t  node_id;
    uint8_t  chain_index;
    uint8_t  status_flags;
} inhabit_state_t;

uint32_t inhabit_can_id(uint8_t node_id);
void     inhabit_pack(const inhabit_state_t *s, uint8_t out[INHABIT_DLC]);
bool     inhabit_unpack(const uint8_t in[INHABIT_DLC], inhabit_state_t *s); /* false if checksum bad */

#endif

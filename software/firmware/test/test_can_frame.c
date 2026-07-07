/* Host-side unit test for the CAN codec — build with gcc, no STM32 toolchain needed.
 *   cc -I../inc test_can_frame.c ../src/can_frame.c -o t && ./t
 */
#include "can_frame.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    int n = 0;
    for (int i = 0; i < 5000; ++i) {
        inhabit_state_t s = { (uint16_t)(i*37), (int16_t)(i*7 - 16000),
                              (uint8_t)i, (uint8_t)(i>>2), (uint8_t)(i*3) };
        uint8_t f[INHABIT_DLC];
        inhabit_pack(&s, f);
        assert(inhabit_can_id(s.node_id) == 0x100u + s.node_id);
        inhabit_state_t r;
        assert(inhabit_unpack(f, &r) == true);
        assert(r.angle_raw_adc==s.angle_raw_adc && r.angle_millideg==s.angle_millideg);
        assert(r.node_id==s.node_id && r.chain_index==s.chain_index && r.status_flags==s.status_flags);
        f[0] ^= 0x01; /* corrupt -> checksum must fail */
        inhabit_state_t bad;
        assert(inhabit_unpack(f, &bad) == false);
        ++n;
    }
    printf("firmware can_frame: %d frames round-trip + bitflip OK\n", n);
    return 0;
}

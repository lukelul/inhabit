/* CAN service fault-bit policy — pure logic. See can_health.h for the policy. */
#include "can_health.h"
#include "can_frame.h"

uint8_t can_health_apply(uint8_t flags, mcp_status_t st, bool roundtrip_ok) {
    if (st == MCP_OK && roundtrip_ok) {
        /* Healthy round-trip: clear BOTH fault bits uniformly (non-sticky). */
        flags &= (uint8_t)~(ST_SPI_FAULT | ST_CAN_FAULT);
        return flags;
    }
    if (st == MCP_ERR_SPI) {
        flags |= ST_SPI_FAULT;   /* fail loud on a real SPI fault */
    } else {
        flags |= ST_CAN_FAULT;   /* mode/TX/RX timeout, or OK-but-bad-echo */
    }
    return flags;
}

/* Host-side unit test for the CAN fault-bit policy (can_health_apply).
 *   cc -I../inc -I../drivers test_can_health.c ../src/can_health.c -o t && ./t
 *
 * Proves the embedded-reviewer fix (finding 2a): ST_SPI_FAULT is NO LONGER
 * sticky — a healthy round-trip clears BOTH ST_SPI_FAULT and ST_CAN_FAULT,
 * uniformly. Real faults still latch (fail loud). Unrelated status bits are
 * preserved.
 */
#include "can_health.h"
#include "can_frame.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    /* --- healthy round-trip clears BOTH fault bits, keeps the rest --- */
    {
        uint8_t f = ST_SPI_FAULT | ST_CAN_FAULT | ST_NOT_ENUMERATED | ST_ADC_FAULT;
        f = can_health_apply(f, MCP_OK, /*roundtrip_ok=*/true);
        assert((f & ST_SPI_FAULT) == 0);          /* the regression: SPI clears now */
        assert((f & ST_CAN_FAULT) == 0);
        assert((f & ST_NOT_ENUMERATED) != 0);     /* untouched */
        assert((f & ST_ADC_FAULT) != 0);          /* untouched */
    }

    /* --- the exact bug scenario: one transient SPI glitch must not persist --- */
    {
        uint8_t f = 0;
        f = can_health_apply(f, MCP_ERR_SPI, false);  /* glitch */
        assert(f & ST_SPI_FAULT);
        f = can_health_apply(f, MCP_OK, true);        /* recovery */
        assert((f & ST_SPI_FAULT) == 0);              /* no longer poisoned */
    }

    /* --- SPI fault sets ST_SPI_FAULT only (fail loud) --- */
    {
        uint8_t f = can_health_apply(0, MCP_ERR_SPI, false);
        assert(f == ST_SPI_FAULT);
    }

    /* --- mode/TX/RX timeouts set ST_CAN_FAULT only --- */
    {
        assert(can_health_apply(0, MCP_ERR_MODE, false)       == ST_CAN_FAULT);
        assert(can_health_apply(0, MCP_ERR_TX_TIMEOUT, false) == ST_CAN_FAULT);
        assert(can_health_apply(0, MCP_ERR_RX_TIMEOUT, false) == ST_CAN_FAULT);
    }

    /* --- OK status but a bad loopback echo is a CAN fault, not a clear --- */
    {
        uint8_t f = can_health_apply(0, MCP_OK, /*roundtrip_ok=*/false);
        assert(f == ST_CAN_FAULT);
        /* and it must not have cleared a pre-existing SPI fault */
        f = can_health_apply(ST_SPI_FAULT, MCP_OK, false);
        assert(f & ST_SPI_FAULT);
        assert(f & ST_CAN_FAULT);
    }

    /* --- both bits are non-sticky and clear together on the next healthy trip --- */
    {
        uint8_t f = ST_SPI_FAULT | ST_CAN_FAULT;
        f = can_health_apply(f, MCP_OK, true);
        assert((f & (ST_SPI_FAULT | ST_CAN_FAULT)) == 0);
    }

    printf("can_health: fault-bit clear/set policy OK (SPI no longer sticky)\n");
    return 0;
}

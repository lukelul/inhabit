/* Host-side unit test for the MCP2515 driver loopback path — no hardware.
 *   cc -I../inc -I../drivers test_mcp2515.c ../drivers/mcp2515.c ../src/can_frame.c -o t && ./t
 *
 * A mock register file emulates the MCP2515 enough to validate, host-side:
 *   - reset leaves the device reporting Configuration mode,
 *   - CNF1/2/3 get the 500k/16MHz values,
 *   - LOOPBACK mode is entered and confirmed via CANSTAT,
 *   - an inhabit_pack() frame loaded into TXB0 + RTS round-trips into RXB0,
 *   - TX-done is seen via TXB0CTRL.TXREQ clearing, RX via CANINTF.RX0IF,
 *   - the bytes read back equal what the frozen codec produced (checksum valid).
 */
#include "mcp2515.h"
#include "can_frame.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* ---- Mock MCP2515 -------------------------------------------------------- */
typedef struct {
    uint8_t reg[0x80];   /* register file */
    uint8_t opmode;      /* current OPMOD bits, mirrored into CANSTAT[7:5] */
    int spi_fail;        /* force SPI faults to exercise ST_SPI_FAULT path */
} mock_t;

/* Emulate a single CS-framed SPI command. */
static int mock_transfer(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n) {
    mock_t *m = (mock_t *)ctx;
    if (m->spi_fail) return 1;
    memset(rx, 0, n);
    uint8_t cmd = tx[0];

    if (cmd == MCP_CMD_RESET) {
        memset(m->reg, 0, sizeof m->reg);
        m->opmode = MCP_MODE_CONFIG;                 /* RESET -> Config mode */
        m->reg[MCP_REG_CANSTAT] = m->opmode;
        m->reg[MCP_REG_CANCTRL] = m->opmode;
        return 0;
    }
    if (cmd == MCP_CMD_READ) {                        /* READ addr -> rx[2] */
        rx[2] = m->reg[tx[1] & 0x7F];
        return 0;
    }
    if (cmd == MCP_CMD_WRITE) {
        uint8_t a = tx[1] & 0x7F;
        m->reg[a] = tx[2];
        if (a == MCP_REG_CANCTRL) {                  /* mode change request */
            m->opmode = tx[2] & MCP_MODE_MASK;
            m->reg[MCP_REG_CANSTAT] = m->opmode;     /* hardware confirms */
        }
        return 0;
    }
    if (cmd == MCP_CMD_BIT_MODIFY) {
        uint8_t a = tx[1] & 0x7F, mask = tx[2], data = tx[3];
        m->reg[a] = (uint8_t)((m->reg[a] & ~mask) | (data & mask));
        if (a == MCP_REG_CANCTRL) {
            m->opmode = m->reg[a] & MCP_MODE_MASK;
            m->reg[MCP_REG_CANSTAT] = m->opmode;
        }
        return 0;
    }
    if ((cmd & 0xF8) == 0x80) {                       /* RTS (0x80 | bufmask) */
        if (cmd & 0x01) {                            /* TXB0 requested */
            /* Loopback: TXREQ self-clears, frame appears in RXB0, RX0IF set. */
            m->reg[MCP_REG_TXB0CTRL] &= (uint8_t)~MCP_TXBCTRL_TXREQ;
            m->reg[MCP_REG_RXB0SIDH] = m->reg[MCP_REG_TXB0SIDH];
            m->reg[MCP_REG_RXB0SIDL] = m->reg[MCP_REG_TXB0SIDL];
            m->reg[MCP_REG_RXB0DLC]  = m->reg[MCP_REG_TXB0DLC];
            for (int i = 0; i < 8; ++i)
                m->reg[MCP_REG_RXB0D0 + i] = m->reg[MCP_REG_TXB0D0 + i];
            m->reg[MCP_REG_CANINTF] |= MCP_INTF_RX0IF;
        }
        return 0;
    }
    return 0; /* READ_STATUS / RX_STATUS unused here */
}

int main(void) {
    /* --- bit-timing constants (pure logic) match the documented 500k/16MHz --- */
    assert(MCP_CNF1_500K_16MHZ == 0x00);
    assert(MCP_CNF2_500K_16MHZ == 0xB1);
    assert(MCP_CNF3_500K_16MHZ == 0x05);

    /* --- SID encode/decode is reversible for all 11-bit IDs --- */
    for (uint32_t id = 0; id <= 0x7FF; ++id) {
        uint8_t sidh, sidl;
        mcp2515_encode_sid(id, &sidh, &sidl);
        uint32_t back = ((uint32_t)sidh << 3) | ((sidl >> 5) & 0x07u);
        assert(back == id);
        assert((sidl & 0x08u) == 0); /* IDE must be 0 for standard frames */
    }

    mock_t m; memset(&m, 0, sizeof m);
    mcp2515_io_t io = { mock_transfer, &m };

    /* --- init in loopback, mode confirmed via CANSTAT --- */
    assert(mcp2515_init(&io, MCP_MODE_LOOPBACK) == MCP_OK);
    assert(m.reg[MCP_REG_CNF1] == MCP_CNF1_500K_16MHZ);
    assert(m.reg[MCP_REG_CNF2] == MCP_CNF2_500K_16MHZ);
    assert(m.reg[MCP_REG_CNF3] == MCP_CNF3_500K_16MHZ);
    assert((m.reg[MCP_REG_CANSTAT] & MCP_MODE_MASK) == MCP_MODE_LOOPBACK);

    /* --- CANINTE enables RX0/RX1 only on /INT (PB6); no TXnIE (TX polled).
     * Loopback RX sets RX0IF, which drives /INT -> the EXTI path. ERRIE/MERRE
     * are omitted for loopback (level-/INT + edge-EXTI with no error-flag clear
     * path would latch /INT low forever — re-add in P2 with a clear+sweep). --- */
    assert(m.reg[MCP_REG_CANINTE] == MCP_CANINTE_BRINGUP);
    assert(m.reg[MCP_REG_CANINTE] & MCP_INTE_RX0IE);
    assert(m.reg[MCP_REG_CANINTE] & MCP_INTE_RX1IE);
    /* error sources must NOT be on /INT yet (no clear path -> would fail silent) */
    assert((m.reg[MCP_REG_CANINTE] & (MCP_INTE_ERRIE | MCP_INTE_MERRE)) == 0);
    assert((m.reg[MCP_REG_CANINTE] &
            (MCP_INTE_TX0IE | MCP_INTE_TX1IE | MCP_INTE_TX2IE)) == 0);

    /* --- build a schema-v1 frame with the FROZEN codec and round-trip it --- */
    int frames = 0;
    for (int i = 0; i < 2000; ++i) {
        inhabit_state_t s = { (uint16_t)(i*41), (int16_t)(i*5 - 5000),
                              (uint8_t)i, (uint8_t)(i>>3), (uint8_t)(i*9) };
        uint8_t frame[INHABIT_DLC];
        inhabit_pack(&s, frame);
        uint32_t id = inhabit_can_id(s.node_id);

        /* Model real silicon: TXB0 is "armed" (TXREQ set) before send. send_std
         * issues RTS last; the mock clears TXREQ on RTS (frame sent), so
         * poll_tx_done observes the set->clear transition. */
        m.reg[MCP_REG_TXB0CTRL] |= MCP_TXBCTRL_TXREQ;

        assert(mcp2515_send_std(&io, id, frame, INHABIT_DLC) == MCP_OK);
        assert(mcp2515_poll_tx_done(&io, 50) == MCP_OK);

        uint32_t rid = 0; uint8_t rlen = 0; uint8_t rbuf[INHABIT_DLC] = {0};
        assert(mcp2515_poll_recv(&io, 50, &rid, rbuf, &rlen) == MCP_OK);
        assert(rid == id);
        assert(rlen == INHABIT_DLC);
        assert(memcmp(rbuf, frame, INHABIT_DLC) == 0);  /* byte-identical TX->RX */

        /* The bytes read back must decode through the frozen codec (checksum ok). */
        inhabit_state_t r;
        assert(inhabit_unpack(rbuf, &r) == true);
        assert(r.node_id == s.node_id && r.angle_raw_adc == s.angle_raw_adc &&
               r.angle_millideg == s.angle_millideg && r.status_flags == s.status_flags);

        /* RX0IF must be cleared after a successful recv. */
        assert((m.reg[MCP_REG_CANINTF] & MCP_INTF_RX0IF) == 0);
        ++frames;
    }

    /* --- fault injection: SPI failure surfaces as MCP_ERR_SPI (-> ST_SPI_FAULT) --- */
    m.spi_fail = 1;
    assert(mcp2515_read_reg(&io, MCP_REG_CANSTAT, &(uint8_t){0}) == MCP_ERR_SPI);
    assert(mcp2515_init(&io, MCP_MODE_LOOPBACK) == MCP_ERR_SPI);
    m.spi_fail = 0;

    /* --- TX timeout: TXREQ never clears -> MCP_ERR_TX_TIMEOUT (-> ST_CAN_FAULT) --- */
    m.reg[MCP_REG_TXB0CTRL] = MCP_TXBCTRL_TXREQ; /* stuck set, no RTS */
    assert(mcp2515_poll_tx_done(&io, 8) == MCP_ERR_TX_TIMEOUT);

    /* --- RX timeout: no RX0IF -> MCP_ERR_RX_TIMEOUT --- */
    m.reg[MCP_REG_CANINTF] &= (uint8_t)~MCP_INTF_RX0IF;
    assert(mcp2515_poll_recv(&io, 8, NULL, (uint8_t[8]){0}, NULL) == MCP_ERR_RX_TIMEOUT);

    /* --- emit one known example frame (hex) for Track 2's bridge test --- */
    {
        inhabit_state_t ex = { 0x0ABC /*raw*/, 12345 /*millideg*/,
                               3 /*node_id*/, 1 /*chain_index*/, 0x00 /*status*/ };
        uint8_t f[INHABIT_DLC];
        inhabit_pack(&ex, f);
        printf("example frame id=0x%03X data=", inhabit_can_id(ex.node_id));
        for (unsigned i = 0; i < INHABIT_DLC; ++i) printf("%02X ", f[i]);
        printf("\n");
    }

    printf("mcp2515 loopback: %d frames TX->RX byte-identical + codec valid OK\n", frames);
    return 0;
}

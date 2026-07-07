/* MCP2515 driver implementation — polled, loopback bring-up.
 * No heap. No blocking inside ISRs (this module is polled from the main loop).
 * Every SPI failure returns MCP_ERR_SPI so the caller raises ST_SPI_FAULT and
 * keeps the loop alive; mode/TX/RX timeouts map to ST_CAN_FAULT. Never hangs:
 * all polls are bounded by an explicit budget.
 *
 * Datasheet: Microchip MCP2515 DS20001801 (sections cited in mcp2515.h).
 */
#include "mcp2515.h"

/* ---- SPI primitives ---------------------------------------------------- */

mcp_status_t mcp2515_reset(const mcp2515_io_t *io) {
    uint8_t tx[1] = { MCP_CMD_RESET };
    uint8_t rx[1];
    return io->transfer(io->ctx, tx, rx, 1) ? MCP_ERR_SPI : MCP_OK;
}

mcp_status_t mcp2515_read_reg(const mcp2515_io_t *io, uint8_t addr, uint8_t *val) {
    uint8_t tx[3] = { MCP_CMD_READ, addr, 0x00 };
    uint8_t rx[3] = { 0 };
    if (io->transfer(io->ctx, tx, rx, 3)) return MCP_ERR_SPI;
    *val = rx[2];
    return MCP_OK;
}

mcp_status_t mcp2515_write_reg(const mcp2515_io_t *io, uint8_t addr, uint8_t val) {
    uint8_t tx[3] = { MCP_CMD_WRITE, addr, val };
    uint8_t rx[3];
    return io->transfer(io->ctx, tx, rx, 3) ? MCP_ERR_SPI : MCP_OK;
}

mcp_status_t mcp2515_bit_modify(const mcp2515_io_t *io, uint8_t addr,
                                uint8_t mask, uint8_t data) {
    uint8_t tx[4] = { MCP_CMD_BIT_MODIFY, addr, mask, data };
    uint8_t rx[4];
    return io->transfer(io->ctx, tx, rx, 4) ? MCP_ERR_SPI : MCP_OK;
}

/* ---- Mode control (verify, never assume) ------------------------------- */

mcp_status_t mcp2515_set_mode(const mcp2515_io_t *io, uint8_t mode) {
    mcp_status_t st = mcp2515_bit_modify(io, MCP_REG_CANCTRL, MCP_MODE_MASK, mode);
    if (st != MCP_OK) return st;
    /* OPMOD in CANSTAT[7:5] reflects the actual mode once the change applies. */
    uint8_t canstat = 0;
    st = mcp2515_read_reg(io, MCP_REG_CANSTAT, &canstat);
    if (st != MCP_OK) return st;
    return ((canstat & MCP_MODE_MASK) == mode) ? MCP_OK : MCP_ERR_MODE;
}

/* ---- Init: reset -> config -> CNF -> requested mode -------------------- */

mcp_status_t mcp2515_init(const mcp2515_io_t *io, uint8_t mode) {
    mcp_status_t st = mcp2515_reset(io);
    if (st != MCP_OK) return st;

    /* RESET leaves the device in Configuration mode (DS sec 10.1). Confirm. */
    uint8_t canstat = 0;
    st = mcp2515_read_reg(io, MCP_REG_CANSTAT, &canstat);
    if (st != MCP_OK) return st;
    if ((canstat & MCP_MODE_MASK) != MCP_MODE_CONFIG) return MCP_ERR_MODE;

    /* Bit timing must be written in Configuration mode only (DS sec 5.0). */
    if ((st = mcp2515_write_reg(io, MCP_REG_CNF1, MCP_CNF1_500K_16MHZ)) != MCP_OK) return st;
    if ((st = mcp2515_write_reg(io, MCP_REG_CNF2, MCP_CNF2_500K_16MHZ)) != MCP_OK) return st;
    if ((st = mcp2515_write_reg(io, MCP_REG_CNF3, MCP_CNF3_500K_16MHZ)) != MCP_OK) return st;

    /* RXB0 accept-all so loopback frames land in RXB0 regardless of filters
     * (RXM=11, DS Register 4-1). */
    if ((st = mcp2515_write_reg(io, MCP_REG_RXB0CTRL, 0x60u)) != MCP_OK) return st;
    /* Enable RX + error interrupts on /INT (PB6 EXTI handled in main.c). Loopback
     * RX still sets RX0IF, so loopback RX is serviced via the INT path too.
     * TX-complete is left polled (no TXnIE). DS Register 7-1. */
    if ((st = mcp2515_write_reg(io, MCP_REG_CANINTE, MCP_CANINTE_BRINGUP)) != MCP_OK) return st;
    if ((st = mcp2515_write_reg(io, MCP_REG_CANINTF, 0x00u)) != MCP_OK) return st;

    return mcp2515_set_mode(io, mode);
}

/* ---- Standard 11-bit ID packing (pure) -------------------------------- */

void mcp2515_encode_sid(uint32_t id11, uint8_t *sidh, uint8_t *sidl) {
    id11 &= 0x7FFu;
    *sidh = (uint8_t)(id11 >> 3);            /* SID[10:3] */
    *sidl = (uint8_t)((id11 & 0x07u) << 5);  /* SID[2:0] in bits 7:5, IDE=0, SRR=0 */
}

/* ---- TX path ----------------------------------------------------------- */

mcp_status_t mcp2515_send_std(const mcp2515_io_t *io, uint32_t id11,
                              const uint8_t *data, uint8_t len) {
    mcp_status_t st;
    uint8_t sidh, sidl;
    if (len > 8u) len = 8u;
    mcp2515_encode_sid(id11, &sidh, &sidl);

    if ((st = mcp2515_write_reg(io, MCP_REG_TXB0SIDH, sidh)) != MCP_OK) return st;
    if ((st = mcp2515_write_reg(io, MCP_REG_TXB0SIDL, sidl)) != MCP_OK) return st;
    if ((st = mcp2515_write_reg(io, MCP_REG_TXB0DLC, len)) != MCP_OK) return st; /* RTR=0 */
    for (uint8_t i = 0; i < len; ++i) {
        if ((st = mcp2515_write_reg(io, MCP_REG_TXB0D0 + i, data[i])) != MCP_OK) return st;
    }
    /* Request-to-send TXB0 (DS sec 12.5). */
    uint8_t tx[1] = { MCP_CMD_RTS_TX0 };
    uint8_t rx[1];
    return io->transfer(io->ctx, tx, rx, 1) ? MCP_ERR_SPI : MCP_OK;
}

mcp_status_t mcp2515_poll_tx_done(const mcp2515_io_t *io, uint32_t poll_budget) {
    /* TXB0CTRL.TXREQ (bit3) clears when the controller finishes sending. In
     * loopback the frame is sent internally and TXREQ self-clears. */
    for (uint32_t i = 0; i < poll_budget; ++i) {
        uint8_t ctrl = 0;
        mcp_status_t st = mcp2515_read_reg(io, MCP_REG_TXB0CTRL, &ctrl);
        if (st != MCP_OK) return st;
        if (ctrl & (MCP_TXBCTRL_ABTF | MCP_TXBCTRL_MLOA | MCP_TXBCTRL_TXERR)) {
            /* Arbitration loss can't happen in loopback; any of these => fault. */
            return MCP_ERR_TX_TIMEOUT;
        }
        if (!(ctrl & MCP_TXBCTRL_TXREQ)) return MCP_OK;
    }
    return MCP_ERR_TX_TIMEOUT;
}

/* ---- RX path (loopback read-back) -------------------------------------- */

mcp_status_t mcp2515_poll_recv(const mcp2515_io_t *io, uint32_t poll_budget,
                               uint32_t *id11, uint8_t *data, uint8_t *len) {
    for (uint32_t i = 0; i < poll_budget; ++i) {
        uint8_t intf = 0;
        mcp_status_t st = mcp2515_read_reg(io, MCP_REG_CANINTF, &intf);
        if (st != MCP_OK) return st;
        if (intf & MCP_INTF_RX0IF) {
            uint8_t sidh = 0, sidl = 0, dlc = 0;
            if ((st = mcp2515_read_reg(io, MCP_REG_RXB0SIDH, &sidh)) != MCP_OK) return st;
            if ((st = mcp2515_read_reg(io, MCP_REG_RXB0SIDL, &sidl)) != MCP_OK) return st;
            if ((st = mcp2515_read_reg(io, MCP_REG_RXB0DLC, &dlc)) != MCP_OK) return st;
            uint8_t n = dlc & 0x0Fu;
            if (n > 8u) n = 8u;
            for (uint8_t k = 0; k < n; ++k) {
                if ((st = mcp2515_read_reg(io, MCP_REG_RXB0D0 + k, &data[k])) != MCP_OK)
                    return st;
            }
            if (id11) *id11 = ((uint32_t)sidh << 3) | ((uint32_t)(sidl >> 5) & 0x07u);
            if (len)  *len = n;
            /* Clear RX0IF so the next frame can be detected (DS sec 4.2). */
            return mcp2515_bit_modify(io, MCP_REG_CANINTF, MCP_INTF_RX0IF, 0x00u);
        }
    }
    return MCP_ERR_RX_TIMEOUT;
}

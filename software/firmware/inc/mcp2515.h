/* MCP2515 stand-alone CAN controller driver — Inhabit Rev-A joint node.
 *
 * Scope of THIS module: SPI bring-up + CAN TX/RX in LOOPBACK mode. SPI access
 * is POLLED (this module is never called from an ISR). The active-low /INT pin
 * is confirmed routed to STM32 PB6 (root CLAUDE.md pin map); the EXTI wiring for
 * it lives in main.c. mcp2515_init() enables CANINTE (MCP_CANINTE_BRINGUP) so
 * /INT asserts on RX; TX-complete is still detected by polling TXBnCTRL.
 *
 * Pin map (Rev-A, root CLAUDE.md): CS=PA4, SCK=PA5, MISO=PA6, MOSI=PA7.
 *
 * Pure logic in this module (CNF bit-timing constants, TX-buffer byte layout,
 * register-value construction) is host-testable — the SPI layer is abstracted
 * behind mcp2515_io_t so a mock register file can drive the loopback round-trip
 * without hardware. Datasheet refs: Microchip MCP2515 DS20001801, sections noted.
 */
#ifndef INHABIT_MCP2515_H
#define INHABIT_MCP2515_H
#include <stdint.h>
#include <stdbool.h>

/* ---- SPI command bytes (DS Table 12-1) ---- */
#define MCP_CMD_RESET        0xC0u
#define MCP_CMD_READ         0x03u
#define MCP_CMD_WRITE        0x02u
#define MCP_CMD_READ_STATUS  0xA0u
#define MCP_CMD_RX_STATUS    0xB0u
#define MCP_CMD_BIT_MODIFY   0x05u
#define MCP_CMD_RTS_TX0      0x81u /* RTS base 0x80 | (1<<n) per buffer */
#define MCP_CMD_RTS_TX1      0x82u
#define MCP_CMD_RTS_TX2      0x84u

/* ---- Register addresses (DS Register map, sec 11/12) ---- */
#define MCP_REG_CANSTAT      0x0Eu
#define MCP_REG_CANCTRL      0x0Fu
#define MCP_REG_CNF3         0x28u
#define MCP_REG_CNF2         0x29u
#define MCP_REG_CNF1         0x2Au
#define MCP_REG_CANINTE      0x2Bu
#define MCP_REG_CANINTF      0x2Cu

/* TXB0 (DS sec 3) */
#define MCP_REG_TXB0CTRL     0x30u
#define MCP_REG_TXB0SIDH     0x31u
#define MCP_REG_TXB0SIDL     0x32u
#define MCP_REG_TXB0DLC      0x35u
#define MCP_REG_TXB0D0       0x36u

/* RXB0 (DS sec 4) */
#define MCP_REG_RXB0CTRL     0x60u
#define MCP_REG_RXB0SIDH     0x61u
#define MCP_REG_RXB0SIDL     0x62u
#define MCP_REG_RXB0DLC      0x65u
#define MCP_REG_RXB0D0       0x66u

/* ---- CANCTRL / CANSTAT mode bits (REQOP/OPMOD = bits 7:5) ---- */
#define MCP_MODE_MASK        0xE0u
#define MCP_MODE_NORMAL      0x00u
#define MCP_MODE_SLEEP       0x20u
#define MCP_MODE_LOOPBACK    0x40u
#define MCP_MODE_LISTENONLY  0x60u
#define MCP_MODE_CONFIG      0x80u

/* ---- CANINTF flag bits (DS Register 7-9) ---- */
#define MCP_INTF_RX0IF       (1u<<0)
#define MCP_INTF_RX1IF       (1u<<1)
#define MCP_INTF_TX0IF       (1u<<2)
#define MCP_INTF_TX1IF       (1u<<3)
#define MCP_INTF_TX2IF       (1u<<4)
#define MCP_INTF_ERRIF       (1u<<5)
#define MCP_INTF_WAKIF       (1u<<6)
#define MCP_INTF_MERRF       (1u<<7)

/* ---- CANINTE enable bits (DS Register 7-1) — same bit positions as CANINTF ---- */
#define MCP_INTE_RX0IE       (1u<<0)
#define MCP_INTE_RX1IE       (1u<<1)
#define MCP_INTE_TX0IE       (1u<<2)
#define MCP_INTE_TX1IE       (1u<<3)
#define MCP_INTE_TX2IE       (1u<<4)
#define MCP_INTE_ERRIE       (1u<<5)
#define MCP_INTE_WAKIE       (1u<<6)
#define MCP_INTE_MERRE       (1u<<7)

/* CANINTE value programmed by mcp2515_init(): both RX buffers drive /INT so an
 * RX (incl. a loopback RX, which still sets RX0IF) is serviced via the EXTI/INT
 * path on PB6. TX-complete is intentionally NOT enabled — TX is polled
 * (poll_tx_done) so it does not share the RX-driven INT path.
 *
 * ERRIE/MERRE are deliberately OMITTED for the loopback milestone. The MCP2515
 * /INT is level (stays low until ALL set CANINTF flags clear) while our EXTI is
 * edge-triggered; the RX path only clears RX0IF. If an error flag (ERRIF/MERRF)
 * were enabled onto /INT with no code to clear it, the first bus error would
 * hold /INT low forever and the RX interrupt would die SILENTLY — the opposite
 * of fail-loud. P2 PREREQUISITE (live 2-board bus): re-add ERRIE|MERRE together
 * with an ERRIF/MERRF clear path and a level-recovery sweep (re-service while
 * PB6 reads low / CANINTF nonzero). Until then, poll error flags. */
#define MCP_CANINTE_BRINGUP \
    (MCP_INTE_RX0IE | MCP_INTE_RX1IE)

/* ---- TXBnCTRL bits (DS Register 3-1) ---- */
#define MCP_TXBCTRL_TXREQ    (1u<<3)
#define MCP_TXBCTRL_TXERR    (1u<<4)
#define MCP_TXBCTRL_MLOA     (1u<<5)
#define MCP_TXBCTRL_ABTF     (1u<<6)

/* ---- TXBnDLC / RXBnDLC ---- */
#define MCP_DLC_RTR          (1u<<6)

/* =========================================================================
 * Bit timing for 500 kbit/s on a 16 MHz crystal (target per CLAUDE.md).
 *
 * Tq        = 2 * (BRP+1) / Fosc.  BRP=0 -> Tq = 2/16MHz = 125 ns.
 * Bit time  = SyncSeg(1) + PropSeg(2) + PS1(7) + PS2(6) = 16 Tq = 2000 ns
 *            -> 1/2000ns = 500 kbit/s. Sample point (1+2+7)/16 = 62.5%.
 * SJW = 1 Tq.
 *
 * CNF1 (DS Reg 5-1): bit7:6 SJW-1 = 0; bit5:0 BRP = 0            -> 0x00
 * CNF2 (DS Reg 5-2): bit7 BTLMODE=1 (PS2 from CNF3);
 *                    bit6 SAM=0;
 *                    bit5:3 PHSEG1 = PS1-1 = 6;
 *                    bit2:0 PRSEG  = PropSeg-1 = 1               -> 0xB1
 *   (1<<7)|(6<<3)|(1) = 0x80|0x30|0x01 = 0xB1
 * CNF3 (DS Reg 5-3): bit2:0 PHSEG2 = PS2-1 = 5                   -> 0x05
 * ========================================================================= */
#define MCP_CNF1_500K_16MHZ  0x00u
#define MCP_CNF2_500K_16MHZ  0xB1u
#define MCP_CNF3_500K_16MHZ  0x05u

/* SPI hardware abstraction: lets the main loop wire LL/HAL SPI here, and lets
 * the host test mock a register file. transfer() does one CS-framed exchange:
 * writes tx[0..n-1], captures the simultaneous MISO bytes into rx[0..n-1].
 * Return 0 on success, non-zero on SPI fault (timeout / bus error). */
typedef struct {
    int (*transfer)(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n);
    void *ctx;
} mcp2515_io_t;

/* Result codes — non-zero means the caller should raise ST_SPI_FAULT or
 * ST_CAN_FAULT and keep the loop alive. */
typedef enum {
    MCP_OK = 0,
    MCP_ERR_SPI,        /* SPI transfer failed */
    MCP_ERR_MODE,       /* CANSTAT did not confirm requested mode */
    MCP_ERR_TX_TIMEOUT, /* TX did not complete within poll budget */
    MCP_ERR_RX_TIMEOUT, /* loopback RX never arrived */
} mcp_status_t;

/* Low-level register helpers (also used by tests). */
mcp_status_t mcp2515_reset(const mcp2515_io_t *io);
mcp_status_t mcp2515_read_reg(const mcp2515_io_t *io, uint8_t addr, uint8_t *val);
mcp_status_t mcp2515_write_reg(const mcp2515_io_t *io, uint8_t addr, uint8_t val);
mcp_status_t mcp2515_bit_modify(const mcp2515_io_t *io, uint8_t addr,
                                uint8_t mask, uint8_t data);

/* Enter a mode and verify it via CANSTAT (does NOT assume). */
mcp_status_t mcp2515_set_mode(const mcp2515_io_t *io, uint8_t mode);

/* Full init: reset -> confirm config mode -> CNF 500k/16MHz -> requested mode
 * (pass MCP_MODE_LOOPBACK for bring-up) -> verify. */
mcp_status_t mcp2515_init(const mcp2515_io_t *io, uint8_t mode);

/* Pure logic: build the SIDH/SIDL pair for an 11-bit standard ID. */
void mcp2515_encode_sid(uint32_t id11, uint8_t *sidh, uint8_t *sidl);

/* Load TXB0 with a standard-ID frame and request-to-send. data/len <= 8. */
mcp_status_t mcp2515_send_std(const mcp2515_io_t *io, uint32_t id11,
                              const uint8_t *data, uint8_t len);

/* Poll TXB0CTRL.TXREQ until clear (TX done) or budget exhausted. */
mcp_status_t mcp2515_poll_tx_done(const mcp2515_io_t *io, uint32_t poll_budget);

/* Poll CANINTF.RX0IF until set or budget exhausted, then read RXB0 out.
 * On success fills id11/data/len and clears RX0IF. */
mcp_status_t mcp2515_poll_recv(const mcp2515_io_t *io, uint32_t poll_budget,
                               uint32_t *id11, uint8_t *data, uint8_t *len);

#endif

/* CAN service fault-bit policy — pure logic, host-testable.
 *
 * One place decides how a can_service() round-trip maps onto the SPI/CAN fault
 * bits of status_flags. Extracted from main.c so the latch/clear policy can be
 * unit-tested without hardware (EXTI/SPI register config cannot be).
 *
 * Policy (uniform for BOTH bits — see embedded-reviewer finding 2a):
 *   - A round-trip is "healthy" when SPI succeeded end-to-end AND the loopback
 *     echo matched (id + len + checksum). On a healthy round-trip we CLEAR both
 *     ST_SPI_FAULT and ST_CAN_FAULT — neither bit is sticky, so one transient
 *     glitch can no longer permanently poison the status word.
 *   - On an SPI-layer failure (MCP_ERR_SPI) we SET ST_SPI_FAULT (fail loud).
 *   - On any other non-OK status, or an OK status with a bad echo, we SET
 *     ST_CAN_FAULT (fail loud).
 * Bits other than ST_SPI_FAULT / ST_CAN_FAULT are left untouched.
 */
#ifndef INHABIT_CAN_HEALTH_H
#define INHABIT_CAN_HEALTH_H
#include <stdint.h>
#include <stdbool.h>
#include "mcp2515.h"

/* Given the prior status_flags, the result of the SPI/CAN exchange, and whether
 * the loopback echo verified, return the next status_flags. Pure: no I/O. */
uint8_t can_health_apply(uint8_t flags, mcp_status_t st, bool roundtrip_ok);

#endif

# Firmware Bench Evidence — Rev-A 3-Pod Chain

Reference for bench verification. Compare logic-analyzer / `candump` captures
against the golden-reference frames produced by `firmware/test/test_bench_3pod.c`.

## Setup

```
Host ENUM_OUT ---[HIGH]---> Pod0 ENUM_IN (PA1)
                            Pod0 ENUM_OUT (PA2) ---> Pod1 ENUM_IN (PA1)
                                                     Pod1 ENUM_OUT (PA2) ---> Pod2 ENUM_IN (PA1)

All three share: 5V5, GND, CANH, CANL (daisy-chain bus)
```

Each pod runs `main.c` (on `main`) with the ENUM FSM wired into the main loop.

## Expected CAN bus traffic (schema v1)

After enumeration completes, each pod transmits schema-v1 frames at the 1 kHz
tick rate. Frame layout:

```
CAN ID: 0x100 + node_id   DLC: 8
  [0:1] angle_raw_adc   (uint16, LE)
  [2:3] angle_millideg  (int16, LE)
  [4]   node_id
  [5]   chain_index     <-- assigned by ENUM FSM
  [6]   status_flags    <-- ST_NOT_ENUMERATED (0x10) must be CLEAR
  [7]   checksum        (XOR of bytes 0..6)
```

### Pass criteria — 3-pod chain

| Pod | CAN ID   | byte[4] node_id | byte[5] chain_index | byte[6] bit 4 (0x10) |
|-----|----------|-----------------|---------------------|----------------------|
| 0   | 0x100+N0 | N0              | 0                   | 0 (clear)            |
| 1   | 0x100+N1 | N1              | 1                   | 0 (clear)            |
| 2   | 0x100+N2 | N2              | 2                   | 0 (clear)            |

Where N0, N1, N2 are the node_ids assigned to each board.

### Pass criteria — 2-pod chain (minimum viable)

| Pod | byte[5] chain_index | byte[6] bit 4 |
|-----|---------------------|---------------|
| 0   | 0                   | 0 (clear)     |
| 1   | 1                   | 0 (clear)     |

### Fail-loud verification

Before enumeration (or if ENUM wiring is broken), every pod's frame must have
`status_flags & 0x10 != 0` (ST_NOT_ENUMERATED set). A host must never trust
`chain_index` from a frame with this flag set.

## How to capture

### With candump (USB-CAN adapter on the bus)
```bash
candump can0
# Expected output (repeating at ~1 kHz per pod):
#   can0  101   [8]  E8 03 00 00 01 00 00 EA   <- pod 0 (chain_index=0)
#   can0  102   [8]  xx xx xx xx 02 01 00 xx   <- pod 1 (chain_index=1)
#   can0  103   [8]  xx xx xx xx 03 02 00 xx   <- pod 2 (chain_index=2)
```

### With logic analyzer (SPI + CAN lines)
Capture SPI MOSI/MISO/SCK/CS and CANH/CANL. Decode CAN frames and verify
byte[5] matches chain position.

## Enumeration timing

| Phase     | Duration               | Notes                            |
|-----------|------------------------|----------------------------------|
| Debounce  | ENUM_DEBOUNCE_TICKS=10 | 10 ms at 1 kHz tick              |
| Out delay | ENUM_OUT_DELAY_TICKS=5 | 5 ms to let CAN TX propagate     |
| Per pod   | ~15 ms                 | debounce + out delay              |
| 3-pod     | ~45 ms                 | sequential, cascaded              |

## Failure diagnosis

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| No CAN frames at all | SPI fault, MCP2515 not initialized | scope SPI SCK/MOSI/MISO/CS for activity during init; verify MCP2515 CANSTAT reads 0x80 (config mode) after reset; check 16 MHz crystal oscillation |
| Frames but chain_index all 0 | ENUM wiring broken, ENUM_IN not reaching pods | scope PA1 on each pod; verify pull-down |
| ST_NOT_ENUMERATED never clears | ENUM_IN stuck LOW | check ENUM daisy chain continuity |
| Pod N never enumerates | Pod N-1's ENUM_OUT not going HIGH | scope PA2 on pod N-1 after it enumerates |
| chain_index gap (0, 2 but no 1) | Pod 1 not receiving CAN from Pod 0 | check bus termination, CAN transceiver |

## Golden reference

Run the host-side 3-pod test to see exact expected bytes:
```bash
cd firmware/test
gcc -I../inc test_bench_3pod.c ../src/enum.c ../src/can_frame.c -o bench3 && ./bench3
```
This prints the exact frame bytes for comparison with bench captures.

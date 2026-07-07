# ENUM Bringup Checklist

## Single Pod
- [ ] ENUM_IN (PA1) tied HIGH (host seed signal)
- [ ] Pod powers on with ST_NOT_ENUMERATED set
- [ ] ENUM FSM transitions: WAIT -> DEBOUNCE -> ASSIGNED -> DONE
- [ ] chain_index = 0 assigned
- [ ] ST_NOT_ENUMERATED cleared in status_flags
- [ ] ENUM_OUT (PA2) goes HIGH after delay
- [ ] CAN frames show chain_index = 0

## Two Pods
- [ ] Pod A ENUM_OUT wired to Pod B ENUM_IN
- [ ] Pod A ENUM_IN seeded HIGH
- [ ] Pod A claims chain_index = 0
- [ ] Pod A ENUM_OUT goes HIGH
- [ ] Pod B detects ENUM_IN HIGH
- [ ] Pod B claims chain_index = 1
- [ ] Both pods transmitting CAN with correct chain_index
- [ ] Repeat power cycle 10x -- ordering always consistent

## Edge Cases
- [ ] No ENUM_IN (stays un-enumerated, ST_NOT_ENUMERATED stays set)
- [ ] Noisy ENUM_IN (debounce rejects glitches)
- [ ] Late peer CAN frame after ENUM_DONE (ignored by guard)

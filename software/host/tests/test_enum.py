"""Host-side state-machine unit test for the ENUM protocol.

Mirrors the C implementation (firmware/src/enum.c) in Python so the protocol
logic can be verified independently. Tests single-pod, multi-pod chain,
debounce rejection, and edge cases.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEBOUNCE_TICKS = 10
OUT_DELAY_TICKS = 5
ST_NOT_ENUMERATED = 1 << 4
ENUM_MAX_CHAIN_INDEX = 0xFE
ENUM_PEER_NONE = 0xFF


@dataclass
class EnumCtx:
    phase: str = "WAIT"
    debounce_count: int = 0
    out_delay_count: int = 0
    max_peer_index: int | None = None
    enum_out: bool = False


@dataclass
class PodState:
    chain_index: int = 0
    status_flags: int = field(default=ST_NOT_ENUMERATED)


def enum_init() -> EnumCtx:
    return EnumCtx()


def enum_notify_peer(ctx: EnumCtx, peer_index: int) -> None:
    if ctx.phase == "DONE":
        return
    if peer_index == 0xFF:
        return  # 0xFF is the "none" sentinel
    if ctx.max_peer_index is None or peer_index > ctx.max_peer_index:
        ctx.max_peer_index = peer_index


def enum_step(ctx: EnumCtx, state: PodState, enum_in: bool) -> None:
    if ctx.phase == "WAIT":
        if enum_in:
            ctx.debounce_count = 1
            ctx.phase = "DEBOUNCE"

    elif ctx.phase == "DEBOUNCE":
        if not enum_in:
            ctx.debounce_count = 0
            ctx.phase = "WAIT"
        else:
            ctx.debounce_count += 1
            if ctx.debounce_count >= DEBOUNCE_TICKS:
                if ctx.max_peer_index is None:
                    state.chain_index = 0
                    state.status_flags &= ~ST_NOT_ENUMERATED & 0xFF
                    ctx.out_delay_count = 0
                    ctx.phase = "ASSIGNED"
                elif ctx.max_peer_index < ENUM_MAX_CHAIN_INDEX:
                    state.chain_index = ctx.max_peer_index + 1
                    state.status_flags &= ~ST_NOT_ENUMERATED & 0xFF
                    ctx.out_delay_count = 0
                    ctx.phase = "ASSIGNED"
                else:
                    state.status_flags |= ST_NOT_ENUMERATED
                    ctx.phase = "WAIT"
                    ctx.debounce_count = 0

    elif ctx.phase == "ASSIGNED":
        ctx.out_delay_count += 1
        if ctx.out_delay_count >= OUT_DELAY_TICKS:
            ctx.enum_out = True
            ctx.phase = "DONE"


# -- Tests ------------------------------------------------------------------

def test_single_pod_index_zero() -> None:
    ctx = enum_init()
    st = PodState()

    # ENUM_IN low: nothing happens
    for _ in range(20):
        enum_step(ctx, st, False)
    assert ctx.phase == "WAIT"
    assert st.status_flags & ST_NOT_ENUMERATED

    # ENUM_IN high through debounce
    for _ in range(DEBOUNCE_TICKS):
        enum_step(ctx, st, True)
    assert ctx.phase == "ASSIGNED"
    assert st.chain_index == 0
    assert not (st.status_flags & ST_NOT_ENUMERATED)

    # Wait for ENUM_OUT
    for _ in range(OUT_DELAY_TICKS):
        enum_step(ctx, st, True)
    assert ctx.phase == "DONE"
    assert ctx.enum_out


def test_debounce_rejects_glitch() -> None:
    ctx = enum_init()
    st = PodState()

    for _ in range(DEBOUNCE_TICKS - 2):
        enum_step(ctx, st, True)
    assert ctx.phase == "DEBOUNCE"

    enum_step(ctx, st, False)  # glitch
    assert ctx.phase == "WAIT"
    assert st.status_flags & ST_NOT_ENUMERATED

    # Full stable assertion after glitch
    for _ in range(DEBOUNCE_TICKS):
        enum_step(ctx, st, True)
    assert ctx.phase == "ASSIGNED"
    assert st.chain_index == 0


def test_peer_index_increments() -> None:
    ctx = enum_init()
    st = PodState()

    enum_notify_peer(ctx, 0)
    enum_notify_peer(ctx, 2)

    for _ in range(DEBOUNCE_TICKS):
        enum_step(ctx, st, True)
    assert st.chain_index == 3


def test_two_pod_chain() -> None:
    ca, cb = enum_init(), enum_init()
    sa, sb = PodState(), PodState()

    for _ in range(100):
        enum_step(ca, sa, True)  # host drives A
        if ca.phase in ("ASSIGNED", "DONE"):
            enum_notify_peer(cb, sa.chain_index)
        enum_step(cb, sb, ca.enum_out)  # A's ENUM_OUT -> B's ENUM_IN

    assert ca.phase == "DONE" and cb.phase == "DONE"
    assert sa.chain_index == 0
    assert sb.chain_index == 1
    assert ca.enum_out and cb.enum_out


def test_three_pod_chain() -> None:
    ctxs = [enum_init() for _ in range(3)]
    states = [PodState() for _ in range(3)]

    for _ in range(200):
        # Pod 0: ENUM_IN from host
        enum_step(ctxs[0], states[0], True)
        # Pods 1..N: ENUM_IN = upstream's ENUM_OUT
        for i in range(1, 3):
            for j in range(i):
                if ctxs[j].phase in ("ASSIGNED", "DONE"):
                    enum_notify_peer(ctxs[i], states[j].chain_index)
            enum_step(ctxs[i], states[i], ctxs[i - 1].enum_out)

    for i in range(3):
        assert ctxs[i].phase == "DONE"
        assert states[i].chain_index == i


def test_status_flags_preserved() -> None:
    ctx = enum_init()
    st = PodState(status_flags=ST_NOT_ENUMERATED | 0x03)  # ADC + SPI faults

    for _ in range(DEBOUNCE_TICKS):
        enum_step(ctx, st, True)
    assert not (st.status_flags & ST_NOT_ENUMERATED)
    assert st.status_flags & 0x03  # other bits untouched


def test_done_is_idempotent() -> None:
    ctx = enum_init()
    st = PodState()

    for _ in range(DEBOUNCE_TICKS + OUT_DELAY_TICKS):
        enum_step(ctx, st, True)
    assert ctx.phase == "DONE"

    idx, flags = st.chain_index, st.status_flags
    for _ in range(100):
        enum_step(ctx, st, True)
    assert st.chain_index == idx
    assert st.status_flags == flags


def test_sentinel_0xff_rejected() -> None:
    ctx = enum_init()
    st = PodState()

    enum_notify_peer(ctx, 0xFF)
    assert ctx.max_peer_index is None  # sentinel ignored

    enum_notify_peer(ctx, 3)
    enum_notify_peer(ctx, 0xFF)
    assert ctx.max_peer_index == 3  # still 3

    for _ in range(DEBOUNCE_TICKS):
        enum_step(ctx, st, True)
    assert st.chain_index == 4


def test_lower_peer_does_not_clobber() -> None:
    ctx = enum_init()
    enum_notify_peer(ctx, 7)
    enum_notify_peer(ctx, 3)
    enum_notify_peer(ctx, 5)
    assert ctx.max_peer_index == 7  # monotonic max


def test_chain_full_faults() -> None:
    """C parity: max_peer_index at 0xFE must fault, not wrap to 0xFF."""
    ctx = enum_init()
    st = PodState()
    enum_notify_peer(ctx, ENUM_MAX_CHAIN_INDEX)  # 0xFE

    for _ in range(DEBOUNCE_TICKS + OUT_DELAY_TICKS):
        enum_step(ctx, st, True)

    # Must NOT enumerate — no valid index left
    assert st.status_flags & ST_NOT_ENUMERATED
    assert not ctx.enum_out
    assert ctx.phase != "DONE"


def test_seven_pod_chain() -> None:
    """Manufacturing scale: 7-pod passive arm (P4 roadmap target)."""
    n = 7
    ctxs = [enum_init() for _ in range(n)]
    states = [PodState() for _ in range(n)]

    for _ in range(500):
        enum_step(ctxs[0], states[0], True)  # host seeds pod 0
        for i in range(1, n):
            for j in range(i):
                if ctxs[j].phase in ("ASSIGNED", "DONE"):
                    enum_notify_peer(ctxs[i], states[j].chain_index)
            enum_step(ctxs[i], states[i], ctxs[i - 1].enum_out)

    for i in range(n):
        assert ctxs[i].phase == "DONE", f"pod {i} not DONE"
        assert states[i].chain_index == i, f"pod {i} got index {states[i].chain_index}"
        assert not (states[i].status_flags & ST_NOT_ENUMERATED)
        assert ctxs[i].enum_out


def test_notify_peer_noop_after_done() -> None:
    ctx = enum_init()
    st = PodState()
    enum_notify_peer(ctx, 5)

    for _ in range(DEBOUNCE_TICKS + OUT_DELAY_TICKS):
        enum_step(ctx, st, True)
    assert ctx.phase == "DONE"
    assert st.chain_index == 6

    enum_notify_peer(ctx, 99)
    assert ctx.max_peer_index == 5  # unchanged

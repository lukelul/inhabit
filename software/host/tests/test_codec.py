import random
from inhabit_can.codec import State, encode_state, decode_state, can_id


def test_roundtrip_and_bitflip() -> None:
    for i in range(5000):
        s = State(random.randint(0, 65535), random.randint(-32768, 32767),
                  random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        cid, data = encode_state(s)
        assert cid == 0x100 + s.node_id
        r = decode_state(data)
        assert r.valid
        assert (r.angle_raw_adc, r.angle_millideg, r.node_id, r.chain_index, r.status_flags) == \
               (s.angle_raw_adc, s.angle_millideg, s.node_id, s.chain_index, s.status_flags)
        bad = bytearray(data); bad[0] ^= 0x01
        assert decode_state(bytes(bad)).valid is False


def test_sim_adapter() -> None:
    from inhabit_can.adapter import SimAdapter, RobotCommand
    a = SimAdapter(dof=6); a.connect()
    a.send_command(RobotCommand(joint_targets=[1.0] * 6))
    assert a.read_state().joint_angles == [1.0] * 6
    assert a.capabilities().dof == 6

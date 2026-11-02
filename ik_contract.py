"""Versioned AXI-Lite ABI for SO-101 task geometry plus bounded WLS."""
import numpy as np

ABI = "so101-ik-step-v2"
TOP = "z20_ik_step"
MAGIC = 0x534F0202
ARRAYS = dict(q=5, target_position=3, target_axis=3, weights=6, scales=6,
              tool=3, tool_axis=3, limits=10, dq=5, q_next=5, error=6)
FIELDS = dict(ARRAYS, mu=1, max_step=1, mode=1, position_error=1,
              tilt_error=1, abi_version=1, **{"return": 1})
NOMINAL_OFFSETS = np.asarray([[.0612,0,.0598],[.02943,0,.05504],
    [.02798,0,.1127],[.15504,0,.00519],[.0593,0,.00996]])
NOMINAL_AXES = np.asarray([[0,0,1],[0,1,0],[0,1,0],[0,1,0],[1,0,0]])


def model_matches_nominal(model):
    """Only links/axes are fixed; calibrated pen and limits are runtime inputs."""
    try:
        return (model.offsets.shape == (5,3) and model.axes.shape == (5,3)
                and np.allclose(model.offsets, NOMINAL_OFFSETS, atol=1e-9, rtol=0)
                and np.allclose(model.axes, NOMINAL_AXES, atol=1e-9, rtol=0))
    except (AttributeError, TypeError, ValueError):
        return False


def validate_registers(registers, require_identity=False):
    if not isinstance(registers, dict):
        raise ValueError("需要 z20_ik_step HLS 寄存器 JSON")
    if require_identity or "abi" in registers or "top" in registers:
        if registers.get("abi") != ABI or registers.get("top") != TOP:
            raise ValueError("需要 so101-ik-step-v2 映射")
    occupied = {0,4,8,12}
    for field, words in FIELDS.items():
        offset = registers.get(field)
        if type(offset) is not int or offset < 16 or offset % 4:
            raise ValueError("无效寄存器：" + field)
        addresses = set(range(offset, offset+4*words, 4))
        if addresses & occupied:
            raise ValueError("寄存器区间重叠：" + field)
        occupied.update(addresses)
    return max(occupied)+4


def validate_ip(description, required_bytes):
    parts = str(description.get("type", "")).split(":")
    if len(parts) != 4 or parts[2] != TOP:
        raise ValueError("hwh 中不是 z20_ik_step")
    if type(description.get("addr_range")) is not int or description["addr_range"] < required_bytes:
        raise ValueError("AXI 地址窗口不足")

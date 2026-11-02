"""ABI contract for the z20_pl_image streaming image core."""
ABI = 'so101-pl-image-v1'
TOP = 'z20_pl_image'

# 寄存器字段名 → 占 word 数（导出脚本与驱动共同依赖）
FIELDS = {
    'width': 1, 'height': 1, 'mode': 1, 'sobel_thr': 1,
    'edge_count': 1, 'return': 1,
}


def validate_registers(registers, require_identity=False):
    if not isinstance(registers, dict):
        raise ValueError('需要 HLS 生成头文件导出的寄存器 JSON')
    if require_identity and (registers.get('abi') != ABI or registers.get('top') != TOP):
        raise ValueError('当前驱动只对应 z20_pl_image；请用 export_image_register_map.py 重新导出，不能复用 IK 核映射')
    occupied = {0, 4, 8, 12}  # AP_CTRL / IP core 标准控制字
    for field, words in FIELDS.items():
        offset = registers.get(field)
        if type(offset) is not int or offset < 16 or offset % 4:
            raise ValueError('无效寄存器偏移：' + field)
        addresses = set(range(offset, offset + 4*words, 4))
        if addresses & occupied:
            raise ValueError('寄存器区间重叠：' + field)
        occupied.update(addresses)
    return max(occupied) + 4
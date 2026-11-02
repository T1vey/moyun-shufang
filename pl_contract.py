"""The current WLS ABI; independent of Vivado's allocated register offsets."""
ABI = 'so101-wls-step-v1'
TOP = 'z20_wls_step'
ARRAYS = {'j': 30, 'e': 6, 'w': 6, 'scales': 6, 'dq': 5}
FIELDS = dict(ARRAYS, mu=1, mode=1, **{'return': 1})


def validate_registers(registers, require_identity=False):
    if not isinstance(registers, dict):
        raise ValueError('需要 HLS 生成头文件导出的寄存器 JSON')
    if require_identity or 'abi' in registers or 'top' in registers:
        if registers.get('abi') != ABI or registers.get('top') != TOP:
            raise ValueError('当前驱动只对应 z20_wls_step；请用本包 export_register_map.py 重新导出，不能使用 xf_solver_lm_so101 映射')
    occupied = {0, 4, 8, 12}
    for field, words in FIELDS.items():
        offset = registers.get(field)
        if type(offset) is not int or offset < 16 or offset % 4:
            raise ValueError('无效 HLS 寄存器：'+field)
        addresses = set(range(offset, offset+4*words, 4))
        if addresses & occupied:
            raise ValueError('HLS 寄存器区间重叠：'+field)
        occupied.update(addresses)
    return max(occupied)+4


def validate_ip(description, required_bytes):
    vlnv = str(description.get('type', '')).split(':')
    if len(vlnv) != 4 or vlnv[2] != TOP:
        raise ValueError('软件要求 z20_wls_step，hwh 中实际为 '+str(description.get('type'))+
                         '；不能通过改 IP 实例名兼容另一个核')
    size = description.get('addr_range')
    if type(size) is not int or size < required_bytes:
        raise ValueError('hwh 的 AXI 地址窗口不足以容纳此寄存器映射')

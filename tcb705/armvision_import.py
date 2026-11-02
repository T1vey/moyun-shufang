"""Read only allowlisted numeric calibration scalars from ArmVision YAML.

No YAML execution, no cloud credentials or vendor axis count are imported.
"""
import hashlib
import json
import re
from pathlib import Path
from .calibration import METHOD,fields

def import_settings(path):
    path=Path(path);raw=path.read_bytes();selected={};section=None
    wanted={'table':{'x_min','x_max','y_min','y_max','z_table'},
            'pen':{'lift_mm','final_lift_mm'},
            'motion':{'swap_xy','draw_speed','tool','coord','extool'},
            'tianlian':{'robot_id','pose_u','pose_v','pose_w'}}
    for line in raw.decode('utf-8-sig').splitlines():
        match=re.match(r'^([A-Za-z0-9_]+):\s*(?:#.*)?$',line)
        if match:section=match[1];continue
        match=re.match(r'^  ([A-Za-z0-9_]+):\s*([^#]+)',line)
        if not match or match[1] not in wanted.get(section,set()):continue
        key=(section,match[1])
        if key in selected:raise ValueError('重复标定参数 '+'.'.join(key))
        try:selected[key]=json.loads(match[2].strip())
        except (ValueError,TypeError) as exc:raise ValueError('标定参数必须为数值或布尔值 '+'.'.join(key)) from exc
    def value(s,k):
        if (s,k) not in selected:raise ValueError('缺少 ArmVision 参数 '+s+'.'+k)
        return selected[s,k]
    a=dict(method=METHOD,a_mm=[value('table','x_min'),value('table','y_min')],
           b_mm=[value('table','x_max'),value('table','y_max')],z_table_mm=value('table','z_table'),
           pose_uvw_deg=[value('tianlian','pose_'+v) for v in 'uvw'],robot_id=value('tianlian','robot_id'),
           lift_mm=value('pen','lift_mm'),final_lift_mm=value('pen','final_lift_mm'),
           draw_speed_percent=value('motion','draw_speed'),swap_xy=value('motion','swap_xy'),
           tool=value('motion','tool'),coord=value('motion','coord'),extool=value('motion','extool'))
    return fields(a),dict(path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),
        imported_fields_only=True,physical_setup_verified=False,
        note='原文件保存的是排序后的范围；初始 A/B 按最小/最大角显示。重新采集保留两点原始值。')

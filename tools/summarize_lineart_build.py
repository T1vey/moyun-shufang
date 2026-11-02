"""Collect measured build evidence. Never treats simulation as board acceptance."""
import argparse,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--export',type=Path,default=ROOT/'hw/vivado_lineart/export');a=ap.parse_args()
 directory=ROOT/'hw/reports/lineart'
 timing=json.loads((a.export/'build_verified.json').read_text())
 if timing['setup_slack_ns']<0 or timing['hold_slack_ns']<0 or timing['drc_errors']:raise ValueError('implementation did not pass')
 tests=json.loads((directory/'regression_desktop.json').read_text())
 if not tests['passed'] or any(s['skipped'] for s in tests['suites']):raise ValueError('regression incomplete')
 gallery=json.loads((directory/'gallery_desktop.json').read_text())
 if not gallery['passed'] or not all(i['exact'] for i in gallery['images']):raise ValueError('gallery mismatch')
 if 'CSim done with 0 errors.' not in (directory/'csim_full.txt').read_text():raise ValueError('C simulation missing')
 if not re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',(directory/'tcb_lineart_accel_cosim.rpt').read_text()):raise ValueError('RTL simulation missing')
 from lineart_contract import validate_hwh
 contract=validate_hwh(a.export/'tcb705_planner.hwh')
 timing_text=(a.export/'timing_summary.rpt').read_text()
 baseline_text=(directory/'baseline_timing_summary.rpt').read_text()
 def criticals(text):
  return {m[0]:int(m[1]) for m in re.findall(r'^(\S+)\s+Critical Warning\s+.*?\s+(\d+)\s*$',text,re.M)}
 inherited=criticals(timing_text)
 if inherited!=criticals(baseline_text):raise ValueError('new methodology critical warnings need review')
 def cdc_counts(text):
  return {m[0]:int(m[1]) for m in re.findall(r'^(CDC-\d+)\s+Critical\s+(\d+)\s+',text,re.M)}
 cdc=cdc_counts((a.export/'cdc.rpt').read_text())
 if cdc!=cdc_counts((directory/'baseline_cdc.rpt').read_text()):raise ValueError('new critical CDC findings need review')
 checks={name:int(count) for name,count in re.findall(r'checking (\w+) \((\d+)\)',timing_text)}
 if checks.get('no_clock')!=0 or checks.get('unconstrained_internal_endpoints')!=0:raise ValueError('internal timing coverage incomplete')
 utilization=(a.export/'utilization.rpt').read_text()
 resources={}
 for label in ('Slice LUTs','Slice Registers','Block RAM Tile','DSPs'):
  match=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)\s*\|',utilization)
  if match:resources[label]=float(match[1])
 artifacts={}
 for name in ('tcb705_planner.bit','tcb705_planner.hwh','tcb705_md0700r.xsa'):
  path=a.export/name
  if path.stat().st_size==0:raise ValueError('empty artifact')
  artifacts[name]=dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
 sources={}
 for name in ('tcb_lineart_accel.cpp','tcb_lineart_accel.h','tb_lineart.cpp','lineart_2024.cfg'):
  path=ROOT/'hls_source/tcb705'/name;sources[name]=hashlib.sha256(path.read_bytes()).hexdigest()
 report=dict(schema='tcb705-lineart-build-evidence-v1',contract=contract,timing=timing,resources=resources,
    software_tests=tests['tests'],gallery_images=len(gallery['images']),
    csim_cases=len(json.loads((directory/'csim_vectors.json').read_text())),
    cosim_cases=len(json.loads((directory/'cosim_vectors.json').read_text())),
    artifacts=artifacts,hls_sources_sha256=sources,timing_checks=checks,
    inherited_methodology_critical_warnings=inherited,inherited_cdc_critical_counts=cdc,
    board_acceptance=False,board_note='Pending: board network connection unavailable; no new bitstream programmed.',
    physical_robot_motion=False)
 (directory/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 rows='\n'.join('| '+name+' | '+str(value)+' |' for name,value in resources.items())
 body=f'''# 线稿 PL 加速构建验收报告

生成日期：2026-10-20。工具：Vivado / Vitis HLS 2024.2，器件 xc7z020clg400-2。

## 已完成

- 独立 Vivado 工程、综合、布局布线和比特流生成完成。
- 建立时间最差余量 **{timing['setup_slack_ns']} ns**；保持时间最差余量 **{timing['hold_slack_ns']} ns**；DRC 错误 **{timing['drc_errors']}**。
- 软件回归 **{tests['tests']} 项全部通过、无跳过**。
- 真实图库 **{len(gallery['images'])} 张**：细化位图、原生图追踪、笔画几何和顺序、完整路径哈希与原算法一致。
- HLS C 仿真 **{report['csim_cases']} 组**通过；C/RTL 联合仿真 **{report['cosim_cases']} 组**通过，另含非法尺寸保护。真实图库 RTL 样本缩至 96×96，边界样本覆盖最大宽/高 1536、空图及多轮调用。
- 8 级 Zhang–Suen、100 MHz、HP2 DDR；运行时只附着启动验证的平台，异常可回退原 CPU。

## 整个平台资源

|资源|使用量|
|---|---:|
{rows}

## 保留的平台约束告警

DRC 为 0 错误并不表示所有方法学告警已消除。与原 `vivado_v2c_gepl` 导出报告对照，TIMING-4（1 项）、TIMING-27（1 项）、TIMING-54（4 项）数量一致，分别来自显示时钟 IP 的内部主时钟定义和 GE_PL IP 的 scoped 时钟约束。本次没有通过新增 false path 隐藏线稿路径。

CDC 报告仍有 CDC-1 两项、CDC-13 六项，与原平台一致；可见端点涉及原 GE_PL 的 GMII/时钟切换逻辑。本次不能宣称全平台 CDC 告警已清零。新增线稿数据通路使用同一个 FCLK0 时钟域。

`no_clock=0`、`unconstrained_internal_endpoints=0`；同时保留原平台的 5 个无输入延迟检查项、34 个无输出延迟检查项及 1 个多时钟检查项。因此上述时序通过指**现有约束下的内部时序通过**，外部 LCD/触摸/网口仍须按既有接口要求上板验收。相关原始报告一并保留，不能将其描述为全平台“零告警”。

## 交付位置

- 工程：`hw/vivado_lineart/tcb705_lineart.xpr`
- 比特流及 HWH：`hw/vivado_lineart/export/tcb705_planner.bit`、`.hwh`
- XSA：`hw/vivado_lineart/export/tcb705_md0700r.xsa`
- 时序/资源/DRC/CDC 报告：`hw/vivado_lineart/export/`
- 可部署平台：`overlay/tcb705_lineart/platform.json`
- 验证数据及 SHA-256：`hw/reports/lineart/acceptance.json`
- 复现、部署及回滚：`docs/线稿PL加速实施说明.md`

文件名称保留原平台命名，但本目录的 bit/hwh/xsa 已包含新增线稿 IP；不可与旧目录同名文件混用。

完整 Vivado 工程归档建议解压至短英文路径（例如 `C:/fpga_build/lineart`），避免 Windows 260 字符路径限制。

## 尚未完成的板端验收

本次构建期间电脑原板卡网口显示断开，192.168.2.99 无法连接。**尚未烧录新比特流，也没有板端加速耗时数据**。未对当前板卡启动配置、标定或机械臂下发动作。

连接恢复后按实施说明隔离安装并重启加载，验证启动自检、完整图库逐像素一致性与整链路耗时，以及 LCD、触摸、GE_PL。桌面仿真通过和时序收敛不能替代这一步；不能将方案中的约 1 秒当成已达到的结果。
'''
 (ROOT/'docs/线稿PL加速_构建验收报告.md').write_text(body,encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SO-101 一体化控制台 (ArmStudio)
================================

一个 GUI 集成全部功能:

  ① 绘画 (Drawing)
       给一张图 → 云端大模型生成线稿 → 提取笔画 → 规划轨迹 → 机械臂直接动
  ② 手势跟随 (Hand Follow)
       PC 摄像头 + MediaPipe 识别食指 → 板卡 IK → 机械臂实时跟随
  ③ 舵机调试 (Servo)
       探测 / 读位置 / 回中位 / 单独运动
  ④ 日志 (Log)

架构:
   本 GUI (PC)  ──SSH 隧道──▶  板卡 8765 (绘画 Web 服务)
                ──SSH 隧道──▶  板卡 8770 (手势跟随服务)
                ──SFTP─────▶  板卡文件

用法:
    python scripts/arm_studio.py                 # 默认, 直连 127.0.0.1:8765
    python scripts/arm_studio.py --use-tunnel    # 自动建立 SSH 隧道
"""
import argparse
import copy
import hashlib
import http.client
import io
import json
import math
import os
import queue
import subprocess
import shlex
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import urllib.error
import urllib.request
import uuid
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.sugar_dialogs import filedialog, messagebox
from scripts import sugar_theme as theme

from cloud_gallery import CloudImageLibrary
from bluetooth_inbox import BluetoothInbox
from four_point_calibration import POINTS as GEOMETRY_POINTS, LABELS as GEOMETRY_LABELS


def geometry_status(paper):
    from four_point_calibration import ready
    if ready(paper):
        detail=paper['xy_calibration']
        return '已应用四点 %g×%g mm；最大拟合残差 %.2f mm%s' % (
            detail['distance_mm'],detail['distance_mm'],detail['fit']['max_fit_residual_mm'],
            '（已强制接受，已保存）' if (detail.get('residual_override') or {}).get('accepted') is True else '')
    return '等待四点标定：记录并应用 A、B、C、D 后可绘画'


def refresh_existing_calibration_snapshots(before, updated, board_cache=None):
    """Refresh only existing backups of this machine; never a public template."""
    old_marks=(before.get('paper',{}).get('xy_calibration') or {}).get('captures')
    new_calibration=updated.get('paper',{}).get('xy_calibration')
    from four_point_calibration import ready
    if ready(updated.get('paper',{})):
        locations=((Path(board_cache)/'default_four_point.json',) if board_cache else
                   (Path.home()/'Pictures/SO101/Calibration/default_four_point.json',
                    ROOT/'config/four_point_calibration.local.json'))
        profile=dict(schema='so101-default-four-point-v1',machine=copy.deepcopy(updated),
                     saved_at=datetime.now().astimezone().isoformat(),
                     source='USER_MEASURED_FOUR_POINT_CALIBRATION')
        for path in locations:
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                path.with_name(path.stem+'.before_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+path.suffix).write_bytes(path.read_bytes())
            temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            temporary.replace(path)
        return [str(path) for path in locations]
    if not old_marks or not new_calibration:
        return []
    def measured_marks(machine):
        captures=(machine.get('paper',{}).get('xy_calibration') or {}).get('captures') or {}
        return {name:{str(k):v for k,v in row.get('counts',{}).items()} for name,row in captures.items()}
    from drawing_geometry import calibration_signature
    refreshed=[]
    locations=(Path.home()/'Pictures/SO101/Calibration/default_three_point.json',
               ROOT/'config/three_point_calibration.local.json')
    for path in locations:
        if not path.is_file():
            continue
        raw=path.read_bytes()
        try:
            profile=json.loads(raw)
        except (ValueError,TypeError):
            continue
        if not isinstance(profile,dict):
            continue
        saved=profile.get('machine') or {}
        if not isinstance(saved,dict):
            continue
        if (profile.get('schema')!='so101-default-three-point-v1'
                or saved.get('joints')!=before.get('joints')
                or measured_marks(saved)!=measured_marks(before)):
            continue
        stamp=datetime.now().astimezone().isoformat()
        profile.update(saved_at=stamp,source='USER_SAVED_MACHINE_CALIBRATION',
            previous_profile_source=profile.get('source'),machine=copy.deepcopy(updated),
            xy_calibration=copy.deepcopy(new_calibration),calibration_signature=calibration_signature(updated),
            calibration_sha256=hashlib.sha256(json.dumps(new_calibration,sort_keys=True,
                separators=(',',':')).encode()).hexdigest())
        suffix=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        path.with_name(path.stem+'.before_'+suffix+path.suffix).write_bytes(raw)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(path);refreshed.append(str(path))
    return refreshed


def motion_mode_from_label(label):
    if label.startswith('糖画连续'):
        return 'sugar_fast'
    if label.startswith('旧版绘画'):
        return 'classic_fast'
    if label.startswith('速度优先'):
        return 'speed_priority'
    if label.startswith('平滑加速'):
        return 'smooth_fast'
    if label.startswith('平缓'):
        return 'gentle'
    if label.startswith('标准'):
        return 'standard'
    raise ValueError('未知运动模式')


BOARD_IP = "192.168.2.99"
BOARD_USER = "xilinx"
BOARD_PASS = "xilinx"
WEB_PORT = 8765      # 板卡绘画服务
FOLLOW_PORT = 8770   # 板卡手势跟随服务

# --- 夹爪映射 (2026 实测标定) ---
# 板卡 hand_follow_server.py: gripper = GRIP_CLOSED + ratio*(GRIP_OPEN-GRIP_CLOSED)
# 这两个值是机械行程的硬边界, 实测: 合拢止点≈1312, 张开止点≈2832
GRIP_CLOSED = 1300   # ratio=0.0 合拢
GRIP_OPEN = 2800     # ratio=1.0 张开
# 手部捏合距离 -> ratio 的映射区间 (归一化画面坐标)
PINCH_MIN = 0.02     # 拇指-食指距离小于此值 => 完全捏合 => ratio 0
PINCH_SPAN = 0.13    # 超过 PINCH_MIN+PINCH_SPAN => 完全张开 => ratio 1


# ============================================================
# 板卡通信层
# ============================================================
class BoardConnectionError(RuntimeError):
    """The reply was lost; a write may already have reached the board."""


class BoardClient:
    """与 PYNQ 板卡绘画 Web 服务 (app.py) 通信"""

    def __init__(self, host="127.0.0.1", port=WEB_PORT):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.token = None
        self.allow_motion = False
        # Board traffic is loopback SSH forwarding; Windows HTTP proxies must
        # not intercept it. Cloud HTTPS requests use their own configuration.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path, method="GET", data=None, headers=None, raw=None, timeout=30):
        # Only reads are safe to replay after losing a connection. A lost POST
        # response must never submit another plan or send another motor command.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                return self._request_once(path, method, data, headers, raw, timeout)
            except BoardConnectionError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(.3 * (attempt + 1))

    def _request_once(self, path, method="GET", data=None, headers=None, raw=None,
                      timeout=30, _auth_retry=True):
        # 自动获取 token: 所有写操作都要 X-Console-Token, 否则板卡返回 403
        if self.token is None and path != "/api/status":
            try:
                self.fetch_status()
            except Exception:
                pass

        url = self.base_url + path
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        if headers:
            hdrs.update(headers)
        if self.token:
            hdrs["X-Console-Token"] = self.token
        if raw is not None:
            req = urllib.request.Request(url, data=raw, method=method, headers=hdrs)
        elif data is not None:
            body = json.dumps(data).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        else:
            req = urllib.request.Request(url, method=method, headers=hdrs)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                body = resp.read()
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct:
                    return json.loads(body)
                return body
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            # token 过期 (板卡重启后 session 变了) -> 重新取一次再试
            if _auth_retry and e.code == 403 and "Reload the console" in err_body:
                try:
                    self.token = None
                    self.fetch_status()
                    return self._request_once(path, method, data, headers, raw, timeout,
                                              _auth_retry=False)
                except BoardConnectionError:
                    raise
                except Exception:
                    pass
            raise RuntimeError(f"HTTP {e.code}: {err_body}")
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError,
                TimeoutError) as e:
            raise BoardConnectionError(f"连接失败: {getattr(e, 'reason', e)}") from e

    # --- 基础 ---
    def fetch_status(self, timeout=8):
        s = self._request("/api/status", timeout=timeout)
        self.token = s.get("token")
        self.allow_motion = bool(s.get("motion_supported"))
        return s

    def fetch_config(self):
        return self._request("/api/config")

    def save_config(self, config):
        return self._request("/api/config", method="POST", data=config)

    def get_jobs(self):
        return self._request("/api/jobs", timeout=8)

    def heartbeat(self):
        return self._request("/api/heartbeat", method="POST", data={})

    def plans(self):
        """历史规划列表 (持久化在板卡 saved_plans/, 服务重启后仍可用)"""
        return self._request("/api/plans")

    def stop(self):
        return self._request("/api/stop", method="POST", data={})

    # --- 舵机 ---
    def list_ports(self):
        return self._request("/api/ports")

    def probe(self, port="/dev/ttyACM0", ids=(1, 2, 3, 4, 5, 6), mode="real",
              baudrate=1000000, scenario="normal"):
        data = dict(mode=mode, port=port, baudrate=baudrate, ids=list(ids),
                    confirmed=True, scenario=scenario)
        return self._request("/api/probe", method="POST", data=data, timeout=40)

    def enable(self, port="/dev/ttyACM0", baudrate=1000000, mode="real"):
        """使能扭矩并保持当前位置 (板卡动作 /api/enable)"""
        data = dict(mode=mode, port=port, baudrate=baudrate, confirmed=True)
        return self._request("/api/enable", method="POST", data=data, timeout=60)

    def jog(self, sid, delta, port="/dev/ttyACM0", baudrate=1000000, mode="real"):
        """点动: delta 必须是 ±1..20 计数 (板卡限制)"""
        data = dict(mode=mode, port=port, baudrate=baudrate, confirmed=True,
                    id=int(sid), delta=int(delta))
        return self._request("/api/jog", method="POST", data=data, timeout=60)

    def preset(self, name="line", width_mm=100.0, height_mm=100.0):
        return self._request("/api/preset", method="POST",
                             data=dict(name=name, width_mm=width_mm, height_mm=height_mm),
                             timeout=60)

    def strokes(self, paths_dict):
        """登记 PC 端算好的笔画 (板卡无 ezdxf/svgpathtools, 图像处理必须在 PC 完成)"""
        return self._request("/api/strokes", method="POST",
                             data=dict(paths=paths_dict), timeout=60)

    def read_pen_pose(self,port='/dev/ttyACM0'):
        return self._request('/api/read_pen_pose',method='POST',
            data=dict(mode='real',port=port,baudrate=1000000,confirmed=True))

    # --- 图片 ---
    def upload_image(self, raw_bytes, style="lineart", width_mm=100, height_mm=100,
                     max_segments=4000, detail="fine"):
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Image-Style": style,
            "X-Width-MM": str(width_mm),
            "X-Height-MM": str(height_mm),
            "X-Max-Segments": str(max_segments),
            "X-Trace-Detail": detail,
        }
        return self._request("/api/image", method="POST", raw=raw_bytes, headers=headers, timeout=120)

    def _require_drawing_pipeline(self):
        from stroke_paths import PIPELINE_VERSION
        status=self.fetch_status()
        if status.get('drawing_pipeline_version') != PIPELINE_VERSION:
            raise RuntimeError('板端仍使用旧绘画程序，请先安装绘画修复版软件包')

    def plan(self, image_job_id, mode="real", use_hw=False,
             port="/dev/ttyACM0", baudrate=1000000, motion_mode="sugar_fast",start_counts=None,counts_source=None,drawing_size_mm=None,background_save=False):
        caps=self.fetch_status()
        if caps.get('robot_type')=='TCB705':
            if start_counts is not None:raise ValueError('天链使用七轴角度反馈，不接受 STS 计数')
            data={'image_job':image_job_id,'mode':'demo' if caps.get('simulation') else 'real','motion_mode':'tcb705'}
            if drawing_size_mm is not None:data['drawing_size_mm']=list(drawing_size_mm)
            return self._request('/api/plan',method='POST',data=data,timeout=60)
        self._require_drawing_pipeline()
        if motion_mode not in ('sugar_fast','classic_fast','speed_priority','gentle','smooth_fast','standard'):
            raise ValueError('未知运动模式')
        if motion_mode in ('sugar_fast','classic_fast','speed_priority','gentle','smooth_fast'):
            status=self.fetch_status()
            if status.get('motion_algorithm_version') != 'motion-smooth-v1':
                raise RuntimeError('板端尚未安装平缓运动版，请先更新板端软件')
            if motion_mode == 'sugar_fast' and motion_mode not in status.get('motion_modes', []):
                raise RuntimeError('板端尚未安装糖画连续运动版，请先更新板端软件')
            if motion_mode=='classic_fast' and motion_mode not in status.get('motion_modes',[]):
                raise RuntimeError('板端尚未安装旧版直驱加速模式')
            if motion_mode == 'smooth_fast' and motion_mode not in status.get('motion_modes',[]):
                raise RuntimeError('板端尚未安装平滑加速版，请先更新板端软件或选择平缓模式')
            if motion_mode == 'speed_priority' and motion_mode not in status.get('motion_modes',[]):
                raise RuntimeError('板端尚未安装速度优先版，请先更新板端软件')
        data = {"image_job": image_job_id, "mode": mode, "use_hw": use_hw, "motion_mode": motion_mode}
        if background_save and self.fetch_status().get('background_plan_save_supported'):
            data['background_save'] = True
        if drawing_size_mm is not None:
            if not self.fetch_status().get('drawing_size_supported'):
                raise RuntimeError('请先更新板端软件以使用绘画尺寸选择')
            data['drawing_size_mm']=list(drawing_size_mm)
        if mode == "real":
            data.update(port=port, baudrate=baudrate, confirmed=True)
            if start_counts is not None:
                if not self.fetch_status().get('external_start_counts_supported'):
                    raise RuntimeError('请先更新板端软件以使用 PC 舵机读数规划')
                data.update(start_counts=start_counts,counts_source=counts_source or 'PC_encoder')
        return self._request("/api/plan", method="POST", data=data, timeout=60)

    def execute(self, plan_job_id, mode="real", port="/dev/ttyACM0", baudrate=1000000):
        """执行规划; 板卡会在画完后强制归位 (不可关闭)"""
        self._require_drawing_pipeline()
        data = {"plan_job": plan_job_id, "mode": mode}
        if mode == "real":
            # confirmed 必填: 板卡 validate_scan 要求 confirmed is True
            data.update(port=port, baudrate=baudrate, confirmed=True)
        return self._request("/api/execute", method="POST", data=data, timeout=60)

    def home(self, mode="real", port="/dev/ttyACM0", baudrate=1000000):
        """回到绘画起始姿态 (板卡动作 /api/home, 约 12s)"""
        data = {"mode": mode}
        if mode == "real":
            data.update(port=port, baudrate=baudrate, confirmed=True)
        return self._request("/api/home", method="POST", data=data, timeout=60)

    def get_preview(self, job_id, filename="preview.svg"):
        return self._request(f"/job/{job_id}/{filename}")

    def calibrate_pen(self, kind, port='/dev/ttyACM0', baudrate=1000000):
        return self._request('/api/calibrate_pen', method='POST', data=dict(
            mode='real',kind=kind,port=port,baudrate=baudrate,confirmed=True,pose_confirmed=True),timeout=60)

    def get_job_file(self, job_id, filename):
        return self._request(f"/job/{job_id}/{filename}")

    def prediction_data(self, plan_job_id):
        return self._request(f'/api/plans/{plan_job_id}/preview', timeout=60)

    def prediction_svg(self, plan_job_id):
        return self._request(f'/api/plans/{plan_job_id}/preview.svg', timeout=60)


class SSHLink:
    """SSH/SFTP 连接管理(复用单条连接)"""

    def __init__(self, ip=BOARD_IP, user=BOARD_USER, password=BOARD_PASS):
        self.ip, self.user, self.password = ip, user, password
        self._client = None
        self._lock = threading.Lock()

    def client(self):
        with self._lock:
            if self._client is None:
                import paramiko
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(self.ip, username=self.user, password=self.password, timeout=15)
                self._client = c
            else:
                # 探活
                try:
                    tr = self._client.get_transport()
                    if tr is None or not tr.is_active():
                        raise RuntimeError("dead")
                except Exception:
                    self._client = None
                    return self.client()
            return self._client

    def run(self, cmd, timeout=60):
        """执行命令, 返回 (stdout, stderr, exit_code)"""
        c = self.client()
        stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return out, err, code

    def sudo(self, cmd, timeout=60):
        return self.run("sudo -n bash -c " + shlex.quote(cmd), timeout=timeout)

    def put(self, local, remote):
        c = self.client()
        sftp = c.open_sftp()
        try:
            sftp.put(str(local), remote)
        finally:
            sftp.close()

    def put_bytes(self, data: bytes, remote):
        c = self.client()
        sftp = c.open_sftp()
        try:
            with sftp.open(remote, "wb") as f:
                f.write(data)
        finally:
            sftp.close()

    def close(self):
        with self._lock:
            if self._client:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None


class SSHTunnel:
    """SSH 端口转发隧道 (端口占用检测 + 保活 + 可重启)"""

    def __init__(self, ip=BOARD_IP, user=BOARD_USER, password=BOARD_PASS, forwards=None):
        self.ip, self.user, self.password = ip, user, password
        # forwards: [(local_port, remote_port), ...]
        self.forwards = forwards or [(WEB_PORT, WEB_PORT)]
        self.tunnel = None

    @staticmethod
    def port_busy(port):
        """本地端口是否已被占用 (占用说明已有隧道在跑)"""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True
        finally:
            s.close()

    def busy_ports(self):
        return [lp for lp, _ in self.forwards if self.port_busy(lp)]

    def start(self):
        """建立隧道; 端口被占用时抛异常并说明原因"""
        from sshtunnel import SSHTunnelForwarder
        busy = self.busy_ports()
        if busy:
            raise RuntimeError(
                "本地端口已被占用: %s\n"
                "说明已有隧道在运行。请二选一:\n"
                "  · 取消勾选「SSH 隧道」直接使用已有隧道; 或\n"
                "  · 关闭旧的隧道进程 (任务管理器结束多余的 python.exe) 后重试"
                % ", ".join(str(p) for p in busy))
        self.tunnel = SSHTunnelForwarder(
            (self.ip, 22),
            ssh_username=self.user,
            ssh_password=self.password,
            local_bind_addresses=[("127.0.0.1", lp) for lp, _ in self.forwards],
            remote_bind_addresses=[("127.0.0.1", rp) for _, rp in self.forwards],
        )
        self.tunnel.start()
        # 保活: 防止空闲被服务端断开 (这是之前频繁掉线的根因)
        try:
            for srv in getattr(self.tunnel, "_server_list", []):
                srv.transport.set_keepalive(30)
        except Exception:
            pass
        return True

    def alive(self):
        """隧道是否仍然可用"""
        if not self.tunnel:
            return False
        try:
            if not self.tunnel.is_active:
                return False
            # 进一步确认能真的连上本地端口
            import socket
            for lp, _ in self.forwards:
                s = socket.create_connection(("127.0.0.1", lp), timeout=2)
                s.close()
            return True
        except Exception:
            return False

    def restart(self):
        self.stop()
        time.sleep(0.8)
        return self.start()

    def stop(self):
        if self.tunnel:
            try:
                self.tunnel.stop()
            except Exception:
                pass
            self.tunnel = None


# ============================================================
# 本地图片处理 (PC OpenCV)
# ============================================================
def process_image_local(image_path, output_dir, width_mm=100.0, height_mm=100.0,
                        max_segments=4000, style='lineart', detail='fine'):
    """Use the same centerline graph as the HTTP image pipeline."""
    from vision import convert
    # Preserve the desktop's existing paper direction; changing extraction
    # must not silently reflect a drawing relative to its calibrated axes.
    return convert(image_path,output_dir,style,width_mm,height_mm,max_segments,detail,
                   coordinate_system='full_canvas_xy_down')


# ============================================================
# 主窗口
# ============================================================
class ArmStudio:
    board_mode = False
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.board_mode = bool(getattr(args,'board_local',False))
        root.so101_touch = self.board_mode
        self.client = BoardClient(args.host, args.port)
        self.backend_name = "未连接"
        self.ssh = None if self.board_mode else SSHLink(args.board_ip, args.board_user, args.board_pass)
        self.tunnel = None
        self.link = args.tunnel and not self.board_mode

        self.image_job_id = getattr(args, "restore_image_job", None)
        self.plan_job_id = getattr(args, "restore_plan_job", None)
        self._planning_token = None
        self._active_plan_job_id = None
        self._plan_before_planning = None
        self._execution_active = False
        self._calibration_active = False
        self._last_execution_job = None
        self._geometry_captures = {}
        self._four_point_ready = False
        self._calibration_cache = (Path(args.data_dir)/'gui_calibration' if self.board_mode else
                                   Path.home()/'Pictures/SO101/Calibration')
        self._geometry_draft_path = self._calibration_cache/'four_point_draft.json'
        self._extraction_active = False
        self._cloud_active = False
        self._prediction_active = False
        self._path_data = None
        self._path_cache_key = None
        self._path_output_dir = None
        self._history_refresh_id = 0
        self._plan_history = []          # 历史规划列表 (来自板卡 /api/plans)
        self.cloud_image_path = None
        self.original_image_path = None
        self.cloud_library = CloudImageLibrary(getattr(args, 'cloud_image_dir', None))
        self.bluetooth_inbox = BluetoothInbox(Path(args.data_dir) / 'bluetooth_images') if self.board_mode else None

        # 手势跟随
        self.follower = None
        self.follow_running = False
        self.follow_thread = None
        self._follow_stop = threading.Event()

        # UI presence only. Motion cancellation is explicit /api/stop.
        self._beat_stop = threading.Event()
        self._beat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)

        self._build_ui()
        self._update_plan_controls()
        if getattr(args,'image',None):
            self.ent_image.insert(0,str(args.image))
        if getattr(args,'preview_paths',None):
            result=json.loads(Path(args.preview_paths).read_text(encoding='utf-8'))
            from stroke_paths import validate_paths
            validate_paths(result)
            self._path_data=result
            self.root.after(200,lambda:self._show_path_preview(result))
        if self.image_job_id:
            self.lbl_image_job.config(text=f"Image Job: {self.image_job_id[:12]}… (已恢复)")
        if self.plan_job_id:
            self.lbl_plan_hist.config(text=f"已恢复规划 {self.plan_job_id[:12]}，刷新列表可查看详情")
            self.root.after(500, self._refresh_plans)
        self.root.after(400, self._auto_start)
        if getattr(args, 'show_cloud_history', False):
            self.root.after(250, self._show_cloud_history)
        self._beat_thread.start()

    # ---------------- 心跳 + 隧道看门狗 ----------------
    def _heartbeat_loop(self):
        """Update UI presence and monitor only a tunnel owned by this GUI."""
        fail_count = 0
        while not self._beat_stop.is_set():
            try:
                if self.client.token:
                    self.client.heartbeat()
                    fail_count = 0
            except Exception:
                fail_count += 1
                # 只监控由本 GUI 建立的隧道
                if fail_count == 3 and self.tunnel and self.link:
                    self.log_msg("⚠ 隧道连接中断, 尝试自动重连…")
                    self.root.after(0, lambda: self._status("🟡 隧道重连中…", theme.GOLD))
                    try:
                        self.tunnel.restart()
                        self.log_msg("✅ 隧道已自动重连")
                        self.root.after(0, self._connect)
                    except Exception as e:
                        self.log_msg(f"❌ 隧道重连失败: {str(e)[:120]}")
                    fail_count = 0
                elif fail_count > 0 and fail_count % 15 == 0:
                    self.log_msg(f"⚠ 已连续 {fail_count} 次心跳失败 (隧道可能已断)")
            self._beat_stop.wait(1.0)

    # ---------------- UI ----------------
    def _build_ui(self):
        theme.install(self.root, self.board_mode)
        self.root.title("SO-101 中心线绘画控制台 — 绘画 / 手势跟随 / 舵机调试")
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry('%dx%d' % (min(1020, screen_w-80), min(860, screen_h-110)))
        self.root.minsize(min(900, screen_w-80), min(700, screen_h-110))
        if self.board_mode:
            self.root.geometry('1024x600+0+0')
            self.root.minsize(800,480)
            self.root.attributes('-fullscreen',not getattr(self.args,'windowed',False))

        brand = theme.brand_header(self.root)
        # 顶栏
        top = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        if self.board_mode and getattr(self.args, 'return_user_gui', False):
            ttk.Button(brand, text='返回用户界面', style='Primary.TButton', command=self.on_close).pack(side='right', padx=(8, 0))
        self.lbl_status = ttk.Label(top, text="⚪ 未连接", font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(side="left")
        self.lbl_info = ttk.Label(top, text="", foreground=theme.MUTED)
        self.lbl_info.pack(side="left", padx=12)
        ttk.Button(top, text="连接板卡", command=self._connect).pack(side="right")
        ttk.Button(top, text="四点标定", command=self._show_geometry_section).pack(side="right", padx=5)
        # 默认不自动建隧道: 外部隧道 (C:\fpga_build\tunnel_dual.py) 已占用 8765/8770
        self.var_link = tk.BooleanVar(value=self.link)
        if not self.board_mode:
            ttk.Checkbutton(top, text="SSH 隧道", variable=self.var_link,
                            command=self._toggle_tunnel).pack(side="right", padx=8)
        else:
            from scripts.touch_ui import TouchKeyboard
            self._keyboard=TouchKeyboard(self.root)
            self.root.so101_keyboard=self._keyboard
            from scripts.touch_network import show_network
            ttk.Button(top,text='Wi-Fi',command=lambda:show_network(self.root)).pack(side='right',padx=3)
            ttk.Button(top,text='键盘',command=self._keyboard.show).pack(side='right',padx=3)
            ttk.Button(brand,text='停止',style='Danger.TButton', command=self._stop).pack(side='right',padx=5)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.tab_draw = ttk.Frame(nb, padding=10)
        self.tab_hand = ttk.Frame(nb, padding=10)
        self.tab_servo = ttk.Frame(nb, padding=10)
        nb.add(self.tab_draw, text="① 绘画")
        nb.add(self.tab_hand, text="② 手势跟随")
        nb.add(self.tab_servo, text="③ 舵机调试")
        if self.args.target_drawing:
            self.root.title("SO-101 四点标定 · 绘画预测 — ArmStudio")
            nb.tab(self.tab_hand, state="disabled")

        self._build_draw_tab()
        self._build_hand_tab()
        self._build_servo_tab()

        # 日志
        logf = ttk.LabelFrame(nb if self.board_mode else self.root, text="日志", padding=4)
        if not self.board_mode: logf.pack(fill="both", padx=10, pady=(0, 8))
        self.log = tk.Text(logf, height=11, font=("Consolas", 9), wrap="word")
        sb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if self.board_mode:
            from scripts.touch_ui import configure_touch_console
            configure_touch_console(self,nb,logf)

    # ---- 绘画页 ----
    def _build_draw_tab(self):
        # Keep the added history row and lower drawing controls accessible on
        # smaller Windows displays, rather than clipping the bottom controls.
        canvas = tk.Canvas(self.tab_draw, highlightthickness=0, height=520)
        scrollbar = ttk.Scrollbar(self.tab_draw, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        t = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=t, anchor='nw')
        t.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        self._draw_canvas = canvas
        if self.board_mode:
            nav=ttk.Frame(self.tab_draw)
            nav.pack(side='right',fill='y',before=scrollbar)
            ttk.Button(nav,text='上',width=3,command=lambda:canvas.yview_scroll(-1,'pages')).pack(pady=5)
            ttk.Button(nav,text='下',width=3,command=lambda:canvas.yview_scroll(1,'pages')).pack(pady=5)
            ttk.Button(nav,text='顶',width=3,command=lambda:canvas.yview_moveto(0)).pack(pady=5)

        def mousewheel(event):
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if widget is None or widget.winfo_class() in ('TCombobox', 'TSpinbox', 'Text'):
                return
            while widget is not None:
                if widget == canvas:
                    units = max(1, abs(event.delta) // 120) * (-1 if event.delta > 0 else 1)
                    canvas.yview_scroll(units, 'units')
                    return 'break'
                widget = getattr(widget, 'master', None)
        self.root.bind('<MouseWheel>', mousewheel, add='+')
        self.root.bind('<Button-4>',lambda e:canvas.yview_scroll(-3,'units') if self.tab_draw.winfo_ismapped() else None,add='+')
        self.root.bind('<Button-5>',lambda e:canvas.yview_scroll(3,'units') if self.tab_draw.winfo_ismapped() else None,add='+')

        # 图片选择
        f1 = ttk.LabelFrame(t, text="1. 选择图片", padding=8)
        f1.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f1); row.pack(fill="x")
        self.ent_image = ttk.Entry(row)
        self.ent_image.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(row, text="浏览...", command=self._browse).pack(side="left")
        if self.board_mode:
            from scripts.touch_bluetooth import show_bluetooth
            ttk.Button(row, text='蓝牙收图', command=lambda: show_bluetooth(self)).pack(side='left', padx=5)

        row = ttk.Frame(f1); row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="尺寸:").pack(side="left")
        self.var_w = tk.StringVar(value="100")
        self.var_h = tk.StringVar(value="100")
        self.var_size_preset=tk.StringVar(value='100×100 mm')
        self.cmb_drawing_size=ttk.Combobox(row,textvariable=self.var_size_preset,width=15,state='readonly',
            values=('100×100 mm','200×200 mm','300×300 mm','自定义'))
        self.cmb_drawing_size.pack(side='left',padx=(3,8))
        self.cmb_drawing_size.bind('<<ComboboxSelected>>',self._pick_drawing_size)
        self.ent_drawing_w=ttk.Entry(row, textvariable=self.var_w, width=5)
        self.ent_drawing_w.pack(side="left", padx=3)
        ttk.Label(row, text="×").pack(side="left")
        self.ent_drawing_h=ttk.Entry(row, textvariable=self.var_h, width=5)
        self.ent_drawing_h.pack(side="left", padx=3)
        self.var_w.trace_add('write',self._drawing_dimensions_changed)
        self.var_h.trace_add('write',self._drawing_dimensions_changed)
        ttk.Label(row, text="mm").pack(side="left")
        ttk.Label(row, text="   线段数:").pack(side="left")
        self.var_segs = tk.StringVar(value="4000")
        ttk.Entry(row, textvariable=self.var_segs, width=6).pack(side="left", padx=3)
        ttk.Label(row, text="   风格:").pack(side="left")
        self.var_style = tk.StringVar(value="lineart")
        ttk.Radiobutton(row, text="线稿", variable=self.var_style, value="lineart").pack(side="left")
        ttk.Radiobutton(row, text="照片", variable=self.var_style, value="photo").pack(side="left")

        # 云端 AI
        f2 = ttk.LabelFrame(t, text="2. 云端大模型生成线稿 (可选，效果更好)", padding=8)
        f2.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f2); row.pack(fill="x")
        ttk.Label(row, text="模型:").pack(side="left")
        self.var_cloud_model = tk.StringVar(value="seedream")
        self.cmb_cloud = ttk.Combobox(row, textvariable=self.var_cloud_model, width=18,
                                      state="readonly",
                                      values=["seedream", "image2", "image25-flare", "image25-sunburst"])
        self.cmb_cloud.pack(side="left", padx=4)
        ttk.Label(row, text="主体:").pack(side="left", padx=(10, 0))
        self.var_subject = tk.StringVar(value="portrait")
        ttk.Radiobutton(row, text="人像", variable=self.var_subject, value="portrait").pack(side="left")
        ttk.Radiobutton(row, text="物体", variable=self.var_subject, value="object").pack(side="left")
        self.btn_cloud = ttk.Button(row, text="☁ AI 生成线稿", style="Primary.TButton", command=self._cloud_generate)
        self.btn_cloud.pack(side="right")
        self.lbl_cloud = ttk.Label(f2, text="使用配置的云端接口与私用密钥；原图上传后接收线稿",
                                   foreground=theme.MUTED)
        self.lbl_cloud.pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(f2); row.pack(fill='x', pady=(5, 0))
        self.btn_cloud_history = ttk.Button(row, text='历史云端图片', command=self._show_cloud_history)
        self.btn_cloud_history.pack(side='left')
        ttk.Button(row, text='另存当前云端图…', command=self._save_cloud_image_as).pack(side='left', padx=5)
        ttk.Button(row, text='打开图片库', command=self._open_cloud_directory).pack(side='left', padx=5)
        ttk.Label(row, text='生成后自动保存；选历史图可直接提取并上传', foreground=theme.MUTED).pack(side='left', padx=6)

        # 提取笔画
        f3 = ttk.LabelFrame(t, text="3. 提取笔画并上传板卡", padding=8)
        f3.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f3); row.pack(fill="x")
        self.btn_extract = ttk.Button(row, text="提取笔画 → 上传", style="Primary.TButton", command=self._extract)
        self.btn_extract.pack(side="left")
        self.btn_predict = ttk.Button(row, text='预测绘画效果（含顺序）', command=self._predict_image)
        self.btn_predict.pack(side='left', padx=6)
        self.lbl_image_job = ttk.Label(row, text="", foreground=theme.MUTED)
        self.lbl_image_job.pack(side="left", padx=10)

        # 规划执行
        f4 = ttk.LabelFrame(t, text="4. 规划轨迹 & 让机械臂直接动起来", padding=8)
        f4.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f4); row.pack(fill="x")
        self.var_hw = tk.BooleanVar(value=False)
        self.chk_hw = ttk.Checkbutton(row, text="FPGA 硬件 IK 校验", variable=self.var_hw)
        self.chk_hw.pack(side="left", padx=10)
        self.var_motion_mode = tk.StringVar(value='糖画连续（自动）')
        ttk.Label(row,text='糖画连续 · 自动分段调速').pack(side='left',padx=4)
        if self.args.target_drawing:
            self.chk_hw.config(text="完整目标 FPGA IK（由板端配置）", state="disabled")
        self.btn_plan = ttk.Button(row, text="规划轨迹", style="Primary.TButton", command=self._plan)
        self.btn_plan.pack(side="right")

        row = ttk.Frame(f4); row.pack(fill="x", pady=(8, 0))
        self.btn_home = ttk.Button(row, text="🏠 回绘画起始位", command=self._draw_home)
        self.btn_home.pack(side="left")
        self.btn_auto = ttk.Button(row, text="▶ 一键绘画 (规划+直接驱动)", style="Primary.TButton", command=self._one_click_draw)
        self.btn_auto.pack(side="left", padx=5)
        self.btn_exec_arm = ttk.Button(row, text="🦾 直接驱动机械臂", style="Primary.TButton", command=self._drive_arm)
        self.btn_exec_arm.pack(side="left", padx=5)
        self.btn_preview = ttk.Button(row, text="已规划轨迹预测", command=self._preview)
        self.btn_preview.pack(side="left", padx=5)
        self.btn_feedback_preview = ttk.Button(row,text='实际执行轨迹',command=self._feedback_preview,state='disabled')
        self.btn_feedback_preview.pack(side='left',padx=4)
        ttk.Button(row, text="停止", style="Danger.TButton", command=self._stop).pack(side="left", padx=5)

        # ---- 历史规划 (持久化): 可直接选用以前生成的规划, 无需重新规划 ----
        f5 = ttk.LabelFrame(f4, text="历史规划 (服务重启后仍保留, 可直接执行)", padding=6)
        f5.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(f5); row.pack(fill="x")
        ttk.Label(row, text="选择:").pack(side="left")
        self.var_plan_hist = tk.StringVar()
        self.cmb_plans = ttk.Combobox(row, textvariable=self.var_plan_hist,
                                      state="readonly", width=46 if self.board_mode else 72)
        self.cmb_plans.pack(side="left", padx=(4, 6))
        self.cmb_plans.bind("<<ComboboxSelected>>", lambda e: self._on_pick_plan())
        ttk.Button(row, text="🔄 刷新列表", command=self._refresh_plans).pack(side="left", padx=3)
        self.btn_exec_history = ttk.Button(row, text="✅ 用选中的规划执行", command=self._execute_selected_plan)
        self.btn_exec_history.pack(side="left", padx=3)
        self.lbl_plan_hist = ttk.Label(f5, text="点「刷新列表」载入历史规划", foreground=theme.MUTED)
        self.lbl_plan_hist.pack(anchor="w", pady=(4, 0))

        # 一键生成"画一条直线"的实物测试规划 (无需准备图片, 约 5 秒)
        row2 = ttk.Frame(f5); row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="测试直线边长:").pack(side="left")
        self.var_test_mm = tk.StringVar(value="40")
        ttk.Combobox(row2, textvariable=self.var_test_mm, state="readonly", width=5,
                     values=("20", "30", "40", "60", "80", "100")).pack(side="left", padx=(4, 2))
        ttk.Label(row2, text="mm").pack(side="left", padx=(0, 8))
        self.btn_make_test = ttk.Button(row2, text="📏 生成直线测试规划 (实物模式)",
                                        command=self._make_test_plan)
        self.btn_make_test.pack(side="left", padx=4)
        ttk.Label(row2, text="← 机械臂必须已在绘画起始位", foreground=theme.DIM).pack(side="left", padx=6)

        # 笔尖高度微调 (写入 machine.json 的 paper.draw_height_offset_m)
        row3 = ttk.Frame(f5); row3.pack(fill="x", pady=(6, 0))
        ttk.Label(row3, text="✏️ 落笔高度微调:").pack(side="left")
        self.var_pen_lift = tk.StringVar(value="0")
        ttk.Spinbox(row3, from_=-20, to=150, increment=1, width=6,
                    textvariable=self.var_pen_lift).pack(side="left", padx=(4, 2))
        ttk.Label(row3, text="mm").pack(side="left", padx=(0, 8))
        ttk.Button(row3, text="应用", command=self._apply_pen_lift).pack(side="left", padx=3)
        ttk.Button(row3, text="读取当前值", command=self._read_pen_lift).pack(side="left", padx=3)
        ttk.Button(row3, text="归零", command=lambda: (self.var_pen_lift.set("0"), self._apply_pen_lift())
                   ).pack(side="left", padx=3)
        self.lbl_pen_lift = ttk.Label(row3, text="(正值抬离纸面，负值压向纸面；四点接触平面为 0)", foreground=theme.MUTED)
        self.lbl_pen_lift.pack(side="left", padx=8)
        axis_row = ttk.Frame(f5); axis_row.pack(fill='x',pady=(6,0))
        ttk.Label(axis_row,text='标定读取来源:').pack(side='left')
        try:
            from serial.tools import list_ports
            calibration_ports=[p.device for p in list_ports.comports() if p.device.startswith('COM')]
        except ImportError:calibration_ports=[]
        self.var_calibration_source=tk.StringVar(value=getattr(self.args,'calibration_port',None) or '板端')
        ttk.Combobox(axis_row,textvariable=self.var_calibration_source,values=['板端']+calibration_ports,
                     state='readonly',width=8).pack(side='left',padx=4)
        self.btn_pen_axis = ttk.Button(axis_row,text='笔已垂直：记录姿态',
            command=lambda:self._record_pen_calibration('axis'))
        self.btn_pen_axis.pack(side='left',padx=3)
        self.btn_pen_contact = ttk.Button(axis_row,text='笔已轻触纸面：记录高度',
            command=lambda:self._record_pen_calibration('contact_height'))
        self.btn_pen_contact.pack(side='left',padx=3)
        ttk.Button(axis_row, text='多点零位与笔长标定', command=self._open_kinematic_calibration).pack(side='left',padx=3)
        ttk.Label(f5,text='先手动调整，再记录；记录后自动重新规划当前图片。',foreground=theme.MUTED).pack(anchor='w',pady=(3,0))
        placement_row=ttk.Frame(f5);placement_row.pack(fill='x',pady=(7,0))
        ttk.Label(placement_row,text='绘画位置：横向').pack(side='left')
        self.var_draw_x=tk.StringVar(value='0')
        self.var_draw_y=tk.StringVar(value='0')
        ttk.Spinbox(placement_row,from_=-300,to=300,increment=5,textvariable=self.var_draw_x,width=6).pack(side='left',padx=3)
        ttk.Label(placement_row,text='mm（+右移）  纵向').pack(side='left')
        ttk.Spinbox(placement_row,from_=-300,to=300,increment=5,textvariable=self.var_draw_y,width=6).pack(side='left',padx=3)
        ttk.Label(placement_row,text='mm（+沿原图下方）').pack(side='left')
        self.btn_drawing_placement=ttk.Button(placement_row,text='应用位置',command=self._apply_drawing_placement)
        self.btn_drawing_placement.pack(side='left',padx=5)
        self.lbl_drawing_alignment=ttk.Label(f5,text='读取当前位置设置中…',foreground=theme.MUTED)
        self.lbl_drawing_alignment.pack(anchor='w',pady=(3,0))
        lift_row=ttk.Frame(f5);lift_row.pack(fill='x',pady=(3,0))
        ttk.Label(lift_row,text='转移抬笔高度：').pack(side='left')
        self.var_travel_lift=tk.StringVar(value='6')
        ttk.Spinbox(lift_row,from_=1,to=50,increment=1,textvariable=self.var_travel_lift,width=6).pack(side='left',padx=3)
        ttk.Label(lift_row,text='mm（与位置一起应用；从落笔高度向上抬起）',foreground=theme.MUTED).pack(side='left')
        pause_row=ttk.Frame(f5);pause_row.pack(fill='x',pady=(3,0))
        self.var_stroke_end_pause=tk.StringVar(value='0');self.var_lift_ready_pause=tk.StringVar(value='0')
        ttk.Label(pause_row,text='抬笔前停顿（0=立即抬）：').pack(side='left')
        ttk.Spinbox(pause_row,from_=0,to=3.,increment=.05,textvariable=self.var_stroke_end_pause,width=6).pack(side='left',padx=3)
        ttk.Label(pause_row,text='秒   抬笔后等待：').pack(side='left')
        ttk.Spinbox(pause_row,from_=0,to=3.,increment=.05,textvariable=self.var_lift_ready_pause,width=6).pack(side='left',padx=3)
        ttk.Label(pause_row,text='秒（与位置一起应用；近距离换笔也执行）',foreground=theme.MUTED).pack(side='left')
        self._geometry_header=ttk.Label(f5,text='四点几何校正：A 左上 → B 右上 → C 右下 → D 左下。保持笔垂直，笔尖轻触各角后分别记录。',
            foreground=theme.MUTED,wraplength=880)
        self._geometry_header.pack(anchor='w',pady=(7,0))
        ttk.Label(f5,text='正方形相邻边默认 200 mm，对角线约 282.8 mm；应用后图形以四点中心为基准，位置偏移和接触高度微调归零。',
            foreground=theme.MUTED,wraplength=880).pack(anchor='w',pady=(3,0))
        geo_row=ttk.Frame(f5);geo_row.pack(fill='x',pady=(3,0))
        ttk.Label(geo_row,text='正方形实测边长').pack(side='left')
        self.var_geometry_span=tk.StringVar(value='200')
        ttk.Entry(geo_row,textvariable=self.var_geometry_span,width=6).pack(side='left',padx=3)
        ttk.Label(geo_row,text='mm').pack(side='left')
        for key in GEOMETRY_POINTS:
            button=ttk.Button(geo_row,text='记录 '+key+' '+GEOMETRY_LABELS[key],command=lambda k=key:self._capture_geometry_point(k))
            button.pack(side='left',padx=3);setattr(self,'btn_geometry_'+key,button)
        geo_actions=ttk.Frame(f5);geo_actions.pack(fill='x',pady=(3,0))
        self.btn_geometry_apply=ttk.Button(geo_actions,text='应用四点校正',command=self._apply_geometry_calibration)
        self.btn_geometry_apply.pack(side='left',padx=3)
        self.btn_geometry_reset=ttk.Button(geo_actions,text='清除四点，重新采集',command=self._reset_geometry_calibration)
        self.btn_geometry_reset.pack(side='left',padx=3)
        self.var_geometry_force=tk.BooleanVar(value=False)
        self.chk_geometry_force=ttk.Checkbutton(geo_actions,text='超差需重新标定',
            variable=self.var_geometry_force,state='disabled')
        self.chk_geometry_force.pack(side='left',padx=8)
        self.lbl_geometry_points=ttk.Label(f5,text='待记录：A 左上、B 右上、C 右下、D 左下；采点只读取位置。',foreground=theme.MUTED)
        self.lbl_geometry_points.pack(anchor='w',pady=(3,0))
        # 爪子离地面高度 (写入 machine.json 的 paper.home_height_offset_m)
        row4 = ttk.Frame(f5); row4.pack(fill="x", pady=(6, 0))
        ttk.Label(row4, text="🖐 爪子离地高度:").pack(side="left")
        self.var_home_lift = tk.StringVar(value="0")
        ttk.Spinbox(row4, from_=0, to=200, increment=1, width=6,
                    textvariable=self.var_home_lift).pack(side="left", padx=(4, 2))
        ttk.Label(row4, text="mm").pack(side="left", padx=(0, 8))
        ttk.Button(row4, text="应用", command=self._apply_home_height).pack(side="left", padx=3)
        ttk.Button(row4, text="读取当前值", command=self._read_home_height).pack(side="left", padx=3)
        ttk.Button(row4, text="归零", command=lambda: (self.var_home_lift.set("0"), self._apply_home_height())
                   ).pack(side="left", padx=3)
        self.lbl_home_lift = ttk.Label(row4, text="(归位时爪子抬离纸面的高度)", foreground=theme.MUTED)
        self.lbl_home_lift.pack(side="left", padx=8)

        ttk.Label(f4, text="提示: 规划会以机械臂「当前姿态」为起点。若它不在绘画起始位，"
                           "请先点「回绘画起始位」(约 12 秒)，否则 IK 可能停滞。"
                           "绘画和手势跟随共用串口，需用「② 手势跟随」页切换模式。",
                  foreground=theme.MUTED, wraplength=900, justify="left").pack(anchor="w", pady=(6, 0))

        self.prog = ttk.Progressbar(f4, mode="determinate", maximum=100)
        self.prog.pack(fill="x", pady=(8, 0))
        self.lbl_prog = ttk.Label(f4, text="就绪", foreground=theme.MUTED)
        self.lbl_prog.pack(anchor="w")

    # ---- 手势跟随页 ----
    def _build_hand_tab(self):
        from scripts.touch_ui import scroll_page
        t = scroll_page(self.tab_hand, self.root)

        f1 = ttk.LabelFrame(t, text="板卡服务模式 (绘画与跟随共用串口，需互斥切换)", padding=8)
        f1.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f1); row.pack(fill="x")
        self.btn_follow_srv = ttk.Button(row, text="切到跟随模式", command=self._start_follow_server)
        self.btn_follow_srv.pack(side="left")
        ttk.Button(row, text="切回绘画模式", command=self._switch_to_drawing).pack(side="left", padx=5)
        ttk.Button(row, text="检查状态", command=self._check_follow_server).pack(side="left", padx=5)
        ttk.Button(row, text="部署脚本到板卡", command=self._deploy_follow).pack(side="left", padx=5)
        self.lbl_follow_srv = ttk.Label(row, text="未检查", foreground=theme.MUTED)
        self.lbl_follow_srv.pack(side="left", padx=10)

        f2 = ttk.LabelFrame(t, text="摄像头跟随", padding=8)
        f2.pack(fill="both", expand=True, pady=(0, 8))
        row = ttk.Frame(f2); row.pack(fill="x")
        ttk.Label(row, text="摄像头:").pack(side="left")
        self.var_cam = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self.var_cam, width=4).pack(side="left", padx=3)
        self.btn_follow = ttk.Button(row, text="▶ 开始跟随", command=self._toggle_follow)
        self.btn_follow.pack(side="left", padx=8)
        ttk.Button(row, text="回中位", command=self._follow_home).pack(side="left")
        ttk.Button(row, text="测试夹爪行程", command=self._test_gripper).pack(side="left", padx=6)

        # --- 夹爪控制行 ---
        grow = ttk.Frame(f2); grow.pack(fill="x", pady=(6, 0))
        self.var_pinch = tk.BooleanVar(value=True)
        ttk.Checkbutton(grow, text="自动捏合跟随", variable=self.var_pinch,
                        command=self._toggle_pinch).pack(side="left")
        ttk.Label(grow, text="   手动夹爪:").pack(side="left", padx=(14, 0))
        self.var_grip = tk.DoubleVar(value=0.0)
        self.scale_grip = ttk.Scale(grow, from_=0.0, to=1.0, variable=self.var_grip,
                                    orient="horizontal", length=150,
                                    command=self._on_grip_manual, state="disabled")
        self.scale_grip.pack(side="left", padx=4)
        self.lbl_grip = ttk.Label(grow, text="自动", width=16, foreground=theme.MUTED)
        self.lbl_grip.pack(side="left", padx=6)

        ttk.Label(f2, text="夹爪行程 1300=合拢 / 2800=张开 (实测机械边界)　|　"
                           "捏合手指 → 夹爪合拢，张开手指 → 夹爪张开",
                  foreground=theme.MUTED).pack(anchor="w", pady=(4, 0))

        self.lbl_cam = ttk.Label(f2, text="摄像头未启动", background=theme.BG,
                                 foreground=theme.MUTED, anchor="center")
        self.lbl_cam.pack(fill="both", expand=True, pady=(8, 0))
        self.lbl_follow_stat = ttk.Label(f2, text="", foreground=theme.MUTED)
        self.lbl_follow_stat.pack(anchor="w", pady=(4, 0))
        self._cam_photo = None

    # ---- 舵机页 ----
    def _build_servo_tab(self):
        from scripts.touch_ui import scroll_page
        t = scroll_page(self.tab_servo, self.root)

        f1 = ttk.LabelFrame(t, text="探测", padding=8)
        f1.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f1); row.pack(fill="x")
        ttk.Label(row, text="端口:").pack(side="left")
        self.var_port = tk.StringVar(value="/dev/ttyACM0")
        ttk.Entry(row, textvariable=self.var_port, width=18).pack(side="left", padx=4)
        ttk.Label(row, text="ID:").pack(side="left", padx=(8, 0))
        self.var_ids = tk.StringVar(value="1,2,3,4,5,6")
        ttk.Entry(row, textvariable=self.var_ids, width=14).pack(side="left", padx=4)
        ttk.Button(row, text="探测舵机", command=self._probe).pack(side="left", padx=6)
        ttk.Button(row, text="刷新位置", command=self._probe).pack(side="left")

        cols = ("id", "ping", "pos", "err")
        self.tree = ttk.Treeview(f1, columns=cols, show="headings", height=7)
        for c, w, txt in zip(cols, (70, 90, 110, 160),
                             ("ID", "Ping", "位置计数", "错误")):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="x", pady=(8, 0))

        f2 = ttk.LabelFrame(t, text="动作", padding=8)
        f2.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(f2); row.pack(fill="x")
        ttk.Button(row, text="读取标定配置", command=self._read_config).pack(side="left")
        ttk.Button(row, text="回中位 (home)", command=self._home_arm).pack(side="left", padx=5)
        ttk.Button(row, text="停止", style="Danger.TButton", command=self._stop).pack(side="left", padx=5)

        row = ttk.Frame(f2); row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="单舵机测试  ID:").pack(side="left")
        self.var_jog_id = tk.StringVar(value="5")
        ttk.Entry(row, textvariable=self.var_jog_id, width=4).pack(side="left", padx=3)
        ttk.Label(row, text="目标计数:").pack(side="left")
        self.var_jog_pos = tk.StringVar(value="2032")
        ttk.Entry(row, textvariable=self.var_jog_pos, width=7).pack(side="left", padx=3)
        ttk.Button(row, text="执行", command=self._jog_servo).pack(side="left", padx=6)

        f3 = ttk.LabelFrame(t, text="标定配置 (machine.json)", padding=8)
        f3.pack(fill="both", expand=True, pady=(0, 8))
        self.txt_cfg = tk.Text(f3, height=12, font=("Consolas", 9))
        self.txt_cfg.pack(fill="both", expand=True)
        row = ttk.Frame(f3); row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="从板卡载入", command=self._read_config).pack(side="left")
        ttk.Button(row, text="保存到板卡", command=self._save_config).pack(side="left", padx=5)

    # ---------------- 日志 ----------------
    def log_msg(self, msg):
        def _do():
            ts = time.strftime("%H:%M:%S")
            self.log.insert("end", f"[{ts}] {msg}\n")
            self.log.see("end")
            self.root.update_idletasks()
        self.root.after(0, _do)

    def set_prog(self, pct, text=None):
        def _do():
            self.prog["value"] = max(0, min(100, pct))
            if text:
                self.lbl_prog.config(text=text)
        self.root.after(0, _do)

    def _status(self, text, color=theme.TEXT):
        self.root.after(0, lambda: self.lbl_status.config(text=text, foreground=color))

    # ---------------- 连接 ----------------
    def _auto_start(self):
        """启动时自动准备隧道: 端口空闲则自建, 已占用则复用现有隧道"""
        if getattr(self.args,'offline',False):
            self.log_msg('离线查看笔画：板卡接通后可点击「连接板卡」')
            return
        if not self.link:
            self._connect()
            return
        busy = SSHTunnel(ip=self.args.board_ip).busy_ports()
        if busy:
            self.log_msg(f"检测到端口 {busy} 已有隧道在运行 → 直接复用")
            self.root.after(0, lambda: self.var_link.set(False))
            self._connect()
        else:
            self._toggle_tunnel()

    def _toggle_tunnel(self):
        if self.board_mode:
            self.var_link.set(False);self._connect();return
        if self.var_link.get() and not self.tunnel:
            def worker():
                try:
                    self.log_msg("建立 SSH 隧道 (8765 + 8770)...")
                    self.tunnel = SSHTunnel(self.args.board_ip, self.args.board_user,
                                            self.args.board_pass,
                                            forwards=[(self.args.port, WEB_PORT),
                                                      (FOLLOW_PORT, FOLLOW_PORT)])
                    self.tunnel.start()
                    time.sleep(1.5)
                    self.log_msg("✅ SSH 隧道已建立")
                    self._connect()
                except Exception as e:
                    self.log_msg(f"❌ 隧道建立失败: {e}")
                    self._status("🔴 隧道失败", theme.ERROR)
            threading.Thread(target=worker, daemon=True).start()
        elif not self.var_link.get() and self.tunnel:
            try:
                self.tunnel.stop()
                self.log_msg("隧道已关闭")
            except Exception:
                pass
            self.tunnel = None

    def _connect(self):
        def worker():
            try:
                s = self.client.fetch_status()
                self.backend_name = s.get('ik_backend', '未知')
                self._status(f"🟢 已连接 — {s.get('version','?')}", theme.OK)
                self.root.after(0, lambda: self.lbl_info.config(
                    text=f"IK:{s.get('ik_backend','未知')}  运动:{'✓' if s.get('motion_supported') else '✗'}  "
                         f"实物调试:{'✓' if s.get('allow_real') else '✗'}  "
                         f"会话:{str(s.get('session_id',''))[:12]}"))
                self.log_msg(f"已连接板卡 — 版本 {s.get('version')}, "
                             f"后端 {self.backend_name}, 运动支持 {s.get('motion_supported')}")
                from stroke_paths import PIPELINE_VERSION
                if s.get('drawing_pipeline_version') != PIPELINE_VERSION:
                    self.log_msg('⚠ 板端仍是旧绘画程序，需安装修复版后才能规划和执行')
                if self.args.target_drawing:
                    self.root.after(0, lambda: self.var_hw.set(self.backend_name == 'PL_z20_ik_target'))
                if hasattr(self,'var_draw_x'):
                    cfg=self.client.fetch_config();paper=cfg.get('paper',{})
                    offset=paper.get('drawing_offset_mm',[0,0])
                    def placement():
                        self.var_draw_x.set('%g'%offset[0]);self.var_draw_y.set('%g'%offset[1])
                        self.var_travel_lift.set('%g'%(cfg.get('trajectory',{}).get('lift_m',.005)*1000))
                        self.var_stroke_end_pause.set('%g'%cfg.get('trajectory',{}).get('stroke_end_pause_s',0.))
                        self.var_lift_ready_pause.set('%g'%cfg.get('trajectory',{}).get('lift_ready_pause_s',.8))
                        self.lbl_drawing_alignment.config(text='当前横移 %g mm / 纵移 %g mm；%s'%(offset[0],offset[1],geometry_status(paper)))
                        self._sync_pen_height_fields(cfg)
                        self._sync_four_point_fields(cfg,load_draft=True)
                    self.root.after(0,placement)
                if not self.args.target_drawing:
                    self._check_follow_server(silent=True)
            except Exception as e:
                self._status("🔴 连接失败", theme.ERROR)
                self.log_msg(f"❌ 连接失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 绘画: 选择/云AI ----------------
    def _drawing_busy(self):
        return (self._planning_token is not None or self._execution_active or
                getattr(self, '_extraction_active', False) or getattr(self, '_cloud_active', False) or
                getattr(self, '_prediction_active', False) or getattr(self,'_calibration_active',False))

    def _clear_image_jobs(self):
        self.image_job_id = None
        self.plan_job_id = None
        self._plan_before_planning = None
        self._path_data = None
        self._path_cache_key = None
        self._path_output_dir = None
        self._image_requires_plan = True
        self.cmb_plans.set('')
        self.lbl_image_job.config(text='新图片待提取并上传')
        self.lbl_plan_hist.config(text='已切换图片，请重新规划', foreground=theme.MUTED)
        self._update_plan_controls()

    def _pick_drawing_size(self, event=None):
        if self._drawing_busy():return
        label=self.var_size_preset.get()
        if label=='自定义':return
        side=label.split('×')[0]
        self._setting_drawing_size=True
        try:self.var_w.set(side);self.var_h.set(side)
        finally:self._setting_drawing_size=False
        self._drawing_dimensions_changed()

    def _drawing_dimensions_changed(self,*args):
        if getattr(self,'_setting_drawing_size',False) or self._drawing_busy():return
        try:w,h=float(self.var_w.get()),float(self.var_h.get())
        except ValueError:return
        label=('%d×%d mm'%(w,h)) if w==h and w in (100,200,300) else '自定义'
        self.var_size_preset.set(label)
        self.plan_job_id=None
        self._plan_before_planning=None
        self._image_requires_plan=True
        self._path_cache_key=None
        self._path_data=None
        self._path_output_dir=None
        self.cmb_plans.set('')
        self.lbl_plan_hist.config(text='尺寸已变更，请重新规划（原笔画可直接缩放）',foreground=theme.MUTED)
        self._update_plan_controls()

    def _browse(self):
        if self._drawing_busy():
            self.log_msg('已有生成、提取、规划或执行任务，请等待结束'); return
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"),
                       ("所有文件", "*.*")])
        if path:
            self.original_image_path = path
            self.ent_image.delete(0, "end")
            self.ent_image.insert(0, path)
            self.cloud_image_path = None
            self._clear_image_jobs()
            self.log_msg(f"已选择图片: {path}")

    def _use_bluetooth_image(self, record):
        if self._drawing_busy():
            self.log_msg('已有生成、提取、规划或执行任务，请等待结束后选择蓝牙图片')
            return False
        try:
            verified = self.bluetooth_inbox.get(record['id'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showwarning('蓝牙图片不可用', str(exc), parent=self.root)
            return False
        path = str(verified['path'])
        self.original_image_path = path
        self.cloud_image_path = None
        self.ent_image.delete(0, 'end')
        self.ent_image.insert(0, path)
        self.var_style.set('photo')
        self._clear_image_jobs()
        self.lbl_cloud.config(text='已选择蓝牙原图；可生成线稿或直接提取笔画', foreground=theme.OK)
        self.log_msg('已选择蓝牙图片: ' + (verified['source_name'] or verified['filename']))
        return True

    def _open_cloud_directory(self):
        if self.board_mode:
            self._show_cloud_history();return
        try:
            if hasattr(os,'startfile'): os.startfile(str(self.cloud_library.directory))
            else: subprocess.Popen(['xdg-open',str(self.cloud_library.directory)])
        except OSError as e:
            messagebox.showerror('打开图片库失败', str(e), parent=self.root)

    def _save_cloud_image_as(self, path=None):
        path = Path(path or self.cloud_image_path or '')
        if not path.is_file():
            messagebox.showwarning('提示', '请先生成线稿或选择历史云端图片', parent=self.root); return
        destination = filedialog.asksaveasfilename(
            title='另存云端图片', initialfile=path.name, defaultextension=path.suffix,
            filetypes=[('原格式图片', '*' + path.suffix)], parent=self.root)
        if destination:
            try:
                self.cloud_library.export(path, destination)
                self.log_msg('云端图片已另存: ' + destination)
            except (OSError, ValueError) as e:
                messagebox.showerror('保存失败', str(e), parent=self.root)

    def _use_cloud_image(self, record, upload=False):
        if self._drawing_busy():
            self.log_msg('已有生成、提取、规划或执行任务，请等待结束'); return False
        path = Path(record['path'])
        if not path.is_file():
            messagebox.showwarning('图片不存在', '文件可能已被移走，请刷新历史列表', parent=self.root); return False
        self.cloud_image_path = str(path)
        self.original_image_path = None
        self.ent_image.delete(0, 'end')
        self.ent_image.insert(0, str(path))
        self.var_style.set('lineart')
        self._clear_image_jobs()
        self.lbl_cloud.config(text='已选择已保存线稿: ' + path.name, foreground=theme.OK)
        self.log_msg('已选择历史云端图片: ' + str(path))
        if upload:
            self._extract()
        return True

    def _show_cloud_history(self):
        """PC image history is available offline, independently of board jobs."""
        from PIL import Image, ImageOps, ImageTk
        win = tk.Toplevel(self.root)
        win.title('历史云端图片 — 选择、预览、上传')
        win.geometry('1000x630')
        win.minsize(860, 540)
        if self.board_mode:
            from scripts.touch_ui import fit_window
            fit_window(win,self.root,1000,550)
        win.transient(self.root)
        toolbar = ttk.Frame(win, padding=8); toolbar.pack(fill='x')
        ttk.Label(toolbar, text='图片库: ' + str(self.cloud_library.directory), wraplength=750).pack(side='left')
        ttk.Button(toolbar, text='关闭' if self.board_mode else '打开文件夹',
                   command=win.destroy if self.board_mode else self._open_cloud_directory).pack(side='right')
        body = ttk.Frame(win, padding=8); body.pack(fill='both', expand=True)
        left = ttk.Frame(body); left.pack(side='left', fill='both', expand=True)
        tree = ttk.Treeview(left, columns=('time', 'model', 'subject'), show='headings', selectmode='browse')
        tree.heading('time', text='生成时间'); tree.column('time', width=155, stretch=False)
        tree.heading('model', text='模型配置 / 历史导入'); tree.column('model', width=160)
        tree.heading('subject', text='主体'); tree.column('subject', width=70, stretch=False)
        scroll = ttk.Scrollbar(left, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        right = ttk.Frame(body, width=450); right.pack(side='right', fill='both', padx=(12, 0))
        preview = ttk.Label(right, text='选择左侧图片查看预览', anchor='center')
        preview.pack(fill='both', expand=True)
        details = ttk.Label(right, text='', wraplength=440, justify='left'); details.pack(fill='x', pady=6)
        records = {}
        buttons = ttk.Frame(win, padding=8); buttons.pack(fill='x')
        count = ttk.Label(buttons); count.pack(side='left')

        def selected():
            ids = tree.selection()
            return records.get(ids[0]) if ids else None

        def show_selected(_event=None):
            record = selected()
            if not record: return
            try:
                with Image.open(record['path']) as source:
                    image = ImageOps.exif_transpose(source).convert('RGBA')
                    image.thumbnail((380, 260) if self.board_mode else (440, 440))
                photo = ImageTk.PhotoImage(image, master=win)
                preview.configure(image=photo, text=''); preview.image = photo
                details.configure(text='%s\n%d × %d 像素\n来源: %s' % (
                    record['filename'], record['width'], record['height'], record['source_name'] or '旧版云端生成'))
                for button in (use_button, upload_button, save_button, predict_button): button.config(state='normal')
            except (OSError, ValueError) as e:
                preview.configure(image='', text='无法预览: ' + str(e)); preview.image = None
                for button in (use_button, upload_button, save_button, predict_button): button.config(state='disabled')

        def refresh():
            old = selected()
            old_path = old['path'] if old else None
            tree.delete(*tree.get_children()); records.clear()
            for index, record in enumerate(self.cloud_library.records()):
                key = str(index); records[key] = record
                tree.insert('', 'end', iid=key, values=(record['created_at'][:19].replace('T', ' '),
                            ('历史导入' if record['imported'] else record['profile'] or record['model'] or '未知'),
                            {'portrait': '人像', 'object': '物体'}.get(record['subject'], '未知')))
            count.config(text='共 %d 张' % len(records))
            for button in (use_button, upload_button, save_button, predict_button): button.config(state='disabled')
            if records:
                key = next((key for key, record in records.items() if record['path'] == old_path), '0')
                tree.selection_set(key); tree.focus(key); tree.see(key); show_selected()
            else:
                preview.configure(image='', text='暂无历史图片\n云端生成后会自动保存到这里')
                preview.image = None; details.config(text='')

        def use(upload=False):
            record = selected()
            if record and self._use_cloud_image(record, upload=upload): win.destroy()

        ttk.Button(buttons, text='关闭', command=win.destroy).pack(side='right', padx=3)
        upload_button = ttk.Button(buttons, text='使用并上传板卡', command=lambda: use(True))
        upload_button.pack(side='right', padx=3)
        use_button = ttk.Button(buttons, text='使用此图片', command=use)
        use_button.pack(side='right', padx=3)
        def predict_selected():
            record = selected()
            if record and self._use_cloud_image(record):
                win.destroy(); self._predict_image()
        predict_button = ttk.Button(buttons, text='预测此图片', command=predict_selected)
        predict_button.pack(side='right', padx=3)
        save_button = ttk.Button(buttons, text='另存选中图…',
                                 command=lambda: self._save_cloud_image_as(selected()['path']) if selected() else None)
        save_button.pack(side='right', padx=3)
        ttk.Button(buttons, text='刷新', command=refresh).pack(side='right', padx=3)
        tree.bind('<<TreeviewSelect>>', show_selected)
        tree.bind('<Double-1>', lambda event: use(False))
        refresh()
        return win

    def _cloud_generate(self):
        if self._drawing_busy():
            self.log_msg('已有提取、规划或执行任务，请等待结束');return
        path = self.ent_image.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("提示", "请先选择图片文件")
            return
        profile = self.var_cloud_model.get()
        subject = self.var_subject.get()
        self._cloud_active = True
        self._clear_image_jobs()

        self.btn_cloud.config(state="disabled")
        self.set_prog(10, "云端 AI 生成线稿中…")

        def worker():
            try:
                import cloud as cloud_mod
                # 载入密钥
                secrets = getattr(getattr(self,'args',None),'secrets_file',None) or ROOT / "config" / "secrets.local.json"
                if secrets.is_file():
                    try:
                        cloud_mod.load_secrets(secrets)
                        self.log_msg("已载入私用密钥")
                    except Exception as e:
                        self.log_msg(f"⚠ 密钥载入: {e}")
                cfg = cloud_mod.load_config(cloud_mod.profile_path(profile))
                if self.board_mode: cfg=dict(cfg,client_max_edge=1024)
                self.log_msg(f"☁ 调用云端模型 {cfg['model']} (主体={subject})…")
                raw = Path(path).read_bytes()
                started = time.time()
                image, info = cloud_mod.generate(raw, cfg, subject)
                record = self.cloud_library.save(image, profile=profile, model=cfg['model'],
                                                  subject=subject, source_name=Path(path).name)
                out_file = record['path']
                self.log_msg(f"✅ 线稿生成并保存完成 ({time.time()-started:.1f}s) → {out_file}")
                def publish():
                    self.cloud_image_path = str(out_file)
                    self.ent_image.delete(0, 'end')
                    self.ent_image.insert(0, str(out_file))
                    self.var_style.set('lineart')
                    self.lbl_cloud.config(text='线稿已自动保存: ' + out_file.name, foreground=theme.OK)
                    self._show_image_preview(out_file)
                self.root.after(0, publish)
                self.set_prog(30, "线稿就绪，可提取笔画")
            except Exception as e:
                self.log_msg(f"❌ AI 生成失败: {e}")
                self.set_prog(0, "AI 生成失败")
                self.root.after(0, lambda error=str(e): messagebox.showerror("云端生成或保存失败", error))
            finally:
                def finish():
                    self._cloud_active = False
                    self._update_plan_controls()
                self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _show_image_preview(self, path):
        """在日志区上方弹出预览窗口"""
        win = None
        try:
            from PIL import Image, ImageOps, ImageTk
            win = tk.Toplevel(self.root)
            win.title(f"线稿预览 — {Path(path).name}")
            win.transient(self.root)
            win.protocol('WM_DELETE_WINDOW', win.destroy)
            win.bind('<Escape>', lambda _event: win.destroy())
            image_size = (560, 560)
            if self.board_mode:
                from scripts.touch_ui import fit_window
                self.root.update_idletasks()
                width, height = fit_window(win, self.root, 680, 550)
                image_size = (min(560, width - 32), max(120, min(360, height - 160)))
            toolbar = ttk.Frame(win, padding=8)
            toolbar.pack(side='top', fill='x')
            ttk.Button(toolbar, text='关闭预览', width=12,
                       command=win.destroy).pack(side='right', ipady=6)
            ttk.Label(toolbar, text='线稿已保存，关闭后可继续绘画操作',
                      wraplength=360).pack(side='left', fill='x', expand=True, padx=(0, 8))
            actions = ttk.Frame(win, padding=8)
            actions.pack(side='bottom', fill='x')
            ttk.Button(actions, text='另存此图片…',
                       command=lambda: self._save_cloud_image_as(path)).pack(side='left', ipady=4)
            def predict_this():
                if self._use_cloud_image({'path': Path(path)}):
                    win.destroy()
                    self._predict_image()
            ttk.Button(actions, text='预测绘画效果（含顺序）',
                       command=predict_this).pack(side='right', ipady=4)
            with Image.open(path) as source:
                img = ImageOps.exif_transpose(source).copy()
                img.thumbnail(image_size)
            photo = ImageTk.PhotoImage(img, master=win)
            lbl = ttk.Label(win, image=photo)
            lbl.image = photo
            lbl.pack(padx=10, pady=10, expand=True)
            return win
        except Exception as e:
            if win is not None:
                win.destroy()
            self.log_msg(f"预览窗口失败: {e}")

    # ---------------- 绘画: 提取 + 上传 ----------------
    def _show_path_preview(self, result):
        from drawing_prediction import ordered_preview
        from scripts.drawing_preview_ui import DrawingPreviewWindow
        return DrawingPreviewWindow(self.root, ordered_preview(result), self.ent_image.get().strip())

    def _image_inputs(self):
        path = self.ent_image.get().strip()
        if not path or not Path(path).is_file(): raise ValueError('请先选择图片文件')
        w, h = float(self.var_w.get()), float(self.var_h.get())
        segs = int(self.var_segs.get())
        if not all(math.isfinite(v) and 2 <= v <= 300 for v in (w, h)):
            raise ValueError('绘制尺寸必须在 2–300 mm 之间')
        if not 1 <= segs <= 12000: raise ValueError('线段预算必须在 1–12000 之间')
        style = 'lineart' if path == self.cloud_image_path else self.var_style.get()
        key = (hashlib.sha256(Path(path).read_bytes()).hexdigest(), w, h, segs, style)
        return dict(path=path, width_mm=w, height_mm=h, max_segments=segs, style=style, key=key)

    def _prepare_local_paths(self, inputs):
        directory = getattr(self, '_path_output_dir', None)
        if (getattr(self, '_path_cache_key', None) == inputs['key'] and self._path_data is not None
                and directory and (Path(directory) / 'paths.json').is_file()):
            self.log_msg('复用已预览的笔画，上传路径与预测顺序一致')
            return self._path_data, Path(directory)
        directory = Path(tempfile.gettempdir()) / ('so101_img_' + uuid.uuid4().hex[:8])
        result = process_image_local(inputs['path'], directory, width_mm=inputs['width_mm'],
                                     height_mm=inputs['height_mm'], max_segments=inputs['max_segments'],
                                     style=inputs['style'])
        if result.get('source_sha256') != inputs['key'][0]:
            raise ValueError('图片在提取期间被修改，请重新预览')
        return result, directory

    def _cache_paths(self, result, directory, key):
        self._path_data = result
        self._path_output_dir = directory
        self._path_cache_key = key

    def _predict_image(self):
        if self._drawing_busy():
            self.log_msg('已有任务，请等待结束后查看预测'); return
        try: inputs = self._image_inputs()
        except (OSError, ValueError) as e:
            messagebox.showwarning('无法预测', str(e), parent=self.root); return
        if getattr(self, '_path_cache_key', None) != inputs['key']:
            self._clear_image_jobs()
        self._prediction_active = True
        self._update_plan_controls(); self.set_prog(10, '生成绘画效果与逐段顺序预测…')
        def worker():
            try:
                result, directory = self._prepare_local_paths(inputs)
                def publish():
                    self._cache_paths(result, directory, inputs['key'])
                    self._show_path_preview(result)
                    self.set_prog(30, '预测就绪，可检查顺序或提取上传')
                self.root.after(0, publish)
                self.log_msg('预测完成：%d 笔画 / %d 落笔线段（仅 PC 预览）' % (result['strokes'], result['segments']))
            except Exception as e:
                self.log_msg('预测失败: ' + str(e))
                self.set_prog(0, '绘画预测失败')
                self.root.after(0, lambda error=str(e): messagebox.showerror('预测失败', error, parent=self.root))
            finally:
                def finish():
                    self._prediction_active = False; self._update_plan_controls()
                self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _extract(self):
        if self._drawing_busy():
            self.log_msg('已有提取、规划或执行任务，请等待结束');return
        try: inputs = self._image_inputs()
        except (OSError, ValueError) as e:
            messagebox.showwarning('提示', str(e), parent=self.root); return
        w, h, segs, style = (inputs[k] for k in ('width_mm', 'height_mm', 'max_segments', 'style'))

        self._extraction_active = True
        self._image_requires_plan = True
        self.plan_job_id = None
        self.image_job_id = None
        self._plan_before_planning = None
        self.cmb_plans.set('')
        self._update_plan_controls()
        self.btn_extract.config(state="disabled")
        self.set_prog(40, "提取笔画…")

        def worker():
            try:
                # 1. PC 本地提取笔画
                self.log_msg(f"中心线提取 + 连续链连接 + 外到内排序 (尺寸 {w}×{h}mm, 上限 {segs} 段)…")
                result, tmp_dir = self._prepare_local_paths(inputs)
                self.log_msg(f"✅ 提取完成 — {result['strokes']} 笔画, {result['segments']} 线段")
                self.log_msg('落笔路径 %.1f mm / 图边重复访问 %d / 算法 %s'%(result['draw_length_mm'],result['extraction']['graph']['edge_revisits'],result['algorithm_version']))
                def publish():
                    self._cache_paths(result, tmp_dir, inputs['key'])
                    self._show_path_preview(result)
                self.root.after(0, publish)

                # 2. 直接把 PC 算好的笔画登记到板卡 (板卡无 ezdxf/svgpathtools, 不能自己转图)
                self.log_msg("登记笔画到板卡…")
                if not self.client.token:
                    self.client.fetch_status()
                paths_dict = dict(result)
                paths_dict["style"] = style
                up = self.client.strokes(paths_dict)
                self.image_job_id = up.get("id")
                self.log_msg(f"Image Job: {self.image_job_id}")

                # 3. 等板卡登记完成
                job_info = None
                for _ in range(60):
                    jobs = self.client.get_jobs()
                    job_info = next((j for j in jobs.get("jobs", [])
                                     if j["id"] == self.image_job_id), None)
                    if job_info and job_info["status"] in ("DONE", "FAILED"):
                        break
                    time.sleep(0.3)
                st = job_info["status"] if job_info else "?"
                if st != "DONE":
                    raise RuntimeError(f"板卡登记失败: {job_info.get('detail') if job_info else '超时'}")
                self.log_msg(f"✅ 板卡已登记笔画 ({st})")

                # 4. 把 paths.svg / 预览图也推过去, 方便网页端查看
                self._push_paths(self.image_job_id, tmp_dir)

                self.root.after(0, lambda: self.lbl_image_job.config(
                    text=f"Image Job: {str(self.image_job_id)[:12]}…"))
                self.set_prog(60, "笔画已就绪，可规划轨迹")
            except Exception as e:
                self.log_msg(f"❌ 提取失败: {e}")
                self.set_prog(0, "提取失败")
            finally:
                def finish():
                    self._extraction_active = False
                    self.btn_extract.config(state='normal')
                    self._update_plan_controls()
                self.root.after(0,finish)
        threading.Thread(target=worker, daemon=True).start()

    def _push_paths(self, job_id, tmp_dir):
        """把本地 paths.json 等推到板卡 job 目录"""
        if self.board_mode:
            # /api/strokes already persists canonical paths.json. Optional
            # previews remain locally accessible without privileged file copies.
            self.log_msg('笔画已在本机登记；预览目录: '+str(tmp_dir))
            return
        try:
            status = self.client.fetch_status()
            session_id = status.get("session_id", "")
            # job 目录可能在多个候选根目录下, 逐个尝试
            roots = [self.args.data_dir, "/home/xilinx/SO101_FPGA_ArmSystem/logs",
                     "/home/xilinx/so101_team/logs", "/home/xilinx/SO101_IK_PYNQ_Integrated/app/logs"]
            job_dir = None
            for r in roots:
                out, _, code = self.ssh.run(f"ls -d {r}/{session_id}/job_{job_id} 2>/dev/null")
                if out.strip():
                    job_dir = out.strip().splitlines()[0]
                    break
            if not job_dir:
                job_dir = f"{roots[0]}/{session_id}/job_{job_id}"
                raise RuntimeError("未找到当前服务的 job 目录；笔画已通过 HTTP 登记")

            # The HTTP registration owns paths.json; push optional previews only.
            files = ["paths.svg", "input.png", "lineart.png"]
            for name in files:
                local = Path(tmp_dir) / name
                if not local.is_file():
                    continue
                remote_tmp = f"/tmp/{name.replace('.', '_')}_{job_id}"
                self.ssh.put(local, remote_tmp)
                self.ssh.sudo(f"cp {remote_tmp} {job_dir}/{name}")
            self.log_msg(f"✅ 预览文件已推到 {job_dir}")
        except Exception as e:
            self.log_msg(f"⚠ 推送预览附件失败: {e}")

    # ---------------- 绘画: 规划 ----------------
    def _update_plan_controls(self):
        busy = self._drawing_busy()
        calibrated = getattr(self,'_four_point_ready',True)
        for name in ("btn_plan", "btn_auto", "btn_make_test", "btn_home"):
            getattr(self, name).config(state="disabled" if busy or not calibrated else "normal")
        for name in ("btn_exec_arm", "btn_exec_history", "btn_preview"):
            getattr(self, name).config(
                state="disabled" if busy or not self.plan_job_id or (name!='btn_preview' and not calibrated) else "normal")
        self.cmb_plans.config(state="disabled" if busy else "readonly")
        if hasattr(self,'btn_extract'):
            self.btn_extract.config(state='disabled' if busy else 'normal')
        for name in ('btn_cloud', 'btn_cloud_history', 'btn_predict'):
            if hasattr(self, name): getattr(self, name).config(state='disabled' if busy else 'normal')
        for name in ('btn_pen_axis','btn_pen_contact','btn_drawing_placement','btn_geometry_A','btn_geometry_B','btn_geometry_C','btn_geometry_D',
                     'btn_geometry_apply','btn_geometry_reset','chk_geometry_force'):
            if hasattr(self,name):getattr(self,name).config(state='disabled' if busy else 'normal')
        for name in ('btn_pen_axis','btn_pen_contact'):
            if hasattr(self,name):getattr(self,name).config(state='disabled' if busy or not calibrated else 'normal')
        if hasattr(self,'btn_geometry_apply'):
            complete=set(getattr(self,'_geometry_captures',{}))==set(GEOMETRY_POINTS)
            self.btn_geometry_apply.config(state='disabled' if busy or not complete else 'normal')
        if hasattr(self,'btn_feedback_preview'):
            self.btn_feedback_preview.config(state='disabled' if busy or not getattr(self,'_last_execution_job',None) else 'normal')
        for name in ('ent_drawing_w','ent_drawing_h','cmb_drawing_size'):
            if hasattr(self,name):
                getattr(self,name).config(state='disabled' if busy else ('readonly' if name=='cmb_drawing_size' else 'normal'))

    def _open_kinematic_calibration(self):
        from scripts.kinematic_calibration_ui import open_calibration
        open_calibration(self)

    def _record_pen_calibration(self, kind):
        if self._drawing_busy():
            self.log_msg('请在当前任务完成后记录笔尖姿态'); return
        self._calibration_active = True
        self._update_plan_controls()
        port = self.var_port.get().strip()
        source = self.var_calibration_source.get()
        self.log_msg('读取当前姿态并记录%s…' % ('垂直笔轴' if kind=='axis' else '轻触纸面高度'))
        def worker():
            ok = False
            try:
                self.client.fetch_status()
                if source != '板端':
                    from pc_pen_calibration import read_pose
                    from pen_calibration import calibrate_pen
                    machine=self.client.fetch_config()
                    captured=read_pose(source,machine)
                    updated,detail=calibrate_pen(machine,captured['counts'],kind)
                    self.client.save_config(updated)
                    cache=Path.home()/'Pictures'/'SO101'/'Calibration'
                    cache.mkdir(parents=True,exist_ok=True)
                    (cache/('pen_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')).write_text(
                        json.dumps(dict(captured=captured,calibration=detail,machine=updated),ensure_ascii=False,indent=2),encoding='utf-8')
                else:
                    job = self.client.calibrate_pen(kind,port=port)
                    info = self._wait_job(job['id'],timeout=30)
                    if not info or info['status'] != 'DONE':
                        raise RuntimeError(info.get('detail','读取超时') if info else '读取超时')
                    detail = info.get('result') or {}
                self.log_msg('已记录%s：%s' % ('垂直笔轴（绘画与初始位共用）' if kind=='axis' else '接触高度',
                    detail.get('tool_axis_local') if kind=='axis' else '当前接触位置，抬高微调归零'))
                ok = True
            except Exception as exc:
                self.log_msg('标定记录失败：%s' % exc)
            finally:
                def finish():
                    self._calibration_active = False
                    if ok:
                        self.plan_job_id = None
                        self._image_requires_plan = True
                        if kind=='contact_height':self.var_pen_lift.set('0')
                        self._refresh_plans()
                    self._update_plan_controls()
                    if ok and self.image_job_id:self._plan()
                self.root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()

    def _invalidate_geometry_plan(self):
        self.plan_job_id=None;self._plan_before_planning=None;self._image_requires_plan=True
        self.cmb_plans.set('');self.lbl_plan_hist.config(text='位置/几何已更新，请重新规划',foreground=theme.MUTED)
        self._update_plan_controls()

    def _sync_pen_height_fields(self, machine):
        paper=machine.get('paper') or {}
        mm=float(paper.get('draw_height_offset_m',0.) or 0.)*1000
        if hasattr(self,'var_pen_lift'):
            self.var_pen_lift.set('%g'%mm)
        if hasattr(self,'lbl_pen_lift'):
            contact=(paper.get('xy_calibration') or {}).get('contact_plane_enabled')
            self.lbl_pen_lift.config(text='当前 %g mm%s'%(mm,'（相对实测笔尖接触平面）' if contact else ''),foreground=theme.MUTED)

    def _show_geometry_section(self):
        notebook=self.tab_draw.master
        notebook.select(self.tab_draw)
        self.root.update_idletasks()
        canvas=self._draw_canvas
        bounds=canvas.bbox('all')
        if bounds and bounds[3]>0:
            y=canvas.canvasy(self._geometry_header.winfo_rooty()-canvas.winfo_rooty())
            canvas.yview_moveto(max(0.,y-12)/bounds[3])

    def _sync_four_point_fields(self, machine, load_draft=False):
        from four_point_calibration import ready
        from drawing_geometry import calibration_signature
        paper=machine.get('paper') or {}
        self._four_point_ready=ready(paper)
        self.var_draw_x.set('%g'%paper.get('drawing_offset_mm',[0,0])[0])
        self.var_draw_y.set('%g'%paper.get('drawing_offset_mm',[0,0])[1])
        self.var_geometry_span.set('%g'%paper.get('four_point_side_mm',200.))
        if load_draft and not self._four_point_ready and not self._geometry_captures:
            try:
                draft=json.loads(self._geometry_draft_path.read_text(encoding='utf-8'))
                if draft.get('signature')==calibration_signature(machine):
                    self._geometry_captures={k:v for k,v in draft.get('captures',{}).items() if k in GEOMETRY_POINTS}
                    self.var_geometry_span.set('%g'%draft['side_mm'])
            except (OSError,ValueError,KeyError,TypeError):pass
        self._show_geometry_captures()
        self._update_plan_controls()
        if load_draft and not self._four_point_ready:
            self.root.after(100,self._show_geometry_section)

    def _show_geometry_captures(self):
        captured=[k+' '+GEOMETRY_LABELS[k] for k in GEOMETRY_POINTS if k in self._geometry_captures]
        if not captured and getattr(self,'_four_point_ready',False):
            self.lbl_geometry_points.config(text='已加载保存的四点标定，无需重新采点，可直接规划；更换安装或纸面后再重新采集。')
            return
        pending=[k+' '+GEOMETRY_LABELS[k] for k in GEOMETRY_POINTS if k not in self._geometry_captures]
        text=('已记录：'+', '.join(captured)+'；' if captured else '')
        text+=('待记录：'+', '.join(pending)) if pending else '四点已齐，可应用四点校正'
        self.lbl_geometry_points.config(text=text)

    def _save_geometry_draft(self, machine, side):
        from drawing_geometry import calibration_signature
        path=self._geometry_draft_path;path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.tmp')
        temporary.write_text(json.dumps(dict(schema='so101-four-point-draft-v1',
            signature=calibration_signature(machine),side_mm=side,captures=self._geometry_captures),
            ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)

    def _update_drawing_geometry(self, updater, message, replan=True, clear_captures=False):
        if self._drawing_busy():self.log_msg('请在当前任务完成后更新绘画位置/几何');return
        self._calibration_active=True;self._update_plan_controls()
        def worker():
            ok=False
            try:
                status=self.client.fetch_status()
                if not status.get('four_point_calibration_supported'):raise RuntimeError('请先更新板端四点标定软件')
                before=self.client.fetch_config();updated=updater(copy.deepcopy(before))
                self.client.save_config(updated);ok=True
                cache=getattr(self,'_calibration_cache',Path.home()/'Pictures/SO101/Calibration')
                cache.mkdir(parents=True,exist_ok=True)
                try:
                    (cache/('geometry_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')).write_text(
                        json.dumps(dict(before=before,after=updated),ensure_ascii=False,indent=2),encoding='utf-8')
                    refreshed=refresh_existing_calibration_snapshots(before,updated,
                        board_cache=cache if self.board_mode else None)
                    if refreshed:self.log_msg('已同步这台机械臂的 PC 默认标定备份；旧备份另存')
                except OSError as exc:self.log_msg('配置已保存，PC 备份写入失败：'+str(exc))
                paper=updated['paper'];offset=paper.get('drawing_offset_mm',[0,0])
                def sync_fields():
                    if clear_captures:
                        self._geometry_captures={}
                        try:self._save_geometry_draft(updated,paper.get('four_point_side_mm',200.))
                        except OSError as exc:self.log_msg('旧采点草稿清理失败：'+str(exc))
                    self.lbl_drawing_alignment.config(text='横移 %g mm / 纵移 %g mm；%s'%(offset[0],offset[1],geometry_status(paper)))
                    self._sync_pen_height_fields(updated)
                    self._sync_four_point_fields(updated)
                self.root.after(0,sync_fields)
                self.log_msg(message+'；已保存。'+geometry_status(paper))
            except Exception as exc:self.log_msg('位置/几何更新失败：'+str(exc))
            finally:
                def finish():
                    self._calibration_active=False
                    if ok:self._invalidate_geometry_plan()
                    self._update_plan_controls()
                    if ok and replan and self._four_point_ready and self.image_job_id:self._plan()
                self.root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()

    def _apply_drawing_placement(self):
        try:
            offset=[float(self.var_draw_x.get()),float(self.var_draw_y.get())]
            if not all(math.isfinite(v) for v in offset):raise ValueError()
            lift=float(self.var_travel_lift.get()) if hasattr(self,'var_travel_lift') else None
            if lift is not None and (not math.isfinite(lift) or lift<=0):raise ValueError()
            pauses={}
            for attr,key in (('var_stroke_end_pause','stroke_end_pause_s'),('var_lift_ready_pause','lift_ready_pause_s')):
                if hasattr(self,attr):
                    value=float(getattr(self,attr).get())
                    if not math.isfinite(value) or not 0.<=value<=3.:raise ValueError()
                    pauses[key]=value
        except ValueError:messagebox.showwarning('绘画位置','请输入有限的毫米偏移值和正的转移抬笔高度');return
        def update(machine):
            machine.setdefault('paper',{})['drawing_offset_mm']=offset
            if lift is not None:machine.setdefault('trajectory',{})['lift_m']=lift/1000
            machine.setdefault('trajectory',{}).update(pauses)
            overrides=machine['trajectory'].setdefault('sugar_fast_overrides',{})
            if lift is not None:overrides['lift_m']=lift/1000
            overrides.update(pauses)
            return machine
        self._update_drawing_geometry(update,'绘画位置已设置：横移 %g mm / 纵移 %g mm'%tuple(offset))

    def _capture_geometry_point(self, key):
        if self._drawing_busy():return
        try:
            side=float(self.var_geometry_span.get())
            if not math.isfinite(side) or side<=0 or key not in GEOMETRY_POINTS:raise ValueError()
        except ValueError:messagebox.showwarning('四点校正','请输入正方形的实际边长（毫米）');return
        self._calibration_active=True;self._update_plan_controls()
        source=self.var_calibration_source.get();port=self.var_port.get().strip()
        def worker():
            try:
                from drawing_geometry import calibration_signature
                machine=self.client.fetch_config()
                if any(c.get('signature')!=calibration_signature(machine) or c.get('side_mm')!=side
                       for c in self._geometry_captures.values()):
                    self._geometry_captures={}
                    self.log_msg('模型或实测边长已变化，本轮四点从头记录')
                if source=='板端':
                    job=self.client.read_pen_pose(port);done=self._wait_job(job['id'],timeout=30)
                    if not done or done['status']!='DONE':raise RuntimeError((done or {}).get('detail','读取超时'))
                    counts=done['result']['counts']
                else:
                    from pc_pen_calibration import read_pose
                    counts=read_pose(source,machine)['counts']
                self._geometry_captures[key]=dict(counts=counts,signature=calibration_signature(machine),side_mm=side)
                self._save_geometry_draft(machine,side)
                self.root.after(0,self._show_geometry_captures)
                self.log_msg('实物几何点 '+key+' '+GEOMETRY_LABELS[key]+' 已记录并保存草稿（只读位置）')
            except Exception as exc:self.log_msg('点位读取失败：'+str(exc))
            finally:
                def finish():self._calibration_active=False;self._update_plan_controls()
                self.root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()

    def _apply_geometry_calibration(self):
        try:distance=float(self.var_geometry_span.get())
        except ValueError:messagebox.showwarning('四点校正','请输入正方形实际边长（毫米）');return
        captures=dict(self._geometry_captures)
        def update(machine):
            from four_point_calibration import calibrate_four_points
            updated = calibrate_four_points(machine,captures,distance,allow_large_residual=False)[0]
            if updated.get('kinematic_calibration'):
                from kinematic_calibration import assert_sugar_calibration
                assert_sugar_calibration(updated, require_four_point=True)
                updated.setdefault('checks',{})['kinematics'] = True
            return updated
        self._update_drawing_geometry(update,'四点纸面校正已应用，位置偏移与高度微调已归零',replan=False)

    def _reset_geometry_calibration(self):
        try:side=float(self.var_geometry_span.get())
        except ValueError:messagebox.showwarning('四点校正','请输入正方形实际边长（毫米）');return
        def update(machine):
            from four_point_calibration import begin_calibration
            return begin_calibration(machine,side)
        self._update_drawing_geometry(update,'已清除四点，请重新记录 A、B、C、D',replan=False,clear_captures=True)

    def _begin_planning(self):
        if not getattr(self,'_four_point_ready',True):
            self.log_msg('请先记录并应用 A、B、C、D 四点标定');return None
        if self._drawing_busy():
            self.log_msg("已有规划或执行任务进行中，请等待该任务结束")
            return None
        token = object()
        self._planning_token = token
        self._active_plan_job_id = None
        self._plan_before_planning = self.plan_job_id
        # A submitted request owns its result. A previous saved plan is never
        # executable while this request is still pending.
        self.plan_job_id = None
        self.cmb_plans.set("")
        self.lbl_plan_hist.config(text="正在生成新规划，历史选择暂停", foreground=theme.MUTED)
        self._update_plan_controls()
        return token

    def _finish_planning(self, token, job_id, ok, callback=None):
        """Publish one worker's result on the Tk thread, before any callback."""
        if self._planning_token is not token:
            return
        self.plan_job_id = job_id if ok else self._plan_before_planning
        if ok: self._image_requires_plan = False
        self._planning_token = None
        self._active_plan_job_id = None
        self._plan_before_planning = None
        self._update_plan_controls()
        self._select_current_plan()
        if ok:
            self._refresh_plans()
        if callback:
            callback(ok)

    def _plan(self, callback=None):
        if not self.image_job_id:
            messagebox.showwarning("提示", "请先提取笔画")
            return
        use_hw = self.var_hw.get()
        label=self.var_motion_mode.get() if getattr(self,'var_motion_mode',None) is not None else '平缓'
        motion_mode=motion_mode_from_label(label)
        image_job_id = self.image_job_id
        port = self.var_port.get().strip()
        calibration_source=self.var_calibration_source.get() if hasattr(self,'var_calibration_source') else '板端'
        drawing_size=None
        if hasattr(self,'var_w') and hasattr(self,'var_h'):
            try:
                drawing_size=[float(self.var_w.get()),float(self.var_h.get())]
                if not all(math.isfinite(v) and 2<=v<=300 for v in drawing_size):raise ValueError()
            except ValueError:
                messagebox.showwarning('绘画尺寸','绘制尺寸必须在 2–300 mm 之间');return
        token = self._begin_planning()
        if token is None:
            return
        self.set_prog(65, "规划轨迹中…")
        self.log_msg(f"规划轨迹 — 当前后端 {self.backend_name}…")

        def worker():
            ok = False
            plan_job_id = None
            try:
                options = dict(use_hw=use_hw,port=port)
                if drawing_size is not None:
                    options['drawing_size_mm']=drawing_size
                    self.log_msg('本次绘画尺寸：%g×%g mm'%tuple(drawing_size))
                if calibration_source != '板端':
                    from pc_pen_calibration import read_pose
                    captured=read_pose(calibration_source,self.client.fetch_config())
                    options.update(start_counts=captured['counts'],counts_source='PC_encoder_'+calibration_source)
                if getattr(self,'var_motion_mode',None) is not None:
                    options['motion_mode']=motion_mode
                res = self.client.plan(image_job_id, **options)
                plan_job_id = res.get("id")
                if not plan_job_id:
                    raise RuntimeError("板卡未返回规划 Job ID")
                self._active_plan_job_id = plan_job_id
                self.log_msg(f"规划 Job: {plan_job_id}, 等待完成…")

                status, job_info = "RUNNING", None
                started = time.monotonic()
                deadline = started + 900
                next_log = started + 15
                disconnected_at = None
                missing = 0
                while time.monotonic() < deadline:
                    requested_at = time.monotonic()
                    try:
                        jobs = self.client.get_jobs()
                    except BoardConnectionError:
                        if disconnected_at is None:
                            disconnected_at = requested_at
                            self.log_msg("状态连接暂时中断，正在重新查询本次规划；不会重复提交…")
                        if time.monotonic() - disconnected_at >= 30:
                            raise BoardConnectionError("状态连接持续中断，请刷新历史规划确认本次结果；未重新提交规划")
                        time.sleep(1.0)
                        continue
                    if disconnected_at is not None:
                        self.log_msg("状态连接已恢复，继续查询本次规划")
                        disconnected_at = None
                    job_info = next((j for j in jobs.get("jobs", [])
                                     if j["id"] == plan_job_id), None)
                    missing = missing + 1 if job_info is None else 0
                    if missing >= 3:
                        raise RuntimeError("板端已找不到本次规划，请刷新历史规划检查服务是否重启；未重新提交规划")
                    if (job_info and job_info["status"] in ("DONE", "FAILED")
                            and jobs.get("active") != plan_job_id):
                        status = job_info["status"]
                        break
                    if time.monotonic() >= next_log:
                        self.log_msg(f"  规划中… {time.monotonic() - started:.0f}s · Job {plan_job_id[:8]}")
                        next_log = time.monotonic() + 15
                    time.sleep(1.0)

                if status == "DONE":
                    r = job_info.get("result", {})
                    m = r.get("metrics", {})
                    self.log_msg(f"✅ 规划完成 — {r.get('status','?')} · Job {plan_job_id[:8]}")
                    self.log_msg(f"   目标点 {m.get('completed_targets','?')} / "
                                 f"命令 {m.get('commands','?')} / "
                                 f"预计运动时长 {m.get('duration_s','?')}s")
                    self._log_plan_timing(plan_job_id, m)
                    self.set_prog(85, "轨迹已就绪")
                    ok = True
                else:
                    self.log_msg(f"❌ 规划失败: {job_info.get('detail','超时') if job_info else '超时'}")
                    self.set_prog(0, "规划失败")
            except Exception as e:
                self.log_msg(f"❌ 规划异常: {e}")
                self.set_prog(0, "规划异常")
            finally:
                self.root.after(0, lambda: self._finish_planning(token, plan_job_id, ok, callback))
        threading.Thread(target=worker, daemon=True).start()

    def _log_plan_timing(self, job_id, metrics):
        if metrics.get('motion_algorithm_version') == 'motion-smooth-v1':
            self.log_msg('   %s / jerk 峰值 %.3f rad/s³ / 必要停点 %s / 可避免停点 %s' %
                ({'sugar_fast':'糖画连续','classic_fast':'旧版加速','speed_priority':'速度优先','smooth_fast':'平滑加速'}.get(metrics.get('motion_mode'),'平缓'),
                 metrics.get('peak_jerk_rad_s3',0),metrics.get('hard_stop_knots','?'),metrics.get('avoidable_stop_knots','?')))
        timing = dict(metrics.get('timing') or {})
        try:
            timing.update(self.client.get_job_file(job_id, 'timing.json'))
        except Exception:
            pass
        total, ik = timing.get('job_ready_s', timing.get('build_total_s')), timing.get('ik_s')
        if isinstance(total, (int, float)) and isinstance(ik, (int, float)):
            self.log_msg("   规划耗时 %.3fs / IK %.3fs / 后端 %s" %
                         (total, ik, metrics.get('ik_backend', self.backend_name)))
            self.log_msg('   30 秒目标：%s / 规划引擎 %s'%
                         ('达标' if total<=30 else '未达标',metrics.get('planning_engine_version','旧版')))
        stages = [('interpolation_s', '插值'), ('quantization_s', '量化检查'),
                  ('drawing_preview_s', '预览'), ('plan_save_s', '计划保存'),
                  ('saved_plan_s', '历史保存')]
        parts = ['%s %.3fs' % (label, timing[key]) for key, label in stages
                 if isinstance(timing.get(key), (int, float))]
        if parts:
            self.log_msg('   ' + ' / '.join(parts))
        if metrics.get('history_saved') is False:
            self.log_msg('   历史保存失败：本次计划仅在当前服务中可用，重启后需重新规划。')
        geometry=metrics.get('max_draw_path_error_m')
        if isinstance(geometry,(int,float)):
            self.log_msg('   DRAW 模型路径偏差 %.3f mm / FK 检查 %s'%(geometry*1000,metrics.get('geometry_samples','?')))
        pl=metrics.get('pl_job') or {}
        if 'wait_s' in pl:
            self.log_msg('   本次 PL 写入 %.3fs / 核等待 %.3fs / 读取 %.3fs / 结果校验 %.3fs'%
                         tuple(pl.get(k,0.) for k in ('write_s','wait_s','read_s','validate_s')))
        source=metrics.get('path_source') or {}
        if source:
            self.log_msg('   笔画来源 %s / %s / 摘要 %s'%(source.get('engine'),source.get('algorithm_version') or '矢量',str(source.get('path_sha256',''))[:12]))

    # ---------------- 绘画: 执行 ----------------
    # ---------------- 笔尖抬高量 ----------------
    def _read_pen_lift(self):
        """读取板卡上当前的笔尖抬高量"""
        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                cfg = self.client.fetch_config() or {}
                v = float((cfg.get("paper") or {}).get("draw_height_offset_m", 0.0) or 0.0)
                mm = v * 1000.0
                def apply():
                    self.var_pen_lift.set("%.1f" % mm)
                    self.lbl_pen_lift.config(text="当前 %.1f mm" % mm, foreground=theme.MUTED)
                self.root.after(0, apply)
            except Exception as e:
                self.root.after(0, lambda: self.lbl_pen_lift.config(
                    text=f"读取失败: {str(e)[:70]}", foreground=theme.ERROR))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_pen_lift(self):
        """把笔尖抬高量写入板卡 machine.json (paper.draw_height_offset_m)"""
        try:
            mm = float(self.var_pen_lift.get())
        except Exception:
            messagebox.showwarning("提示", "抬高量必须是数字（毫米）")
            return
        if abs(mm) > 200:
            messagebox.showwarning("提示", "抬高量超出合理范围（±200 mm）")
            return
        if not messagebox.askokcancel(
                "应用笔尖抬高量",
                "把笔尖抬高量设为 %.1f mm（沿纸面法向）。\n\n"
                "· 正值 = 抬离纸面；负值 = 压向纸面\n"
                "· 0 = 回到原始标定纸面\n"
                "· 会写入板卡 machine.json，标定指纹随之改变\n"
                "· 之后必须【重新规划】，旧规划会被拒绝执行\n\n继续吗？" % mm):
            return

        def worker():
            try:
                cfg = self.client.fetch_config() or {}
                cfg.setdefault("paper", {})["draw_height_offset_m"] = mm / 1000.0
                self.client.save_config(cfg)
                self.log_msg(f"✅ 笔尖抬高量 = {mm:.1f} mm（已写入板卡标定），请重新规划")
                self.root.after(0, lambda: self.lbl_pen_lift.config(
                    text="已设 %.1f mm —— 需重新规划" % mm, foreground=theme.OK))
            except Exception as e:
                self.log_msg(f"❌ 设置抬高量失败: {str(e)[:120]}")
                self.root.after(0, lambda: self.lbl_pen_lift.config(
                    text=f"设置失败: {str(e)[:60]}", foreground=theme.ERROR))
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 历史规划 (持久化) ----------------
    def _read_home_height(self):
        """读取板卡上当前的爪子离地高度 (paper.home_height_offset_m)"""
        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                cfg = self.client.fetch_config() or {}
                v = float((cfg.get("paper") or {}).get("home_height_offset_m", 0.0) or 0.0)
                mm = v * 1000.0
                def apply():
                    self.var_home_lift.set("%.1f" % mm)
                    self.lbl_home_lift.config(text="当前 %.1f mm" % mm, foreground=theme.MUTED)
                self.root.after(0, apply)
            except Exception as e:
                self.root.after(0, lambda: self.lbl_home_lift.config(
                    text=f"读取失败: {str(e)[:70]}", foreground=theme.ERROR))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_home_height(self):
        """把爪子离地高度写入板卡 machine.json (paper.home_height_offset_m)"""
        try:
            mm = float(self.var_home_lift.get())
        except Exception:
            messagebox.showwarning("提示", "爪子离地高度必须是数字（毫米）")
            return
        if abs(mm) > 200:
            messagebox.showwarning("提示", "高度超出合理范围（0–200 mm）")
            return
        if not messagebox.askokcancel(
                "应用爪子离地高度",
                "把爪子离地高度设为 %.1f mm（沿纸面法向抬高）。\n\n"
                "· 正值 = 归位后爪子抬离纸面更高\n"
                "· 0 = 回到原始标定高度\n"
                "· 会写入板卡 machine.json，标定指纹随之改变\n"
                "· 之后【归位】会停在新的高度，规划不受影响\n\n继续吗？" % mm):
            return

        def worker():
            try:
                cfg = self.client.fetch_config() or {}
                cfg.setdefault("paper", {})["home_height_offset_m"] = mm / 1000.0
                self.client.save_config(cfg)
                self.log_msg(f"✅ 爪子离地高度 = {mm:.1f} mm（已写入板卡标定），下次归位生效")
                self.root.after(0, lambda: self.lbl_home_lift.config(
                    text="已设 %.1f mm" % mm, foreground=theme.OK))
            except Exception as e:
                self.log_msg(f"❌ 设置爪子离地高度失败: {str(e)[:120]}")
                self.root.after(0, lambda: self.lbl_home_lift.config(
                    text=f"设置失败: {str(e)[:60]}", foreground=theme.ERROR))
        threading.Thread(target=worker, daemon=True).start()

    def _wait_job(self, job_id, timeout_s=300):
        """阻塞等待板卡任务结束, 返回最终 job 字典 (供后台线程调用)"""
        deadline = time.time() + timeout_s
        info = None
        while time.time() < deadline:
            try:
                jobs = self.client.get_jobs()
                info = next((j for j in jobs.get("jobs", []) if j["id"] == job_id), None)
                if info and info.get("status") in ("DONE", "FAILED"):
                    return info
            except Exception:
                pass
            time.sleep(1.0)
        return info

    def _make_test_plan(self):
        """一键生成"画一条直线"的实物模式测试规划, 自动存入历史规划。

        真实模式的规划必须基于机械臂当前姿态 (q0 取自舵机读数), 所以不能用
        预先做好的固定文件; 这里现场生成一份, 约 5 秒。
        """
        try:
            size = float(self.var_test_mm.get())
        except Exception:
            size = 40.0
        if not messagebox.askokcancel(
                "生成直线测试规划",
                "将生成一条 %.0f×%.0f mm 直线的【实物模式】规划。\n\n"
                "· 会打开串口读取机械臂当前姿态（只读，不动机械臂）\n"
                "· 机械臂必须已在「绘画起始位」，否则规划会 STAGNATION\n"
                "· 完成后出现在下面的「历史规划」列表里\n\n继续吗？" % (size, size)):
            return
        port = self.var_port.get().strip() or "/dev/ttyACM0"
        token = self._begin_planning()
        if token is None:
            return
        self.log_msg(f"📏 生成直线测试规划 ({size:.0f}×{size:.0f} mm, 实物模式)…")
        test_motion_mode = (motion_mode_from_label(self.var_motion_mode.get())
                            if getattr(self,'var_motion_mode',None) is not None else None)

        def worker():
            ok = False
            plan_id = None
            try:
                self.set_prog(5, "生成直线笔画…")
                pj = (self.client.preset("line", size, size) or {}).get("id")
                self.log_msg(f"  预设笔画 job={str(pj)[:12]}")
                info = self._wait_job(pj, 90)
                if not info or info.get("status") != "DONE":
                    raise RuntimeError("预设生成失败: %s" % str((info or {}).get("detail"))[:80])

                self.set_prog(30, "实物模式规划中…")
                options=dict(mode='real',port=port)
                if test_motion_mode is not None:
                    options['motion_mode']=test_motion_mode
                res = self.client.plan(pj, **options)
                plan_id = (res or {}).get("id")
                if not plan_id:
                    raise RuntimeError("板卡未返回规划 Job ID")
                self._active_plan_job_id = plan_id
                self.log_msg(f"  规划 job={str(plan_id)[:12]}")
                info = self._wait_job(plan_id, 300)
                detail = str((info or {}).get("detail") or "")

                if not info or info.get("status") != "DONE":
                    if "STAGNATION" in detail:
                        self.log_msg("❌ 规划停滞(STAGNATION): 机械臂不在绘画起始位")
                        self.root.after(0, lambda: messagebox.showerror(
                            "需要先回起始位",
                            "规划停滞 (STAGNATION) —— 机械臂不在绘画起始位。\n\n"
                            "请先点【🏠 回绘画起始位】，等它到位后再重新生成测试规划。"))
                    else:
                        self.log_msg(f"❌ 规划失败: {detail[:90]}")
                    self.set_prog(0, "规划失败")
                    return

                m = (info.get("result") or {}).get("metrics") or {}
                self.log_msg("✅ 测试规划完成: %s/%s 目标, %s 指令, %.0fs, 后端 %s" % (
                    m.get("completed_targets"), m.get("total_targets"),
                    m.get("commands"), m.get("duration_s") or 0, m.get("ik_backend")))
                self._log_plan_timing(plan_id, m)
                self.set_prog(100, "测试规划已就绪")
                ok = True
            except Exception as e:
                self.log_msg(f"❌ 生成测试规划失败: {str(e)[:140]}")
                self.set_prog(0, "失败")
            finally:
                self.root.after(0, lambda: self._finish_planning(token, plan_id, ok))
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_plans(self):
        """从板卡拉取历史规划列表 (保存在板卡 saved_plans/, 服务重启不丢)"""
        self._history_refresh_id += 1
        refresh_id = self._history_refresh_id
        self.lbl_plan_hist.config(text="正在读取历史规划…", foreground=theme.MUTED)

        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                data = self.client.plans()
                plans = data.get("plans", []) or []
                labels = []
                for p in plans:
                    ts = str(p.get("saved_utc") or "")[:19].replace("T", " ")
                    ok = p.get("matches_current_calibration")
                    dur = p.get("duration_s") or 0
                    mode = p.get("mode")
                    mode_tag = {"real": "实物", "demo": "模拟"}.get(mode, str(mode))
                    labels.append("%s  [%s]  %5s指令  %4.0fs  %s  [%s]" % (
                        ts, mode_tag, p.get("commands") or 0, dur,
                        "需重新规划" if p.get('needs_replan') else ("标定匹配" if ok else "⚠标定已变"),
                        str(p.get("id"))[:8]))

                def apply():
                    if refresh_id == self._history_refresh_id:
                        self._apply_plan_history(plans, labels)
                self.root.after(0, apply)
            except Exception as e:
                error = str(e)[:100]
                def fail():
                    if refresh_id == self._history_refresh_id:
                        self.lbl_plan_hist.config(text=f"读取失败: {error}", foreground=theme.ERROR)
                self.root.after(0, fail)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_plan_history(self, plans, labels):
        self._plan_history = plans
        self.cmb_plans["values"] = labels
        if (self._planning_token is not None or getattr(self,'_extraction_active',False)
                or getattr(self,'_cloud_active',False) or getattr(self,'_prediction_active',False)):
            self.cmb_plans.set("")
            self.lbl_plan_hist.config(text="正在生成新规划，历史选择暂停", foreground=theme.MUTED)
            return
        if self.plan_job_id:
            # A delayed list can omit a newly completed job. Keep that job as
            # the selection instead of silently substituting another plan.
            self._select_current_plan()
        elif plans and not self._execution_active and not getattr(self, '_image_requires_plan', False):
            want = next((i for i, p in enumerate(plans)
                         if p.get("mode") == "real" and p.get("matches_current_calibration") and not p.get('needs_replan')), None)
            if want is None:
                want = next((i for i, p in enumerate(plans) if not p.get('needs_replan')), None)
            if want is None:
                self.cmb_plans.set('')
                self.lbl_plan_hist.config(text='历史规划需要重新提取中心线并规划',foreground=theme.GOLD)
                self._update_plan_controls();return
            self.cmb_plans.current(want)
            self._on_pick_plan(log_selection=False)
        else:
            self.cmb_plans.set("")
            self.lbl_plan_hist.config(text=('已切换图片，请先提取并重新规划' if getattr(self, '_image_requires_plan', False)
                                           else '板卡上还没有保存的规划（先规划轨迹）'), foreground=theme.GOLD)
        self._update_plan_controls()

    def _select_current_plan(self):
        idx = next((i for i, p in enumerate(self._plan_history)
                    if p.get("id") == self.plan_job_id), None)
        if idx is None:
            self.cmb_plans.set("")
            if self.plan_job_id:
                self.lbl_plan_hist.config(
                    text=f"当前规划 {self.plan_job_id[:12]} · 列表尚未包含该任务，请刷新", foreground=theme.MUTED)
            else:
                self.lbl_plan_hist.config(text="尚未选择规划", foreground=theme.MUTED)
            return
        self.cmb_plans.current(idx)
        if not self._execution_active:
            self._on_pick_plan(log_selection=False)

    def _on_pick_plan(self, log_selection=True):
        if self._drawing_busy():
            # Ignore a selection event already queued before the controls were
            # disabled. It must never mutate a running worker's job ownership.
            if (self._planning_token is not None or getattr(self,'_extraction_active',False)
                    or getattr(self,'_cloud_active',False) or getattr(self,'_prediction_active',False)):
                self.cmb_plans.set("")
            else:
                self._select_current_plan()
            return
        idx = self.cmb_plans.current()
        if not (0 <= idx < len(self._plan_history)):
            return
        p = self._plan_history[idx]
        if p.get('needs_replan'):
            self.plan_job_id=None
            self.lbl_plan_hist.config(text='旧流程规划：请重新提取中心线并规划后执行',foreground=theme.GOLD)
            self._update_plan_controls();return
        size=p.get('path_source') or {}
        if hasattr(self,'var_w') and size.get('width_mm') is not None and size.get('height_mm') is not None:
            self._setting_drawing_size=True
            try:
                w,h=size['width_mm'],size['height_mm']
                self.var_w.set('%g'%w);self.var_h.set('%g'%h)
                self.var_size_preset.set(('%d×%d mm'%(w,h)) if w==h and w in (100,200,300) else '自定义')
            finally:self._setting_drawing_size=False
        self.plan_job_id = p.get("id")
        self._image_requires_plan = False
        ok = p.get("matches_current_calibration")
        mode = p.get("mode")
        if mode != "real":
            self.lbl_plan_hist.config(
                text=("已选中 %s · %s 指令 · %s模式 —— ⚠ 这是模拟规划，"
                      "不能驱动实物机械臂（需用「真实模式」重新规划）" % (
                          str(p.get("id"))[:8], p.get("commands"),
                          {"demo": "模拟", "None": "未知"}.get(str(mode), str(mode)))),
                foreground=theme.ERROR)
        else:
            self.lbl_plan_hist.config(
                text=("已选中 %s · %s 指令 · %.0fs · %s%s" % (
                    str(p.get("id"))[:8], p.get("commands"), p.get("duration_s") or 0,
                    "标定匹配，可直接执行" if ok else "⚠ 标定已变更，执行会被拒绝（需重新规划）",
                    "  [来自上次会话]" if p.get("restored") else "")),
                foreground=theme.MUTED if ok else theme.GOLD)
        if log_selection:
            self.log_msg(f"已选择历史规划 {str(p.get('id'))[:8]} "
                         f"({p.get('commands')} 指令, {mode} 模式)")
        self._update_plan_controls()

    def _execute_selected_plan(self):
        """用选中的历史规划直接驱动机械臂 (无需重新规划)"""
        if self._drawing_busy():
            self.log_msg("规划或执行仍在进行中，当前不能执行历史规划")
            return
        if not self.plan_job_id:
            messagebox.showwarning("提示", "请先「刷新列表」并选择一份历史规划")
            return
        p = next((p for p in self._plan_history if p.get("id") == self.plan_job_id), None)
        if p is not None:
            if p.get("mode") != "real":
                messagebox.showerror(
                    "无法执行",
                    "这份规划是「模拟(demo)模式」生成的。\n\n"
                    "模拟模式用的是理想机械臂模型（没有真实标定、不开串口），\n"
                    "所以它的轨迹不能用来驱动实物。\n\n"
                    "请把模式切到「真实(real)」重新规划一次。")
                return
            if not p.get("matches_current_calibration"):
                if not messagebox.askyesno(
                        "标定已变更",
                        "这份规划是用以前的标定生成的，当前 machine.json 已改动，\n"
                        "板卡会拒绝执行。\n\n仍要尝试吗？"):
                    return
        self.log_msg(f"用历史规划执行: {str(self.plan_job_id)[:12]}…")
        self._drive_arm()

    def _drive_arm(self, callback=None, expected_plan_job_id=None):
        """让机械臂直接动起来: 用板卡 execute 动作驱动舵机执行 plan"""
        if self._drawing_busy():
            self.log_msg("规划或执行仍在进行中，请等待该任务结束")
            return
        if expected_plan_job_id is not None and self.plan_job_id != expected_plan_job_id:
            self.log_msg("规划选择已改变，取消自动执行")
            return
        if not self.plan_job_id:
            messagebox.showwarning("提示", "请先规划轨迹")
            return
        plan_job_id = self.plan_job_id
        port = self.var_port.get().strip()
        self._execution_active = True
        self._update_plan_controls()
        self.set_prog(88, "机械臂开始绘画…（画完自动归位）")
        self.log_msg("🦾 驱动机械臂…  画完会强制归位")

        def worker():
            ok = False
            try:
                res = self.client.execute(plan_job_id, port=port)
                exec_job = res.get("id")
                self.log_msg(f"执行 Job: {exec_job}")

                info, last = None, ""
                for i in range(3600):
                    jobs = self.client.get_jobs()
                    info = next((j for j in jobs.get("jobs", []) if j["id"] == exec_job), None)
                    if info:
                        if info.get("detail") != last:
                            last = info.get("detail", "")
                            self.log_msg(f"  {last}")
                        if info["status"] in ("DONE", "FAILED"):
                            break
                    if i and i % 20 == 0:
                        self.log_msg(f"  执行中… {i}s")
                    time.sleep(1.0)

                if info and info["status"] == "DONE":
                    outcome = info.get('result') or {}
                    self._last_execution_job = exec_job if outcome.get('execution_trace_url') else None
                    controller = outcome.get('feedback_control') or {}
                    if controller:
                        self.log_msg('   跟随补偿 %s / 每关节最大补偿 %s 计数' % (
                            controller.get('version'),controller.get('max_correction_counts')))
                    phase = outcome.get('pen_phase') or {}
                    if phase:self.log_msg('   抬落笔补偿更新增加 %.2fs；超时仍继续绘画' % phase.get('extra_time_s',0.))
                    tracking = outcome.get('tracking')
                    if tracking:self.log_msg('   编码器模型：笔尖最大偏差 %.2fmm / 笔轴偏角 %.2f°' % (
                        1000*tracking.get('max_tip_error_m',0.),tracking.get('max_pen_axis_error_deg',0.)))
                    confirmed = outcome.get('task_complete', False)
                    qualified = tracking is not None and tracking.get('tracking_qualified', False)
                    home = outcome.get('auto_home')
                    returned = home is not None and home.get('task_complete', False)
                    ok = bool(confirmed and qualified and returned and not outcome.get('auto_home_error'))
                    self.log_msg(f"{'✅' if ok else '⚠'} {info.get('detail','指令处理结束')}")
                    self.set_prog(100, "绘画完成 · 跟踪合格 · 归位确认" if ok else "指令处理结束 · 请查看质量记录")
                else:
                    self.log_msg(f"❌ 执行失败: {info.get('detail','超时') if info else '超时'}")
                    self.set_prog(0, "执行失败")
            except Exception as e:
                self.log_msg(f"❌ 驱动失败: {e}")
                self.set_prog(0, "驱动失败")
            finally:
                def finish():
                    self._execution_active = False
                    self._update_plan_controls()
                    if callback:
                        callback(ok)
                self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _find_job_dir(self, job_id):
        if self.board_mode:
            if not isinstance(job_id,str) or len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):return None
            paths=list(Path(self.args.data_dir).glob('*/job_'+job_id))
            return str(paths[0]) if paths else None
        try:
            status = self.client.fetch_status()
            session_id = status.get("session_id", "")
            for r in [self.args.data_dir, "/home/xilinx/SO101_FPGA_ArmSystem/logs", "/home/xilinx/so101_team/logs",
                      "/home/xilinx/SO101_IK_PYNQ_Integrated/app/logs"]:
                out, _, _ = self.ssh.run(f"ls -d {r}/{session_id}/job_{job_id} 2>/dev/null; "
                                         f"ls -d {r}/*/job_{job_id} 2>/dev/null | head -1")
                if out.strip():
                    return out.strip().splitlines()[0]
            out, _, _ = self.ssh.run(f"find /home/xilinx -maxdepth 5 -type d -name 'job_{job_id}' 2>/dev/null | head -1")
            if out.strip():
                return out.strip().splitlines()[0]
        except Exception as e:
            self.log_msg(f"查找目录出错: {e}")
        return None

    def _one_click_draw(self):
        """一键: 规划 → 直接驱动"""
        if not self.image_job_id:
            messagebox.showwarning("提示", "请先提取笔画 (第 3 步)")
            return
        self.log_msg("▶ 一键绘画: 规划 → 机械臂直接执行")

        def after_plan(ok):
            if ok:
                plan_job_id = self.plan_job_id
                self.root.after(600, lambda: self._drive_arm(expected_plan_job_id=plan_job_id))
            else:
                self.log_msg("规划未成功, 取消执行")
        self._plan(callback=after_plan)

    def _feedback_preview(self):
        jid = getattr(self,'_last_execution_job',None)
        if not jid or self._drawing_busy():return
        self._prediction_active = True; self._update_plan_controls()
        def worker():
            try:
                from drawing_prediction import feedback_preview
                from scripts.drawing_preview_ui import DrawingPreviewWindow
                trace = self.client.get_job_file(jid,'execution_trace.json')
                data = self.client.prediction_data(trace['plan_job_id'])
                preview = feedback_preview(data,trace)
                source_path=self.ent_image.get().strip()
                self.root.after(0,lambda:DrawingPreviewWindow(self.root,preview,source_path))
            except Exception as exc:self.log_msg('读取实际执行轨迹失败：%s' % exc)
            finally:
                def finish():
                    self._prediction_active = False; self._update_plan_controls()
                self.root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()

    def _preview(self):
        if self._drawing_busy():
            self.log_msg('已有任务，请等待结束后查看规划预测'); return
        if not self.plan_job_id:
            messagebox.showwarning("提示", "请先规划轨迹")
            return
        plan_job_id = self.plan_job_id
        source_path = self.ent_image.get().strip()
        self._prediction_active = True; self._update_plan_controls()
        def worker():
            try:
                from drawing_prediction import command_preview
                from scripts.drawing_preview_ui import DrawingPreviewWindow
                data = self.client.prediction_data(plan_job_id)
                if data.get('job_id') != plan_job_id:
                    raise ValueError('返回的预测数据不属于当前选择的规划')
                preview = command_preview(data)
                self.root.after(0, lambda: DrawingPreviewWindow(self.root, preview, source_path))
                self.log_msg('已规划轨迹预测：Job %s / %d 段 / %d 落笔指令' % (
                    plan_job_id[:8], preview['segments'], preview['predicted_commands']))
            except Exception as e:
                error = str(e)
                if 'HTTP 404' in error:
                    error += '\n板端可能仍为旧版，请安装本次交付包后重新规划；离线路径预测可直接使用。'
                self.log_msg('规划预测失败: ' + error)
                self.root.after(0, lambda message=error: messagebox.showerror('规划预测失败', message, parent=self.root))
            finally:
                def finish():
                    self._prediction_active = False; self._update_plan_controls()
                self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _stop(self):
        def worker():
            try:
                self.client.stop()
                self.log_msg("停止请求已发送")
                self.set_prog(0, "已停止")
            except Exception as e:
                self.log_msg(f"停止失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 手势跟随 ----------------
    def _start_follow_server(self):
        if self.board_mode: return
        """切到跟随模式 (会停止绘画服务, 释放串口)"""
        self.log_msg("切换到跟随模式 (停止绘画服务, 释放串口)…")

        def worker():
            try:
                out, _, _ = self.ssh.sudo("/usr/local/bin/so101_mode.sh follow 2>&1", timeout=90)
                self.log_msg(f"切换输出: {out.strip()[-200:]}")
                time.sleep(2)
                self._check_follow_server()
            except Exception as e:
                self.log_msg(f"❌ 切换失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _switch_to_drawing(self):
        if self.board_mode: self._connect();return
        """切回绘画模式 (会停止跟随服务, 释放串口)"""
        self.log_msg("切换到绘画模式 (停止跟随服务)…")

        def worker():
            try:
                out, _, _ = self.ssh.sudo("/usr/local/bin/so101_mode.sh drawing 2>&1", timeout=120)
                self.log_msg(f"切换输出: {out.strip()[-200:]}")
                time.sleep(2)
                self._connect()
            except Exception as e:
                self.log_msg(f"❌ 切换失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _deploy_follow(self):
        if self.board_mode: return
        self.log_msg("部署手势跟随脚本到板卡…")

        def worker():
            try:
                for name in ("hand_follow_server.py",):
                    local = ROOT / "scripts" / name
                    if not local.is_file():
                        self.log_msg(f"⚠ 本地缺少 {name}")
                        continue
                    self.ssh.put(local, f"/tmp/{name}")
                    self.ssh.sudo(f"cp /tmp/{name} /home/xilinx/{name}")
                    self.log_msg(f"✅ 已部署 {name}")
            except Exception as e:
                self.log_msg(f"❌ 部署失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _check_follow_server(self, silent=False):
        def worker():
            try:
                r = urllib.request.urlopen(
                    f"http://{self.args.host}:{FOLLOW_PORT}/status", timeout=3)
                ok = r.status == 200
                self.root.after(0, lambda: self.lbl_follow_srv.config(
                    text="🟢 跟随服务在线" if ok else "🔴 离线", foreground=theme.OK if ok else theme.ERROR))
                if not silent:
                    self.log_msg("跟随服务在线" if ok else "跟随服务离线")
            except Exception as e:
                self.root.after(0, lambda: self.lbl_follow_srv.config(
                    text="🔴 跟随服务离线", foreground=theme.ERROR))
                if not silent:
                    self.log_msg(f"跟随服务离线: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_pinch(self):
        """自动捏合 与 手动滑块 互斥"""
        auto = self.var_pinch.get()
        self.scale_grip.config(state="disabled" if auto else "normal")
        if auto:
            self.lbl_grip.config(text="自动", foreground=theme.MUTED)
            self.log_msg("夹爪: 自动捏合跟随 (捏合=合拢, 张开=张开)")
        else:
            self.log_msg("夹爪: 手动滑块控制")
            self._on_grip_manual(str(self.var_grip.get()))

    def _on_grip_manual(self, _val=None):
        """手动滑块: 0=合拢(1300), 1=张开(2800)"""
        if self.var_pinch.get():
            return
        r = float(self.var_grip.get())
        cnt = int(GRIP_CLOSED + r * (GRIP_OPEN - GRIP_CLOSED))
        state = "合拢" if r < 0.2 else ("张开" if r > 0.8 else "中间")
        self.lbl_grip.config(text=f"{r:.2f} → {cnt} ({state})", foreground=theme.GOLD)

    def _test_gripper(self):
        """通过跟随服务跑一遍夹爪全行程, 验证 1300/2800 标定"""
        self.log_msg("测试夹爪行程 (位置固定在画面中心)…")

        def worker():
            try:
                base = f"http://{self.args.host}:{FOLLOW_PORT}"
                urllib.request.urlopen(base + "/status", timeout=4)
                samples = []
                for r in (0.0, 1.0, 0.0, 1.0):
                    body = json.dumps({"x": 0.5, "y": 0.5,
                                       "gripper_ratio": r}).encode()
                    req = urllib.request.Request(
                        base + "/follow", data=body, method="POST",
                        headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=3)
                    time.sleep(2.6)
                    st = json.loads(urllib.request.urlopen(
                        base + "/arm_state", timeout=4).read())
                    cnt = st.get("servo_counts", {}).get("gripper")
                    samples.append((r, cnt))
                    label = "合拢" if r == 0.0 else "张开"
                    self.log_msg(f"  ratio={r:.1f} ({label}) → gripper={cnt}")

                vals = [c for _, c in samples if c]
                if len(vals) >= 2:
                    lo, hi = min(vals), max(vals)
                    span, want = hi - lo, GRIP_OPEN - GRIP_CLOSED
                    self.log_msg(f"✅ 实测行程 {lo} ~ {hi} (跨度 {span})")
                    self.log_msg(f"   标定期望 {GRIP_CLOSED} ~ {GRIP_OPEN} (跨度 {want})")
                    if span > want * 0.6:
                        self.log_msg("   → 夹爪响应正常")
                    else:
                        self.log_msg("   ⚠ 行程偏小, 检查夹爪是否卡住或限位未更新")
                    self.root.after(0, lambda: self.lbl_grip.config(
                        text=f"实测 {lo}~{hi}", foreground=theme.OK))
            except Exception as e:
                self.log_msg(f"❌ 夹爪测试失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _follow_home(self):
        def worker():
            try:
                req = urllib.request.Request(
                    f"http://{self.args.host}:{FOLLOW_PORT}/home",
                    data=b"{}", method="POST",
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
                self.log_msg("机械臂回中位")
            except Exception as e:
                self.log_msg(f"回中位失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_follow(self):
        if self.follow_running:
            self._follow_stop.set()
            self.follow_running = False
            self.root.after(0, lambda: self.btn_follow.config(text="▶ 开始跟随"))
            self.log_msg("停止跟随")
            return
        try:
            cam = int(self.var_cam.get())
        except ValueError:
            cam = 0
        self.follow_running = True
        self._follow_stop.clear()
        self.btn_follow.config(text="■ 停止跟随")
        self.follow_thread = threading.Thread(target=self._follow_loop, args=(cam,), daemon=True)
        self.follow_thread.start()

    def _follow_loop(self, cam_index):
        import cv2
        import numpy as np
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
        except ImportError:
            self.log_msg("❌ 未安装 mediapipe: pip install mediapipe")
            self.follow_running = False
            self.root.after(0, lambda: self.btn_follow.config(text="▶ 开始跟随"))
            return

        model_path = ROOT / "models" / "hand_landmarker.task"
        landmarker = None
        try:
            opts = mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp_vision.RunningMode.VIDEO,
                num_hands=1, min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.5, min_tracking_confidence=0.5)
            landmarker = mp_vision.HandLandmarker.create_from_options(opts)
        except Exception as e:
            self.log_msg(f"❌ MediaPipe 初始化失败: {e}")
            self.follow_running = False
            self.root.after(0, lambda: self.btn_follow.config(text="▶ 开始跟随"))
            return

        cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(cam_index)
        if not cap.isOpened():
            self.log_msg(f"❌ 无法打开摄像头 {cam_index}")
            self.follow_running = False
            self.root.after(0, lambda: self.btn_follow.config(text="▶ 开始跟随"))
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.log_msg(f"摄像头 {cam_index} 已打开, 开始跟随 (在镜头前移动食指)")

        smooth_x, smooth_y = 0.5, 0.5
        alpha = 0.5
        fps, fps_counter, fps_t0 = 0, 0, time.time()
        sent_ok, hand_label = 0, ""
        grip_line = "无手部"

        try:
            while not self._follow_stop.is_set():
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.03)
                    continue
                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                landmarks = None
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                res = landmarker.detect_for_video(mp_img, int(time.time() * 1000))
                if res.hand_landmarks:
                    landmarks = res.hand_landmarks[0]
                    if res.handedness:
                        hand_label = res.handedness[0][0].category_name

                if landmarks is not None:
                    tip = landmarks[8]      # 食指指尖 -> 笔尖位置
                    thumb = landmarks[4]    # 拇指指尖 -> 捏合检测
                    smooth_x = alpha * tip.x + (1 - alpha) * smooth_x
                    smooth_y = alpha * tip.y + (1 - alpha) * smooth_y

                    # --- 捏合检测: 拇指-食指距离 ---
                    pdx, pdy = tip.x - thumb.x, tip.y - thumb.y
                    pinch = (pdx * pdx + pdy * pdy) ** 0.5
                    # 板卡语义: 0=合拢(1300), 1=张开(2800)
                    # 捏合(pinch 小) -> 0 ; 张开(pinch 大) -> 1
                    ratio_auto = max(0.0, min(1.0, (pinch - PINCH_MIN) / PINCH_SPAN))

                    if self.var_pinch.get():
                        grip_ratio = ratio_auto
                        self.var_grip.set(grip_ratio)      # 同步给滑块显示
                    else:
                        grip_ratio = float(self.var_grip.get())

                    grip_cnt = int(GRIP_CLOSED + grip_ratio * (GRIP_OPEN - GRIP_CLOSED))
                    grip_state = "合拢" if grip_ratio < 0.2 else ("张开" if grip_ratio > 0.8 else "中间")

                    # 画关键点
                    for idx, pt in enumerate(landmarks):
                        px, py = int(pt.x * w), int(pt.y * h)
                        cv2.circle(frame, (px, py), 4 if idx == 8 else 2,
                                   (0, 255, 255) if idx == 8 else (0, 255, 0), -1)
                    # 画捏合连线 + 拇指
                    tx, ty = int(thumb.x * w), int(thumb.y * h)
                    cv2.circle(frame, (tx, ty), 8, (255, 128, 0), 2)
                    cv2.line(frame, (tx, ty), (int(tip.x * w), int(tip.y * h)),
                             (0, 0, 255) if grip_ratio < 0.5 else (0, 255, 0), 3)
                    # 画跟随目标点
                    px, py = int(smooth_x * w), int(smooth_y * h)
                    cv2.circle(frame, (px, py), 12, (0, 255, 0), 3)

                    # 发目标到板卡
                    try:
                        body = json.dumps({"x": float(smooth_x), "y": float(smooth_y),
                                           "gripper_ratio": float(grip_ratio)}).encode()
                        req = urllib.request.Request(
                            f"http://{self.args.host}:{FOLLOW_PORT}/follow", data=body,
                            method="POST", headers={"Content-Type": "application/json"})
                        urllib.request.urlopen(req, timeout=0.5)
                        sent_ok += 1
                    except Exception:
                        pass

                    grip_line = f"{grip_ratio:.2f} → {grip_cnt} ({grip_state})"
                else:
                    grip_line = "无手部"
                    cv2.putText(frame, "NO HAND - show your hand", (10, 100),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                fps_counter += 1
                now = time.time()
                if now - fps_t0 >= 1.0:
                    fps, fps_counter, fps_t0 = fps_counter, 0, now

                for i, line in enumerate([f"FPS {fps}", f"Hand {hand_label or '-'}",
                                          f"Norm ({smooth_x:.2f},{smooth_y:.2f})",
                                          f"Grip {grip_line}",
                                          f"Sent {sent_ok}"]):
                    cv2.putText(frame, line, (10, 24 + i * 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)

                # 显示到 Tkinter
                self._show_frame(frame)

                self.root.after(0, lambda: self.lbl_follow_stat.config(
                    text=f"FPS {fps} · 手部 {hand_label or '未检测'} · "
                         f"目标 ({smooth_x:.2f}, {smooth_y:.2f}) · 夹爪 {grip_line} · 已发送 {sent_ok}"))
                self.root.after(0, lambda: self.lbl_grip.config(
                    text=grip_line, foreground=theme.OK))
                time.sleep(0.01)
                if self._follow_stop.is_set():
                    break
        except Exception as e:
            self.log_msg(f"❌ 跟随循环出错: {e}")
        finally:
            cap.release()
            try:
                landmarker.close()
            except Exception:
                pass
            self.follow_running = False
            self.root.after(0, lambda: self.btn_follow.config(text="▶ 开始跟随"))
            self._follow_home()
            self.log_msg("跟随已停止")

    def _show_frame(self, frame):
        try:
            from PIL import Image, ImageTk
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            img.thumbnail((720, 420))
            photo = ImageTk.PhotoImage(img)
            def _do():
                self._cam_photo = photo
                self.lbl_cam.config(image=photo, text="")
            self.root.after(0, _do)
        except Exception:
            pass

    # ---------------- 舵机 ----------------
    def _probe(self):
        port = self.var_port.get().strip()
        try:
            ids = [int(x.strip()) for x in self.var_ids.get().split(",") if x.strip()]
        except ValueError:
            messagebox.showwarning("提示", "ID 用英文逗号分隔")
            return
        self.log_msg(f"探测舵机 {ids} @ {port}…")

        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                d = self.client.probe(port=port, ids=ids)
                rows = d.get("rows", [])
                def _fill():
                    for i in self.tree.get_children():
                        self.tree.delete(i)
                    for r in rows:
                        self.tree.insert("", "end", values=(
                            r.get("id"), "OK" if r.get("ping_ok") else "失败",
                            r.get("position_count", "—"),
                            (r.get("error") or {}).get("code", "OK") if r.get("error") else "OK"))
                self.root.after(0, _fill)
                self.log_msg(f"探测结果: {d.get('status')} {d.get('error') or ''}")
                for r in rows:
                    if r.get("error"):
                        self.log_msg(f"  ID {r['id']} 错误: {r['error']}")
            except Exception as e:
                self.log_msg(f"❌ 探测失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _read_config(self):
        def worker():
            try:
                cfg = self.client.fetch_config()
                txt = json.dumps(cfg, ensure_ascii=False, indent=2)
                self.root.after(0, lambda: (self.txt_cfg.delete("1.0", "end"),
                                            self.txt_cfg.insert("1.0", txt)))
                self.log_msg("已载入板卡标定配置")
            except Exception as e:
                self.log_msg(f"❌ 载入配置失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _save_config(self):
        txt = self.txt_cfg.get("1.0", "end").strip()
        try:
            cfg = json.loads(txt)
        except Exception as e:
            messagebox.showerror("JSON 错误", str(e))
            return

        def worker():
            try:
                self.client.save_config(cfg)
                self.log_msg("✅ 配置已保存到板卡 (重启服务后生效)")
            except Exception as e:
                self.log_msg(f"❌ 保存配置失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _home_arm(self):
        """使能扭矩保持当前位置 (板卡 /api/enable), 机械臂会锁住在当前姿态"""
        port = self.var_port.get().strip()
        self.log_msg(f"使能扭矩 (保持当前姿态) on {port}…")

        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                job = self.client.enable(port=port, mode="real")
                jid = job.get("id")
                info = self._wait_job(jid, timeout=90)
                if info and info.get("status") == "DONE":
                    self.log_msg(f"✅ 扭矩已使能, 保持位置: {info.get('result')}")
                    self._probe()
                else:
                    self.log_msg(f"❌ 使能失败: {info.get('detail') if info else '超时'}")
            except Exception as e:
                self.log_msg(f"❌ 使能失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _draw_home(self):
        """回绘画起始姿态 (板卡 /api/home)。规划以当前姿态为 IK 起点, 不在起始位会导致停滞。"""
        if self._drawing_busy():
            self.log_msg("规划或执行仍在进行中，请等待后再归位")
            return
        port = self.var_port.get().strip()
        self.log_msg(f"回绘画起始位 on {port} (约 12 秒, 请勿断电)…")
        self.root.after(0, lambda: self.btn_home.config(state="disabled"))

        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                job = self.client.home(mode="real", port=port)
                jid = job.get("id")
                info = self._wait_job(jid, timeout=180)
                if info and info.get("status") == "DONE":
                    result = info.get("result") or {}
                    fc = result.get("final_counts")
                    if result.get('task_complete'):
                        self.log_msg(f"✅ 已回到绘画起始位  最终计数: {fc}")
                    else:
                        self.log_msg(f"⚠ 归位指令处理结束，终点未确认  最终反馈: {fc}")
                    self._probe()
                else:
                    self.log_msg(f"❌ 归位失败: {info.get('detail') if info else '超时'}")
            except Exception as e:
                self.log_msg(f"❌ 归位失败: {e}")
            finally:
                self.root.after(0, lambda: self.btn_home.config(state="normal"))
        threading.Thread(target=worker, daemon=True).start()

    def _wait_job(self, job_id, timeout=120):
        """轮询任务直到结束, 返回 job 字典"""
        deadline = time.time() + timeout
        info = None
        while time.time() < deadline:
            try:
                jobs = self.client.get_jobs()
                info = next((j for j in jobs.get("jobs", []) if j["id"] == job_id), None)
                if info and info["status"] in ("DONE", "FAILED"):
                    return info
            except Exception:
                pass
            time.sleep(0.7)
        return info

    def _jog_servo(self):
        """点动: 板卡限制单次 ±1..20 计数, 这里按次数循环实现较大位移"""
        try:
            sid = int(self.var_jog_id.get())
            pos = int(self.var_jog_pos.get())
        except ValueError:
            messagebox.showwarning("提示", "ID 和目标计数必须是整数")
            return
        port = self.var_port.get().strip()

        def worker():
            try:
                if not self.client.token:
                    self.client.fetch_status()
                # 读当前值
                d = self.client.probe(port=port, ids=[sid])
                row = next((r for r in d.get("rows", []) if r["id"] == sid), None)
                if not row or not row.get("ping_ok"):
                    self.log_msg(f"❌ ID {sid} 无响应")
                    return
                cur = row.get("position_count")
                if cur is None:
                    self.log_msg(f"❌ ID {sid} 读不到位置")
                    return
                remain = pos - cur
                self.log_msg(f"点动 ID {sid}: {cur} → {pos} (差 {remain})")

                steps = 0
                while abs(remain) > 0 and steps < 400:
                    delta = max(-20, min(20, remain))
                    if delta == 0:
                        break
                    job = self.client.jog(sid, delta, port=port, mode="real")
                    info = self._wait_job(job.get("id"), timeout=30)
                    if not info or info.get("status") != "DONE":
                        self.log_msg(f"❌ 点动中断: {info.get('detail') if info else '超时'}")
                        return
                    remain -= delta
                    steps += 1
                self.log_msg(f"✅ 点动完成 ({steps} 步)")
                time.sleep(0.5)
                self._probe()
            except Exception as e:
                self.log_msg(f"❌ 点动失败: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def on_close(self):
        if self.board_mode and self._drawing_busy():
            messagebox.showinfo('任务正在运行','请等待任务完成，或先点停止后再退出界面。',parent=self.root)
            return
        self._follow_stop.set()
        self._beat_stop.set()
        if self.tunnel:
            self.tunnel.stop()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description="SO-101 一体化控制台")
    ap.add_argument("--host", default="127.0.0.1", help="板卡 Web 服务地址")
    ap.add_argument("--port", type=int, default=WEB_PORT, help="板卡 Web 服务端口")
    ap.add_argument("--board-ip", default=BOARD_IP)
    ap.add_argument("--board-user", default=BOARD_USER)
    ap.add_argument("--board-pass", default=BOARD_PASS)
    ap.add_argument("--data-dir", default="/home/xilinx/so101_data", help="板端作业数据目录")
    ap.add_argument("--target-drawing", action="store_true", help="完整目标 FPGA 绘画测试；不切换旧跟随服务")
    ap.add_argument("--restore-image-job", help="恢复已登记的笔画 Job，不提交新任务")
    ap.add_argument("--restore-plan-job", help="恢复已有规划 Job，不自动执行")
    ap.add_argument('--image',type=Path,help='预先选中图片，不自动规划或执行')
    ap.add_argument('--preview-paths',type=Path,help='打开已提取笔画的顺序预览')
    ap.add_argument('--calibration-port',help='PC 标定读取串口，例如 COM7；默认从板端读取')
    ap.add_argument('--offline',action='store_true',help='启动时不连接板卡，可离线查看笔画')
    ap.add_argument('--cloud-image-dir', type=Path, help='PC 云端图片库目录，默认在用户 Pictures/SO101/CloudImages')
    ap.add_argument('--show-cloud-history', action='store_true', help='启动时打开历史云端图片选择窗口')
    ap.add_argument('--board-local',action='store_true',help='MD0700R 板端触摸模式，本机 API，无 SSH')
    ap.add_argument('--windowed',action='store_true',help='触摸界面使用 1024x600 窗口以便调试')
    ap.add_argument('--return-user-gui',action='store_true',help='显示返回用户界面按钮，由板端桌面管理器恢复用户界面')
    ap.add_argument('--secrets-file',type=Path,help='云端私用密钥文件；不记录内容')
    ap.add_argument("--no-tunnel", action="store_true",
                    help="不自动建 SSH 隧道 (默认会自动建, 已存在则复用)")
    args = ap.parse_args()
    args.tunnel = not args.no_tunnel
    if args.board_local:
        if args.host not in ('127.0.0.1','localhost'):
            ap.error('--board-local requires localhost')
        args.tunnel=False;args.target_drawing=True
        if args.cloud_image_dir is None:args.cloud_image_dir=Path(args.data_dir)/'cloud_images'

    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    app = ArmStudio(root, args)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

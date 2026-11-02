#!/usr/bin/env python3
"""
SO-101 机械臂实时手部跟随服务器

接收 PC 发来的 2D 手部坐标 (归一化 0-1)，做 IK 求解，实时驱动舵机。

启动:
  sudo -E /usr/local/share/pynq-venv/bin/python3 /home/xilinx/hand_follow_server.py
"""
import os
os.environ['XILINX_XRT'] = '/usr'
import sys
sys.path.insert(0, '/home/xilinx/SO101_FPGA_ArmSystem/ik_solver')
sys.path.insert(0, '/home/xilinx/SO101_FPGA_ArmSystem/ik_solver/planner')

import json
import time
import math
import socket
import threading
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler

from driver.ftservo_controller import ServoController
from ik.robot import create_so101_5dof
from ik.solvers import IK_LM, IK_GN

# ── 配置 ──
HOST = "0.0.0.0"
PORT = 8770

# 工作平面范围 (米): 机械臂前方的一块区域 — 最大范围
PLANE_X_MIN, PLANE_X_MAX = 0.10, 0.30    # 前后 (x): 20cm 范围
PLANE_Y_MIN, PLANE_Y_MAX = -0.12, 0.12   # 左右 (y): 24cm 范围
GRIP_CLOSED = 1300   # 合拢位置
GRIP_OPEN = 2800     # 张开位置
PLANE_Z = 0.15                            # 固定高度

# IK 初始关节角
Q0 = np.array([0.03, -0.56, 0.98, 1.02, 0.0])

# 舵机控制
SERVO_PORT = "/dev/right_arm"
BAUDRATE = 1_000_000

# 滤波: 指数平滑 (0=无平滑, 0.3=强平滑防抖)
# 实时跟随用小平滑值加快响应
SMOOTH_ALPHA = 0.3  # 关节角平滑 (0.3=中度平滑, 防抖)

# 最小移动距离 (米): 避免抖动
MIN_MOVE_THRESHOLD = 0.003  # 3mm


class ArmController:
    """实时舵机控制器: 接收目标坐标 → IK → 舵机"""
    def __init__(self):
        print("[ArmCtrl] 初始化舵机控制器...")
        self.controller = ServoController(
            port=SERVO_PORT, baudrate=BAUDRATE,
            config_path="/home/xilinx/SO101_FPGA_ArmSystem/ik_solver/driver/right_arm.json"
        )
        # 回中位
        self.controller.move_all_home()
        time.sleep(1.5)
        print("[ArmCtrl] 舵机已回中位")

        # IK 模型
        self.robot = create_so101_5dof()
        self.q_current = Q0.copy()
        self.pos_current = np.array([0.21, 0.0, PLANE_Z])
        self.grip_current = 0.0
        self.initialized = False
        self.lock = threading.Lock()

        # 先做一次 IK 到初始位置
        self._move_to(0.21, 0.0)
        self.initialized = True
        print("[ArmCtrl] 就绪，等待手部坐标...")

    def _ik_solve(self, x, y):
        """增量式 IK 求解: 只约束位置, 不约束姿态 (SO-ARM101 笔轴朝下不可达)"""
        Tep = np.eye(4)
        Tep[0, 3] = x
        Tep[1, 3] = y
        Tep[2, 3] = PLANE_Z

        # 只约束位置 (mask=[1,1,1,0,0,0]), 不约束旋转姿态
        mask = np.array([1, 1, 1, 0, 0, 0], dtype=float)

        # 增量式: 迭代 8 步, 从上一帧解出发
        solver = IK_LM(ilimit=8, slimit=1, tol=1e-3)
        sol = solver.solve(self.robot.ets, Tep, q0=self.q_current, mask=mask)
        q = sol.q

        # 限位
        limits = self.robot.ets.qlim if hasattr(self.robot.ets, 'qlim') else None
        if limits is not None:
            for i in range(min(5, len(q))):
                q[i] = max(limits[0, i], min(limits[1, i], q[i]))
        return q

        # 限位
        limits = self.robot.ets.qlim if hasattr(self.robot.ets, 'qlim') else None
        if limits is not None:
            for i in range(min(5, len(q))):
                q[i] = max(limits[0, i], min(limits[1, i], q[i]))
        return q

    def _rad_to_counts(self, q_rad, gripper_ratio=0.0):
        """5 关节角(弧度) → 6 舵机计数, gripper_ratio 0=合拢 1=张开"""
        names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
        counts = {}
        for name, angle in zip(names, q_rad):
            c = int(2048 + angle * 4096 / (2 * math.pi))
            c = max(0, min(4095, c))
            counts[name] = c
        # gripper: 0=合拢(1300), 1=张开(2800), 线性映射
        # 1300/2800 为实测机械行程边界 (2026 标定)
        gripper_ratio = max(0.0, min(1.0, gripper_ratio))
        counts["gripper"] = int(GRIP_CLOSED + gripper_ratio * (GRIP_OPEN - GRIP_CLOSED))
        return counts

    def _move_to(self, x, y, gripper_ratio=0.0):
        """IK + 驱动舵机 (含关节角平滑防抖, 限速)"""
        # 最小移动距离检查: 低于阈值不驱动, 消除静止抖动
        dx = x - self.pos_current[0]
        dy = y - self.pos_current[1]
        dist = math.sqrt(dx*dx + dy*dy)
        # 位置没变 且 夹爪指令也没变 -> 才跳过 (修复: 手不动时捏合无响应)
        if dist < MIN_MOVE_THRESHOLD and abs(gripper_ratio - self.grip_current) < 0.02:
            return

        q = self._ik_solve(x, y)
        # 关节角平滑: 减小抖动
        a = SMOOTH_ALPHA
        q_smooth = a * q + (1 - a) * self.q_current
        counts = self._rad_to_counts(q_smooth, gripper_ratio)
        # 限速驱动舵机 (速度=8000, 约 max 的 1/4, 减少冲击)
        servo_data = {}
        for name, pos in counts.items():
            cfg = self.controller.config[name]
            sid = cfg["id"]
            if name == "gripper":
                limited = max(0, min(4095, pos))
            else:
                limited = self.controller.limit_position(name, pos)
            servo_data[sid] = [
                limited & 0xFF, (limited >> 8) & 0xFF,  # 位置
                0x00, 0x00,                             # 时间=0
                0x1F, 0x40,                             # 速度=8000 (适中)
            ]
        self.controller.servo.sync_write(0x2A, 6, servo_data)
        self.grip_current = gripper_ratio
        self.q_current = q_smooth
        self.pos_current = np.array([x, y, PLANE_Z])

    def get_state(self):
        """返回当前机械臂状态: 关节角 + 末端位置 + 舵机计数"""
        try:
            servo_counts = self.controller.read_servo_positions()
        except Exception:
            servo_counts = {}

        # 正运动学计算末端位置
        try:
            T = self.robot.fkine(self.q_current)
            tip = [float(T[0, 3]), float(T[1, 3]), float(T[2, 3])]
        except Exception:
            tip = [float(self.pos_current[0]), float(self.pos_current[1]), float(PLANE_Z)]

        return {
            "q_rad": [float(x) for x in self.q_current[:5]],
            "q_deg": [float(np.degrees(x)) for x in self.q_current[:5]],
            "tip_m": tip,
            "tip_mm": [round(t * 1000, 1) for t in tip],
            "pos_target_m": [float(self.pos_current[0]), float(self.pos_current[1]), float(self.pos_current[2])],
            "norm_target": [
                float((self.pos_current[0] - PLANE_X_MIN) / (PLANE_X_MAX - PLANE_X_MIN)),
                float((self.pos_current[1] - PLANE_Y_MIN) / (PLANE_Y_MAX - PLANE_Y_MIN)),
            ],
            "servo_counts": servo_counts,
        }

    def follow(self, norm_x, norm_y, gripper_ratio=0.0):
        """跟随: norm_x, norm_y ∈ [0, 1], gripper_ratio 0=合拢 1=张开"""
        with self.lock:
            # 归一化坐标 → 平面坐标
            tx = PLANE_X_MIN + norm_x * (PLANE_X_MAX - PLANE_X_MIN)
            ty = PLANE_Y_MIN + norm_y * (PLANE_Y_MAX - PLANE_Y_MIN)

            self._move_to(tx, ty, gripper_ratio)

    def home(self):
        """回中位"""
        with self.lock:
            self.controller.soft_move_to_home(step_count=20, interval=0.05)
            self.q_current = Q0.copy()
            self.pos_current = np.array([0.21, 0.0, PLANE_Z])
        self.grip_current = 0.0

    def close(self):
        self.controller.close()


# ── 全局控制器 ──
arm = None


class FollowHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global arm
        if self.path == "/follow":
            try:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                nx = float(data.get("x", 0.5))
                ny = float(data.get("y", 0.5))
                gripper_ratio = float(data.get("gripper_ratio", 0.0))
                # 限制范围
                nx = max(0.0, min(1.0, nx))
                ny = max(0.0, min(1.0, ny))
                gripper_ratio = max(0.0, min(1.0, gripper_ratio))
                arm.follow(nx, ny, gripper_ratio)
                self._respond(200, {"ok": True, "x": nx, "y": ny, "gripper_ratio": gripper_ratio})
            except Exception as e:
                self._respond(500, {"ok": False, "error": str(e)})
        elif self.path == "/home":
            arm.home()
            self._respond(200, {"ok": True})
        else:
            self._respond(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/status":
            self._respond(200, {"ok": True, "arm": "ready"})
        elif self.path == "/arm_state":
            try:
                state = arm.get_state()
                self._respond(200, state)
            except Exception as e:
                self._respond(500, {"error": str(e)})
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静默


def main():
    global arm
    print("=" * 50)
    print("  SO-101 手部跟随服务器")
    print("=" * 50)

    arm = ArmController()

    server = HTTPServer((HOST, PORT), FollowHandler)
    print(f"\n[Server] 监听 {HOST}:{PORT}")
    print(f"[Server] POST /follow {{x: 0-1, y: 0-1}} → 驱动机械臂")
    print(f"[Server] POST /home → 回中位")
    print(f"[Server] 等待连接...\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] 停止中...")
        arm.home()
        arm.close()
        server.server_close()


if __name__ == "__main__":
    main()

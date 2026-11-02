"""
Pure Python robot kinematics implementation
"""

import numpy as np
import math
from scipy.spatial.transform import Rotation as R

# Hardware drivers are optional (only needed when actually controlling hardware)
try:
    from driver.ftservo_controller import ServoController
    from driver.ftservo_driver import FTServo
except ImportError:
    ServoController = None
    FTServo = None

# Support direct execution and module import
try:
    from .et import ET, ETS
    from .solvers import IK_LM, IK_GN, IK_NR, IK_QP
    from .utils import IKResult
except ImportError:
    # 直接运行时使用绝对导入
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from ik.et import ET, ETS
    from ik.solvers import IK_LM, IK_GN, IK_NR, IK_QP
    from ik.utils import IKResult


def atan2(first, second):
    """atan2 with 3 decimal places preserved"""
    return round(math.atan2(first, second), 3)


def sin(radians_angle):
    """sin with 3 decimal places preserved"""
    return round(math.sin(radians_angle), 3)


def cos(radians_angle):
    """cos with 3 decimal places preserved"""
    return round(math.cos(radians_angle), 3)


def acos(value):
    """acos with 3 decimal places preserved"""
    return round(math.acos(value), 3)


class Robot:
    """
    Robot wrapper class providing API compatible with roboticstoolbox
    
    Attributes
    ----------
    ets : ETS
        Elementary Transform Sequence
    n : int
        Number of joints
    qlim : np.ndarray
        Joint limits (2, n)
    joint_names : list
        List of joint names
    gear_sign : dict
        Direction signs for each joint (+1/-1)
    gear_ratio : dict
        Gear ratios for each joint
    """
    
    def __init__(self, ets, qlim=None, joint_names=None, gear_sign=None, gear_ratio=None):
        """
        初始化机器人模型
        
        Parameters
        ----------
        ets : ETS
            机器人运动学链
        qlim : np.ndarray, optional
            Joint limits (2, n), first row is lower limits, second row is upper limits
        joint_names : list, optional
            List of joint names
        gear_sign : dict, optional
            Direction signs for each joint
        gear_ratio : dict, optional
            Gear ratios for each joint
        """
        self.ets = ets
        self.n = ets.n
        self.qlim = qlim
        self.joint_names = joint_names or [f"joint_{i}" for i in range(self.n)]
        self.gear_sign = gear_sign or {name: +1 for name in self.joint_names}
        self.gear_ratio = gear_ratio or {name: 1.0 for name in self.joint_names}
        
        # Lazy initialization of ServoController (only when needed)
        self._servo = None
        
        # Set qlim on ETS object (IK solver reads from ets.qlim)
        if qlim is not None:
            self.ets.qlim = qlim
    
    def set_servo_controller(self, controller):
        """
        手动设置 ServoController 实例
        
        Parameters
        ----------
        controller : ServoController
            舵机控制器实例
        """
        self._servo = controller
    
    @property
    def servo(self):
        """懒加载 ServoController"""
        if self._servo is None:
            try:
                # 寻找 servo_config.json 的正确路径
                import os
                config_paths = [
                    "servo_config.json",
                    "driver/servo_config.json",
                    os.path.join(os.path.dirname(__file__), "..", "driver", "servo_config.json"),
                    os.path.join(os.path.dirname(__file__), "..", "servo_config.json"),
                ]
                
                config_path = None
                for path in config_paths:
                    if os.path.exists(path):
                        config_path = path
                        break
                
                if config_path is None:
                    print(f"⚠️ 无法找到 servo_config.json，尝试的路径: {config_paths}")
                    return None
                
                self._servo = ServoController(
                    port="/dev/ttyACM0",
                    baudrate=1_000_000,
                    config_path=config_path
                )
            except Exception as e:
                print(f"⚠️ 无法初始化 ServoController: {e}")
                self._servo = None
        return self._servo

    def q_to_servo_targets(self, q_rad, joint_names=None, home_pose=None, 
                            counts_per_rev=4096, gear_ratio=None, gear_sign=None):
        """
        将关节角度（弧度）转换为舵机目标步数
        
        Parameters
        ----------
        q_rad : array-like
            关节角度数组（弧度）
        joint_names : list of str
            关节名称列表
        home_pose : dict, optional
            各关节的中位步数 {"joint_name": home_position}
            若为 None，则使用 self.servo.home_pose
        counts_per_rev : int
            每转编码器计数（默认4096）
        gear_ratio : dict, optional
            齿轮比 {"joint_name": ratio}
        gear_sign : dict, optional
            方向符号 {"joint_name": +1 or -1}
        
        Returns
        -------
        targets : dict
            舵机目标位置 {"joint_name": target_steps}
        """
        # 如果未提供 home_pose，从 servo 获取
        if home_pose is None:
            if self.servo is None:
                raise ValueError("home_pose 必须提供，或者 ServoController 必须可用")
            home_pose = self.servo.home_pose
        
        if gear_ratio is None:
            gear_ratio = self.gear_ratio
            
        if gear_sign is None:
            gear_sign = self.gear_sign
        if joint_names is None:
            joint_names = self.joint_names
        counts_per_rad = counts_per_rev / (2 * 3.141592653589793)  # 2*pi
        targets = {}
        
        for i, name in enumerate(joint_names):
            steps = int(round(
                home_pose[name] + 
                gear_sign[name] * gear_ratio[name] * q_rad[i] * counts_per_rad
            ))
            targets[name] = steps
        
        return targets
    def read_joint_angles(self, joint_names=None, home_pose=None, gear_sign=None, verbose=True):
        """
        读取舵机实际位置并计算关节角度
        
        Parameters
        ----------
        joint_names : list of str
            关节名称列表
        home_pose : dict, optional
            各关节的中位步数 {"joint_name": home_position}
            若为 None，则使用 self.servo.home_pose
        gear_sign : dict, optional
            方向符号 {"joint_name": +1 or -1}，默认为 self.gear_sign
        verbose : bool
            是否打印详细信息（默认 True）
        
        Returns
        -------
        q : np.ndarray
            关节角度数组（弧度）
        """
        if self.servo is None:
            raise RuntimeError("ServoController 不可用，无法读取舵机位置")
        
        # 如果未提供，使用默认值
        if joint_names is None:
            joint_names = self.joint_names
        if gear_sign is None:
            gear_sign = self.gear_sign
        if home_pose is None:
            home_pose = self.servo.home_pose
        positions = self.servo.read_servo_positions(joint_names=joint_names, verbose=False)
        q = np.zeros(len(joint_names))
        counts_per_rad = 4096 / (2 * np.pi)
        
        if verbose:
            print("\n📡 读取关节角度:")
        
        for i, name in enumerate(joint_names):
            current = positions[name]
            delta = current - home_pose[name]
            q[i] = gear_sign[name] * delta / counts_per_rad
            
            if verbose:
                print(f" {name:15s} : 步数={current:4d}, Δ={delta:+5d} → q={q[i]:+.4f} rad ")
        
        return q


    
    def fkine(self, q):
        """
        正运动学计算
        
        Parameters
        ----------
        q : array_like
            关节角度
            
        Returns
        -------
        np.ndarray
            4x4 齐次变换矩阵
        """
        return self.ets.fkine(q)

    def fk(self, qpos_data, joint_indices=None):
        """
        并返回末端执行器位姿向量 [X, Y, Z, Roll, Pitch, Yaw]

        Parameters
        ----------
        qpos_data : np.ndarray
            关节角度向量（可以比机器人关节多，会根据 joint_indices 提取）
        joint_indices : list or np.ndarray, optional
            要使用的关节索引。如果为 None，则使用前 n 个关节

        Returns
        -------
        np.ndarray
            末端执行器位姿 [X, Y, Z, Roll, Pitch, Yaw]
        """
        # 如果提供了关节索引，使用索引提取关节角度
        if joint_indices is not None:
            if max(joint_indices) >= len(qpos_data):
                raise Exception(
                    f"Joint index {max(joint_indices)} out of range for qpos_data "
                    f"with length {len(qpos_data)}"
                )
            q = qpos_data[joint_indices]
        else:
            # 否则，检查长度并提取前 n 个
            if len(qpos_data) < self.n:
                raise Exception(
                    f"The dimensions of qpos_data ({len(qpos_data)}) "
                    f"is less than the robot joint dimensions ({self.n})"
                )
            q = qpos_data[:self.n]

        # 计算正运动学，获取齐次变换矩阵
        T = self.fkine(q)

        # 提取位置
        X, Y, Z = T[0, 3], T[1, 3], T[2, 3]

        # 提取旋转矩阵并计算欧拉角 (XYZ -> Roll, Pitch, Yaw)
        R_mat = T[:3, :3]

        beta = atan2(-R_mat[2, 0], math.sqrt(R_mat[0, 0]**2 + R_mat[1, 0]**2))

        if cos(beta) != 0:
            alpha = atan2(R_mat[1, 0] / cos(beta), R_mat[0, 0] / cos(beta))
            gamma = atan2(R_mat[2, 1] / cos(beta), R_mat[2, 2] / cos(beta))
        else:
            # 万向节锁情况
            alpha = 0
            gamma = atan2(R_mat[0, 1], R_mat[1, 1])

        return np.array([X, Y, Z, gamma, beta, alpha])
    
    def ikine_LM(self, Tep, q0=None, ilimit=100, slimit=10, tol=1e-3, mask=None, 
                 k=1.0, method='chan'):
        """
        使用 Levenberg-Marquardt 方法求解逆运动学
        
        Parameters
        ----------
        Tep : np.ndarray
            目标位姿 (4x4 齐次变换矩阵)
        q0 : array_like, optional
            初始关节角度，默认为零向量
        ilimit : int
            最大迭代次数
        slimit : int
            搜索次数限制
        tol : float
            收敛容差
        mask : array_like, optional
            位姿权重 [x, y, z, roll, pitch, yaw]，0 表示忽略该维度
        k : float
            LM 阻尼系数
        method : str
            LM 更新方法 ('chan', 'wampler', 'sugihara')
        hardware : bool
            是否使用 FPGA 硬件加速（需在 PYNQ 板上运行）
        bitstream_path : str, optional
            FPGA bitstream 文件路径 (e.g., "design_3.bit")
        ip_name : str
            FPGA IP 核名称
            
        Returns
        -------
        IKResult
            求解结果，包含 .success, .q, .reason 属性
        """
        if q0 is None:
            q0 = np.zeros(self.n)
        
        
        # 使用软件版本
        if not hardware:
            solver = IK_LM(ilimit=ilimit, slimit=slimit, tol=tol, k=k, method=method)
            
            # 构建默认 mask
            if mask is None:
                mask = np.ones(6)
            else:
                mask = np.asarray(mask)
            
            # 求解
            sol = solver.solve(self.ets, Tep, q0=q0, mask=mask)
            
            return IKResult(
                success=sol.success,
                q=sol.q,
                reason=sol.reason,
                iterations=sol.iterations,
                final_error=sol.residual
            )
    
    def ikine_GN(self, Tep, q0=None, ilimit=50, tol=1e-3, mask=None, pinv=False):
        """
        使用 Gauss-Newton 方法求解逆运动学
        
        Parameters
        ----------
        Tep : np.ndarray
            目标位姿 (4x4 齐次变换矩阵)
        q0 : array_like, optional
            初始关节角度
        ilimit : int
            最大迭代次数
        tol : float
            收敛容差
        mask : array_like, optional
            位姿权重
        pinv : bool
            是否使用伪逆
            
        Returns
        -------
        IKResult
            求解结果
        """
        if q0 is None:
            q0 = np.zeros(self.n)
        
        solver = IK_GN(ilimit=ilimit, tol=tol, pinv=pinv)
        
        if mask is None:
            mask = np.ones(6)
        else:
            mask = np.asarray(mask)
        
        sol = solver.solve(self.ets, Tep, q0=q0, mask=mask)
        return IKResult(sol.success, sol.q, sol.reason)
    
    def ikine_NR(self, Tep, q0=None, ilimit=50, tol=1e-3, mask=None, pinv=False):
        """使用 Newton-Raphson 方法求解逆运动学"""
        if q0 is None:
            q0 = np.zeros(self.n)
        
        solver = IK_NR(ilimit=ilimit, tol=tol, pinv=pinv)
        
        if mask is None:
            mask = np.ones(6)
        else:
            mask = np.asarray(mask)
        
        sol = solver.solve(self.ets, Tep, q0=q0, mask=mask)
        return IKResult(sol.success, sol.q, sol.reason)
    
    def ikine_QP(self, Tep, q0=None, ilimit=50, tol=1e-3, mask=None, 
                 kj=0.01, ks=1.0):
        """使用二次规划方法求解逆运动学"""
        if q0 is None:
            q0 = np.zeros(self.n)
        
        solver = IK_QP(ilimit=ilimit, tol=tol, kj=kj, ks=ks)
        
        if mask is None:
            mask = np.ones(6)
        else:
            mask = np.asarray(mask)
        
        sol = solver.solve(self.ets, Tep, q0=q0, mask=mask)
        return IKResult(sol.success, sol.q, sol.reason)


def create_so101_5dof():
    """
    SO-101 五自由度机械臂（基于 URDF 简化结构）ET 建模
    包含关节限位（通过 ERobot.qlim 设置）
    """

    # ---------------------------
    # 1) URDF 同步的关节限位
    # ---------------------------
    qlim = np.array([
        [-1.91986, -1.74533, -1.69,    -1.65806, -2.74385],
        [ 1.91986,  1.74533,  1.69,     1.65806,  2.84121]
    ])


    # E1 = ET.tx(0.002798)
    # E2 = ET.tz(0.05031)
    # E3 = ET.Rz()
    
    # # to joint 2
    # E4 = ET.tx(0.02957)
    # E5 = ET.tz(0.11590)
    # E6 = ET.Ry()
    
    # # to joint 3
    # E7 = ET.tx(0.11323)
    # E8 = ET.tz(0.00500)
    # E9 = ET.Ry()

    # # to joint 4
    # E10 = ET.tx(0.0650)
    # E11 = ET.tz(0.00519)
    # E12 = ET.Ry()
    
    # # to joint 5
    # E13 = ET.tx(0.02413)
    # E14 = ET.tz(0)
    # E15 = ET.Rx()  
    
    # E17 = ET.tx(0.07440)
        # to joint 1
    E1 = ET.tx(0.0612)
    E2 = ET.tz(0.0598)
    E3 = ET.Rz()
    
    # to joint 2
    E4 = ET.tx(0.02943)
    E5 = ET.tz(0.05504)
    E6 = ET.Ry()
    
    # to joint 3
    E7 = ET.tz(0.1127)
    E8 = ET.tx(0.02798)
    E9 = ET.Ry()

    # to joint 4
    E10 = ET.tx(0.15504)
    E11 = ET.tz(0.00519)
    E12 = ET.Ry()
    
    # to joint 5
    E13 = ET.tx(0.0593)
    E14 = ET.tz(0.00996)
    E15 = ET.Rx()  
    
    #E17 = ET.tx(0.09538)
    # to gripper

    ets = E1 * E2 * E3 *E4 * E5 * E6 * E7 * E8 * E9 * E10 * E11 * E12 * E13 * E14 * E15 

    
    # 关节名称
    joint_names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
    
    # 各关节的方向符号 (+1/-1)
    gear_sign = {
        "shoulder_pan": -1,
        "shoulder_lift": +1,
        "elbow_flex":   +1,
        "wrist_flex":   -1,
        "wrist_roll":   +1,
    }
    
    # 各关节的减速比
    gear_ratio = {
        "shoulder_pan": 1.0,
        "shoulder_lift": 1.0,
        "elbow_flex":   1.0,
        "wrist_flex":   1.0,
        "wrist_roll":   1.0,
    }
    
    return Robot(ets, qlim, joint_names=joint_names, gear_sign=gear_sign, gear_ratio=gear_ratio)
def create_so101_5dof_gripper():
    """

    """

    # ---------------------------
    # 1) URDF 同步的关节限位
    # ---------------------------
    qlim = np.array([
        [-1.91986, -1.74533, -1.69,    -1.65806, -2.74385],
        [ 1.91986,  1.74533,  1.69,     1.65806,  2.84121]
    ])


    # E1 = ET.tx(0.002798)
    # E2 = ET.tz(0.05031)
    # E3 = ET.Rz()
    
    # # to joint 2
    # E4 = ET.tx(0.02957)
    # E5 = ET.tz(0.11590)
    # E6 = ET.Ry()
    
    # # to joint 3
    # E7 = ET.tx(0.11323)
    # E8 = ET.tz(0.00500)
    # E9 = ET.Ry()

    # # to joint 4
    # E10 = ET.tx(0.0650)
    # E11 = ET.tz(0.00519)
    # E12 = ET.Ry()
    
    # # to joint 5
    # E13 = ET.tx(0.02413)
    # E14 = ET.tz(0)
    # E15 = ET.Rx()  
    
    # E17 = ET.tx(0.07440)
        # to joint 1
    E1 = ET.tx(0.0612)
    E2 = ET.tz(0.0598)
    E3 = ET.Rz()
    
    # to joint 2
    E4 = ET.tx(0.02943)
    E5 = ET.tz(0.05504)
    E6 = ET.Ry()
    
    # to joint 3
    E7 = ET.tx(0.02798)
    E8 = ET.tz(0.1127)
    E9 = ET.Ry()

    # to joint 4
    E10 = ET.tx(0.13504)
    E11 = ET.tz(0.00519)
    E12 = ET.Ry()
    
    # to joint 5
    E13 = ET.tx(0.0593)
    E14 = ET.tz(0.00996)
    E15 = ET.Rx()  
    
    E17 = ET.tx(0.1)
    # to gripper

    ets = E1 * E2 * E3 *E4 * E5 * E6 * E7 * E8 * E9 * E10 * E11 * E12 * E13 * E14 * E15 * E17

    
    # 关节名称
    joint_names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
    
    # 各关节的方向符号 (+1/-1)
    gear_sign = {
        "shoulder_pan": -1,
        "shoulder_lift": +1,
        "elbow_flex":   +1,
        "wrist_flex":   -1,
        "wrist_roll":   +1,
    }
    
    # 各关节的减速比
    gear_ratio = {
        "shoulder_pan": 1.0,
        "shoulder_lift": 1.0,
        "elbow_flex":   1.0,
        "wrist_flex":   1.0,
        "wrist_roll":   1.0,
    }
    
    return Robot(ets, qlim, joint_names=joint_names, gear_sign=gear_sign, gear_ratio=gear_ratio)

def create_so101():
    # to joint 1
    E1 = ET.tx(0.0612)
    E2 = ET.tz(0.0598)
    E3 = ET.Rz()
    
    # to joint 2
    E4 = ET.tx(0.02943)
    E5 = ET.tz(0.05504)
    E6 = ET.Ry()
    
    # to joint 3
    E7 = ET.tz(0.1127)
    E8 = ET.tx(0.02798)
    E9 = ET.Ry()

    # to joint 4
    E10 = ET.tx(0.13504)
    E11 = ET.tz(0.00519)
    E12 = ET.Ry()
    
    # to joint 5
    E13 = ET.tx(0.0593)
    E14 = ET.tz(0.00996)
    E15 = ET.Rx()  
    
    E17 = ET.tx(0.09538)
    # to gripper
   
    ets = E4 * E5 * E6 * E7 * E8 * E9 * E10 * E11 * E12 * E13 * E14 * E15 # E1 * E2 * E3 * E17 
    joint_names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
    # Set joint limits
    qlim = [[-1.57, -1.57, -1.5, -3.14158], 
                  [ 1.57,  1.57,  1.5,  3.14158]]
    gear_sign = {
        "shoulder_pan": -1,
        "shoulder_lift": +1,
        "elbow_flex":   +1,
        "wrist_flex":   -1,
        "wrist_roll":   +1,
    }
    
    # 各关节的减速比
    gear_ratio = {
        "shoulder_pan": 1.0,
        "shoulder_lift": 1.0,
        "elbow_flex":   1.0,
        "wrist_flex":   1.0,
        "wrist_roll":   1.0,
    }
    
    return Robot(ets, qlim, joint_names=joint_names, gear_sign=gear_sign, gear_ratio=gear_ratio)



def get_robot(robot="so101"):
    """
    获取指定的机器人模型
    
    Parameters
    ----------
    robot : str
        机器人类型： 'so101_5dof'
        
    Returns
    -------
    ETS or None
        机器人的运动学模型
    """

    if robot == "so101_5dof":
        return create_so101_5dof()
    else:
        print(f"Sorry, we don't support {robot} robot now")
        return None

def smooth_joint_motion(q_now, q_new, robot, max_joint_change=0.1):
    """
    平滑关节运动，限制单步最大变化量
    
    Parameters
    ----------
    q_now : np.ndarray
        当前关节角度
    q_new : np.ndarray
        新的关节角度
    robot : ETS
        机器人运动学模型
    max_joint_change : float
        单步允许的最大关节变化量
        
    Returns
    -------
    np.ndarray
        平滑后的关节角度
    """
    q_smoothed = q_new.copy()
    
    for i in range(len(q_new)):
        delta = q_new[i] - q_now[i]
        if abs(delta) > max_joint_change:
            delta = np.sign(delta) * max_joint_change
        q_smoothed[i] = q_now[i] + delta
    
    return q_smoothed


if __name__ == "__main__":
    robot = create_so101_5dof()
    qpos_data = np.array([0.0, -0.5, 0.5, 0.0, 0.0])
    T = robot.fkine(qpos_data)
    print(T)

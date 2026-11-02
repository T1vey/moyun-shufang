"""Original E1pco HWSolver + original FPGA ABI, with drawing task adaptation."""
import json
from pathlib import Path
import time
from types import SimpleNamespace
import numpy as np
from upstream_runtime import load_upstream

TOP = 'xf_solver_lm_so101'
ABI = 'e1pco-so101-lm-v1'
DRAWING_MASK = np.array([1.,1.,1.,.05,.05,.05], dtype=np.float32)
FIELDS = {**{'sin'+str(i):0x10+8*i for i in range(5)},
          **{'cos'+str(i):0x38+8*i for i in range(5)},
          **{'e'+str(i):0x60+8*i for i in range(6)},
          'lambda':0x90, **{'d'+str(i):0x98+16*i for i in range(5)}, 'status':0xE8}


def validate_map(registers):
    if registers.get('abi') != ABI or registers.get('top') != TOP:
        raise ValueError('需要上游 xf_solver_lm_so101 的寄存器映射，请用 export_upstream_register_map.py')
    occupied = {0,4,8,12}
    for field in FIELDS:
        offset = registers.get(field)
        if type(offset) is not int or offset < 16 or offset % 4 or offset in occupied:
            raise ValueError('无效上游寄存器：'+field)
        occupied.add(offset)
    return max(occupied)+4


class RegisterBridge:
    """Map original wrapper offsets to the actual generated HLS header."""
    def __init__(self, mmio, registers, timeout_s=.5):
        validate_map(registers)
        self.mmio = mmio
        self.mapping = {old:registers[field] for field,old in FIELDS.items()}
        self.timeout_s, self.deadline = timeout_s, None
        self.faulted, self.error = False, None

    def write(self, address, value):
        if self.faulted:
            raise FloatingPointError('上游 PL 已故障，请重载 overlay')
        if address == 0:
            self.mmio.read(0)  # clear stale AP_DONE before a new request
            self.deadline = time.monotonic()+self.timeout_s
            return self.mmio.write(0,value)
        return self.mmio.write(self.mapping[address],value)

    def read(self, address):
        if address != 0:
            return self.mmio.read(self.mapping[address])
        # Original code polls by loop count. Bound one call by wall-clock time
        # so slow Python hosts and fast hosts get the same timeout policy.
        while True:
            value = self.mmio.read(0)
            if value & 2:
                return value
            if self.deadline is None or time.monotonic() >= self.deadline:
                self.faulted = True
                raise TimeoutError('上游 PL timeout')
            time.sleep(.00005)


class HostIterator:
    """Equation reference only: upstream ET + NumPy, not FPGA cycle emulation."""
    def __init__(self, robot):
        self.robot = robot
    def solve_step(self,q,error,lambda_damping=.01):
        q = np.asarray(q,dtype=np.float32)
        j = self.robot.ets.jacob0(q).astype(np.float32)
        a = j.T@j + np.float32(lambda_damping)*np.eye(5,dtype=np.float32)
        b = j.T@np.asarray(error,dtype=np.float32)
        try:
            return np.linalg.solve(a,b), 0
        except np.linalg.LinAlgError:
            return np.zeros(5), 1


def align_axis(rotation, local_axis, desired):
    """Nearest rotation satisfying the pen axis, leaving axial roll free."""
    current = rotation@local_axis
    cross = np.cross(current,desired)
    sine, cosine = np.linalg.norm(cross), float(np.clip(np.dot(current,desired),-1,1))
    if sine < 1e-10:
        if cosine > 0:
            return rotation.copy()
        axis = np.eye(3)[int(np.argmin(np.abs(current)))]
        axis = np.cross(current,axis); axis /= np.linalg.norm(axis)
        return (2*np.outer(axis,axis)-np.eye(3))@rotation
    axis = cross/sine
    x,y,z = axis
    k = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return (np.eye(3)+sine*k+(1-cosine)*(k@k))@rotation


class UpstreamBackend:
    def __init__(self, bitfile=None, ip_name='xf_solver_lm_so101_0', mmio=None, registers=None, timeout_s=.5):
        if not np.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('Invalid PL timeout')
        robot_module, self.wrapper, _ = load_upstream()
        self.robot = robot_module.create_so101_5dof()
        self.calls, self.total_s = 0, 0.
        self.bridge = None
        if bitfile is not None:
            from pynq import Overlay
            bitfile = Path(bitfile).resolve()
            if not bitfile.is_file() or not bitfile.with_suffix('.hwh').is_file():
                raise ValueError('提供实际 CLG400 板卡的 bit/hwh')
            registers = json.loads(bitfile.with_suffix('.registers.json').read_text(encoding='utf-8'))
            required = validate_map(registers)
            self.overlay = Overlay(str(bitfile),download=False)
            desc = self.overlay.ip_dict.get(ip_name,{})
            parts = str(desc.get('type','')).split(':')
            if len(parts) != 4 or parts[2] != TOP or desc.get('addr_range',0) < required:
                raise ValueError('上游版本只接 xf_solver_lm_so101；检查 IP 名称、类型和地址范围')
            self.overlay.download()
            mmio = getattr(self.overlay,ip_name).mmio
        if mmio is None:
            self.iterator = HostIterator(self.robot)
            self.name = 'UPSTREAM_HOST_EQUATION_REFERENCE'
        else:
            self.bridge = RegisterBridge(mmio,registers,timeout_s)
            self.iterator = self.wrapper.HWSolverIterator(SimpleNamespace(mmio=self.bridge),self.robot)
            self.name = 'PL_UPSTREAM_xf_solver_lm_so101'

    def metrics(self):
        return dict(calls=self.calls,total_s=self.total_s,backend=self.name,
                    solver='unmodified E1pco HWSolver.solve',task='projected pen-axis / flange goal')

    def validate_model(self,model):
        # The original HLS hard-codes flange geometry. Tool offsets are handled
        # in task conversion; link offsets/axes must still match the kernel.
        from planning import load
        nominal = load('nominal_so101.json')
        if not np.allclose(model.offsets,nominal['offsets_m'],atol=1e-10,rtol=0) or not np.allclose(model.axes,nominal['axes'],atol=1e-10,rtol=0):
            raise ValueError('上游核固定连杆/转轴；修改几何后需要同步修改 HLS。笔尖偏移可在软件配置。')

    def solve_target(self,model,position,axis,q0,config,cancel=None):
        from r1a.solve import Result
        from r1a.model import finite_array
        self.validate_model(model)
        position = finite_array(position,(3,),'position')
        axis = finite_array(axis,(3,),'axis')
        if not np.isclose(np.linalg.norm(axis),1.,atol=1e-8):
            raise ValueError('pen axis must be unit length')
        q = finite_array(q0,(5,),'q').copy()
        history = []
        calls = [0]
        goal = np.eye(4)
        def result(status):
            p,t = model.pose_errors(model.pose(q),position,axis)
            return Result(status,q.tolist() if status=='OK' else None,q.tolist(),calls[0],p,t,history)
        owner = self
        class Reached(Exception):
            pass
        class ProjectedRobot:
            def fkine(self, angles):
                nonlocal q
                if cancel and cancel():
                    raise InterruptedError('ABORT')
                angles = finite_array(angles,(5,),'upstream q')
                if not model.legal(angles):
                    raise ValueError('上游 IK 关节超限')
                q = angles.copy()
                pose = owner.robot.fkine(angles)
                goal[:3,:3] = align_axis(pose[:3,:3],model.tool_axis,axis)
                goal[:3,3] = position-goal[:3,:3]@model.tool
                p,t = model.pose_errors(model.pose(q),position,axis)
                history.append(dict(iteration=calls[0],q=q.tolist(),position_m=p,tilt_rad=t))
                if p <= config['position_tolerance_m'] and t <= config['tilt_tolerance_rad']:
                    raise Reached()
                return pose
        class GuardedIterator:
            def solve_step(self, angles, error, lambda_damping):
                if cancel and cancel():
                    raise InterruptedError('ABORT')
                dq,status = owner.iterator.solve_step(angles,error,lambda_damping)
                calls[0] += 1; owner.calls += 1
                if status or not np.isfinite(dq).all():
                    raise FloatingPointError('上游核求解失败 status='+str(status))
                dq = np.asarray(dq,dtype=float)
                dq *= min(1.,config['max_joint_step_rad']/max(np.max(np.abs(dq)),1e-30))
                # Truncate to the legal box; retain original direction within it.
                ratios = [1.]
                for i,d in enumerate(dq):
                    if d > 0: ratios.append((model.limits[i,1]-angles[i])/d)
                    elif d < 0: ratios.append((model.limits[i,0]-angles[i])/d)
                return dq*max(0.,min(ratios))*.999999,0
        started = time.monotonic()
        try:
            if not model.legal(q):
                return result('INVALID_INPUT')
            solver = self.wrapper.HWSolver(ProjectedRobot(),GuardedIterator())
            # Original wrapper weights only the RHS (J.T @ mask @ e), while
            # HLS retains J.T @ J. This is its error-feedback policy, not WLS.
            # Drawing de-emphasizes orientation but accepts both physical gates.
            tolerance = .125*min(config['position_tolerance_m'],config['tilt_tolerance_rad'])**2
            answer = solver.solve(goal,q0=q,ilimit=config['max_iterations'],slimit=1,
                                  tol=tolerance,mask=DRAWING_MASK,k=config['mu'],verbose=False)
            # Use the observed, unwrapped q rather than angle normalization that
            # could introduce a branch jump. Physical errors define acceptance.
            out = result('OK')
            if out.position_error_m > config['position_tolerance_m'] or out.tilt_error_rad > config['tilt_tolerance_rad']:
                return result('MAX_ITER' if not answer.success else 'TASK_ERROR')
            return out
        except Reached:
            return result('OK')
        except InterruptedError:
            return result('ABORT')
        except (FloatingPointError,ValueError,np.linalg.LinAlgError):
            return result('NUMERIC')
        finally:
            self.total_s += time.monotonic()-started

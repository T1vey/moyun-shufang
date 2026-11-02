"""Image, planning and physical-debug jobs owned by the PS application."""
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
from protocol import DemoPort, ProbeError
from motion import Executor, read_all, validate_machine, counts_from_angles
from plan_storage import load_history_plan, remove_history_manifest, save_history_manifest


class StoredPlan:
    """从磁盘恢复的规划: 执行器只需要 status / commands / metrics。"""

    def __init__(self, doc):
        self.status = doc.get('status')
        self.commands = doc.get('commands') or []
        self.metrics = dict(doc.get('metrics') or {})
        self.targets = None
        self.diagnostics = None
        self.physical_authorized = False
        self.trajectory_segments = doc.get('trajectory_segments')
        self.execution_contract = doc.get('execution_contract')


class Workbench:
    def __init__(self, state, allow_motion=False):
        self.state = state
        self.allow_motion = allow_motion
        self.backend = None
        self.machine = None
        self.jobs = {}
        # Only published, detached job records live in this dictionary. The
        # worker owns its mutable record until finalization has completed.
        # This short lock is independent of state.lock (held for the whole job).
        self._jobs_lock = threading.Lock()
        self.plans = {}
        self.cancel = threading.Event()
        self.heartbeat_at = time.monotonic()
        self.active = None
        self.worker = None
        self._save_states = {}
        self._save_threads = []
        self._save_shutdown = threading.Event()
        self._save_pause = threading.Event()
        self.demo = DemoPort()
        state.demo = self.demo
        self.config_file = state.directory.parent / "machine.json"
        if self.config_file.is_file():
            self.machine = json.loads(self.config_file.read_text(encoding="utf-8"))
        # 规划持久化: 服务重启后仍可复用以前生成的规划
        self.plans_dir = state.directory.parent / "saved_plans"
        try:
            self.plans_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._load_saved_plans()

    # ---------------- 规划持久化 ----------------
    def _queue_plan_save(self, job_id, stored, folder):
        """A completed immutable in-memory plan remains usable if disk fails."""
        from app import utc_now
        # Only metrics are still used as job diagnostics; freeze their small
        # nested dictionaries. Owned commands/curves are read-only after build.
        from types import SimpleNamespace
        frozen = SimpleNamespace(**dict(vars(stored['result']), metrics=copy.deepcopy(stored['result'].metrics)))
        metadata = {k: stored.get(k) for k in ('mode','digest','port','baudrate','machine','paths','drawing')}
        metadata.update(job_id=job_id, saved_utc=utc_now(), q0=list(stored['q0']), status='OK', metrics=frozen.metrics)
        state = dict(status='pending', saved_utc=None)
        self._save_states[job_id] = state
        def checkpoint():
            while self._save_pause.is_set():
                if self._save_shutdown.wait(.05): raise ValueError('ABORT: service stopping')
            if self._save_shutdown.is_set(): raise ValueError('ABORT: service stopping')
        def save():
            started = time.perf_counter()
            try:
                # A normal Python object is weak-referenceable (SimpleNamespace
                # is not), as required by the publication receipt registry.
                snapshot = StoredPlan(vars(frozen))
                snapshot.__dict__.update(vars(frozen))
                from plan_storage import publish_execution_plan_streamed
                checkpoint()
                publish_execution_plan_streamed(folder/'plan.json', snapshot, self._save_shutdown.is_set, checkpoint)
                checkpoint()
                save_history_manifest(self._plan_path(job_id), metadata, snapshot,
                                      self.state.directory.parent, self._save_shutdown.is_set)
                state.update(status='saved', saved_utc=metadata['saved_utc'], seconds=time.perf_counter()-started)
                self.state.record('PLAN_SAVED', dict(id=job_id, background=True))
                if self.state.lock.acquire(blocking=False):
                    try: self._prune_plans()
                    finally: self.state.lock.release()
            except Exception as exc:
                state.update(status='failed', error=type(exc).__name__, seconds=time.perf_counter()-started)
                # Never discard a complete in-memory plan or change its curve.
                self.state.record('PLAN_SAVE_FAILED', dict(id=job_id, background=True, detail=str(exc)[:160]))
            finally:
                try:
                    (folder/'persistence.json').write_text(json.dumps(state), encoding='utf-8')
                except OSError: pass
        self._save_threads = [t for t in self._save_threads if t.is_alive()]
        thread = threading.Thread(target=save, name='plan-save-'+job_id[:8], daemon=True)
        self._save_threads.append(thread); thread.start()

    def close_persistence(self):
        self._save_shutdown.set(); self._save_pause.clear()
        for thread in self._save_threads: thread.join(2.)

    def _plan_path(self, job_id):
        if not isinstance(job_id, str) or not job_id or any(not (c.isascii() and (c.isalnum() or c in '-_')) for c in job_id):
            raise ValueError('invalid plan job id')
        return self.plans_dir / ("plan_" + str(job_id) + ".json")

    def _save_plan(self, job_id, stored):
        """只保存已完成 plan.json 的校验引用和冻结上下文，不重复写执行轨迹。"""
        published = False
        try:
            from app import utc_now
            result = stored.get('result')
            if result is None or getattr(result, 'status', None) != 'OK' or not getattr(result, 'commands', None):
                return False
            doc = dict(job_id=job_id,
                       saved_utc=utc_now(),
                       mode=stored.get('mode'),
                       digest=stored.get('digest'),
                       port=stored.get('port'),
                       baudrate=stored.get('baudrate'),
                       q0=list(stored.get('q0') or []),
                       status=result.status,
                       metrics=dict(getattr(result, 'metrics', {}) or {}),
                       machine=stored.get('machine'), paths=stored.get('paths'), drawing=stored.get('drawing'))
            save_history_manifest(self._plan_path(job_id), doc, result,
                                  self.state.directory.parent, self.cancel.is_set)
            published = True
            if self.cancel.is_set():
                raise ValueError('ABORT: plan persistence cancelled')
            # 同步回内存: 否则 list_plans() 读不到时间戳, 排序会把新规划排到最后
            stored['saved_utc'] = doc['saved_utc']
            self._prune_plans()
            self.state.record("PLAN_SAVED", dict(id=job_id, commands=len(result.commands),
                                                 bytes=self._plan_path(job_id).stat().st_size))
            return True
        except Exception as exc:
            if published:
                self._discard_plan(job_id)
            stored.pop('saved_utc', None)
            self.state.record("PLAN_SAVE_FAILED", dict(id=job_id, detail=str(exc)))
            return False

    def _discard_plan(self, job_id):
        """Revoke availability only; job artifacts remain available for diagnosis."""
        self.plans.pop(job_id, None)
        remove_history_manifest(self._plan_path(job_id))

    MAX_PLANS = 10

    def _prune_plans(self):
        """只裁剪历史引用，绝不删除任务产物或未关联的执行文件。"""
        try:
            files = sorted(self.plans_dir.glob("plan_*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return
        keep = {p.stem[5:] for p in files[:self.MAX_PLANS]}
        keep.update(k for k,v in self._save_states.items() if v['status'] in ('pending','failed'))
        for old in files[self.MAX_PLANS:]:
            try:
                remove_history_manifest(old)
            except OSError:
                keep.add(old.stem[5:])
        for job_id in list(self.plans):
            if job_id not in keep:
                self.plans.pop(job_id, None)

    def _load_saved_plans(self):
        """启动时把磁盘上的规划读回内存 (digest 不匹配的仍会被执行时拒绝)。"""
        loaded = 0
        try:
            files = sorted(self.plans_dir.glob("plan_*.json"))
        except OSError:
            return
        for path in files:
            try:
                doc = load_history_plan(path, self.state.directory.parent)
                self.plans[doc['job_id']] = dict(
                    result=StoredPlan(doc),
                    q0=doc.get('q0') or [],
                    mode=doc.get('mode'),
                    digest=doc.get('digest'),
                    machine=copy.deepcopy(doc.get('machine') if 'machine' in doc else self.machine),
                    paths=doc.get('paths'), drawing=doc.get('drawing'),
                    port=doc.get('port'),
                    baudrate=doc.get('baudrate'),
                    saved_utc=doc.get('saved_utc'),
                    restored=True)
                loaded += 1
            except Exception:
                continue
        if loaded:
            self.state.record("PLANS_RESTORED", dict(count=loaded))

    def list_plans(self):
        """列出已保存的规划 (含是否与当前标定匹配)。"""
        now = self.digest() if self.machine else None
        out = []
        for job_id, stored in list(self.plans.items()):
            result = stored.get('result')
            metrics = dict(getattr(result, 'metrics', {}) or {})
            from stroke_paths import PIPELINE_VERSION
            needs_replan=(metrics.get('drawing_pipeline_version') != PIPELINE_VERSION
                          or metrics.get('motion_algorithm_version') != 'motion-smooth-v1')
            out.append(dict(id=job_id,
                            saved_utc=self._save_states.get(job_id, {}).get('saved_utc') or stored.get('saved_utc'),
                            ready_utc=stored.get('ready_utc'),
                            persistence=dict(self._save_states.get(job_id, {'status':'saved'})),
                            mode=stored.get('mode'),
                            commands=len(getattr(result, 'commands', []) or []),
                            targets=metrics.get('completed_targets'),
                            total_targets=metrics.get('total_targets'),
                            duration_s=metrics.get('duration_s'),
                            ik_backend=metrics.get('ik_backend'),
                            path_source=metrics.get('path_source'),
                            needs_replan=needs_replan,
                            motion_mode=metrics.get('motion_mode','standard'),
                            motion_algorithm_version=metrics.get('motion_algorithm_version'),
                            digest=stored.get('digest'),
                            matches_current_calibration=bool(now and stored.get('digest') == now),
                            restored=bool(stored.get('restored'))))
        # 时间戳缺失的排到最后 (str(None) 会被当成有效字符串, 必须显式处理)
        out.sort(key=lambda r: str(r.get('saved_utc') or r.get('ready_utc') or ''), reverse=True)
        return dict(plans=out, current_digest=now)

    def prediction_data(self, job_id):
        """Read a plan snapshot without connecting to servos or using today's config."""
        stored = self.plans.get(job_id)
        if not stored:
            raise ValueError('找不到该历史规划')
        if not stored.get('paths') or not stored.get('drawing'):
            raise ValueError('旧规划未保存预测资料，请用当前图片重新规划')
        result = stored['result']
        return copy.deepcopy(dict(job_id=job_id, status=result.status, mode=stored['mode'],
                                  commands=result.commands, metrics=result.metrics,
                                  machine=stored.get('machine'), paths=stored['paths'], drawing=stored['drawing']))

    def prediction_svg(self, job_id):
        """Return a small, finished preview without copying/transporting a plan.

        Plans are frozen after publication. Keep a strong local reference so
        history pruning cannot invalidate an in-progress read.
        """
        stored = self.plans.get(job_id)
        if not stored or not stored.get('paths') or not stored.get('drawing'):
            raise ValueError('找不到该规划的预测资料，请重新规划')
        from user_gui.workflow import prediction_svg
        result = stored['result']
        return prediction_svg(dict(job_id=job_id, status=result.status, mode=stored['mode'],
            commands=result.commands, metrics=result.metrics, machine=stored.get('machine'),
            paths=stored['paths'], drawing=stored['drawing']))

    def digest(self):
        return hashlib.sha256(json.dumps(self.machine, sort_keys=True).encode()).hexdigest()

    def configure(self, data):
        if not self.state.lock.acquire(blocking=False):
            raise RuntimeError("等待当前任务结束后更新标定")
        try:
            if not isinstance(data, dict) or data.get('schema') != 'so101-machine-v1':
                raise ValueError("配置格式不正确")
            if 'pen_tcp_calibration' in (data.get('model') or {}):
                raise ValueError("工具偏移标定已移除，请使用当前纸面几何配置")
            from four_point_calibration import validate
            if ((self.machine or {}).get('paper',{}).get('geometry_mode') == 'four_point'
                    and data.get('paper',{}).get('geometry_mode') != 'four_point'):
                raise ValueError('当前使用四点标定，不能恢复旧三点校正')
            validate(data)
            # Allow incomplete templates to be saved; validate before motion.
            self.config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            self.machine = copy.deepcopy(data)
            # 不再清空 plans: 标定变化由执行时的 digest 校验拒绝, 历史规划保留可查
            self.state.record("CONFIG", {"sha256": self.digest()})
            return {"saved": True, "sha256": self.digest()}
        finally:
            self.state.lock.release()

    def snapshot(self):
        with self._jobs_lock:
            return dict(active=self.active,
                        jobs=copy.deepcopy([self.jobs[k] for k in list(self.jobs)[-12:]]),
                        allow_motion=self.allow_motion, machine_loaded=self.machine is not None)

    def _publish_job(self, job):
        """Publish progress without exposing the worker's mutable result/metrics."""
        published = copy.deepcopy(job)
        with self._jobs_lock:
            self.jobs[job['id']] = published

    def touch(self):
        self.heartbeat_at = time.monotonic()

    def stop(self):
        self.cancel.set()
        return {"stop_requested": True}

    def start(self, kind, data, upload=None):
        from app import utc_now
        if len(self.jobs) >= 100:
            raise ValueError("本会话已达 100 个任务，请导出后重启")
        if not isinstance(data, dict):
            raise ValueError("任务参数必须是对象")
        if kind == 'plan' and data.get('background_save') is True:
            if sum(s['status']=='pending' for s in self._save_states.values()) >= 2:
                raise RuntimeError('历史计划仍在保存，请稍后再规划')
            if sum(s['status']=='failed' for s in self._save_states.values()) >= self.MAX_PLANS:
                raise RuntimeError('历史存储空间异常，请先处理存储问题')
        if not self.state.lock.acquire(blocking=False):
            raise RuntimeError("已有任务运行，请完成或停止后再操作")
        jid = uuid.uuid4().hex
        folder = self.state.directory / ("job_" + jid)
        try:
            folder.mkdir()
            if upload is not None:
                (folder / "upload.dat").write_bytes(upload)
            job = dict(id=jid, kind=kind, status="RUNNING", detail="开始处理", created_utc=utc_now(), mode=data.get('mode'))
            accepted = copy.deepcopy(job)
            self.cancel.clear()
            self.touch()
            with self._jobs_lock:
                self.jobs[jid] = copy.deepcopy(job)
                self.active = jid
            self.state.record("JOB_BEGIN", {"id": jid, "kind": kind, "mode": data.get('mode')})
            (folder/'request.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            if self.machine and data.get('mode') == 'real':
                (folder/'machine.json').write_text(json.dumps(self.machine, ensure_ascii=False, indent=2), encoding='utf-8')
            self.worker = threading.Thread(target=self._run, args=(job, folder, data), daemon=True)
            self.worker.start()
            # The worker may already be updating its private record; return the
            # original acceptance response rather than copying that live record.
            return accepted
        except Exception:
            with self._jobs_lock:
                self.active = None
                self.state.lock.release()
            raise

    def connect(self, data, drawing=False):
        mode = data.get('mode')
        if mode not in ('demo', 'real'):
            raise ValueError("选择运行模式")
        if mode == 'demo':
            from planning import load, nominal
            _, paper, q0 = nominal()
            machine = dict(schema='so101-machine-v1', model=load('nominal_so101.json'), paper=paper,
                           joints=[dict(id=i+1, direction=1, zero_count=2048, min_count=0, max_count=4095) for i in range(5)],
                           checks=dict(limits=True, kinematics=True, single_joint=True), trajectory={})
            if not hasattr(self, 'demo_initialized'):
                self.demo.positions.update(counts_from_angles(machine, q0))
                self.demo_initialized = True
            return self.demo, machine
        from app import validate_scan
        if not self.allow_motion and drawing != 'plan':
            raise ValueError("启动时加 --allow-motion 开放实物调试")
        joints = validate_machine(self.machine, drawing=bool(drawing))
        scan = dict(mode='real', port=data.get('port'), baudrate=data.get('baudrate'),
                    confirmed=data.get('confirmed'), ids=[j['id'] for j in joints])
        validate_scan(scan, self.state.allow_real)
        return self.state.real_factory(scan['port'], scan['baudrate']), copy.deepcopy(self.machine)

    def _ensure_torque(self, device, machine, executor):
        """确保舵机扭矩已开启 (归位/绘画的前提)。

        未开启时自动"启用保持": 先读当前位置并作为目标下发, 再打开扭矩,
        所以机械臂不会跳动。返回 True 表示本次自动开启了扭矩。
        """
        try:
            read_all(device, machine, preflight=True, need_torque=True)
            return False                      # 已开启, 无需处理
        except ValueError as exc:
            if '尚未启用扭矩' not in str(exc):
                raise
        counts = executor.enable()
        self.state.record("AUTO_ENABLE", dict(detail='归位/绘画前自动启用扭矩并保持当前位置',
                                              counts=counts))
        return True

    def _home_move(self, device, machine, executor):
        """平滑移回绘画起始位 (与 /api/home 完全相同的动作), 夹爪保持不动。

        paper.home_height_offset_m 可把起始姿态沿纸面法向抬高 (米)。
        """
        from planning import nominal, home_pose
        _, _, default_q0 = nominal()
        from planning import Model
        model, paper = Model(machine['model']), machine['paper']
        q0 = machine.get('home_q_rad',default_q0)
        lift = float((machine.get("paper") or {}).get("home_height_offset_m", 0.0) or 0.0)
        if lift:
            self.state.record("HOME_LIFT", dict(metres=lift))
        q0 = home_pose(model, paper, q0, lift, backend=self.backend)
        end = counts_from_angles(machine, q0)
        return executor.move_pen_up_to(end,backend=self.backend)

    def _run(self, job, folder, data):
        # Also detach records when _run is invoked directly (offline checks).
        self._publish_job(job)
        device = None
        pending_plan = None
        job_started = time.perf_counter()
        if job['kind'] in ('execute','home','jog','enable'):
            self._save_pause.set()
        try:
            kind = job['kind']
            if kind == 'image':
                from vision import convert
                result = convert(folder / 'upload.dat', folder, data.get('style', 'lineart'),
                                 float(data.get('width_mm', 20)), float(data.get('height_mm', 20)), int(data.get('max_segments', 4000)),
                                 detail=data.get('detail', 'fine'))
                job.update(result={k: v for k, v in result.items() if k != 'paths'}, detail='连续笔画已生成', preview='paths.svg')
            elif kind == 'preset':
                from vision import preset
                result = preset(data.get('name', 'line'), folder, float(data.get('width_mm', 20)), float(data.get('height_mm', 20)))
                job.update(result={k:v for k,v in result.items() if k != 'paths'}, detail='预设笔画已生成', preview='paths.svg')
            elif kind == 'strokes':
                # PC 端已完成图像处理，板卡只登记结果（板卡无 ezdxf/svgpathtools 时的标准路径）
                raw = data.get('paths')
                if not isinstance(raw, dict) or not raw.get('paths'):
                    raise ValueError("缺少 paths 笔画数据")
                from stroke_paths import validate_paths,path_digest,save_preview
                stroke_count,segment_count=validate_paths(raw)
                claimed=raw.get('path_sha256')
                if claimed and claimed != path_digest(raw):
                    raise ValueError('笔画摘要与上传数据不一致，请重新提取')
                raw=dict(raw,strokes=stroke_count,segments=segment_count,path_sha256=path_digest(raw))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'paths.json').write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
                save_preview(raw,folder)
                job.update(result=dict(units=raw.get('units', 'mm'),
                                       width_mm=raw.get('width_mm'),
                                       height_mm=raw.get('height_mm'),
                                       style=raw.get('style', 'lineart'),
                                       engine=raw.get('engine', 'pc_opencv'),
                                       algorithm_version=raw.get('algorithm_version'),
                                       source_sha256=raw.get('source_sha256'),path_sha256=raw.get('path_sha256'),
                                       ordering=raw.get('ordering'),draw_length_mm=raw.get('draw_length_mm'),
                                       strokes=stroke_count,segments=segment_count),
                           detail='PC 端笔画已登记', preview='paths.svg')
            elif kind == 'plan':
                from planning import build
                source = data.get('image_job')
                if source not in self.jobs or self.jobs[source]['kind'] not in ('image','preset','strokes') or self.jobs[source]['status'] != 'DONE':
                    raise ValueError("先完成图片转轨迹")
                paths = json.loads((self.state.directory / ('job_' + source) / 'paths.json').read_text(encoding='utf-8'))
                if data.get('drawing_size_mm') is not None:
                    size=data['drawing_size_mm']
                    if (not isinstance(size,list) or len(size)!=2
                            or any(type(v) not in (int,float) for v in size)):
                        raise ValueError('绘画尺寸需要宽、高两个毫米数值')
                    from stroke_paths import resize_paths
                    paths=resize_paths(paths,*size)
                machine, counts = None, None
                if data.get('mode') == 'real':
                    if data.get('start_counts') is not None:
                        # PC-connected servo capture can plan on the PL without
                        # requiring a second adapter on the board. Execution
                        # still measures its real start through its own port.
                        from app import validate_scan
                        validate_scan(dict(mode='real',port=data.get('port'),baudrate=data.get('baudrate'),
                            confirmed=data.get('confirmed'),ids=[j['id'] for j in self.machine['joints']]),self.state.allow_real)
                        validate_machine(self.machine,drawing=True)
                        machine=copy.deepcopy(self.machine)
                        raw=data['start_counts']
                        if not isinstance(raw,dict):raise ValueError('起始位置需要完整的关节读数')
                        counts={int(k):v for k,v in raw.items()}
                        if (set(counts)!={j['id'] for j in machine['joints']}
                                or any(type(v) is not int for v in counts.values())):
                            raise ValueError('起始位置需要五关节整数计数')
                        from motion import angles_from_counts
                        counts_from_angles(machine,angles_from_counts(machine,counts))
                    else:
                        try:
                            device, machine = self.connect(data, drawing='plan')
                            counts = read_all(device, machine, preflight=True, need_torque=False)
                        except ProbeError as exc:
                            raise ProbeError(exc.code, '规划前舵机读取失败，尚未开始轨迹计算：' + str(exc)) from exc
                        except OSError as exc:
                            raise RuntimeError('规划前舵机读取失败，尚未开始轨迹计算：' + str(exc)) from exc
                elif data.get('mode') != 'demo':
                    raise ValueError("请选择模式")
                background_save = data.get('background_save') is True
                result, spec, cfg = build(paths, folder, machine, counts, self.cancel.is_set, self.backend,
                                          motion_mode=data.get('motion_mode','sugar_fast'), persist=not background_save)
                result.metrics['start_counts_source']=str(data.get('counts_source','board_encoder' if machine else 'nominal_demo'))[:80]
                (folder/'trajectory_config.json').write_text(json.dumps(cfg, indent=2), encoding='utf-8')
                job.update(result=dict(status=result.status, metrics=result.metrics, mode=data['mode']),
                           preview='preview.svg', detail='规划结果：' + result.status)
                if result.status != 'OK':
                    raise ValueError("规划失败：%s；详情见 plan.json" % result.status)
                if self.cancel.is_set():
                    raise ValueError('ABORT: planning cancelled')
                pending_plan = dict(result=result, q0=spec['q0'], mode=data['mode'],
                                    digest=self.digest(), machine=copy.deepcopy(machine),
                                    paths=copy.deepcopy(paths), drawing=copy.deepcopy(spec),
                                    port=data.get('port'), baudrate=data.get('baudrate'))
                persist_started = time.perf_counter()
                history_saved=False if background_save else self._save_plan(job['id'], pending_plan)
                result.metrics['history_saved']=history_saved
                result.metrics['memory_ready']=True
                if not history_saved and not background_save:
                    raise ValueError('规划保存失败，计划不可用，请重新规划')
                timing = result.metrics.setdefault('timing', {})
                timing['saved_plan_s'] = time.perf_counter()-persist_started
                timing['job_ready_s'] = time.perf_counter()-job_started
                result.metrics['planning_goal']=dict(target_s=30.,scope='job including preflight and history persistence',
                    measured_s=timing['job_ready_s'],met=timing['job_ready_s']<=30.)
                (folder/'timing.json').write_text(json.dumps(timing, indent=2), encoding='utf-8')
            elif kind == 'read_pen_pose':
                if data.get('mode')!='real':raise ValueError('几何标定需要实物读数')
                device,machine=self.connect(data)
                counts=read_all(device,machine,preflight=True,need_torque=False)
                job.update(result=dict(counts=counts),detail='实物姿态已读取，未发送运动指令')
            elif kind == 'calibrate_pen':
                if data.get('mode') != 'real' or data.get('pose_confirmed') is not True:
                    raise ValueError('请先把笔调整至按钮所说明的姿态再记录')
                device, machine = self.connect(data)
                counts = read_all(device, machine, preflight=True, need_torque=False)
                from pen_calibration import calibrate_pen
                updated, detail = calibrate_pen(machine, counts, data.get('kind'))
                # This worker already owns state.lock. Persist atomically and
                # preserve a recovery copy without opening another motor owner.
                if self.config_file.exists():
                    (folder/'machine.before.json').write_bytes(self.config_file.read_bytes())
                temporary = self.config_file.with_suffix('.json.tmp')
                temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
                temporary.replace(self.config_file)
                self.machine = updated
                self.state.record('PEN_CALIBRATION',detail)
                job.update(result=detail,detail='笔轴已记录' if data.get('kind')=='axis' else '接触高度已记录')
            elif kind in ('enable', 'jog', 'execute', 'home'):
                stored = None
                prepared_curve = None
                if kind == 'execute':
                    # 先校验再执行; 不消耗计划, 同一份规划可以重复执行
                    _key = data.get('plan_job')
                    stored = self.plans.get(_key)
                    if not stored:
                        raise ValueError("找不到该规划，请先规划或从历史规划中选择")
                    if stored['mode'] != data.get('mode'):
                        raise ValueError("该规划是 %s 模式生成的，不能用于 %s 模式：demo 规划基于模拟机械臂，"
                                         "无法驱动实物。请用「真实模式」重新规划。"
                                         % (stored['mode'], data.get('mode')))
                    from stroke_paths import PIPELINE_VERSION
                    if (data.get('mode') == 'real' and stored['result'].metrics.get('drawing_pipeline_version') != PIPELINE_VERSION):
                        raise ValueError('该历史规划使用旧绘画流程，请重新提取中心线并重新规划')
                    if stored['digest'] != self.digest():
                        raise ValueError("运动配置或标定已变更：该规划基于旧 machine.json，请重新规划"
                                         "（使用当前配置重新规划即可）")
                    if data['mode'] == 'real' and (stored['port'], stored['baudrate']) != (data.get('port'), data.get('baudrate')):
                        raise ValueError("端口已变化，请重新规划")
                    if data['mode'] == 'real':
                        if stored['result'].metrics.get('motion_mode') == 'sugar_fast':
                            from kinematic_calibration import assert_sugar_calibration
                            assert_sugar_calibration(self.machine, require_four_point=True)
                        if stored['result'].metrics.get('motion_algorithm_version') != 'motion-smooth-v1':
                            raise ValueError('该历史规划使用旧运动算法，请用「平缓」模式重新规划')
                        from smooth_motion import validate_plan
                        prepared_curve = validate_plan(stored['result'], self.machine)
                if kind == 'home' and data.get('mode') == 'real':
                    from four_point_calibration import validate
                    validate(self.machine, require_ready=True)
                device, machine = self.connect(data, drawing=kind == 'execute')
                def cancelled():
                    return self.cancel.is_set()
                def execution_audit(event, detail):
                    if event in ('FIRST_COMMAND', 'FIRST_DRAW_COMMAND'):
                        name = 'first_command' if event == 'FIRST_COMMAND' else 'first_pen_down'
                        job.setdefault('timeline', {}).setdefault(name, detail['monotonic_s'])
                        self._publish_job(job)
                    self.state.record(event, detail)
                executor = Executor(device, machine, cancelled, execution_audit)
                if kind == 'enable':
                    result = executor.enable()
                elif kind == 'jog':
                    result = executor.jog(data.get('id'), data.get('delta'))
                elif kind == 'home':
                    self._ensure_torque(device, machine, executor)
                    result = self._home_move(device, machine, executor)
                else:
                    if data['mode'] == 'demo':
                        self.demo.positions.update(counts_from_angles(machine, stored['q0']))
                    else:
                        self._ensure_torque(device, machine, executor)   # 绘画前也要有扭矩
                    if prepared_curve is not None:
                        result = executor.execute_curve(prepared_curve, stored['q0'], backend=self.backend)
                    else:
                        result = executor.execute(stored['result'], stored['q0'])
                    trace = result.pop('_tracking_trace', [])
                    try:
                        (folder/'execution_trace.json').write_text(json.dumps(dict(
                            schema='so101-execution-trace-v1',plan_job_id=data.get('plan_job'),
                            machine=machine,points=trace,scope='encoder model reconstruction, not measured ink'),
                            ensure_ascii=False,allow_nan=False),encoding='utf-8')
                        result['execution_trace_url']='/job/'+job['id']+'/execution_trace.json'
                    except (OSError, ValueError) as exc:
                        # A diagnostic file must not prevent returning home.
                        result['execution_trace_error']=str(exc)[:140]
                    # 画完强制归位 (不可关闭)
                    try:
                        self.state.record("AUTO_HOME_BEGIN", dict(job=job['id']))
                        home = self._home_move(device, machine, executor)
                        result = dict(result or {})
                        result['auto_home'] = home
                        self.state.record("AUTO_HOME_DONE", dict(
                            residual=home.get('final_counts'),
                            settled=home.get('timing', {}).get('settled')))
                    except Exception as exc:
                        # Keep drawing measurements, and report return-home failure separately.
                        self.state.record("AUTO_HOME_FAILED", dict(detail=str(exc)[:140]))
                        result = dict(result or {})
                        result['auto_home_error'] = str(exc)[:140]
                job.update(result=result, detail='操作完成 · ' + data['mode'])
                result.pop('_tracking_trace',None)
                if isinstance(result.get('auto_home'),dict):result['auto_home'].pop('_tracking_trace',None)
                if kind in ('execute', 'home') and 'task_complete' in result:
                    parts = ['指令处理结束', data['mode'],
                             '终点已确认' if result['task_complete'] else '终点未确认']
                    tracking = result.get('tracking')
                    if tracking is not None:
                        parts.append('跟踪合格' if tracking.get('tracking_qualified') else '跟踪未合格')
                    home = result.get('auto_home')
                    if home is not None:
                        parts.append('归位已确认' if home.get('task_complete') else '归位未确认')
                    elif result.get('auto_home_error'):
                        parts.append('归位失败')
                    job['quality_warning'] = bool(not result['task_complete'] or
                        (tracking is not None and not tracking.get('tracking_qualified')) or
                        (home is not None and not home.get('task_complete')) or result.get('auto_home_error'))
                    job['detail'] = ' · '.join(parts)
            else:
                raise ValueError("不支持的任务")
            if kind == 'plan' and self.cancel.is_set():
                raise ValueError('ABORT: planning cancelled')
            job['status'] = 'DONE'
        except Exception as exc:
            job.update(status='FAILED', detail=str(exc))
            lift_fault = getattr(exc, 'lift_completion', None)
            if lift_fault is not None:
                job['result'] = dict(task_complete=False, execution_finished=False,
                                     lift_completion=lift_fault, stopped_on_lift=True)
                try:
                    (folder/'execution_trace.json').write_text(json.dumps(dict(
                        schema='so101-execution-trace-v1',plan_job_id=data.get('plan_job'),
                        machine=machine,points=getattr(exc, 'tracking_trace', []),
                        stopped_on_lift=True,scope='encoder model reconstruction, not measured ink'),
                        ensure_ascii=False,allow_nan=False),encoding='utf-8')
                    job['result']['execution_trace_url']='/job/'+job['id']+'/execution_trace.json'
                except (OSError, ValueError) as trace_exc:
                    job['result']['execution_trace_error']=str(trace_exc)[:140]
        finally:
            if device is not None and device is not self.demo:
                try:
                    device.close()
                except Exception as exc:
                    job.update(status='FAILED', detail='关闭串口失败：' + str(exc))
            try:
                if job['kind'] == 'plan' and self.cancel.is_set():
                    job.update(status='FAILED', detail='ABORT: planning cancelled')
                (folder / 'result.json').write_text(json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
                self.state.record("JOB_END", dict(id=job['id'], status=job['status'], detail=job['detail']))
            except Exception as exc:
                job.update(status='FAILED', detail='任务结果保存失败：' + str(exc))
            finally:
                try:
                    if job['kind'] == 'plan':
                        if self.cancel.is_set():
                            job.update(status='FAILED', detail='ABORT: planning cancelled')
                        if job['status'] == 'DONE' and pending_plan is not None:
                            self.plans[job['id']] = pending_plan
                            if data.get('background_save') is True:
                                from app import utc_now
                                pending_plan['ready_utc'] = utc_now()
                                self._queue_plan_save(job['id'], pending_plan, folder)
                        else:
                            self._discard_plan(job['id'])
                            if isinstance(job.get('result'), dict):
                                job['result'].setdefault('metrics', {})['history_saved'] = False
                except Exception as exc:
                    # Registration/background-save startup can fail after the
                    # worker computed an OK result. Revoke it before publishing
                    # a terminal status; never announce that partial result.
                    job.update(status='FAILED', detail='任务发布失败：' + str(exc))
                    self._save_states.pop(job['id'], None)
                    self._save_threads = [t for t in self._save_threads if t.is_alive()]
                    try:
                        self._discard_plan(job['id'])
                    except Exception as cleanup_exc:
                        job['detail'] += '；规划清理失败：' + str(cleanup_exc)
                    if isinstance(job.get('result'), dict):
                        job['result'].setdefault('metrics', {}).update(history_saved=False, memory_ready=False)
                    try:
                        (folder/'result.json').write_text(json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
                        self.state.record('JOB_FINALIZE_FAILED', dict(id=job['id'], detail=job['detail']))
                    except Exception:
                        pass  # Still publish FAILED and release the task lock.
                finally:
                    # A terminal status becomes visible only after transport
                    # cleanup and plan registration/revocation. Readers receive
                    # that status and active=None together, after the task lock
                    # is released, without ever waiting for motion or planning.
                    published = copy.deepcopy(job)
                    with self._jobs_lock:
                        self.jobs[job['id']] = published
                        self.active = None
                        self._save_pause.clear()
                        self.state.lock.release()

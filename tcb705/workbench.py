"""TCB705 adapter for the original upload/cloud/job HTTP API."""
import copy
import json
from pathlib import Path
import threading
import time
from workbench import Workbench
from .config import load as load_config,validate,digest,readiness
from .artifact import atomic_write,save,load,preview_svg,freeze
from .planner import plan
from . import VERSION
# Fixed-speed performances (名帖 / 诗词 / 春联 / 硬笔), 2026-10-28: stop only where the brush must stop
# (the planner's 顿笔 / 折 stops, pen down / up, turns over 45 deg) and blend the dense curve points
# between them. Blending needs more than one queued SDK move (sdk_motion.pump forces smooth 0 at
# depth 1, which kept the first blend change at 100 s per column); 4 as in live handwriting.
# 2026-10-29: the blend values live in blend.py (smooth 4 trial, switchable back with blend.TRIAL).
from .blend import PERFORMANCE_BLEND, QUEUE_DEPTH as PERFORMANCE_QUEUE_DEPTH, PAGE_BLEND, LINEART_SMOOTH  # noqa: E402

class _StopRequests:
    """First explicit stop ends drawing; the second also cancels the return home."""
    def __init__(self):
        self._lock=threading.Lock();self._count=0
    def clear(self):
        with self._lock:self._count=0
    def set(self):
        with self._lock:self._count+=1
    def is_set(self):
        with self._lock:return self._count>0
    def recovery_cancelled(self):
        with self._lock:return self._count>1

def _keep_unchanged(new,old):
    """Return new, but with every value that equals the old one (e.g. 1 vs 1.0) taken from old."""
    if isinstance(new,dict) and isinstance(old,dict):
        return {k:(_keep_unchanged(v,old[k]) if k in old else v) for k,v in new.items()}
    if isinstance(new,list) and isinstance(old,list) and len(new)==len(old):
        return [_keep_unchanged(a,b) for a,b in zip(new,old)]
    if isinstance(new,(int,float)) and isinstance(old,(int,float)) and not isinstance(new,bool) \
            and not isinstance(old,bool) and new==old:
        return old
    return new

class TCBWorkbench(Workbench):
    def __init__(self,state,simulation=False,profile=None):
        self.simulation=simulation
        from .accel_runtime import platform_health
        self.platform_health=platform_health()
        from .planning_session import PlanningSession
        self.planning_session=PlanningSession()
        super().__init__(state,allow_motion=False)
        self.cancel=_StopRequests()
        self.config_file=state.directory.parent/'tcb705.machine.json'
        self.machine=load_config(profile or self.config_file) if (profile or self.config_file.is_file()) else load_config()
        self.plans={}
        self._fixed_speed=None     # 名帖表演 runs at a fixed speed
        self._speed_lock=threading.Lock()
        from handwriting.session import HandwritingSession
        self.handwriting=HandwritingSession(self)
        self._load_saved_plans()
        if not self.platform_health.get('faulted',True):
            from lineart_backend import prepare
            # Parse PYNQ/HWH once during service startup, before the first upload.
            # prepare never downloads the platform or starts a hardware operation.
            print('LINEART_ATTACH_PREPARE',prepare(),flush=True)

    def _load_saved_plans(self):
        # Called by the base initializer before the TCB705 profile is installed.
        if not hasattr(self,'simulation') or not getattr(self,'machine',None) or self.machine.get('schema')!='tcb705-machine-v1':return
        root=self.state.directory.parent
        for path in sorted(root.glob('*/job_*/plan.json'),key=lambda p:p.stat().st_mtime)[-10:]:
            try:
                doc=load(path.parent,with_rows=False);jid=path.parent.name[4:]
                self.plans[jid]={'folder':path.parent,'doc':doc}
            except (ValueError,OSError,KeyError):continue

    def digest(self):return digest(self.machine)
    def stop(self):
        session=getattr(self,'handwriting',None)
        if session is not None and session.owns_lock:return session.stop()
        return super().stop()
    def calligraphy_catalog(self):
        from calligraphy.presets import catalog,profile
        from .web_executor import settings
        out=catalog();out['profile']=profile(self.machine);out['simulation']=self.simulation
        out['speed_pct']=settings(self.machine)['draw_speed_pct']
        return out
    def configure_brush(self,data):
        from calligraphy.presets import BRUSH,MAX_PRESS_MM,number,binding
        if data.get('verified') is not True:raise ValueError('请先核对当前毛笔 TCP 和落纸零点')
        old=self.machine.get('calligraphy',{})
        depth=number(data.get('max_press_mm'),.01,MAX_PRESS_MM,'实测下压上限 (mm)')
        hair=number(data.get('hair_length_mm',old.get('hair_length_mm',BRUSH['hair_length_mm'])),1,60,'毛长 (mm)')
        diameter=number(data.get('max_diameter_mm',old.get('max_diameter_mm',BRUSH['max_diameter_mm'])),.5,20,'最粗直径 (mm)')
        if depth>hair:raise ValueError('下压上限不能超过毛长')
        contact=data.get('contact_z_mm',old.get('contact_z_mm'))
        config=copy.deepcopy(self.machine)
        config['calligraphy']=dict(BRUSH,hair_length_mm=hair,max_diameter_mm=diameter,max_press_mm=depth,verified=True,
                                  calibration_binding=binding(config))
        if contact is not None:
            # The brush tip must touch above the sketch pen height and well below home.
            contact=number(contact,0,1000,'毛笔落笔 Z (mm)')
            pen=float(self.machine['armvision']['z_table_mm']) if 'armvision' in self.machine else None
            if pen is not None and not pen-20<=contact<=pen+150:raise ValueError('毛笔落笔 Z 与画笔落笔 Z 相差过大，请重新读取')
            config['calligraphy']['contact_z_mm']=round(contact,3)
        # Keep the inert legacy field only for existing frozen-plan digests.
        # Neither execution nor this API reads it as a speed setting anymore.
        if 'speed_pct' in self.machine.get('calligraphy',{}):
            config['calligraphy']['speed_pct']=self.machine['calligraphy']['speed_pct']
        self.configure(config)
        return self.calligraphy_catalog()
    def configure_hardpen(self,data):
        """硬笔标定 (2026-10-27): the pen tip's contact height and the press taken up by its spring."""
        from calligraphy.presets import number,binding
        from calligraphy import hardpen
        if data.get('verified') is not True:raise ValueError('请先确认：笔尖刚好接触纸面时读取了落笔点')
        old=self.machine.get('hardpen',{})
        contact=data.get('contact_z_mm',old.get('contact_z_mm'))
        if contact is None:raise ValueError('请先读取硬笔落笔点')
        contact=number(contact,0,1000,'硬笔落笔 Z (mm)')
        pen=float(self.machine['armvision']['z_table_mm']) if 'armvision' in self.machine else None
        if pen is not None and not pen-20<=contact<=pen+150:raise ValueError('硬笔落笔 Z 与画笔落笔 Z 相差过大，请重新读取')
        press=number(data.get('press_mm',old.get('press_mm',hardpen.PRESS_MM)),.05,hardpen.MAX_PRESS_MM,'硬笔下压量 (mm)')
        config=copy.deepcopy(self.machine)
        config['hardpen']=dict(contact_z_mm=round(contact,3),press_mm=press,verified=True,calibration_binding=binding(config))
        self.configure(config)
        return self.hardpen_catalog()
    def hardpen_catalog(self):
        from calligraphy import hardpen
        out=dict(sizes=list(hardpen.SIZES),speeds=list(hardpen.SPEEDS),profile=hardpen.profile(self.machine),
                 mounted_tool=self.machine.get('mounted_tool','pen'),simulation=self.simulation)
        try:out.update(revision=hardpen.revision(self.machine),glyph_version=hardpen.manifest()['version'],count=hardpen.manifest()['count'])
        except ValueError as exc:out['error']=str(exc)
        return out
    def set_tool(self,data):
        """画笔 / 毛笔 / 硬笔: which tool is mounted. Real runs refuse plans made for another tool."""
        from calligraphy.presets import TOOLS
        tool=data.get('tool')
        if tool not in TOOLS:raise ValueError('当前工具只能是画笔、毛笔或硬笔')
        if tool=='brush' and self.machine.get('calligraphy',{}).get('contact_z_mm') is None:
            raise ValueError('请先标定毛笔落笔高度，再切换到毛笔')
        if tool=='hardpen' and self.machine.get('hardpen',{}).get('contact_z_mm') is None:
            raise ValueError('请先标定硬笔落笔高度，再切换到硬笔')
        config=copy.deepcopy(self.machine);config['mounted_tool']=tool
        self.configure(config)
        return {'mounted_tool':tool}
    def configure(self,data):
        if not self.state.lock.acquire(blocking=False):raise RuntimeError('等待当前任务结束后保存配置')
        try:
            # The settings page round-trips the whole config through browser JSON, which turns 1.0 into 1;
            # keep every numerically unchanged value as it was so the plan digest only moves on real changes.
            data=_keep_unchanged(data,self.machine)
            if 'armvision' in data:
                from .calibration import apply_armvision,fields
                changed=fields(data['armvision'])!=self.machine.get('armvision')
                data=apply_armvision(data,data['armvision'],reset_verified=changed)
            validate(data)
            from .model import Model
            model=Model(data)
            if data.get('couplet_paper') and data.get('couplet_paper')!=self.machine.get('couplet_paper'):
                from .calibration import check_couplet_reach
                check_couplet_reach(data,model)
            with self._speed_lock:
                atomic_write(self.config_file,json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2).encode())
                self.machine=copy.deepcopy(data)
            self.state.record('TCB_CONFIG',{'digest':self.digest()})
            return {'saved':True,'sha256':self.digest(),'readiness':readiness(data)}
        finally:self.state.lock.release()
    def set_speed(self,data):
        """Arm speed 1..100 (2026-10-20): saved at once (also while drawing, the speed is not part of the
        plan digest) and, in SDK mode, applied to the running drawing through setGlobalSpeed."""
        from .sdk_motion import check_speed,live_speed
        if getattr(self,'_fixed_speed',None) is not None:
            raise ValueError('名帖表演速度固定为 %g%%，写完后再调整速度'%self._fixed_speed)
        v=check_speed((data or {}).get('speed_pct'))
        with self._speed_lock:
            m=copy.deepcopy(self.machine);wp=m.get('execution',{}).get('web_program')
            if not wp:raise ValueError('当前配置没有实机执行设置')
            wp['draw_speed_pct']=v;wp['air_speed_pct']=v
            validate(m)
            atomic_write(self.config_file,json.dumps(m,ensure_ascii=False,allow_nan=False,indent=2).encode())
            # in place: a drawing that is running keeps the same config object
            self.machine['execution']['web_program'].update(draw_speed_pct=v,air_speed_pct=v)
        applied=live_speed(v)
        self.state.record('TCB_SPEED',{'pct':v,'live':applied is not None})
        return {'saved':True,'speed_pct':v,'live_applied':applied is not None,'controller_speed':applied}
    def capabilities(self):
        from stroke_paths import PIPELINE_VERSION
        from .calibration import assert_model_ready
        ready=True;detail='离线示例仅用于算法验证'
        if 'armvision' in self.machine:
            try:assert_model_ready(self.machine);detail='使用 ArmVision A/B、落笔 Z 与 UVW'
            except ValueError as exc:ready=False;detail=str(exc)
        return dict(version=VERSION,robot_type='TCB705',simulation=self.simulation,
            drawing_pipeline_version=PIPELINE_VERSION,
            allow_real=self.state.allow_real,motion_supported=self.simulation,
            physical_authorized=False,sugar_calibration_ready=ready and (self.simulation or self.machine['calibration_verified']),
            sugar_calibration_detail=detail,
            motion_algorithm_version='tcb705-c2-v2-batch',motion_modes=['tcb705'],production_motion_modes=['tcb705'],default_motion_mode='tcb705',
            ik_backend='ZYNQ_PL_7R_BATCH' if self.platform_health.get('faulted') is False else 'ZYNQ_CPU_NATIVE_7R_BATCH',
            ik_metrics=self.platform_health,background_plan_save_supported=False,drawing_size_supported=True,
            readiness=readiness(self.machine))
    def list_plans(self):
        return {'plans':[dict(id=k,mode=v['doc']['mode'],duration_s=v['doc']['metrics']['duration_s'],commands=v['doc']['metrics']['frames'],
            needs_replan=v['doc']['config_digest']!=self.digest(),matches_current_calibration=v['doc']['config_digest']==self.digest(),
            motion_mode='tcb705',ik_backend=v['doc']['metrics'].get('ik_backend','ZYNQ_CPU_NATIVE_7R'),physical_authorized=False) for k,v in reversed(list(self.plans.items()))], 'current_digest':self.digest()}
    def _store_root(self,kind='masterpiece'):return self.state.directory.parent/('%s_plans'%kind)
    def hardpen_works(self,limit=60):
        """硬笔作品: pieces written before, newest first, with whether their commands still match."""
        from calligraphy import hardpen
        from . import plan_store
        root=self._store_root('hardpen');out=[]
        try:revision=hardpen.revision(self.machine)
        except ValueError:revision=None
        for folder in root.glob('hp_*/part_0') if root.is_dir() else []:
            key=folder.parent.name;meta=plan_store.meta(root,key,0);info=meta.get('info') or {}
            if not info.get('text'):continue
            # 手机硬笔 (2026-10-29): a piece of several lines is ready when every plan unit is.
            units=range(int(info.get('unit_count') or 1)) if info.get('layout') else [0]
            out.append(dict(key=key,text=info['text'],font_size_mm=info.get('font_size_mm'),saved=meta.get('saved'),
                            layout=info.get('layout'),line_count=info.get('line_count',1),page_count=info.get('page_count',1),
                            ready=revision is not None and all(plan_store.fresh(root,key,i,self.machine,revision) for i in units)))
        out.sort(key=lambda w:w['saved'] or '',reverse=True)
        return {'works':out[:limit]}
    def _prune_hardpen(self,keep=60):
        import shutil
        works=self.hardpen_works(limit=10000)['works']
        for w in works[keep:]:shutil.rmtree(self._store_root('hardpen')/w['key'],ignore_errors=True)
    def _prune_photo(self,keep=30):
        """照片绘画: keep the newest saved drawings only."""
        import shutil
        root=self._store_root('photo')
        folders=sorted(root.glob('ph_*'),key=lambda f:f.stat().st_mtime,reverse=True) if root.is_dir() else []
        for f in folders[keep:]:shutil.rmtree(f,ignore_errors=True)
    def _stored_plan(self,job,folder,data,root,key,index,revision,make_paths,label,what,info=None):
        """Read a frozen plan from the 指令库 when it still matches the calibration, otherwise plan
        it now and save it there (real mode). Publishes the plan for execute; returns the job result."""
        from . import plan_store
        cached=None if self.simulation else plan_store.load(root,key,index,self.machine,revision)
        if cached:
            doc,nodes=cached
            from .web_executor import prepare_joint
            job['detail']='正在读取已保存的%s指令'%what;self._publish_job(job)
            published={'folder':folder,'doc':doc,'nodes':nodes,'prepared':prepare_joint(doc['config'],nodes,self.cancel.is_set)}
            metrics=dict(doc['metrics'],history_saved=False,memory_ready=True)
        else:
            job['detail']=label;self._publish_job(job)
            published,doc,result=self._plan_paths(make_paths(),folder,data,job,label=label)
            if 'nodes' in published:plan_store.save(root,key,index,doc,published['nodes'],revision,info)
            metrics=dict(result['metrics'],history_saved=self.simulation,memory_ready=True)
        job.update(preview='preview.svg',detail='已读取已保存的%s指令'%what if cached else '%s指令已计算'%what+('' if self.simulation else '并保存'))
        return published,{'status':'OK','metrics':metrics,'mode':doc['mode'],'cached':bool(cached)}
    def masterpiece_store(self):
        """名帖指令库: which work/column has saved commands for the current calibration."""
        from calligraphy import composer,glyph_store
        from calligraphy.text_layout import MASTER_ROWS
        from . import plan_store
        out=[]
        for style in glyph_store.masterpieces():
            m=glyph_store.manifest(style);rev=composer.revision(self.machine,style)
            cols=[]
            for c in range(-(-m['count']//MASTER_ROWS)):
                meta=plan_store.meta(self._store_root(),style,c)
                cols.append(dict(column=c,ready=plan_store.fresh(self._store_root(),style,c,self.machine,rev),
                                 saved=meta.get('saved'),nodes=meta.get('nodes')))
            out.append(dict(style=style,title=m['title'],author=m['author'],columns=cols,ready=all(x['ready'] for x in cols)))
        return {'works':out,'ready':bool(out) and all(w['ready'] for w in out),'simulation':self.simulation}
    def prediction_data(self,jid):
        if jid not in self.plans:raise ValueError('找不到天链规划')
        return copy.deepcopy(self.plans[jid]['doc']['preview'])
    def prediction_svg(self,jid):
        data=self.prediction_data(jid)
        if data.get('source')=='cloud':
            raise ValueError('图案模式使用云端或本地线稿原图，不再生成运动轨迹预测图')
        return preview_svg(data)
    def start(self,kind,data,upload=None):
        handwriting=getattr(self,'handwriting',None)
        if handwriting is not None and handwriting.owns_lock:
            raise RuntimeError('手写会话尚在准备、书写或确认停止，请先结束手写；'+handwriting.snapshot()['message'])
        allowed=('image','preset','strokes','calligraphy','plan','execute','read_pen_pose','home','masterpiece','masterpiece_all','poem_segment','hardpen_line','hardpen_doc','couplet_page')
        if kind not in allowed:raise ValueError('天链版本不支持旧 STS 单舵机动作；请通过示教器调整起始姿态')
        if kind in ('execute','home') and not self.simulation:
            from .bridge import web_program_enabled
            if not web_program_enabled(self.machine):raise ValueError('REAL_STREAM_NOT_COMMISSIONED: 实机执行需开启 execution.web_program（自动模式整程序下发）')
            if not self.state.allow_real:raise ValueError('实机执行需启动时加 --allow-real')
            from .web_executor import mapping_required
            # 复位 is forced (2026-10-29): only a drawing needs the paper calibration.
            if kind=='execute' and (not self.machine['calibration_verified'] or (mapping_required(self.machine) and not self.machine['sdk_mapping_verified'])):raise ValueError('实机执行前需完成纸面标定')
            if data.get('confirm_physical') is not True:raise ValueError('PHYSICAL_CONFIRM_REQUIRED: 确认有人守在急停旁、周围无人后再执行')
        if kind=='read_pen_pose' and not self.state.allow_real:raise ValueError('只读连接需启动时加 --allow-real')
        data=dict(data)
        if self.simulation:data['mode']='demo'
        data['background_save']=False
        return super().start(kind,data,upload)
    def connect(self,*args,**kwargs):raise ValueError('TCB705 不使用 STS 串口')
    def _plan_paths(self,paths,folder,data,job,prepare=True,label=''):
        """Plan registered paths with every real-mode check. Returns (published, doc, result)."""
        from calligraphy.presets import mounted_tool,tool_of,tool_fits,TOOL_NAMES,TASK_NAMES
        need=tool_of(paths.get('calligraphy'));tool=mounted_tool(self.machine)
        if not self.simulation and not tool_fits(tool,need):
            raise ValueError('当前装的是%s，不能规划%s；请在设置中切换当前工具'%(TOOL_NAMES[tool],TASK_NAMES[need]))
        if paths.get('calligraphy') and not self.simulation:
            if need=='hardpen':
                from calligraphy.hardpen import profile as hardpen_profile
                hardpen_profile(self.machine,require_verified=True)
            else:
                from calligraphy.presets import profile
                profile(self.machine,require_verified=True)
            from .web_executor import settings
            if settings(self.machine)['mode']!='joint':raise ValueError('书法模式需 joint 执行配置')
        if data.get('drawing_size_mm') is not None and 'armvision' not in self.machine and not paths.get('calligraphy'):
            from stroke_paths import resize_paths
            paths=resize_paths(paths,*data['drawing_size_mm'])
        q0=self.machine['q_start_rad']
        if not self.simulation:
            if not self.state.allow_real:raise ValueError('实机规划需 --allow-real 读取实际七轴姿态；离线请用 --simulation')
            from .bridge import feedback,web_start,web_program_enabled
            if web_program_enabled(self.machine):
                from .web_executor import mapping_required
                if not self.machine['calibration_verified'] or (mapping_required(self.machine) and not self.machine['sdk_mapping_verified']):raise ValueError('实机规划前需完成纸面标定')
                from .web_executor import home_enabled
                if home_enabled(self.machine):
                    from .model import Model
                    q0=Model(self.machine).from_sdk(self.machine['execution']['web_program']['home']['joint_degrees']).tolist()
                else:q0=web_start(self.machine)['q_rad']
            else:
                if not self.machine['calibration_verified'] or not self.machine['sdk_mapping_verified']:raise ValueError('实机规划前需完成 TCP 纸面与 SDK 坐标映射核对')
                q0=feedback(self.machine)['q_rad']
        def progress(phase,nodes):
            job['detail']='%s七轴连续逆解，已完成 %d 个路径节点'%(label+'：' if label else '',nodes);self._publish_job(job)
        result=self.planning_session.plan(paths,copy.deepcopy(self.machine),q0,self.cancel.is_set,progress)
        if self.cancel.is_set():raise ValueError('CANCELLED')
        if self.simulation:  # the simulator runs from the trajectory file
            doc=save(result,folder,'demo');published={'folder':folder,'doc':doc}
        else:  # real mode (2026-10-18): plan -> draw straight from memory, no plan files
            doc,nodes=freeze(result,'real');published={'folder':folder,'doc':doc,'nodes':nodes}
            if prepare:
                from .web_executor import prepare_joint
                job['detail']='正在准备并校验关节运动段';self._publish_job(job)
                prepared=prepare_joint(result['config'],nodes,self.cancel.is_set)
                published['prepared']=prepared
                if prepared is not None:
                    result['metrics']['execution_prepare_s']=round(prepared.seconds,3)
                    result['metrics']['execution_blocks']=len(prepared.keep)-1
        return published,doc,result
    def _run(self,job,folder,data):
        if job['kind'] in ('image','preset','strokes'):return super()._run(job,folder,data)
        self._publish_job(job);published=None
        try:
            kind=job['kind']
            if kind=='calligraphy':
                from calligraphy.presets import task,preview_svg as brush_svg
                if data.get('schema')=='brush-text-v1':
                    from calligraphy.composer import task as text_task,revision
                    style=data.get('style','kai')
                    if data.get('revision')!=revision(self.machine,style):raise ValueError('文字预览已过期，请重新预览')
                    paths=text_task(data.get('text'),data.get('font_size_mm'),data.get('page_index'),self.machine,style)
                    picture=preview_svg(dict(width_mm=paths['width_mm'],height_mm=paths['height_mm'],
                        paths=[[[x,paths['height_mm']-y] for x,y in p] for p in paths['paths']]))
                elif data.get('schema')=='brush-poem-v1':
                    from calligraphy.poems import task as poem_task,revision as poem_revision
                    if data.get('revision')!=poem_revision(self.machine):raise ValueError('诗词预览已过期，请重新选择')
                    paths=poem_task(data.get('poem_id'),data.get('font_size_mm'),data.get('page_index'),data.get('segment_index'),self.machine)
                    picture=preview_svg(dict(width_mm=paths['width_mm'],height_mm=paths['height_mm'],
                        paths=[[[x,paths['height_mm']-y] for x,y in p] for p in paths['paths']]))
                elif data.get('schema')=='hardpen-text-v1':
                    from calligraphy import hardpen
                    if data.get('revision')!=hardpen.revision(self.machine):raise ValueError('硬笔字库或标定已更新，请重新生成')
                    paths=hardpen.task(data.get('text'),data.get('font_size_mm'),self.machine)
                    picture=preview_svg(dict(width_mm=paths['width_mm'],height_mm=paths['height_mm'],
                        paths=[[[x,paths['height_mm']-y] for x,y in p] for p in paths['paths']]))
                elif data.get('schema')=='brush-couplet-v1':
                    from calligraphy.couplets import task as couplet_task,revision as couplet_revision
                    if data.get('revision')!=couplet_revision(self.machine):raise ValueError('春联预览已过期，请重新选择')
                    paths=couplet_task(data.get('couplet_id'),data.get('page_index'),self.machine)
                    picture=preview_svg(dict(width_mm=paths['width_mm'],height_mm=paths['height_mm'],
                        paths=[[[x,paths['height_mm']-y] for x,y in p] for p in paths['paths']]))
                else:
                    paths=task(data.get('module'),data.get('size_mm',40),self.machine)
                    picture=brush_svg(data['module'])
                atomic_write(folder/'paths.json',json.dumps(paths,ensure_ascii=False,allow_nan=False).encode())
                atomic_write(folder/'paths.svg',picture)
                job.update(result={'module':paths['calligraphy']['module'],'strokes':len(paths['paths'])},preview='paths.svg',detail='预设书法轨迹已生成')
            elif kind=='read_pen_pose':
                if data.get('coordinate_source')=='armvision':
                    from .armvision_feedback import read_world
                    connection=copy.deepcopy(self.machine['controller'])
                    overrides=data.get('connection',{})
                    for key in ('remote_ip','web_port'):
                        if key in overrides:connection[key]=overrides[key]
                    result=read_world(connection,data.get('robot_id',self.machine['robot_id']))
                    job.update(result=result,detail='已读取 ArmVision 同一组控制器 XYZUVW 反馈，未运动')
                elif data.get('coordinate_source')=='sdk_commission':
                    from .commissioning import capture
                    result=capture(self.machine)
                    job.update(result=result,detail='已只读采集 SDK 法兰/工具/七轴数据，尚未验证映射')
                else:
                    from .bridge import feedback
                    job.update(result=feedback(self.machine),detail='七轴只读反馈成功，未使能或运动')
            elif kind=='plan':
                source=data.get('image_job')
                if source not in self.jobs or self.jobs[source]['status']!='DONE' or self.jobs[source]['kind'] not in ('image','preset','strokes','calligraphy'):raise ValueError('先完成图片或笔画处理')
                paths=json.loads((self.state.directory/('job_'+source)/'paths.json').read_text(encoding='utf-8'))
                if data.get('store') is True and not paths.get('calligraphy'):
                    # 照片绘画 (2026-10-28): the same strokes at the same size are planned once and kept
                    # on the board; drawing them again reads the saved commands.
                    import hashlib
                    ident=hashlib.sha256(json.dumps(dict(paths=paths,drawing_size_mm=data.get('drawing_size_mm')),sort_keys=True,
                                                    separators=(',',':')).encode()).hexdigest()
                    published,result=self._stored_plan(job,folder,data,self._store_root('photo'),'ph_'+ident[:24],0,ident,
                                                       lambda:paths,'正在规划运动轨迹','绘画')
                    if result['cached']:job['preview']=None
                    if not self.simulation:self._prune_photo()
                    job['result']=dict(result,key='ph_'+ident[:24])
                else:
                    published,doc,result=self._plan_paths(paths,folder,data,job)
                    job.update(result={'status':'OK','metrics':dict(result['metrics'],history_saved=self.simulation,memory_ready=True),'mode':doc['mode']},preview=None if doc['preview'].get('source')=='cloud' else 'preview.svg',detail='七轴规划准备完毕'+(' · 模拟验证' if self.simulation else ' · 真实执行尚未开放'))
            elif kind=='masterpiece':
                # 名帖表演: one column of a work, read from the 名帖指令库 when it still matches the
                # calibration, otherwise planned now and saved there for the next time.
                from calligraphy import composer,glyph_store
                style=data.get('style');column=data.get('column')
                if style not in glyph_store.masterpieces():raise ValueError('未找到该名帖')
                m=glyph_store.manifest(style)
                published,result=self._stored_plan(job,folder,data,self._store_root(),style,column,composer.revision(self.machine,style),
                    lambda:composer.task(m['characters'],composer.MASTERPIECE_SIZE_MM,0,self.machine,style,column=column),
                    '正在计算《%s》第 %d 列'%(m['title'],column+1 if type(column) is int else 0),'名帖')
                job['result']=dict(result,style=style,column=column)
            elif kind=='hardpen_line':
                # 硬笔书法 (2026-10-27): one line at 1 / 1.5 / 2 cm, kept in the 硬笔作品库 so the same
                # piece is written again straight from its saved commands.
                from calligraphy import hardpen
                text=''.join(ch for ch in str(data.get('text') or '') if not ch.isspace());size=hardpen.size_of(data.get('font_size_mm'))
                key=hardpen.work_key(text,size)
                published,result=self._stored_plan(job,folder,data,self._store_root('hardpen'),key,0,hardpen.revision(self.machine),
                    lambda:hardpen.task(text,size,self.machine),'正在计算硬笔「%s」'%text[:8],'硬笔',
                    info=dict(text=text,font_size_mm=size))
                if not self.simulation:self._prune_hardpen()
                job['result']=dict(result,text=text,font_size_mm=size,key=key)
            elif kind=='hardpen_doc':
                # 手机硬笔 (2026-10-29): one plan unit (characters of one line) of a piece sent from the
                # phone (横排 / 竖排, pages), kept in the 硬笔作品库 under the piece's key (index = unit),
                # written again without planning.
                from calligraphy import hardpen
                doc=hardpen.doc_layout(data.get('text'),data.get('font_size_mm'),data.get('layout'),self.machine['paper'])
                unit=data.get('unit_index')
                if type(unit) is not int or not 0<=unit<doc['unit_count']:raise ValueError('序号无效')
                key=hardpen.doc_key(doc['text'],doc['font_size_mm'],doc['layout'])
                published,result=self._stored_plan(job,folder,data,self._store_root('hardpen'),key,unit,hardpen.revision(self.machine),
                    lambda:hardpen.unit_task(doc['text'],doc['font_size_mm'],doc['layout'],unit,self.machine),
                    '正在计算硬笔第 %d/%d 段'%(unit+1,doc['unit_count']),'硬笔',info=hardpen.doc_info(doc))
                if not self.simulation:self._prune_hardpen()
                job['result']=dict(result,key=key,unit_index=unit)
            elif kind=='couplet_page':
                # 春联 (2026-10-28): one sheet (上联 / 下联 / 横批) from the 春联指令库 when it still matches
                # the calibration, otherwise planned now and saved for the next time.
                from calligraphy import couplets
                cid=data.get('couplet_id');page=data.get('page_index')
                c=couplets.couplet(cid)
                rows=couplets.layout(cid,couplets.surface(self.machine,dict(schema=couplets.SCHEMA)))['page_count']
                if type(page) is not int or not 0<=page<rows:raise ValueError('页码无效')
                published,result=self._stored_plan(job,folder,data,self._store_root('couplet'),'cp_'+cid,page,couplets.revision(self.machine),
                    lambda:couplets.task(cid,page,self.machine),'正在计算春联「%s」第 %d 行'%(c['banner'],page+1),'春联')
                job['result']=dict(result,couplet_id=cid,page_index=page)
            elif kind=='poem_segment':
                # 诗词 (2026-10-27): fixed 70 mm; one segment of one sheet, from the 诗词指令库 when it
                # still matches the calibration, otherwise planned now and saved for the next time.
                from calligraphy import poems
                pid=data.get('poem_id');page=data.get('page_index');segment=data.get('segment_index')
                p=poems.poem(pid)
                if type(page) is not int or not 0<=page<10:raise ValueError('页码无效')
                published,result=self._stored_plan(job,folder,data,self._store_root('poem'),'poem_%s_p%d'%(pid,page),segment,poems.revision(self.machine),
                    lambda:poems.task(pid,poems.POEM_SIZE_MM,page,segment,self.machine),
                    '正在计算《%s》第 %d 张纸第 %d 段'%(p['title'],page+1,segment+1 if type(segment) is int else 0),'诗词')
                job['result']=dict(result,poem_id=pid,page_index=page,segment_index=segment)
            elif kind=='masterpiece_all':
                # Fill the 名帖指令库 for every work and column that has no matching entry.
                from calligraphy import composer,glyph_store
                from calligraphy.text_layout import MASTER_ROWS
                from . import plan_store
                if self.simulation:raise ValueError('模拟模式不保存名帖指令库')
                planned=[];reused=0
                for style in glyph_store.masterpieces():
                    m=glyph_store.manifest(style);revision=composer.revision(self.machine,style);count=-(-m['count']//MASTER_ROWS)
                    for column in range(count):
                        if self.cancel.is_set():raise ValueError('CANCELLED')
                        if plan_store.load(self._store_root(),style,column,self.machine,revision) is not None:reused+=1;continue
                        label='正在计算《%s》第 %d/%d 列'%(m['title'],column+1,count)
                        job['detail']=label;self._publish_job(job)
                        paths=composer.task(m['characters'],composer.MASTERPIECE_SIZE_MM,0,self.machine,style,column=column)
                        published,doc,result=self._plan_paths(paths,folder,data,job,prepare=False,label=label)
                        plan_store.save(self._store_root(),style,column,doc,published['nodes'],revision);planned.append([style,column])
                job.update(result={'status':'OK','planned':planned,'reused':reused},
                           detail='名帖指令库已就绪：新计算 %d 列，沿用 %d 列'%(len(planned),reused))
            elif kind=='home':
                from .bridge import return_home
                def homing(event):
                    stage=event.get('event')
                    labels={'HOME_START':'正在复位','HOME_DONE':'复位完成'}
                    if stage in labels:job.update(motion_stage=stage[:-6] if stage.endswith('_START') else stage,detail=labels[stage]);self._publish_job(job)
                result=return_home(self.machine,simulation=self.simulation,cancel=self.cancel.is_set,progress=homing)
                job.update(result=result,motion_stage='HOME_DONE',detail='模拟复位通过，未发送任何物理运动' if self.simulation else '机械臂已复位')
            elif kind=='execute':
                from .bridge import execute
                stored=self.plans.get(data.get('plan_job'))
                if not stored:raise ValueError('先生成天链规划')
                def moved(event):
                    stage=event.get('event')
                    if stage in ('RESTORE_WAIT','RESTORE_SETTLED'):
                        waiting=stage=='RESTORE_WAIT'
                        finished='已归位' if job.get('motion_stage')=='RETURN_HOME_DONE' else '轨迹已结束'
                        job.update(restore_waiting=waiting,
                                   detail=(finished+'，正在确认静止（最多 %g 秒）'%event['timeout_s']
                                           if waiting else '静止已确认，正在完成模式恢复'))
                        self._publish_job(job)
                        return
                    if stage in ('HOME_START','RETURN_HOME_START','HOME_AFTER_STOP_START'):stage=stage[:-6]
                    labels={'HOME':'开始书写前正在归位','HOME_DONE':'开始前归位完成',
                            'RETURN_HOME':'书写完成，正在归位','RETURN_HOME_DONE':'书写完成并已归位',
                            'HOME_AFTER_STOP':'已停止书写，正在归位',
                            'HOME_AFTER_STOP_DONE':'已停止书写并归位',
                            'HOME_AFTER_STOP_FAILED':'书写已停止，但归位未完成'}
                    if stage in labels:
                        job.update(motion_stage=stage,detail=labels[stage])
                        if stage=='HOME_AFTER_STOP_DONE':job['home_after_stop_status']='done'
                        elif stage=='HOME_AFTER_STOP_FAILED':
                            job['home_after_stop_status']='failed'
                            job['home_after_stop_error']=event.get('detail') or event.get('error')
                            job['return_cancelled_again']=event.get('cancelled_again') is True
                        self._publish_job(job)
                    elif stage=='PROGRESS':
                        job.update(motion_stage='DRAWING',detail='实机绘画中：段 %d，节点 %d/%d'%(event['chunk']+1,event['node'],event['of']))
                        self._publish_job(job)
                frozen=(stored['doc'],stored['nodes']) if 'nodes' in stored else None
                machine=self.machine
                if data.get('speed_pct') is not None:
                    # 名帖表演 (2026-10-27): this run only, at a fixed speed; the saved GUI speed is kept.
                    from .sdk_motion import check_speed
                    fixed=check_speed(data['speed_pct']);machine=copy.deepcopy(self.machine)
                    wp=machine.get('execution',{}).get('web_program')
                    # Stop-and-go at every brush node held 名帖 / 诗词 far below this speed (889 exact stops
                    # in one column, 2026-10-28): blend gentle vertices like 手写; corners stay exact.
                    if wp:wp.update(draw_speed_pct=fixed,air_speed_pct=fixed,brush_blend=dict(PERFORMANCE_BLEND))
                    sdk=machine.get('execution',{}).get('sdk')
                    if sdk:sdk['queue_depth']=max(int(sdk.get('queue_depth',1)),PERFORMANCE_QUEUE_DEPTH)
                    self._fixed_speed=fixed
                elif PAGE_BLEND is not None or LINEART_SMOOTH is not None:
                    # smooth trial (2026-10-29): screen-speed runs (毛笔页面 / 字帖 / text pages / 图案)
                    # blend gentle on-paper bends too; the GUI speed stays live. See blend.py.
                    machine=copy.deepcopy(self.machine)
                    wp=machine.get('execution',{}).get('web_program')
                    if wp:
                        if PAGE_BLEND is not None:wp['brush_blend']=dict(PAGE_BLEND)
                        if LINEART_SMOOTH is not None:wp['smooth']=LINEART_SMOOTH
                    sdk=machine.get('execution',{}).get('sdk')
                    if sdk:sdk['queue_depth']=max(int(sdk.get('queue_depth',1)),PERFORMANCE_QUEUE_DEPTH)
                try:
                    result=execute(stored['folder'],machine,simulation=self.simulation,cancel=self.cancel.is_set,recovery_cancel=self.cancel.recovery_cancelled,realtime=data.get('realtime') is True,progress=moved,frozen=frozen,prepared=stored.get('prepared'))
                finally:
                    self._fixed_speed=None
                job.update(result=result,restore_waiting=False,detail='天链模拟执行通过，未发送任何物理运动' if self.simulation else '实机绘画完成（自动模式整程序下发）')
            if self.cancel.is_set():raise ValueError('CANCELLED')
            job['status']='DONE'
            atomic_write(folder/'result.json',json.dumps(job,ensure_ascii=False,allow_nan=False,indent=2).encode())
            self.state.record('TCB_JOB_END',{'id':job['id'],'kind':kind,'status':'DONE'})
            if published:
                self.plans[job['id']]=published
                # in-memory plans hold the full preview; keep only the latest few
                for old in [k for k,v in self.plans.items() if 'nodes' in v][:-3]:self.plans.pop(old,None)
        except Exception as exc:
            job.update(status='FAILED',detail=str(exc));self.plans.pop(job['id'],None)
            try:atomic_write(folder/'result.json',json.dumps(job,ensure_ascii=False,allow_nan=False,indent=2).encode())
            except OSError:pass
        finally:
            with self._jobs_lock:self.jobs[job['id']]=copy.deepcopy(job);self.active=None
            self.state.lock.release()

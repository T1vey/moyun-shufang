"""Single-image board workflow; physical execution requires a fresh screen click.

The LAN upload channel never receives the backend's token. All hardware requests
are issued through the existing loopback client, so its calibration, start-pose,
pipeline-version and execution checks remain authoritative.
"""
import copy
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from user_gui.text_workflow import COUPLET_SPEED_PCT, TextWorkflowMixin

MASTERPIECE_SIZE_MM = 70     # 名帖表演: fixed character size
MASTERPIECE_SPEED_PCT = 100  # 名帖表演: fixed arm speed for the run (2026-10-27: 100 %; the saved GUI speed is kept)
POEM_SPEED_PCT = 100         # 诗词: fixed arm speed for the run, like 名帖表演


class Cancelled(Exception):
    def __init__(self, message='', job=None):
        super().__init__(message)
        self.job=job or {}


def validate_image(raw, kind):
    """Decode the complete image before publishing a frame or calling the cloud."""
    from PIL import Image
    expected = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != expected.get(kind):
                raise ValueError('文件内容与图片格式不符')
            if image.width * image.height > 16000000:
                raise ValueError('图片请压缩至 1600 万像素以内')
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('请选择一张静态图片')
            orientation = image.getexif().get(274, 1)
            image.load()  # A complete decode rejects truncated pixel streams.
            w, h = image.size
            return {'w': h, 'h': w} if orientation in (5, 6, 7, 8) else {'w': w, 'h': h}
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('图片不完整或无法解码，请重新选择图片') from exc


def prediction_svg(data):
    """Render only the completed, integer-command prediction, without ordering."""
    from drawing_prediction import command_preview
    preview = command_preview(data)
    width, height = preview['width_mm'], preview['height_mm']
    paths = []
    for row in preview['rows']:
        chain = row.get('predicted_points_mm') or []
        if len(chain) < 2:
            continue
        points = ' '.join('%.5f,%.5f' % (p[0], p[1] if preview['coordinate_system'] ==
                                      'full_canvas_xy_down' else height - p[1]) for p in chain)
        paths.append('<polyline points="%s"/>' % points)
    if not paths:
        raise ValueError('规划中没有可显示的绘画轨迹，请重新选择图片')
    # Match the idle fish: transparent canvas, warm amber gradient, rounded
    # sugar threads and a restrained highlight. Reuse the exact same geometry
    # in every layer; styling never smooths, reorders or changes motor commands.
    return ('''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
        viewBox="-2 -2 %.5f %.5f" role="img" aria-label="金色糖丝绘画预测图">
      <defs>
        <linearGradient id="sugar-amber" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="%.5f">
          <stop offset="0" stop-color="#ffe2a6"/>
          <stop offset=".5" stop-color="#f3ad45"/>
          <stop offset="1" stop-color="#d9861f"/>
        </linearGradient>
        <g id="planned-threads" fill="none" stroke-linecap="round" stroke-linejoin="round">%s</g>
      </defs>
      <use xlink:href="#planned-threads" stroke="#f3ad45" stroke-width="1.25" opacity=".12"/>
      <use xlink:href="#planned-threads" stroke="url(#sugar-amber)" stroke-width=".65"/>
      <use xlink:href="#planned-threads" stroke="#fff0cc" stroke-width=".16" opacity=".42"/>
    </svg>''' % (width + 4, height + 4, height, ''.join(paths))).encode('utf-8')


def source_image_svg(path):
    """Embed the returned artwork directly; never reconstruct robot motion.

    The SVG envelope keeps the existing preview endpoint and responsive layout.
    Preserve normal PNG/JPEG/WEBP bytes. Normalize EXIF and bound oversized
    display payloads once per job; the extraction input is never modified.
    """
    from PIL import Image,ImageOps
    raw=Path(path).read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        if image.width*image.height>16000000 or getattr(image,'n_frames',1)!=1:
            raise ValueError('预览需要一张不超过 1600 万像素的静态线稿')
        image.load()
        mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(image.format)
        if mime is None or image.getexif().get(274,1)!=1:
            normalized=ImageOps.exif_transpose(image)
            stream=io.BytesIO();normalized.save(stream,format='PNG')
            raw=stream.getvalue();mime='image/png';width,height=normalized.size
        else:width,height=image.size
        if len(raw)>384*1024:
            # Bound the one-time display payload on the software-rendered LCD.
            # This changes only the shown bitmap, never the extraction input.
            display=ImageOps.exif_transpose(image).convert('RGBA')
            paper=Image.new('RGBA',display.size,'white');paper.alpha_composite(display)
            display=paper.convert('RGB');display.thumbnail((1024,600))
            for quality in (90,75,55):
                stream=io.BytesIO();display.save(stream,format='JPEG',quality=quality,optimize=True)
                raw=stream.getvalue()
                if len(raw)<=384*1024:break
            if len(raw)>384*1024:
                display.thumbnail((640,480));stream=io.BytesIO()
                display.save(stream,format='JPEG',quality=55,optimize=True);raw=stream.getvalue()
            mime='image/jpeg';width,height=display.size
    encoded=base64.b64encode(raw).decode('ascii')
    return (('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             'viewBox="0 0 %d %d" role="img" aria-label="原始线稿预览">'
             '<image width="%d" height="%d" preserveAspectRatio="xMidYMid meet" '
             'xlink:href="data:%s;base64,%s"/></svg>')%
            (width,height,width,height,mime,encoded)).encode('utf-8')



class BoardPipeline:
    """Production adapter. Tests supply a fake with the same narrow interface."""
    def __init__(self, backend_url, data_dir, secrets_file=None, port='/dev/ttyACM0',
                 baudrate=1000000, profile='seedream', stroke_profile='sugar'):
        parsed = urlsplit(backend_url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or
                parsed.username or parsed.password or parsed.path not in ('', '/') or
                parsed.query or parsed.fragment or not parsed.port):
            raise ValueError('backend-url 必须是 http://127.0.0.1:端口')
        from scripts.arm_studio import BoardClient
        self.client = BoardClient(host='127.0.0.1', port=parsed.port)
        self.data_dir = Path(data_dir)
        self.secrets_file = Path(secrets_file) if secrets_file else None
        self.port, self.baudrate, self.profile = port, baudrate, profile
        if stroke_profile not in ('faithful', 'sugar'):
            raise ValueError('未知笔画整理模式')
        self.stroke_profile = stroke_profile
        self.poll_s = .35
        self.timeline = None
        self._execution_stop_lock=threading.RLock()
        self._stopped_execution_id=None
        self._pending_calligraphy_execute=False
        self._deferred_stop_count=0

    def busy(self):
        return bool(self.client.get_jobs().get('active'))

    def check_ready(self):
        status=self.client.fetch_status()
        if status.get('sugar_calibration_ready') is False:
            if status.get('robot_type')=='TCB705':
                raise ValueError(status.get('sugar_calibration_detail') or '请进入设置核对 ArmVision 标定与七轴模型')
            raise ValueError('新糖画模式尚未完成实测标定，请进入设置，完成“多点零位与笔长标定”和四点纸面校正后再上传')

    def generate(self, raw, folder, cancelled, subject='portrait', custom='', detail='simple'):
        self.check_ready()
        import cloud
        from cloud_gallery import CloudImageLibrary
        if self.secrets_file and self.secrets_file.is_file():
            cloud.load_secrets(self.secrets_file)
        cfg = dict(cloud.load_config(cloud.profile_path(self.profile)), client_max_edge=1024)
        try:  # which phone choice this job used (no secrets): matches a cloud error to its options
            (folder / 'cloud_request.json').write_text(json.dumps(dict(
                subject=subject, detail=detail, custom_chars=len(custom), prompt_version=cloud.PROMPT_VERSION,
                prompt_chars=len(cloud.build_prompt(subject, custom, detail))), ensure_ascii=False), encoding='utf-8')
        except (OSError, ValueError):
            pass
        image, info = cloud.generate(raw, cfg, subject, custom=custom, detail=detail)
        # Preserve successful paid results even if the user cancelled meanwhile.
        record = CloudImageLibrary(self.data_dir / 'cloud_images').save(
            image, profile=self.profile, model=cfg['model'], subject=subject, source_name='手机上传')
        try:
            (folder / 'cloud_timing.json').write_text(json.dumps(info, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        except OSError:
            pass  # The successfully generated image has already been saved.
        return record['path']

    def extract(self, image, folder, cancelled):
        from vision import convert
        self.drawing_size_mm = [100., 100.]
        return convert(image, folder / 'paths', 'lineart', 100., 100., 4000, 'fine',
                       coordinate_system='full_canvas_xy_down', diagnostics=False,
                       stroke_profile=self.stroke_profile)

    def extract_local(self, image, folder, cancelled):
        """Trace existing artwork locally, preserving aspect ratio and fine strokes."""
        from PIL import Image, ImageOps
        from vision import convert
        self.check_ready()
        if cancelled():
            raise Cancelled()
        with Image.open(image) as original:
            width, height = ImageOps.exif_transpose(original).size
        scale = 100.0 / max(width, height)
        if min(width, height) * scale < 2:
            raise ValueError('图片过窄，请裁去多余空白后重新选择')
        self.drawing_size_mm = [width * scale, height * scale]
        return convert(image, folder / 'paths', 'lineart', width * scale, height * scale,
                       4000, 'fine', coordinate_system='full_canvas_xy_down',
                       diagnostics=False, stroke_profile='faithful')

    def _wait(self, job_id, cancelled, timeout=1800, wait_after_cancel=False, progress=None):
        from scripts.arm_studio import BoardConnectionError
        deadline = time.monotonic() + timeout
        disconnected_at = None
        missing = 0
        while time.monotonic() < deadline:
            requested_at = time.monotonic()
            try:
                snapshot = self.client.get_jobs()
            except BoardConnectionError:
                # Keep ownership of the submitted job while reconnecting. In
                # particular, never repeat the plan/execute POST after a lost
                # status reply: the board may already have finished the work.
                if disconnected_at is None:
                    disconnected_at = requested_at
                missing = 0
                if time.monotonic() - disconnected_at >= 30:
                    raise BoardConnectionError(
                        '板端状态连接持续中断，请进入设置检查原任务；未重复提交任务或启动运动')
                time.sleep(self.poll_s)
                continue
            disconnected_at = None
            if cancelled() and not wait_after_cancel:
                # Stop only the operation this workflow owns, never a settings job.
                if snapshot.get('active') == job_id:
                    self.client.stop()
                raise Cancelled()
            job = next((j for j in snapshot.get('jobs', []) if j['id'] == job_id), None)
            if wait_after_cancel and cancelled() and snapshot.get('active')==job_id:
                # cancel() normally sends this request. Cover a cancellation
                # racing with execute acceptance, but never duplicate a stop:
                # the second explicit request is reserved for stopping homing.
                self._send_execution_stop(job_id, first_only=True)
            missing = missing + 1 if job is None else 0
            if missing >= 3:
                raise ValueError('板端已找不到原任务，请进入设置检查服务是否重启；未重复提交任务或启动运动')
            if job and self.timeline:
                for event, stamp in job.get('timeline', {}).items():
                    if event in ('first_command', 'first_pen_down') and event not in self.timeline.events:
                        self.timeline.mark(event, stamp)
            if job and progress:progress(job)
            if job and snapshot.get('active') != job_id:
                if wait_after_cancel and cancelled() and job.get('status') in ('DONE','FAILED'):
                    if job.get('home_after_stop_status')=='done' or job.get('motion_stage')=='RETURN_HOME_DONE':
                        raise Cancelled('已停止书写并归位',job)
                    if job.get('return_cancelled_again'):
                        raise Cancelled('已停止归位，尚未返回起始位置',job)
                    if job.get('home_after_stop_status')=='failed':
                        raise ValueError(job.get('detail') or job.get('home_after_stop_error') or '停止后归位未完成')
                    if job.get('status')=='FAILED' and str(job.get('detail','')).startswith('CANCELLED'):
                        raise Cancelled('书写已停止，未确认归位',job)
                if job.get('status') == 'FAILED':
                    raise ValueError(job.get('detail') or '板端任务失败')
                if job.get('status') == 'DONE':
                    return job
            time.sleep(self.poll_s)
        raise ValueError('板端任务超时，请进入设置检查；不会自动重试或启动运动')

    def register(self, paths, cancelled):
        job = self.client.strokes(paths)
        self._wait(job['id'], cancelled, timeout=120)
        return job['id']

    def register_calligraphy(self, module, size_mm, cancelled):
        self.check_ready()
        job=self.client._request('/api/calligraphy',method='POST',data={'module':module,'size_mm':size_mm})
        self._wait(job['id'],cancelled,timeout=120)
        return job['id']

    def text_config(self):
        return self.client._request('/api/config')

    def text_is_simulation(self):
        return self.client.fetch_status().get('simulation') is True

    def register_text(self, spec, cancelled):
        self.check_ready()
        if cancelled():raise Cancelled()
        data={k:spec[k] for k in ('text','font_size_mm','page_index','revision')}
        data['schema']='brush-text-v1'
        if spec.get('style','kai')!='kai':data['style']=spec['style']
        job=self.client._request('/api/calligraphy',method='POST',data=data)
        self._wait(job['id'],cancelled,timeout=120)
        return job['id']

    def return_home(self, cancelled, progress=None):
        """复位: one board job; never retried, a lost reply must not start a second motion."""
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        if self.robot_type!='TCB705':raise ValueError('只有天链机械臂支持复位')
        if self.busy():raise RuntimeError('板端还有任务运行，请等待结束')
        if cancelled():raise Cancelled()
        job=self.client._request('/api/home',method='POST',data={'mode':'demo' if self.simulation else 'real','confirm_physical':True},timeout=60)
        result=self._wait(job['id'],cancelled,timeout=600,wait_after_cancel=True,progress=progress)
        outcome=result.get('result') or {}
        if outcome.get('restore_deferred'):raise ValueError('已停止，但高度或反馈不允许切回手动，请检查机械臂状态')
        if outcome.get('status')!='DONE':raise ValueError('复位未确认完成')
        return result

    def register_couplet(self, spec, cancelled):
        self.check_ready()
        if cancelled():raise Cancelled()
        data=dict(schema='brush-couplet-v1',couplet_id=spec['couplet_id'],page_index=spec['page_index'],revision=spec['revision'])
        job=self.client._request('/api/calligraphy',method='POST',data=data)
        self._wait(job['id'],cancelled,timeout=120)
        return job['id']

    def couplet_plan(self, couplet_id, page_index, cancelled, progress=None):
        """春联指令库: the saved commands of one sheet (planned and saved on the board if stale)."""
        self.check_ready()
        if cancelled():raise Cancelled()
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        job=self.client._request('/api/couplet_page',method='POST',data={'couplet_id':couplet_id,'page_index':page_index,
                                 'mode':'demo' if self.simulation else 'real'})
        result=self._wait(job['id'],cancelled,timeout=1800,progress=progress)
        if (result.get('result') or {}).get('status')!='OK':raise ValueError('春联指令未就绪，请重试')
        self.check_plan(job['id'])
        return job['id'],(result.get('result') or {}).get('cached') is True

    def masterpiece_plan(self, style, column, cancelled, progress=None):
        """名帖指令库: the saved commands of one column (planned and saved on the board if stale)."""
        self.check_ready()
        if cancelled():raise Cancelled()
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        job=self.client._request('/api/masterpiece',method='POST',data={'style':style,'column':column,'mode':'demo' if self.simulation else 'real'})
        result=self._wait(job['id'],cancelled,timeout=1800,progress=progress)
        if (result.get('result') or {}).get('status')!='OK':raise ValueError('名帖指令未就绪，请重试')
        self.check_plan(job['id'])
        return job['id'],(result.get('result') or {}).get('cached') is True

    def hardpen_plan(self, text, size_mm, cancelled, progress=None):
        """硬笔作品库: the saved commands of one hard-pen piece (planned and saved on the board if stale)."""
        self.check_ready()
        if cancelled():raise Cancelled()
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        job=self.client._request('/api/hardpen_line',method='POST',data={'text':text,'font_size_mm':size_mm,
                                 'mode':'demo' if self.simulation else 'real'})
        result=self._wait(job['id'],cancelled,timeout=1800,progress=progress)
        if (result.get('result') or {}).get('status')!='OK':raise ValueError('硬笔指令未就绪，请重试')
        self.check_plan(job['id'])
        return job['id'],(result.get('result') or {}).get('cached') is True

    def hardpen_doc_plan(self, text, size_mm, layout, unit_index, cancelled, progress=None):
        """手机硬笔: the saved commands of one plan unit of a piece (planned and saved on the board if stale)."""
        self.check_ready()
        if cancelled():raise Cancelled()
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        job=self.client._request('/api/hardpen_doc',method='POST',data={'text':text,'font_size_mm':size_mm,'layout':layout,
                                 'unit_index':unit_index,'mode':'demo' if self.simulation else 'real'})
        result=self._wait(job['id'],cancelled,timeout=1800,progress=progress)
        if (result.get('result') or {}).get('status')!='OK':raise ValueError('硬笔指令未就绪，请重试')
        self.check_plan(job['id'])
        return job['id'],(result.get('result') or {}).get('cached') is True

    def hardpen_works(self):
        try:return self.client._request('/api/hardpen_works').get('works',[])
        except Exception:return []

    def poem_plan(self, poem_id, page_index, segment_index, cancelled, progress=None):
        """诗词指令库: the saved commands of one segment (planned and saved on the board if stale)."""
        self.check_ready()
        if cancelled():raise Cancelled()
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        job=self.client._request('/api/poem_segment',method='POST',data={'poem_id':poem_id,'page_index':page_index,
                                 'segment_index':segment_index,'mode':'demo' if self.simulation else 'real'})
        result=self._wait(job['id'],cancelled,timeout=1800,progress=progress)
        if (result.get('result') or {}).get('status')!='OK':raise ValueError('诗词指令未就绪，请重试')
        self.check_plan(job['id'])
        return job['id'],(result.get('result') or {}).get('cached') is True

    def plan(self, image_job, cancelled, store=False):
        caps=self.client.fetch_status()
        self.robot_type=caps.get('robot_type');self.simulation=caps.get('simulation',False)
        mode='demo' if caps.get('robot_type')=='TCB705' and caps.get('simulation') else 'real'
        if store and caps.get('robot_type')=='TCB705':
            # 照片绘画 (2026-10-28): the board keeps this drawing's commands and reuses them next time.
            job = self.client._request('/api/plan', method='POST', timeout=60, data={
                'image_job': image_job, 'mode': mode, 'motion_mode': 'tcb705', 'store': True,
                'drawing_size_mm': list(getattr(self, 'drawing_size_mm', [100., 100.]))})
        else:
            job = self.client.plan(image_job, mode=mode, port=self.port, baudrate=self.baudrate,
                                   motion_mode='sugar_fast', drawing_size_mm=getattr(self, 'drawing_size_mm', [100., 100.]), background_save=True)
        result = self._wait(job['id'], cancelled)
        if (result.get('result', {}).get('status') != 'OK' or
                not any(result.get('result', {}).get('metrics', {}).get(k) is True
                        for k in ('history_saved', 'memory_ready'))):
            raise ValueError('规划未完整就绪，请重新规划')
        self.check_plan(job['id'])
        return job['id']

    def check_plan(self, plan_id):
        plans = self.client.plans().get('plans', [])
        plan = next((p for p in plans if p['id'] == plan_id), None)
        caps=self.client.fetch_status()
        expected='demo' if caps.get('robot_type')=='TCB705' and caps.get('simulation') else 'real'
        if (not plan or plan.get('mode') != expected or plan.get('needs_replan') or
                not plan.get('matches_current_calibration')):
            raise ValueError('规划或标定已变更，请重新上传图片并规划')
        if self.busy():
            raise RuntimeError('板端还有任务运行，请等待结束')

    def preview(self, plan_id):
        return self.client.prediction_svg(plan_id)

    def execute(self, plan_id, cancelled, calligraphy=False, progress=None, speed_pct=None):
        self.check_plan(plan_id)
        if cancelled():raise Cancelled()
        if calligraphy:
            with self._execution_stop_lock:
                self._pending_calligraphy_execute=True
                self._deferred_stop_count=0
        # Never retry this POST: a lost response must not start a second drawing.
        try:
            if getattr(self, 'robot_type', None) == 'TCB705':
                data = {'plan_job': plan_id, 'mode': 'demo' if self.simulation else 'real', 'confirm_physical': True}
                if speed_pct is not None:data['speed_pct'] = speed_pct
                job = self.client._request('/api/execute', method='POST', data=data, timeout=60)
            else:
                job = self.client.execute(plan_id, mode='real', port=self.port, baudrate=self.baudrate)
        finally:
            if calligraphy:
                with self._execution_stop_lock:
                    self._pending_calligraphy_execute=False
                    deferred=self._deferred_stop_count
                    self._deferred_stop_count=0
        if calligraphy:
            if deferred:self._send_execution_stop(job['id'],first_only=True)
            if deferred>1:self._send_execution_stop(job['id'])
        result = self._wait(job['id'], cancelled, timeout=7200,
                            wait_after_cancel=bool(calligraphy),progress=progress)
        outcome = result.get('result') or {}
        if outcome.get('robot_type')=='TCB705':
            if outcome.get('restore_deferred'):
                log=outcome.get('log') or []
                restore=next((event for event in reversed(log) if isinstance(event,dict) and event.get('event')=='RESTORE'),{}) if isinstance(log,list) else {}
                steps=restore.get('steps') or []
                reasons=[str(step[2]) for step in steps if isinstance(step,(list,tuple)) and len(step)>2 and step[1] is False and step[2]] if isinstance(steps,(list,tuple)) else []
                reason='；'.join(reasons) or '高度或位置反馈尚未满足安全条件'
                raise ValueError('轨迹已停止，暂不允许切回手动；原因：'+reason+'；后续动作未启动，请检查机械臂状态')
            if not (outcome.get('task_complete') is True or outcome.get('status') == 'DONE'):
                raise ValueError('天链执行未确认完成')
            return result
        home = outcome.get('auto_home') or {}
        warning = bool(not outcome.get('task_complete') or not home.get('task_complete') or
                       outcome.get('auto_home_error') or result.get('quality_warning'))
        warning_only = (outcome.get('quality_guard_policy') == 'warn_continue' and
                        outcome.get('execution_finished') and home.get('execution_finished') and
                        not outcome.get('auto_home_error'))
        if warning and not warning_only:
            raise ValueError('绘画指令已结束，但结果或归位未完全确认，请进入设置检查')
        if warning:
            result['quality_warning'] = True
        return result

    def _send_execution_stop(self, job_id, first_only=False):
        # The lock also serializes a first stop from cancel() with the polling
        # fallback. Record before I/O: a lost reply must never cause a retry.
        with self._execution_stop_lock:
            if first_only and self._stopped_execution_id==job_id:return
            self._stopped_execution_id=job_id
            self.client.stop()

    def stop_execution(self, first_only=False):
        with self._execution_stop_lock:
            snapshot = self.client.get_jobs()
            active = snapshot.get('active')
            job = next((j for j in snapshot.get('jobs', []) if j.get('id') == active), None)
            if job and job.get('kind') in ('execute', 'home'):
                self._send_execution_stop(active,first_only=first_only)
            elif self._pending_calligraphy_execute:
                self._deferred_stop_count=max(1,self._deferred_stop_count) if first_only else min(2,self._deferred_stop_count+1)


class Workflow(TextWorkflowMixin):
    """One reservation from upload through explicit confirmation and completion."""
    cancelled_error=Cancelled
    def __init__(self, pipeline, data_dir, publish=None):
        self.pipeline = pipeline
        self.directory = Path(data_dir) / 'user_gui_jobs'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.publish = publish or (lambda event, data: None)
        self.lock = threading.RLock()
        self.worker = None
        self.cancelled = threading.Event()
        self.view = 'user'
        self._occupied = False
        self._owner = None
        self._request_id = None
        self._plan_id = None
        self._preview = None
        self._stop_clicks=0
        self.timeline = None
        self.audio_service = None
        self._read_along = False
        self.state = dict(job_id=None, phase='idle', progress=0, message='扫码上传图片，自动准备绘画',
                          preview_url=None, can_start=False, can_cancel=False, revision=0, frame_id=None)

    def set_audio_service(self, service):
        self.audio_service = service

    def _audio(self, action, key=None, owner=None):
        # Queue only: never wait for WAV, codec, a thread join or network I/O here.
        if self.audio_service and (self._read_along or action == 'stop'):
            try:self.audio_service.follow(action, key, owner=owner or self.state.get('job_id'))
            except Exception:pass  # optional sound must not interrupt motion/stop

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def _set(self, **values):
        with self.lock:
            self.state.update(values)
            if self.timeline:
                self.state['timing'] = self.timeline.summary()
            self.state['revision'] += 1
            snap = copy.deepcopy(self.state)
        self.publish('workflow', snap)
        return snap

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def reserve(self, cid, request_id=None, force=False):
        with self.lock:
            if self.view != 'user':
                raise RuntimeError('屏幕正在设置调试，请退出设置后上传')
            if not force and (self._occupied or self.state['phase'] in ('ready','awaiting_paper') or self.state.get('motion_uncertain')):
                raise RuntimeError('当前图片仍在处理或等待确认，请在板子上完成或取消后再上传')
            if request_id and self._owner == cid and self._request_id == request_id:
                raise RuntimeError('这张图片已提交，请查看本次处理状态')
            if self.pipeline.busy():
                raise RuntimeError('板端正在运行其他任务，请稍后上传')
            self._occupied = True
            self.cancelled.clear()
            self._owner, self._request_id = cid, request_id
            self._plan_id, self._preview = None, None
            self._read_along = False
            self._stop_clicks=0
            jid = uuid.uuid4().hex
            from user_gui.timeline import Timeline
            self.timeline = Timeline(self.directory / jid)
            self._set(job_id=jid, phase='idle', progress=0, message='正在接收图片',
                      preview_url=None, can_start=False, can_cancel=False, frame_id=None,
                      input_mode=None, source_url=None, preview_kind=None, motion_uncertain=False,motion_stage=None,fault_message=None,
                      text_mode=False,text=None,page_index=None,page_count=None,can_next_page=False)
            return jid

    def mark(self, jid, event):
        with self.lock:
            if jid == self.state['job_id'] and self.timeline:
                self.timeline.mark(event)

    def preview_shown(self, jid):
        with self.lock:
            if jid != self.state['job_id'] or self._preview is None:
                raise ValueError('预测图已过期')
            self.timeline.mark('preview_shown')
            return {'ok': True}

    def abandon(self, jid):
        with self.lock:
            if self.state['job_id'] == jid and self.state['phase'] == 'idle':
                self._occupied = False
                self._set(phase='error', message='图片上传失败，请重新选择图片', can_cancel=False)

    def submit(self, jid, raw, frame, input_mode='photo', cloud_options=None):
        if input_mode not in ('photo', 'lineart'):
            raise ValueError('未知图片处理方式')
        with self.lock:
            if self.state['job_id'] != jid or not self._occupied:
                raise ValueError('上传批次已失效')
            folder = self.directory / jid
            folder.mkdir(exist_ok=True)
            self.timeline.mark('upload_received')
            self.timeline.mark('validated')
            if isinstance(self.pipeline, BoardPipeline):
                self.pipeline.timeline = self.timeline
            (folder / 'input').write_bytes(raw)
            local = input_mode == 'lineart'
            self._set(phase='extracting' if local else 'cloud', progress=10,
                      message='正在读取本地线条图' if local else '正在生成云端线稿', can_cancel=True,
                      frame_id=frame['id'], input_mode=input_mode,
                      source_url=frame.get('url') if local else None)
            self.worker = threading.Thread(target=self._prepare, args=(jid, raw, folder, input_mode, cloud_options or {}),
                                           daemon=True)
            self.worker.start()
            return self.snapshot()

    def _drawing_cache(self, raw, input_mode, cloud_options):
        """照片绘画 (2026-10-28): the same picture with the same choices is drawn from what was made
        the first time (line art and strokes here, the planned commands on the board)."""
        ident = hashlib.sha256(raw + json.dumps([input_mode, cloud_options or {}], sort_keys=True).encode()).hexdigest()[:32]
        return self.directory.parent / 'drawing_cache' / ident

    def _cached_drawing(self, cache):
        try:
            meta = json.loads((cache / 'meta.json').read_text(encoding='utf-8'))
            paths = json.loads((cache / 'paths.json').read_text(encoding='utf-8'))
            image = cache / meta['image']
            if not image.is_file() or not paths.get('paths'):
                return None
            cache.touch()
            return image, paths, meta['drawing_size_mm']
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def _keep_drawing(self, cache, image, paths, keep=30):
        import shutil
        try:
            cache.mkdir(parents=True, exist_ok=True)
            name = 'image' + Path(str(image)).suffix.lower()[:5]
            shutil.copyfile(image, cache / name)
            (cache / 'paths.json').write_text(json.dumps(paths, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            (cache / 'meta.json').write_text(json.dumps(dict(image=name, drawing_size_mm=list(getattr(self.pipeline, 'drawing_size_mm', [100., 100.])),
                                                             saved=time.strftime('%Y-%m-%d %H:%M:%S'))), encoding='utf-8')
            for old in sorted(cache.parent.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[keep:]:
                shutil.rmtree(old, ignore_errors=True)
        except (OSError, ValueError, TypeError):
            shutil.rmtree(cache, ignore_errors=True)   # never leave half an entry

    def _prepare(self, jid, raw, folder, input_mode, cloud_options=None):
        try:
            self._check_cancel()
            cache = self._drawing_cache(raw, input_mode, cloud_options)
            cached = self._cached_drawing(cache)
            if cached:
                image, paths, size = cached
                self.pipeline.drawing_size_mm = list(size)
                self._set(phase='extracting', progress=40, message='这张图片画过，直接沿用上次的线稿和轨迹')
            else:
                if input_mode == 'photo':
                    self.timeline.mark('cloud_sent')
                    image = self.pipeline.generate(raw, folder, self.cancelled.is_set, **(cloud_options or {}))
                    self.timeline.mark('cloud_returned')
                else:
                    image = folder / 'input'
                self._check_cancel()
                self._set(phase='extracting', progress=40, message='正在提取连续笔画')
                self.timeline.mark('extract_started')
                extract = self.pipeline.extract_local if input_mode == 'lineart' else self.pipeline.extract
                paths = extract(image, folder, self.cancelled.is_set)
                self.timeline.mark('extract_done')
                self._keep_drawing(cache, image, paths)
            self._check_cancel()
            self._set(progress=52, message='正在登记笔画')
            image_job = self.pipeline.register(paths, self.cancelled.is_set)
            self.timeline.mark('registered')
            self._check_cancel()
            self._set(phase='planning', progress=65, message='正在读取上次保存的运动轨迹' if cached else '正在规划运动轨迹')
            plan_id = self.pipeline.plan(image_job, self.cancelled.is_set, store=True)
            self.timeline.mark('plan_all_ready')
            self._check_cancel()
            self._set(progress=90, message='正在准备线稿预览')
            preview = source_image_svg(image)
            self._check_cancel()
            (folder / 'source-preview.svg').write_bytes(preview)
            self.timeline.mark('preview_ready')
            with self.lock:
                self._check_cancel()
                self._plan_id, self._preview = plan_id, preview
                self._occupied = False
                simulated=getattr(self.pipeline,'robot_type',None)=='TCB705' and getattr(self.pipeline,'simulation',False)
                self._set(phase='ready', progress=100, message='线稿已准备好，可以模拟运行' if simulated else '准备完毕，可以开始工作',
                          preview_url='/api/workflow/preview?job_id=' + jid,
                          preview_kind='cloud_image' if input_mode=='photo' else 'source_image',
                          can_start=True, can_cancel=True)
        except Cancelled:
            self._set(phase='cancelled', message='已取消，未开始绘画', can_start=False, can_cancel=False)
        except Exception as exc:
            self._set(phase='error', message=str(exc)[:300], can_start=False, can_cancel=False)
        finally:
            with self.lock:
                if self.state['job_id'] == jid and self.worker is threading.current_thread():
                    self._occupied = False

    def submit_calligraphy(self, module, size_mm, request_id):
        from calligraphy.presets import modules,number
        modules(module);number(size_mm,10,80,'模块大小')
        jid=self.reserve('desktop_calligraphy',request_id)
        with self.lock:
            if isinstance(self.pipeline,BoardPipeline):self.pipeline.timeline=self.timeline
            self._set(phase='planning',progress=10,message='正在准备预设书法轨迹',
                      input_mode='calligraphy',module=module,can_cancel=True)
            self.worker=threading.Thread(target=self._prepare_calligraphy,args=(jid,module,size_mm),daemon=True)
            self.worker.start()
            return self.snapshot()

    def _prepare_calligraphy(self,jid,module,size_mm):
        try:
            self._check_cancel()
            source=self.pipeline.register_calligraphy(module,size_mm,self.cancelled.is_set)
            self._check_cancel()
            self.timeline.mark('registered')
            self.timeline.mark('extract_done')
            self._set(progress=45,message='正在计算七轴提按轨迹')
            plan_id=self.pipeline.plan(source,self.cancelled.is_set)
            self.timeline.mark('plan_all_ready')
            self._check_cancel()
            preview=self.pipeline.preview(plan_id)
            with self.lock:
                self._check_cancel()
                self._plan_id,self._preview=plan_id,preview
                self._occupied=False
                self.timeline.mark('preview_ready')
                self._set(phase='ready',progress=100,message='书法模块已准备好',
                          preview_url='/api/workflow/preview?job_id='+jid,can_start=True,can_cancel=True)
        except Cancelled:
            self._set(phase='cancelled',message='已取消书法任务',can_start=False,can_cancel=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:300],can_start=False,can_cancel=False)
        finally:
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def submit_masterpiece(self, style, request_id, confirmed=False, read_along=False):
        """名帖表演 (2026-10-27): pick a work and it is written at once from the board's 名帖指令库
        (commands computed in advance for the current calibration), 70 mm, speed fixed at 100 %,
        three characters per column, columns left to right, one column after another."""
        from calligraphy import composer, glyph_store
        from calligraphy.text_layout import MASTER_ROWS
        if confirmed is not True:raise ValueError('请先确认急停旁有人、机械臂周围无人')
        if style not in glyph_store.masterpieces():raise ValueError('未找到该名帖')
        m=glyph_store.manifest(style)
        composer.preview(m['characters'],MASTERPIECE_SIZE_MM,self.pipeline.text_config(),style)   # paper check before reserving
        jid=self.reserve('desktop_masterpiece',request_id)
        with self.lock:
            self._read_along = bool(read_along)
            if isinstance(self.pipeline,BoardPipeline):self.pipeline.timeline=self.timeline
            self._set(phase='planning',progress=5,message='正在读取《%s》的运动指令'%m['title'],
                      input_mode='calligraphy',module='masterpiece',style=style,text=m['characters'],can_cancel=True)
            self.worker=threading.Thread(target=self._run_masterpiece,args=(jid,style,-(-m['count']//MASTER_ROWS)),daemon=True)
            self.worker.start()
            return self.snapshot()

    def _run_masterpiece(self,jid,style,columns):
        from calligraphy import glyph_store
        m=glyph_store.manifest(style);executing=False
        try:
            plans=[]
            # Every column's commands first, so nothing moves unless the whole work is ready.
            for column in range(columns):
                self._check_cancel()
                plan,cached=self.pipeline.masterpiece_plan(style,column,self.cancelled.is_set)
                plans.append(plan)
                self._set(progress=5+int(25*(column+1)/columns),
                          message='已读取第 %d/%d 列指令'%(column+1,columns) if cached else '第 %d/%d 列指令已计算并保存'%(column+1,columns))
            self.timeline.mark('plan_all_ready')
            executing=True
            self._check_cancel()
            self._audio('play','masterpiece_'+style[3:],owner=jid)
            for column,plan in enumerate(plans):
                self._check_cancel()
                self._set(phase='drawing',progress=30+int(70*column/columns),
                          message='正在书写《%s》第 %d/%d 列，速度 %d%%'%(m['title'],column+1,columns,MASTERPIECE_SPEED_PCT),can_start=False,can_cancel=True)
                self.pipeline.execute(plan,self.cancelled.is_set,calligraphy=True,speed_pct=MASTERPIECE_SPEED_PCT,
                                      progress=lambda job:self._motion_progress(jid,job))
            self._check_cancel()
            simulated=getattr(self.pipeline,'simulation',False)
            self._set(phase='completed',progress=100,message='模拟验证完成，未发送任何机械臂运动' if simulated else '《%s》写完了，已归位'%m['title'],
                      can_cancel=False,motion_uncertain=False)
        except Cancelled as exc:
            self._set(phase='cancelled',message=str(exc) or ('已请求停止书写，请确认机械臂状态' if executing else '已取消名帖表演'),
                      can_start=False,can_cancel=False,motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+('；如仍在运动，请点击停止书写' if executing else ''),
                      can_start=False,can_cancel=executing,motion_uncertain=executing)
        finally:
            self._audio('stop',owner=jid)
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def submit_hardpen(self, text, size_mm, speed_pct, request_id, confirmed=False):
        """硬笔书法 (2026-10-27): one line in 硬笔正楷 at 1 / 1.5 / 2 cm and 70 / 85 / 100 % speed.
        The commands are kept on the board, so the same piece is written again without planning."""
        from calligraphy import hardpen
        if confirmed is not True:raise ValueError('请先确认急停旁有人、机械臂周围无人')
        size=hardpen.size_of(size_mm)
        if speed_pct not in hardpen.SPEEDS:raise ValueError('速度只能选 70%、85%、100%')
        text=''.join(ch for ch in str(text or '') if not ch.isspace())
        hardpen.task(text,size,self.pipeline.text_config())       # characters and paper check before reserving
        jid=self.reserve('desktop_hardpen',request_id)
        with self.lock:
            if isinstance(self.pipeline,BoardPipeline):self.pipeline.timeline=self.timeline
            self._set(phase='planning',progress=10,message='正在准备硬笔「%s」'%text,input_mode='calligraphy',module='hardpen',
                      text=text,font_size_mm=size,can_cancel=True)
            self.worker=threading.Thread(target=self._run_hardpen,args=(jid,text,size,int(speed_pct)),daemon=True)
            self.worker.start()
            return self.snapshot()

    def _run_hardpen(self,jid,text,size,speed):
        executing=False
        try:
            plan,cached=self.pipeline.hardpen_plan(text,size,self.cancelled.is_set)
            self._check_cancel()
            executing=True
            self._set(phase='drawing',progress=40,message=('已读取保存的指令，' if cached else '指令已计算并保存，')+'正在书写，速度 %d%%'%speed,
                      can_start=False,can_cancel=True)
            self.pipeline.execute(plan,self.cancelled.is_set,calligraphy=True,speed_pct=speed,
                                  progress=lambda job:self._motion_progress(jid,job))
            self._check_cancel()
            simulated=getattr(self.pipeline,'simulation',False)
            self._set(phase='completed',progress=100,message='模拟验证完成，未发送任何机械臂运动' if simulated else '「%s」写完了，已归位'%text,
                      can_cancel=False,motion_uncertain=False)
        except Cancelled as exc:
            self._set(phase='cancelled',message=str(exc) or ('已请求停止书写，请确认机械臂状态' if executing else '已取消硬笔书写'),
                      can_start=False,can_cancel=False,motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+('；如仍在运动，请点击停止书写' if executing else ''),
                      can_start=False,can_cancel=executing,motion_uncertain=executing)
        finally:
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def submit_hardpen_doc(self, text, size_mm, layout, speed_pct, request_id, confirmed=False):
        """硬笔作品 (2026-10-29): write a saved phone piece again from the screen, confirmed there.
        Its lines are read back from the 硬笔作品库 (planned and saved again only when stale)."""
        from calligraphy import hardpen
        if confirmed is not True:raise ValueError('请先确认急停旁有人、机械臂周围无人')
        if speed_pct not in hardpen.SPEEDS:raise ValueError('速度只能选 70%、85%、100%')
        config=self.pipeline.text_config()
        doc=hardpen.doc_layout(text,size_mm,layout,config['paper'])      # characters and paper check before reserving
        self._hardpen_tool_check(config)
        jid=self.reserve('desktop_hardpen',request_id)
        with self.lock:
            self._start_hardpen_doc(jid,doc['text'],doc['font_size_mm'],doc['layout'],doc['page_count'],int(speed_pct),hardpen.revision(config))
            return self.snapshot()

    def _run_hardpen_page(self,jid):
        """One page of a hard-pen piece (spec page_index). All of the page's plan units are ready
        (read back, or planned and saved) before anything moves; the next page follows a confirmed
        paper change (next_text_page)."""
        from calligraphy import hardpen
        executing=False
        try:
            spec=dict(self._text_spec);page=spec['page_index'];speed=spec['speed_pct'];plans=[]
            config=self.pipeline.text_config()
            if hardpen.revision(config)!=spec['revision']:raise ValueError('硬笔标定或字库已变化，请重新提交')
            doc=hardpen.doc_layout(spec['text'],spec['font_size_mm'],spec['layout'],config['paper'])
            units=doc['page_units'][page]
            for k,unit in enumerate(units):
                self._check_cancel()
                plan,cached=self.pipeline.hardpen_doc_plan(spec['text'],spec['font_size_mm'],spec['layout'],unit,self.cancelled.is_set)
                plans.append(plan)
                self._set(progress=10+int(20*(k+1)/len(units)),
                          message=('已读取第 %d 页第 %d/%d 段指令' if cached else '第 %d 页第 %d/%d 段指令已计算并保存')%(page+1,k+1,len(units)))
            self.timeline.mark('plan_all_ready')
            preview=hardpen.doc_preview_svg(spec['text'],spec['font_size_mm'],spec['layout'],config,page)
            with self.lock:
                self._check_cancel()
                self._plan_id,self._preview=(plans[0] if plans else None),preview
                self._set(preview_url='/api/workflow/preview?job_id=%s&page=%d'%(jid,page))
            executing=True
            reuse=len(units)<=3       # the workbench keeps only the latest three plans in memory
            for k,unit in enumerate(units):
                self._check_cancel()
                plan=plans[k] if reuse else self.pipeline.hardpen_doc_plan(spec['text'],spec['font_size_mm'],spec['layout'],unit,self.cancelled.is_set)[0]
                self._set(phase='drawing',message='正在书写第 %d/%d 页第 %d/%d 段，速度 %d%%'%(page+1,spec['page_count'],k+1,len(units),speed),
                          page_index=page,can_start=False,can_cancel=True)
                self.pipeline.execute(plan,self.cancelled.is_set,calligraphy=True,speed_pct=speed,
                                      progress=lambda job:self._motion_progress(jid,job))
            self._check_cancel()
            simulated=getattr(self.pipeline,'simulation',False);more=page+1<spec['page_count']
            with self.lock:
                self._check_cancel()
                self._set(phase='awaiting_paper' if more else 'completed',progress=100,page_index=page,
                          message=(('本页模拟完成，点击继续验证下一页' if more else '硬笔模拟完成，未发送任何机械臂运动') if simulated else
                                   ('第 %d 页写完并归位，请换上空白纸、固定在原标定位置，再点击继续'%(page+1)) if more else '硬笔作品写完了，已归位'),
                          can_cancel=more,can_start=False,can_next_page=more,motion_uncertain=False)
        except Cancelled as exc:
            self._set(phase='cancelled',message=str(exc) or ('已请求停止书写，请确认机械臂状态' if executing else '已取消硬笔书写'),can_cancel=False,
                      can_next_page=False,motion_stage=exc.job.get('motion_stage',self.state.get('motion_stage')),motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+('；如仍在运动，请点击停止书写' if executing else ''),
                      can_start=False,can_cancel=executing,can_next_page=False,motion_uncertain=executing)
        finally:
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def submit_poem(self, poem_id, request_id, confirmed=False, read_along=False):
        """诗词 (2026-10-27): like 名帖表演, confirmed on screen and written at once at a fixed 70 mm and
        100 % speed. Each segment is planned once and kept on the board; later writes read it back.
        One sheet at a time: all of a sheet's segments are ready before that sheet is written."""
        from calligraphy import poems
        if confirmed is not True:raise ValueError('请先确认急停旁有人、机械臂周围无人')
        p=poems.poem(poem_id);size=poems.POEM_SIZE_MM
        config=self.pipeline.text_config()
        doc=poems.layout(poem_id,size,config['paper'])      # paper check before reserving
        jid=self.reserve('desktop_poem',request_id)
        with self.lock:
            self._read_along = bool(read_along)
            if isinstance(self.pipeline,BoardPipeline):self.pipeline.timeline=self.timeline
            self._text_init()
            self._text_spec=dict(kind='poem',poem_id=poem_id,font_size_mm=size,page_index=0,page_count=doc['page_count'],
                                 revision=poems.revision(config))
            self._set(phase='planning',progress=10,message='正在读取《%s》的运动指令'%p['title'],input_mode='calligraphy',module='poem',
                      poem_id=poem_id,poem_title=p['title'],text=poems.text(poem_id),font_size_mm=size,text_mode=True,page_index=0,
                      page_count=doc['page_count'],can_next_page=False,can_cancel=True)
            self._occupied=True
            self.worker=threading.Thread(target=self._run_poem_sheet,args=(jid,dict(self._text_spec)),daemon=True)
            self.worker.start()
            return self.snapshot()

    def _plan_poem_sheet(self,spec):
        from calligraphy import poems
        count=len(poems.layout(spec['poem_id'],spec['font_size_mm'],self.pipeline.text_config()['paper'])['segments'][spec['page_index']])
        plans=[]
        for segment in range(count):
            self._check_cancel()
            plan,cached=self.pipeline.poem_plan(spec['poem_id'],spec['page_index'],segment,self.cancelled.is_set)
            plans.append(plan)
            self._set(progress=10+int(20*(segment+1)/count),
                      message=('已读取第 %d 张纸的指令（%d/%d）' if cached else '第 %d 张纸的指令已计算并保存（%d/%d）')%(spec['page_index']+1,segment+1,count))
        return plans

    def _write_poem_sheet(self,jid,plans,spec):
        """All segments of one sheet back to back; returns whether more sheets follow."""
        self._check_cancel()
        self._audio('play','poem_'+spec['poem_id'],owner=jid)
        for segment,plan in enumerate(plans):
            self._check_cancel()
            self._set(phase='drawing',message='正在书写第 %d/%d 张纸（%d/%d 段），完成后自动归位'%(spec['page_index']+1,spec['page_count'],segment+1,len(plans)),
                      page_index=spec['page_index'])
            self.pipeline.execute(plan,self.cancelled.is_set,calligraphy=True,speed_pct=POEM_SPEED_PCT,progress=lambda job:self._motion_progress(jid,job))
        self._check_cancel()
        self._audio('stop',owner=jid)
        simulated=getattr(self.pipeline,'simulation',False);more=spec['page_index']+1<spec['page_count']
        with self.lock:
            self._check_cancel()
            self._set(phase='awaiting_paper' if more else 'completed',progress=100,
                      message=(('本张模拟完成，点击继续验证下一张' if more else '这首诗模拟完成，未发送任何机械臂运动') if simulated else
                               ('第 %d 张纸写完并归位，请换上空白纸、固定在原位置，再点击继续'%(spec['page_index']+1)) if more else '这首诗写完了，已归位'),
                      can_cancel=more,can_start=False,can_next_page=more,motion_uncertain=False)

    def _run_poem_sheet(self, jid, spec):
        """Later sheets: plan this sheet's segments, then write them (paper change already confirmed)."""
        from calligraphy import poems
        executing=False
        try:
            if poems.revision(self.pipeline.text_config())!=spec['revision']:raise ValueError('标定或诗词库已变化，请重新选择')
            plans=self._plan_poem_sheet(spec)
            with self.lock:
                self._check_cancel()
                self._plan_id,self._preview=plans[0],poems.preview_svg(spec['poem_id'],spec['font_size_mm'],self.pipeline.text_config(),spec['page_index'])
                self._set(preview_url='/api/workflow/preview?job_id=%s&page=%d'%(jid,spec['page_index']))
            executing=True
            self._write_poem_sheet(jid,plans,spec)
        except Cancelled as exc:
            self._set(phase='cancelled',message=str(exc) or ('已停止本次书写' if executing else '已取消，未开始本张书写'),
                      can_start=False,can_cancel=False,can_next_page=False,motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+('；如仍在运动，请点击停止书写' if executing else ''),
                      can_start=False,can_cancel=executing,can_next_page=False,motion_uncertain=executing)
        finally:
            self._audio('stop',owner=jid)
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def home_arm(self, request_id, confirmed):
        """复位 from the screen: the arm moves back to the calibrated home pose (confirmed on screen).

        2026-10-29 强制复位: no start conditions. A picture waiting to start, a page waiting
        for paper, an unclear motion state or processing still running is dropped. Only a motion
        still running on the board is refused, since two motions cannot share the arm (停止 first)."""
        if confirmed is not True:raise ValueError('请先在屏幕上确认复位')
        if self.pipeline.busy():raise RuntimeError('机械臂还在执行其他运动，请先点停止，停下后再复位')
        worker=self.worker
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            self.cancelled.set();worker.join(timeout=15)
            if worker.is_alive():raise RuntimeError('当前任务还没停下，请先点停止，再复位')
        jid=self.reserve('desktop_home',request_id,force=True)
        with self.lock:
            if isinstance(self.pipeline,BoardPipeline):self.pipeline.timeline=self.timeline
            self._set(phase='drawing',progress=0,message='正在复位，回到归位点',input_mode='home',module='home',can_cancel=True,can_start=False)
            self.worker=threading.Thread(target=self._run_home,args=(jid,),daemon=True)
            self.worker.start()
            return self.snapshot()

    def _run_home(self,jid):
        try:
            self._check_cancel()
            result=self.pipeline.return_home(self.cancelled.is_set,progress=lambda job:self._motion_progress(jid,job))
            simulated=(result.get('result') or {}).get('simulation') is True
            self._set(phase='completed',progress=100,message='模拟复位完成，未发送任何机械臂运动' if simulated else '机械臂已复位',
                      can_cancel=False,motion_uncertain=False)
        except Cancelled as exc:
            self._set(phase='cancelled',message=str(exc) or '已停止复位，请确认机械臂状态',can_cancel=False,motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+'；如仍在运动，请点击停止',can_start=False,can_cancel=True,motion_uncertain=True)
        finally:
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def submit_couplet(self, couplet_id, request_id, confirmed=False):
        """春联模式 (2026-10-29): like 名帖表演, 70 mm on the 名帖 paper, three rows of three per sheet,
        confirmed on screen and written at once at a fixed 100 %; a paper change between sheets.
        Each row is planned once and kept on the board, later writes read it back."""
        from calligraphy import couplets
        if confirmed is not True:raise ValueError('请先确认急停旁有人、机械臂周围无人')
        c=couplets.couplet(couplet_id)
        config=self.pipeline.text_config()
        doc=couplets.layout(couplet_id,couplets.surface(config,dict(schema=couplets.SCHEMA)))   # paper check before reserving
        jid=self.reserve('desktop_couplet',request_id)
        with self.lock:
            if isinstance(self.pipeline,BoardPipeline):self.pipeline.timeline=self.timeline
            self._text_init()
            self._text_spec=dict(kind='couplet',couplet_id=couplet_id,page_index=0,page_count=doc['sheet_count'],
                                 revision=couplets.revision(config))
            self._set(phase='planning',progress=10,message='正在读取春联的运动指令',input_mode='calligraphy',module='couplet',
                      couplet_id=couplet_id,text=c['upper']+c['lower']+c['banner'],text_mode=True,page_index=0,
                      page_count=doc['sheet_count'],can_next_page=False,can_cancel=True)
            self._occupied=True
            self.worker=threading.Thread(target=self._run_couplet,args=(jid,),daemon=True)
            self.worker.start()
            return self.snapshot()

    def _run_couplet(self,jid):
        """One sheet (spec page_index) of three rows on the 名帖 paper (2026-10-29). All of the
        sheet's rows are ready (read back, or planned and saved) before anything moves; later
        sheets follow a confirmed paper change (next_text_page)."""
        from calligraphy import couplets
        executing=False
        try:
            spec=dict(self._text_spec);sheet=spec['page_index'];plans=[]
            config=self.pipeline.text_config()
            if couplets.revision(config)!=spec['revision']:raise ValueError('标定或春联库已变化，请重新选择春联')
            rows=couplets.layout(spec['couplet_id'],couplets.surface(config,dict(schema=couplets.SCHEMA)))['sheets'][sheet]
            for k,page in enumerate(rows):
                self._check_cancel()
                plan,cached=self.pipeline.couplet_plan(spec['couplet_id'],page,self.cancelled.is_set)
                plans.append(plan)
                self._set(progress=10+int(20*(k+1)/len(rows)),
                          message=('已读取第 %d 张纸第 %d 行指令' if cached else '第 %d 张纸第 %d 行指令已计算并保存')%(sheet+1,k+1))
            self.timeline.mark('plan_all_ready')
            preview=couplets.preview_svg(spec['couplet_id'],config,sheet)
            with self.lock:
                self._check_cancel()
                self._plan_id,self._preview=plans[0],preview
                self._set(preview_url='/api/workflow/preview?job_id=%s&page=%d'%(jid,sheet))
            executing=True
            for k,plan in enumerate(plans):
                self._check_cancel()
                self._set(phase='drawing',message='正在书写第 %d/%d 张纸第 %d 行，速度 %d%%，完成后自动归位'%(sheet+1,spec['page_count'],k+1,COUPLET_SPEED_PCT),
                          page_index=sheet,can_start=False,can_cancel=True)
                self.pipeline.execute(plan,self.cancelled.is_set,calligraphy=True,speed_pct=COUPLET_SPEED_PCT,
                                      progress=lambda job:self._motion_progress(jid,job))
            self._check_cancel()
            simulated=getattr(self.pipeline,'simulation',False);more=sheet+1<spec['page_count']
            with self.lock:
                self._check_cancel()
                self._set(phase='awaiting_paper' if more else 'completed',progress=100,page_index=sheet,
                          message=(('本张模拟完成，点击继续验证下一张' if more else '春联模拟完成，未发送任何机械臂运动') if simulated else
                                   ('第 %d 张纸写完并归位，请换上空白纸、固定在名帖纸的位置，再点击继续'%(sheet+1)) if more else '春联书写完成，已归位'),
                          can_cancel=more,can_start=False,can_next_page=more,motion_uncertain=False)
        except Cancelled as exc:
            self._set(phase='cancelled',message=str(exc) or ('已请求停止书写，请确认机械臂状态' if executing else '已取消春联书写'),can_cancel=False,
                      can_next_page=False,motion_stage=exc.job.get('motion_stage',self.state.get('motion_stage')),motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+('；如仍在运动，请点击停止书写' if executing else ''),
                      can_start=False,can_cancel=executing,can_next_page=False,motion_uncertain=executing)
        finally:
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def start(self, jid, revision, confirmed):
        with self.lock:
            if (confirmed is not True or jid != self.state['job_id'] or
                    type(revision) is not int or revision != self.state['revision']):
                raise ValueError('确认已过期，请查看当前预测图后重新确认')
            if (self.view != 'user' or self.state['phase'] != 'ready' or
                    not self.state['can_start'] or self._occupied):
                raise RuntimeError('当前图片尚未准备完毕或已经开始绘画')
            self._occupied = True
            self.timeline.mark('confirmed')
            tcb=getattr(self.pipeline,'robot_type',None)=='TCB705'
            self._set(phase='drawing', progress=0, message='正在模拟验证七轴轨迹，机械臂不会运动' if tcb and getattr(self.pipeline,'simulation',False) else '正在绘画，完成后自动归位',
                      can_start=False, can_cancel=True)
            self.worker = threading.Thread(target=self._execute, args=(self._plan_id, jid), daemon=True)
            self.worker.start()
            return self.snapshot()

    def _execute(self, plan_id, jid):
        try:
            self._check_cancel()
            self.timeline.mark('execute_called')
            if isinstance(self.pipeline,BoardPipeline) and self.state.get('input_mode')=='calligraphy':
                result=self.pipeline.execute(plan_id,self.cancelled.is_set,calligraphy=True,
                                             progress=lambda job:self._motion_progress(jid,job))
            else:
                result = self.pipeline.execute(plan_id, self.cancelled.is_set)
            for event, stamp in (result or {}).get('timeline', {}).items():
                self.timeline.mark(event, stamp)
            if self.cancelled.is_set():
                completed_home=(result or {}).get('motion_stage')=='RETURN_HOME_DONE'
                raise Cancelled('已停止书写并归位' if completed_home else '',result)
            message = ('绘画指令已完成，存在质量提示，可在设置中查看'
                       if (result or {}).get('quality_warning') else '绘画完成，已返回起始位置')
            outcome=(result or {}).get('result') or {}
            if outcome.get('robot_type')=='TCB705':
                message='模拟验证完成，未发送任何机械臂运动' if outcome.get('simulation') else '天链轨迹执行完成'
                if self.state.get('input_mode')=='calligraphy' and (result or {}).get('motion_stage')=='RETURN_HOME_DONE':
                    message='书写完成，已归位'
            self._set(phase='completed', progress=100, message=message, can_cancel=False, motion_uncertain=False)
        except Cancelled as exc:
            self._set(phase='cancelled', message=str(exc) or '已请求停止绘画，请确认机械臂状态', can_cancel=False,
                      motion_stage=exc.job.get('motion_stage',self.state.get('motion_stage')),motion_uncertain=False)
        except Exception as exc:
            # A failed response is not proof that an accepted motion stopped.
            # Keep the local stop control available; never resend execute.
            self._set(phase='error', message=str(exc)[:260] + '；如仍在运动，请点击停止绘画',
                      can_start=False, can_cancel=True, motion_uncertain=True)
        finally:
            with self.lock:
                if self.state['job_id'] == jid and self.worker is threading.current_thread():
                    self._occupied = False

    def _motion_progress(self,jid,job):
        with self.lock:
            if self.state['job_id']!=jid:return
            stage=job.get('motion_stage')
            if not stage:return
            if stage==self.state.get('motion_stage'):
                if job.get('restore_waiting') is True and job.get('detail') and job['detail']!=self.state.get('message'):
                    self._set(message=job['detail'])
                return
            values=dict(motion_stage=stage)
            if stage in ('HOME','RETURN_HOME','HOME_AFTER_STOP','HOME_AFTER_STOP_DONE','HOME_AFTER_STOP_FAILED','RETURN_HOME_DONE'):
                values['message']=job.get('detail') or self.state['message']
            if stage=='HOME_AFTER_STOP':values.update(phase='stopping',can_cancel=True)
            self._set(**values)

    def cancel(self, jid):
        with self.lock:
            if jid != self.state['job_id']:
                raise ValueError('任务已过期')
            if not self.state['can_cancel']:
                raise RuntimeError('当前任务不能取消')
            self.cancelled.set()
            self._audio('stop',owner=jid)
            brush_motion=(self.state.get('input_mode')=='calligraphy' and
                          (self.state['phase'] in ('drawing','stopping') or self.state.get('motion_uncertain')))
            if brush_motion:
                self._stop_clicks+=1
                waiting=self._occupied
                fault=None if waiting else self.state.get('fault_message') or self.state.get('message')
                stopped=(fault+'；已请求停止，请检查机械臂状态') if fault else '已请求停止；当前运动状态未确认，请检查机械臂'
                self._set(phase='stopping' if waiting else 'error',
                          message=('正在停止书写并归位；再次点击可停止归位' if self._stop_clicks==1 else '正在停止归位，请等待机械臂停止') if waiting else stopped,
                          can_start=False,can_cancel=True,fault_message=fault)
                try:
                    if isinstance(self.pipeline,BoardPipeline):self.pipeline.stop_execution(first_only=self._stop_clicks==1)
                    else:self.pipeline.stop_execution()
                except Exception as exc:
                    message='停止请求未确认：'+str(exc)[:180]+'；请确认机械臂状态'
                    return self._set(message=(fault+'；'+message) if fault else message,motion_uncertain=True)
                return self.snapshot()
            if self.state['phase'] == 'drawing' or self.state.get('motion_uncertain'):
                self.pipeline.stop_execution()
            message = '正在取消，请等待当前步骤结束' if self._occupied else '已取消，可以重新扫码上传图片'
            return self._set(phase='cancelled', message=message,
                             can_start=False, can_cancel=False, can_next_page=False, motion_uncertain=False)

    def reset(self, jid):
        with self.lock:
            if jid != self.state['job_id']:
                raise ValueError('任务已过期')
            if self._occupied or self.pipeline.busy():
                raise RuntimeError('任务仍在退出，请稍后重试')
            if self.state['phase'] not in ('completed', 'cancelled', 'error', 'idle'):
                raise RuntimeError('请先取消当前任务')
            self._plan_id, self._preview = None, None
            self.timeline = None
            return self._set(job_id=None, phase='idle', progress=0, message='扫码上传图片，自动准备绘画',
                             preview_url=None, can_start=False, can_cancel=False, frame_id=None,
                             input_mode=None, source_url=None, preview_kind=None,motion_uncertain=False,motion_stage=None,fault_message=None,timing={},
                             text_mode=False,text=None,page_index=None,page_count=None,can_next_page=False)

    def status_for(self, cid, jid):
        with self.lock:
            if not jid or cid != self._owner or jid != self.state['job_id']:
                raise ValueError('找不到本次上传，请重新扫码上传')
            return {key: self.state[key] for key in ('job_id', 'phase', 'progress', 'message')}

    def preview(self, jid):
        with self.lock:
            if jid != self.state['job_id'] or self._preview is None:
                raise ValueError('预测图尚未就绪')
            return self._preview

    def set_view(self, view):
        with self.lock:
            if view not in ('user', 'settings'):
                raise ValueError('未知界面')
            if view == 'settings' and (self._occupied or self.pipeline.busy()):
                raise RuntimeError('任务进行中，请结束或停止后切换界面')
            self.view = view
            self.publish('view', {'view': view})
            return {'view': view}

    def close(self):
        self.cancelled.set()
        with self.lock:
            owns_motion = self.state['phase'] in ('drawing','stopping') or self.state.get('motion_uncertain')
        if owns_motion:
            if isinstance(self.pipeline,BoardPipeline) and self.state.get('input_mode')=='calligraphy':
                self.pipeline.stop_execution(first_only=self._stop_clicks==0)
            else:self.pipeline.stop_execution()

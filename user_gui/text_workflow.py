"""Owned phone text jobs: preview -> explicit start -> page -> paper confirmation.

Uses the same Workflow reservation, cancel event and execution backend as brush
modules. Restart never recreates start authority. No SDK calls in HTTP handlers.
"""
import json
import re
import secrets
import threading
import time
from pathlib import Path
from calligraphy import composer, glyph_store

COUPLET_SPEED_PCT = 100      # 春联 (2026-10-28): fixed arm speed, like 名帖表演 and 诗词


class TextWorkflowMixin:
    def _text_init(self):
        if not hasattr(self,'_text_tickets'):
            self._text_tickets={}
            self._text_spec=None
            self._text_receipts={}

    def text_capabilities(self):
        config=self.pipeline.text_config()
        data=glyph_store.manifest()
        styles=[]
        for style in glyph_store.available():
            try:m=glyph_store.manifest(style)
            except ValueError:continue                      # a damaged optional library is simply not offered
            styles.append(dict(style=style,label=glyph_store.STYLES[style],count=m['count'],characters=m['characters'],
                               version=m['version'],font=m.get('font','Make Me a Hanzi / 文鼎楷书'),
                               notice=m.get('source_notice','')))
        return dict(count=data['count'],characters=data['characters'],version=data['version'],styles=styles,
                    min_size_mm=40,max_size_mm=70,max_characters=200,direction='ltr_rows',
                    paper={k:config['paper'][k] for k in ('width_mm','height_mm')},
                    revision=composer.revision(config),punctuation=False,
                    simulation=self.pipeline.text_is_simulation() if hasattr(self.pipeline,'text_is_simulation') else False)

    def text_preview(self,cid,text,size,style='kai'):
        if style not in glyph_store.available():raise ValueError('不支持或未安装的书体')
        doc=composer.preview(text,size,self.pipeline.text_config(),style)
        with self.lock:
            self._text_init();now=time.monotonic()
            self._text_tickets={k:v for k,v in self._text_tickets.items() if now-v['time']<600}
            while len(self._text_tickets)>=32:self._text_tickets.pop(next(iter(self._text_tickets)))
            # One current preview per phone. Editing invalidates its older ticket.
            for k in [k for k,v in self._text_tickets.items() if v['owner']==cid]:self._text_tickets.pop(k)
            ticket=secrets.token_urlsafe(18)
            self._text_tickets[ticket]=dict(owner=cid,time=now,text=doc['text'],font_size_mm=doc['font_size_mm'],
                revision=doc['revision'],page_count=doc['page_count'],style=style)
            doc['preview_id']=ticket
            return doc

    def submit_text(self,cid,data):
        from calligraphy.text_layout import normalize
        rid=data.get('request_id','')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,80}',rid):raise ValueError('无效任务编号')
        if data.get('start_requested') is not True:raise ValueError('请点击“提交并开始书写”')
        with self.lock:
            self._text_init()
            key=composer.digest([cid,rid]);payload=composer.digest(data)
            old=self._text_receipts.get(key)
            if old:
                if old['payload']!=payload:raise ValueError('任务编号已用于不同内容')
                if old['job_id']!=self.state['job_id']:raise ValueError('该任务已处理，不会重复书写')
                return self.text_status(cid,old['job_id'])
            ticket=self._text_tickets.get(data.get('preview_id'))
            if not ticket or ticket['owner']!=cid or time.monotonic()-ticket['time']>=600:raise ValueError('预览已过期，请重新预览')
            style=ticket.get('style','kai')
            if (data.get('style','kai')!=style or normalize(data.get('text'),style)!=ticket['text'] or
                data.get('font_size_mm')!=ticket['font_size_mm'] or data.get('revision')!=ticket['revision'] or
                composer.revision(self.pipeline.text_config(),style)!=ticket['revision']):
                raise ValueError('内容、书体、字号或标定已变，请重新预览')
            # Durable tombstone prevents a retried request after service restart
            # from starting the same writing again. It is not an auto-resume file.
            journal=self.directory.parent/'text_requests';journal.mkdir(exist_ok=True)
            receipt=journal/(key+'.json')
            if receipt.exists():raise ValueError('该任务已接收过；服务重启后不会自动重写，请核对纸面再新建任务')
            jid=self.reserve(cid,rid)
            try:
                with receipt.open('x',encoding='utf-8') as f:json.dump(dict(job_id=jid,payload=payload),f)
            except Exception:
                self.abandon(jid);raise
            self._text_receipts[key]=dict(job_id=jid,payload=payload)
            while len(self._text_receipts)>128:self._text_receipts.pop(next(iter(self._text_receipts)))
            self._text_spec=dict(ticket,page_index=0)
            self._text_tickets.pop(data['preview_id'],None)
            self._set(input_mode='calligraphy',text_mode=True,text=ticket['text'],page_index=0,
                      page_count=ticket['page_count'],font_size_mm=ticket['font_size_mm'],can_next_page=False,
                      style=style)
            if hasattr(self.pipeline,'timeline'):self.pipeline.timeline=self.timeline
            self.timeline.mark('confirmed')
            self._launch_text_page(jid)
            return self.text_status(cid,jid)

    # ---- 手机硬笔 (2026-10-29): text, size, speed and 横排 / 竖排 from the phone ------------------
    def _hardpen_tool_check(self,config):
        from calligraphy.presets import mounted_tool,tool_fits,TOOL_NAMES
        simulated=self.pipeline.text_is_simulation() if hasattr(self.pipeline,'text_is_simulation') else False
        tool=mounted_tool(config)
        if not simulated and not tool_fits(tool,'hardpen'):
            raise ValueError('板子当前装的是%s，请先在屏幕设置中把当前工具切换为硬笔'%TOOL_NAMES[tool])

    def hardpen_capabilities(self):
        from calligraphy import hardpen
        config=self.pipeline.text_config();m=hardpen.manifest()
        return dict(count=m['count'],characters=''.join(m['characters']),version=m['version'],
                    sizes=list(hardpen.SIZES),speeds=list(hardpen.SPEEDS),max_characters=hardpen.MAX_DOC_CHARS,
                    layouts=[dict(id=k,label=v) for k,v in hardpen.LAYOUTS.items()],
                    paper={k:config['paper'][k] for k in ('width_mm','height_mm')},revision=hardpen.revision(config),
                    simulation=self.pipeline.text_is_simulation() if hasattr(self.pipeline,'text_is_simulation') else False)

    def hardpen_preview(self,cid,text,size,layout):
        from calligraphy import hardpen
        config=self.pipeline.text_config()
        doc=hardpen.doc_preview(text,size,layout,config)
        key=hardpen.doc_key(doc['text'],doc['font_size_mm'],doc['layout'])
        works=self.pipeline.hardpen_works() if hasattr(self.pipeline,'hardpen_works') else []
        doc['saved']=any(w.get('key')==key and w.get('ready') for w in works)
        doc.pop('lines',None)
        with self.lock:
            self._text_init();now=time.monotonic()
            self._text_tickets={k:v for k,v in self._text_tickets.items() if now-v['time']<600}
            while len(self._text_tickets)>=32:self._text_tickets.pop(next(iter(self._text_tickets)))
            for k in [k for k,v in self._text_tickets.items() if v['owner']==cid]:self._text_tickets.pop(k)
            ticket=secrets.token_urlsafe(18)
            self._text_tickets[ticket]=dict(owner=cid,time=now,kind='hardpen',text=doc['text'],font_size_mm=doc['font_size_mm'],
                                            layout=doc['layout'],revision=doc['revision'],page_count=doc['page_count'])
            doc['preview_id']=ticket
            return doc

    def submit_hardpen_text(self,cid,data):
        from calligraphy import hardpen
        rid=data.get('request_id','')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,80}',rid):raise ValueError('无效任务编号')
        if data.get('start_requested') is not True:raise ValueError('请点击“提交并开始书写”')
        if data.get('speed_pct') not in hardpen.SPEEDS:raise ValueError('速度只能选 70%、85%、100%')
        with self.lock:
            self._text_init()
            key=composer.digest([cid,rid]);payload=composer.digest(data)
            old=self._text_receipts.get(key)
            if old:
                if old['payload']!=payload:raise ValueError('任务编号已用于不同内容')
                if old['job_id']!=self.state['job_id']:raise ValueError('该任务已处理，不会重复书写')
                return self.text_status(cid,old['job_id'])
            ticket=self._text_tickets.get(data.get('preview_id'))
            if not ticket or ticket.get('kind')!='hardpen' or ticket['owner']!=cid or time.monotonic()-ticket['time']>=600:
                raise ValueError('预览已过期，请重新预览')
            config=self.pipeline.text_config()
            if (hardpen.normalize_doc(data.get('text'))!=ticket['text'] or data.get('font_size_mm')!=ticket['font_size_mm'] or
                data.get('layout')!=ticket['layout'] or data.get('revision')!=ticket['revision'] or hardpen.revision(config)!=ticket['revision']):
                raise ValueError('内容、字号、排版或标定已变，请重新预览')
            self._hardpen_tool_check(config)
            journal=self.directory.parent/'text_requests';journal.mkdir(exist_ok=True)
            receipt=journal/(key+'.json')
            if receipt.exists():raise ValueError('该任务已接收过；服务重启后不会自动重写，请核对纸面再新建任务')
            jid=self.reserve(cid,rid)
            try:
                with receipt.open('x',encoding='utf-8') as f:json.dump(dict(job_id=jid,payload=payload),f)
            except Exception:
                self.abandon(jid);raise
            self._text_receipts[key]=dict(job_id=jid,payload=payload)
            while len(self._text_receipts)>128:self._text_receipts.pop(next(iter(self._text_receipts)))
            self._text_tickets.pop(data['preview_id'],None)
            self._start_hardpen_doc(jid,ticket['text'],ticket['font_size_mm'],ticket['layout'],ticket['page_count'],
                                    data['speed_pct'],ticket['revision'])
            return self.text_status(cid,jid)

    def _start_hardpen_doc(self,jid,text,size,layout,page_count,speed,revision):
        """Under self.lock with the job reserved: the first page of a hard-pen piece."""
        if hasattr(self.pipeline,'timeline'):self.pipeline.timeline=self.timeline
        self._text_init()
        self._text_spec=dict(kind='hardpen',text=text,font_size_mm=size,layout=layout,speed_pct=speed,
                             page_index=0,page_count=page_count,revision=revision)
        self._set(input_mode='calligraphy',module='hardpen',text_mode=True,text=text,font_size_mm=size,layout=layout,
                  speed_pct=speed,page_index=0,page_count=page_count,can_next_page=False)
        self.timeline.mark('confirmed')
        self._launch_text_page(jid)

    def _launch_text_page(self,jid):
        self._occupied=True
        if self._text_spec.get('kind')=='hardpen':
            self._set(phase='planning',progress=10,message='正在准备第 %d/%d 页硬笔指令'%(self._text_spec['page_index']+1,self._text_spec['page_count']),
                      can_cancel=True,can_start=False,can_next_page=False,motion_uncertain=False)
            self.worker=threading.Thread(target=self._run_hardpen_page,args=(jid,),daemon=True)
            self.worker.start()
            return
        if self._text_spec.get('kind')=='poem':
            self._set(phase='planning',progress=10,message='正在规划第 %d/%d 张纸'%(self._text_spec['page_index']+1,self._text_spec['page_count']),
                      can_cancel=True,can_start=False,can_next_page=False,motion_uncertain=False)
            self.worker=threading.Thread(target=self._run_poem_sheet,args=(jid,dict(self._text_spec)),daemon=True)
            self.worker.start()
            return
        if self._text_spec.get('kind')=='couplet':   # 2026-10-29: the next sheet of the 名帖-style couplet
            self._set(phase='planning',progress=10,message='正在读取第 %d/%d 张纸的春联指令'%(self._text_spec['page_index']+1,self._text_spec['page_count']),
                      can_cancel=True,can_start=False,can_next_page=False,motion_uncertain=False)
            self.worker=threading.Thread(target=self._run_couplet,args=(jid,),daemon=True)
            self.worker.start()
            return
        couplet=False
        self._set(phase='planning',progress=10,message='正在规划第 %d/%d 页汉字'%(self._text_spec['page_index']+1,self._text_spec['page_count']),
                  can_cancel=True,can_start=False,can_next_page=False,motion_uncertain=False)
        self.worker=threading.Thread(target=self._run_text_page,args=(jid,dict(self._text_spec)),daemon=True)
        self.worker.start()

    def _run_text_page(self,jid,spec):
        executing=False
        try:
            self._check_cancel()
            couplet=spec.get('kind')=='couplet'
            if couplet:
                from calligraphy import couplets
                if couplets.revision(self.pipeline.text_config())!=spec['revision']:raise ValueError('春联台面或春联库已变化，请重新选择春联')
                self._set(progress=40,message='正在读取横批的运动指令')
                plan_id,_=self.pipeline.couplet_plan(spec['couplet_id'],spec['page_index'],self.cancelled.is_set)
            else:
                if composer.revision(self.pipeline.text_config(),spec.get('style','kai'))!=spec['revision']:raise ValueError('标定或字库已变化，请重新预览文字')
                source=self.pipeline.register_text(spec,self.cancelled.is_set)
                self._check_cancel();self.timeline.mark('registered')
                self._set(progress=40,message='正在计算第 %d 页七轴轨迹'%(spec['page_index']+1))
                plan_id=self.pipeline.plan(source,self.cancelled.is_set)
            self.timeline.mark('plan_all_ready');self._check_cancel()
            preview=couplets.preview_svg(spec['couplet_id'],self.pipeline.text_config(),1) if couplet else self.pipeline.preview(plan_id)
            with self.lock:
                self._check_cancel()
                self._plan_id,self._preview=plan_id,preview
                simulated=getattr(self.pipeline,'simulation',False)
                message=('第 %d/%d 页：模拟书写，不发送机械臂运动' if simulated else '第 %d/%d 页：归位后按标准笔顺书写')%(spec['page_index']+1,spec['page_count'])
                self._set(phase='drawing',progress=0,message=message,
                          preview_url='/api/workflow/preview?job_id=%s&page=%d'%(jid,spec['page_index']))
            executing=True
            result=self.pipeline.execute(plan_id,self.cancelled.is_set,calligraphy=True,progress=lambda job:self._motion_progress(jid,job),
                                         speed_pct=COUPLET_SPEED_PCT if couplet else None)
            self._check_cancel()
            with self.lock:
                self._check_cancel()
                more=spec['page_index']+1<spec['page_count']
                self._set(phase='awaiting_paper' if more else 'completed',progress=100,
                    message=(('本页模拟完成，点击继续验证下一页' if more else '全部文字模拟完成，未发送任何机械臂运动') if simulated else
                             ('第 %d 页完成并归位，请更换空白纸、固定在原标定位置，再点击继续'%(spec['page_index']+1)) if more else
                             '春联书写完成，已归位' if couplet else '文字书写完成，已归位'),
                    can_cancel=more,can_start=False,can_next_page=more,motion_uncertain=False)
        except self.cancelled_error as exc:
            self._set(phase='cancelled',message=str(exc) or ('已停止本次书写' if executing else '已取消，未开始本页书写'),
                      can_start=False,can_cancel=False,can_next_page=False,motion_uncertain=False)
        except Exception as exc:
            self._set(phase='error',message=str(exc)[:260]+('；如仍在运动，请点击停止书写' if executing else ''),
                      can_start=False,can_cancel=executing,can_next_page=False,motion_uncertain=executing)
        finally:
            with self.lock:
                if self.state['job_id']==jid and self.worker is threading.current_thread():self._occupied=False

    def text_status(self,cid,jid):
        with self.lock:
            if cid!=self._owner or jid!=self.state['job_id'] or not self.state.get('text_mode'):raise ValueError('找不到本机的文字任务')
            return {k:self.state.get(k) for k in ('job_id','phase','progress','message','page_index','page_count','text','font_size_mm','style','can_cancel','can_next_page','revision','motion_uncertain')}

    def next_text_page(self,cid,jid,page_index):
        with self.lock:
            self.text_status(cid,jid)
            if type(page_index) is not int or page_index!=self.state['page_index']:raise ValueError('页码已变化，不会重复书写')
            if self._occupied or self.state['phase']!='awaiting_paper':raise RuntimeError('当前不能继续下一页')
            if self.view!='user' or self.pipeline.busy():raise RuntimeError('请先退出设置并等待机械臂空闲')
            self._text_spec['page_index']+=1
            self._set(page_index=self._text_spec['page_index'])
            self._launch_text_page(jid)
            return self.text_status(cid,jid)

    def cancel_text(self,cid,jid):
        with self.lock:
            self.text_status(cid,jid)
            return self.cancel(jid)

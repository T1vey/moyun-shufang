"""Expand ordered Chinese glyphs to the existing brush planner contract."""
import hashlib
import json
from . import glyph_store
from .curves import BrushCurve
from .presets import profile, VERSION, binding
from .text_layout import layout, VERSION as LAYOUT_VERSION, MASTER_VERSION

MASTERPIECE_SIZE_MM = 70     # 名帖表演: fixed character size (7 cm)


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def revision(config,style='kai'):
    value=dict(calibration=binding(config),brush=profile(config),module_version=VERSION,
               glyph_version=glyph_store.manifest(style)['version'],
               layout_version=MASTER_VERSION if glyph_store.is_masterpiece(style) else LAYOUT_VERSION)
    # 楷书 keeps its original revision so existing previews and plans stay valid.
    if style!='kai':value['style']=style
    return digest(value)


def _strokes(cell,style):
    if glyph_store.is_masterpiece(style):return glyph_store.glyph_at(style,cell['text_index'])['strokes']
    return glyph_store.glyph(cell['character'],style)['strokes']


def task(text,size_mm,page_index,config,style='kai',column=None):
    """column: one column of a masterpiece only (名帖指令库 plans each column on its own)."""
    doc=layout(text,size_mm,config['paper'],style)
    if type(page_index) is not int or not 0<=page_index<doc['page_count']:raise ValueError('页码无效')
    if column is not None and (not glyph_store.is_masterpiece(style) or type(column) is not int or
                               not 0<=column<doc.get('columns',0)):raise ValueError('名帖列号无效')
    p=profile(config);paths=[];depths=[];feeds=[];mapping=[]
    scale=doc['font_size_mm']/50.
    for cell in doc['pages'][page_index]:
        if column is not None and cell['column']!=column:continue
        ch=cell['character']
        if ch in ' \u3000':continue
        for index,stroke in enumerate(_strokes(cell,style)):
            dense=BrushCurve(stroke['points']).sample(scale)
            path=[[round(a[0]*scale+cell['x_mm'],6),round(a[1]*scale+cell['y_mm'],6)] for a in dense]
            if any(not 0<=x<=doc['width_mm'] or not 0<=y<=doc['height_mm'] for x,y in path):raise ValueError('字形越出标定纸面')
            paths.append(path);depths.append([round(a[2]*p['max_press_mm'],8) for a in dense]);feeds.append([a[3] for a in dense])
            mapping.append(dict(character=ch,text_index=cell['text_index'],stroke_index=index))
    meta=dict(schema='brush-text-v1',module='text',version=VERSION,brush=p,
              text=doc['text'],font_size_mm=doc['font_size_mm'],page_index=page_index,
              page_count=doc['page_count'],direction=doc['direction'],glyph_version=glyph_store.manifest(style)['version'],
              layout_version=doc['layout_version'],revision=revision(config,style),stroke_map=mapping,
              depth_mm=depths,feed_ratio=feeds)
    if style!='kai':meta['style']=style
    if column is not None:meta['column']=column
    meta['content_digest']=digest({k:v for k,v in meta.items() if k not in ('depth_mm','feed_ratio')})
    return dict(units='mm',width_mm=doc['width_mm'],height_mm=doc['height_mm'],
                coordinate_system='full_canvas_xy_down',paths=paths,calligraphy=meta)


def preview(text,size_mm,config,style='kai'):
    """Small page polylines, never a browser font or a cloud-generated character."""
    doc=layout(text,size_mm,config['paper'],style);out=[];scale=doc['font_size_mm']/50.;sampled={}
    for cells in doc['pages']:
        strokes=[]
        for c in cells:
            if c['character'] in ' \u3000':continue
            ch=c['character'] if not glyph_store.is_masterpiece(style) else c['text_index']
            if ch not in sampled:
                # Repeated characters are tessellated once, even in long text.
                sampled[ch]=[BrushCurve(s['points']).sample(scale,step_mm=1,tolerance_mm=.04,compression_step=.1,feed_step=.15)
                             for s in _strokes(c,style)]
            for pts in sampled[ch]:
                strokes.append([[round(x*scale+c['x_mm'],3),round(y*scale+c['y_mm'],3),round(d,3)] for x,y,d,v in pts])
        out.append(strokes)
    doc.update(preview_pages=out,revision=revision(config,style),glyph_version=glyph_store.manifest(style)['version'],
               style=style,style_label=glyph_store.label(style))
    return doc

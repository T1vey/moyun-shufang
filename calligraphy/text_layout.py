"""Modern Chinese horizontal layout in physical millimetres (no motion)."""
import math
import unicodedata
from .glyph_store import manifest, STYLES, is_masterpiece
from .presets import number

VERSION='text-ltr-20261022-v1'
MASTER_VERSION='masterpiece-ttb3-ltr-20261025-v1'
MASTER_ROWS=3
MAX_CHARS=200
MARGIN_MM=10.


def normalize(text, style='kai'):
    if not isinstance(text,str):raise ValueError('请输入汉字')
    text=unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n')).strip('\n ')
    if not text or len(text)>MAX_CHARS:raise ValueError('请输入 1～200 个字符（含空格、换行）')
    library=manifest(style);known=set(library['characters'])
    if is_masterpiece(style):
        if text!=library['characters']:raise ValueError('名帖表演只书写该帖选定的名句')
        return text
    missing=''.join(dict.fromkeys(c for c in text if c not in known and c not in ' \n\u3000'))
    if missing:raise ValueError(('当前 %d 字字库未收录：'%library['count'] if style=='kai' else
                                 '%s字库（%d 字）未收录：'%(STYLES[style],library['count']))+missing+'；请换用已收录汉字，标点暂不支持')
    if not any(c in known for c in text):raise ValueError('至少输入一个已收录汉字')
    return text


def masterpiece_layout(text,size,W,H):
    """名帖表演: vertical columns of three characters, columns from left to right, one page,
    the block centred on the calibrated paper."""
    gx=max(4.,size*.15);gy=max(4.,size*.1)
    cols=math.ceil(len(text)/MASTER_ROWS);rows=min(MASTER_ROWS,len(text))
    need_w=cols*size+(cols-1)*gx+2*MARGIN_MM;need_h=rows*size+(rows-1)*gy+2*MARGIN_MM
    if need_w>W+1e-8 or need_h>H+1e-8:
        raise ValueError('名帖表演需要至少 %.0f×%.0f mm 的已标定纸面（当前 %.0f×%.0f mm），请换大纸并重新标定'%(need_w,need_h,W,H))
    x0=(W-(need_w-2*MARGIN_MM))/2;y0=(H-(need_h-2*MARGIN_MM))/2
    cells=[dict(character=ch,text_index=i,row=i%MASTER_ROWS,column=i//MASTER_ROWS,
                x_mm=round(x0+(i//MASTER_ROWS)*(size+gx),6),y_mm=round(y0+(i%MASTER_ROWS)*(size+gy),6))
           for i,ch in enumerate(text)]
    return dict(text=text,font_size_mm=size,direction='ttb_columns_ltr',columns=cols,rows=rows,
                width_mm=W,height_mm=H,margin_mm=MARGIN_MM,gap_x_mm=gx,gap_y_mm=gy,
                pages=[cells],page_count=1,layout_version=MASTER_VERSION)


def layout(text,size_mm,paper,style='kai'):
    text=normalize(text,style);size=number(size_mm,40,70,'字号 (mm)')
    W=number(paper['width_mm'],1,2000,'纸面宽度');H=number(paper['height_mm'],1,2000,'纸面高度')
    if is_masterpiece(style):return masterpiece_layout(text,size,W,H)
    gx=max(4.,size*.1);gy=max(6.,size*.2)
    cols=min(5,math.floor((W-2*MARGIN_MM+gx+1e-8)/(size+gx)))
    rows=math.floor((H-2*MARGIN_MM+gy+1e-8)/(size+gy))
    if cols<1 or rows<1:raise ValueError('当前标定纸面放不下这个字号，请缩小字号或重新标定较大纸面')
    pages=[];cells=[];row=col=0;last_wrapped=False
    def flush():
        nonlocal cells,row,col
        if cells:pages.append(cells)
        cells=[];row=col=0
    for index,ch in enumerate(text):
        if ch=='\n':
            # An explicit newline after an exact row does not add a blank row.
            if not last_wrapped:row+=1;col=0
            last_wrapped=False
            if row>=rows:flush()
            continue
        last_wrapped=False
        if row>=rows:flush()
        cells.append(dict(character=ch,text_index=index,row=row,column=col,
                          x_mm=round(MARGIN_MM+col*(size+gx),6),y_mm=round(MARGIN_MM+row*(size+gy),6)))
        col+=1
        if col==cols:col=0;row+=1;last_wrapped=True
    flush()
    # Empty-space-only pages would otherwise be submitted as empty robot paths.
    if any(not any(c['character'] not in ' \u3000' for c in p) for p in pages):
        raise ValueError('有页面只有空格，请删去多余空行或空格')
    return dict(text=text,font_size_mm=size,direction='ltr_rows',columns=cols,rows=rows,
                width_mm=W,height_mm=H,margin_mm=MARGIN_MM,gap_x_mm=gx,gap_y_mm=gy,
                pages=pages,page_count=len(pages),layout_version=VERSION)

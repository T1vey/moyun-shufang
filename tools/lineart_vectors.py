"""Golden vectors from the unchanged OpenCV/Python Zhang-Suen implementation."""
import argparse, json, struct, sys
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stroke_paths import _THIN_TABLES, _THIN_KERNEL
from lineart_contract import STAGES

def passes(source, count):
    image=np.asarray(source,dtype=np.uint8).copy()
    for _ in range(count*(STAGES//2)):
        for table in _THIN_TABLES:
            code=cv2.filter2D(image,cv2.CV_16U,_THIN_KERNEL,borderType=cv2.BORDER_CONSTANT)
            image[(image!=0)&table[code]]=0
    return image

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--cosim',action='store_true');a=p.parse_args()
    rng=np.random.default_rng(20261020);cases=[]
    sizes=[(1,1),(3,65),(19,17),(17,1536),(1536,17)] if a.cosim else [(1,1),(1,1536),(1536,1),(3,65),(19,17),(65,64),(73,127),(64,1536)]
    for h,w in sizes:cases.append((f'random_{w}x{h}',rng.random((h,w))>.45,1))
    if a.cosim:
        cases.extend([('empty',np.zeros((31,33),bool),1),('solid_repeat',np.ones((71,77),bool),10)])
    else:
        for name,mask in [('empty',np.zeros((31,33),bool)),('solid',np.ones((71,77),bool)),('checker',np.indices((51,57)).sum(0)%2!=0)]:
            cases.append((name,mask,5 if name=='solid' else 1))
    images=sorted((ROOT/'build/tcb705/demo_ui').rglob('*.png'))
    images=[v for v in images if 'cloud_images' in v.parts or 'lineart_library' in v.parts]
    images+=sorted((Path.home()/'Pictures/SO101/CloudImages').glob('*.png'))
    if not images:images=[ROOT/'tests/fixtures/duck_lineart.png']
    seen=set()
    for path in images:
        if path.name in seen:continue
        image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        if image is None:continue
        seen.add(path.name)
        limit=96 if a.cosim else 1536
        if max(image.shape)>limit:
            image=cv2.resize(image,(max(1,round(image.shape[1]*limit/max(image.shape))),max(1,round(image.shape[0]*limit/max(image.shape)))))
        blurred=cv2.blur(image,(15,15)).astype(np.int16)
        mask=(image<180)|((image<238)&(blurred-image.astype(np.int16)>=5))
        cases.append((path.name,mask,1 if a.cosim else 3))
        if len(seen)>=(3 if a.cosim else 14):break
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('wb') as f:
        f.write(struct.pack('<II',0x31414c54,len(cases)))
        for name,mask,n in cases:
            gold=passes(mask,n);h,w=mask.shape
            f.write(struct.pack('<III',w,h,n));f.write(mask.astype(np.uint8).tobytes());f.write(gold.tobytes())
    a.output.with_suffix('.json').write_text(json.dumps([dict(name=name,shape=list(m.shape),passes=n) for name,m,n in cases],indent=2),encoding='utf-8')
    print('LINEART_VECTORS',len(cases),a.output)
if __name__=='__main__':main()

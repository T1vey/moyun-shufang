"""Compare bitmaps, graph topology and complete path identity on real line art."""
import argparse,json,os,platform,sys,tempfile,time
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import stroke_paths as sp
from native.lineart import get_kernel
ap=argparse.ArgumentParser();ap.add_argument('--images',type=Path,default=Path.home()/'Pictures/SO101/CloudImages');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--limit',type=int,default=14)
ap.add_argument('--pl',action='store_true',help='Require the already-loaded PL core; never download or actuate')
a=ap.parse_args()
os.environ['TCB705_LINEART']='cpu';os.environ['TCB705_NATIVE_LINEART']='auto';core=get_kernel()
if core is None:raise RuntimeError('native lineart library required')
attachment_prepare=None
if a.pl:
    from lineart_backend import prepare
    os.environ['TCB705_LINEART']='pl'
    attachment_prepare=prepare()
    if not attachment_prepare['ready']:raise RuntimeError(attachment_prepare)
    print('LINEART_PREPARE',json.dumps(attachment_prepare),flush=True)
    os.environ['TCB705_LINEART']='cpu'
records=[]
with tempfile.TemporaryDirectory(prefix='lineart_verify_') as scratch:
 for path in sorted(a.images.glob('*.png'))[:a.limit]:
    with Image.open(path) as im:
        rgba=ImageOps.exif_transpose(im).convert('RGBA');white=Image.new('RGBA',rgba.size,'white');white.alpha_composite(rgba);rgb=white.convert('RGB');rgb.thumbnail((1536,1536));gray=np.asarray(rgb.convert('L'))
    blurred=cv2.blur(gray,(15,15)).astype(np.int16);mask=(gray<180)|((gray<238)&(blurred-gray.astype(np.int16)>=5))
    t=time.perf_counter();gold=sp._thin_cpu(mask);cpu_s=time.perf_counter()-t
    t=time.perf_counter();native,n=core.thin(mask);native_s=time.perf_counter()-t
    np.testing.assert_array_equal(gold,native)
    t=time.perf_counter();graph=sp._graph_trails_python(gold);graph_s=time.perf_counter()-t
    t=time.perf_counter();fast=core.graph(gold);fast_s=time.perf_counter()-t
    if graph!=fast:raise AssertionError('graph/order differs: '+path.name)
    os.environ['TCB705_NATIVE_LINEART']='off'
    t=time.perf_counter()
    old=sp.make_result(gray,path.read_bytes(),Path(scratch)/'old','lineart',100.,100.,12000,'fine',diagnostics=False)
    old_s=time.perf_counter()-t
    os.environ['TCB705_NATIVE_LINEART']='auto'
    os.environ['TCB705_LINEART']='pl' if a.pl else 'cpu'
    pl_metrics=None
    if a.pl:
        from lineart_backend import open_accelerator
        actual,pl_metrics=open_accelerator().thin(mask)
        np.testing.assert_array_equal(gold,actual)
    t=time.perf_counter()
    new=sp.make_result(gray,path.read_bytes(),Path(scratch)/'new','lineart',100.,100.,12000,'fine',diagnostics=False)
    new_s=time.perf_counter()-t
    os.environ['TCB705_LINEART']='cpu'
    if old['paths']!=new['paths'] or old['path_sha256']!=new['path_sha256'] or old['stroke_layers']!=new['stroke_layers']:raise AssertionError('complete path differs: '+path.name)
    records.append(dict(image=path.name,shape=list(gray.shape),cpu_thin_s=cpu_s,cpp_thin_s=native_s,subiterations=n,cpu_graph_s=graph_s,cpp_graph_s=fast_s,full_cpu_s=old_s,full_accelerated_s=new_s,pl=pl_metrics,extraction=new.get('extraction'),strokes=new['strokes'],path_sha256=new['path_sha256'],exact=True))
    print('GALLERY_PASS',path.name,new['strokes'],'cpu_s=%.3f accelerated_s=%.3f'%(old_s,new_s),flush=True)
if not records:raise RuntimeError('no gallery images tested')
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(dict(passed=True,platform=platform.platform(),machine=platform.machine(),attachment_prepare=attachment_prepare,images=records,scope='Loaded PL + native CPU equality and timings' if a.pl else 'CPU/native equality only; no FPGA performance claim'),indent=2),encoding='utf-8')

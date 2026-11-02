"""Offline Mandarin SAPI recordings and two-pass loudness normalization on Windows.

PC-only dependency: imageio-ffmpeg==0.6.0. The board only needs numpy and stdlib.
Each sentence is synthesized separately; timings include its natural trailing pause.
"""
import argparse
import hashlib
import json
import re
import subprocess
import wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RATE = 48000


def read(path):
    with wave.open(str(path),'rb') as w:
        if (w.getframerate(),w.getsampwidth(),w.getnchannels()) != (RATE,2,1):
            raise ValueError('Unexpected SAPI WAV format: '+str(path))
        return w.readframes(w.getnframes())


def write(path, data):
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,RATE,0,'NONE','not compressed'));w.writeframes(data)


def normalize(ffmpeg, source, target):
    first=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-i',str(source),'-af',
        'loudnorm=I=-16:TP=-2.0:LRA=11:print_format=json','-f','null','NUL'],
        capture_output=True,text=True,check=True)
    match=re.findall(r'\{\s*"input_i".*?\}',first.stderr,re.S)
    if not match:raise ValueError('Missing loudness analysis')
    m=json.loads(match[-1])
    spec='loudnorm=I=-16:TP=-2.0:LRA=11:linear=true:print_format=json'
    for key,val in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')]:
        spec+=':'+key+'='+m[val]
    result=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-y','-i',str(source),'-af',spec,
        '-ar',str(RATE),'-ac','1','-c:a','pcm_s16le',str(target)],capture_output=True,text=True,check=True)
    # Measure the final 48 kHz / 16-bit file: resampling can raise true peaks.
    measured=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-i',str(target),'-af',
        'loudnorm=I=-16:TP=-2:LRA=11:print_format=json','-f','null','NUL'],
        capture_output=True,text=True,check=True)
    m=json.loads(re.findall(r'\{\s*"input_i".*?\}',measured.stderr,re.S)[-1])
    raw=read(target);samples=np.frombuffer(raw,dtype='<i2')
    peak=float(np.max(np.abs(samples.astype(float))))/32768
    peak_db=20*np.log10(max(peak,1e-10))
    if peak_db > -1.0 or float(m['input_tp']) > -1.0:
        raise ValueError('Audio peak exceeds -1 dBFS: '+str(target))
    return len(samples)/RATE,dict(lufs=float(m['input_i']),true_peak_db=float(m['input_tp']),sample_peak_db=round(float(peak_db),3))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--skip-sapi',action='store_true')
    ap.add_argument('--voice',default='Microsoft Huihui Desktop')
    ap.add_argument('--ffmpeg',type=Path,help='Use an existing FFmpeg executable')
    ap.add_argument('--sapi-shell',default='powershell.exe',help='PowerShell with working System.Speech voices')
    ap.add_argument('--texts',type=Path,default=ROOT/'data/audio/texts')
    ap.add_argument('--output',type=Path,default=ROOT/'data/audio')
    ap.add_argument('--work',type=Path,default=ROOT/'build/tcb705/audio_20261027/sapi')
    a=ap.parse_args();a.work.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    if a.ffmpeg:
        ffmpeg=str(a.ffmpeg)
    else:
        import imageio_ffmpeg
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    if not a.skip_sapi:
        subprocess.run([a.sapi_shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/build_audio_sapi.ps1'),
                        '-TextDirectory',str(a.texts),'-OutputDirectory',str(a.work),'-Voice',a.voice],check=True)
    items=[]
    for path in sorted(a.texts.glob('*.json')):
        item=json.loads(path.read_text(encoding='utf-8'));key=item['id']
        chunks=[b'\0\0'*14400];position=.3;timeline=[]
        for i,sentence in enumerate(item.pop('sentences')):
            raw=read(a.work/key/('%04d.wav'%i));duration=len(raw)/(2*RATE)
            timeline.append(dict(text=sentence,start=round(position,6),end=round(position+duration,6)))
            position+=duration;chunks.append(raw)
        chunks.append(b'\0\0'*14400)
        assembled=a.work/(key+'_assembled.wav');write(assembled,b''.join(chunks))
        target=a.output/(key+'.wav')
        duration,metrics=normalize(ffmpeg,assembled,target)
        if abs(duration-(position+.3))>1/RATE:
            raise ValueError('Normalization changed timeline duration: '+key)
        item.update(wav=target.name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),duration_s=duration,
                    timeline=timeline,voice=a.voice,sample_rate=RATE,channels=1,bits=16,loudness=metrics)
        items.append(item);print('AUDIO_READY',key,round(duration,2),metrics,flush=True)
    manifest=dict(schema='tcb705-readings-v1',generated='2026-10-27',items=items)
    (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('AUDIO_MANIFEST_READY',len(items),'seconds',round(sum(i['duration_s'] for i in items),1))


if __name__=='__main__':main()

"""Five-style text calligraphy release: select for next boot. Same platform build as 20261024_fp32_r1;
only Python/static files and the 行书/草书/隶书/篆书 glyph libraries differ. No FPGA reload, no motion.

  sudo /home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm/.venv/bin/python /home/xilinx/styles_check/select_styles.py
  sudo reboot

Rollback (root): delete the five zzzzzzzzzzzzzzzzzzzz-styles.conf drop-ins, point /home/xilinx/ZYNQArm back to
the release in previous_release.txt, systemctl daemon-reload, reboot.
"""
import hashlib,json,os,pathlib,re,shutil,subprocess,urllib.request
if os.geteuid()!=0:raise PermissionError('run with sudo')
base='/home/xilinx/tcb705_releases/20261024_fp32_r1/ZYNQArm'
root=pathlib.Path('/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm')
backup=pathlib.Path('/home/xilinx/tcb705_deploy_backups/20261025_styles_r1')
check=pathlib.Path('/home/xilinx/styles_check/STYLES_CHECK_PASS.json')
drop='zzzzzzzzzzzzzzzzzzzz-styles.conf'             # sorts after the FP32 drop-in, so it wins
units=('so101-platform','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl')
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def api(path):
    with op.open('http://127.0.0.1:8785'+path,timeout=5) as response:return json.load(response)
assert api('/api/jobs')['active'] is None,'Active task'
assert api('/api/handwriting/status')['phase']=='CLOSED','Handwriting session active'
assert os.path.realpath('/home/xilinx/ZYNQArm')==base,'Unexpected current release'
assert check.exists(),'Staged checks not completed'
expected=json.loads(check.read_text())['sha256']
for rel,digest in expected.items():
    assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==digest,'Changed after checks: '+rel
shutil.copy2(check,root/'STYLES_CHECK_PASS.json')
subprocess.run(['chmod','-R','go-w',str(root)],check=True)
manifest=root/'overlay/tcb705/platform.json'
subprocess.run([str(root/'.venv/bin/python'),str(root/'scripts/load_platform.py'),'--check','--manifest',str(manifest)],check=True)
commands={}
for unit in units:
    directory=pathlib.Path('/etc/systemd/system')/(unit+'.service.d')
    assert not any(p.name>=drop for p in directory.glob('*.conf')),'Later drop-in exists'
    text=subprocess.check_output(['systemctl','show',unit,'-p','ExecStart','--value'],text=True)
    match=re.search(r'argv\[\]=(.*?)\s*; ignore_errors=',text)
    assert match,unit
    command,count=re.subn(r'/home/xilinx/tcb705_releases/[^/\s]+/ZYNQArm',str(root),match[1])
    assert count and '\n' not in command
    commands[unit]=command
backup.mkdir(parents=True,exist_ok=False)
(backup/'previous_release.txt').write_text(base+'\n')
cal=pathlib.Path('/home/xilinx/tcb705_data/tcb705.machine.json')
(backup/'calibration.sha256').write_text(hashlib.sha256(cal.read_bytes()).hexdigest())
for unit in units:
    (backup/(unit+'.effective.txt')).write_bytes(subprocess.check_output(['systemctl','cat',unit]))
    directory=pathlib.Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
    (directory/drop).write_text('[Service]\nWorkingDirectory='+str(root)+'\nEnvironment="TCB705_PL_MANIFEST='+str(manifest)+
        '" "TCB705_LINEART=auto" "TCB705_NATIVE_LINEART=auto"\nExecStart=\nExecStart='+commands[unit]+'\n'+
        ('TimeoutStartSec=180\n' if unit=='so101-platform' else ''))
link=pathlib.Path('/home/xilinx/ZYNQArm');temp=link.with_name('ZYNQArm.styles-next')
assert not temp.exists() and not temp.is_symlink()
temp.symlink_to(root);temp.replace(link)
subprocess.run(['systemctl','daemon-reload'],check=True)
assert hashlib.sha256(cal.read_bytes()).hexdigest()==(backup/'calibration.sha256').read_text()
print('STYLES_SELECTED_FOR_NEXT_BOOT; no FPGA hot reload and no robot command. Now run: sudo reboot')

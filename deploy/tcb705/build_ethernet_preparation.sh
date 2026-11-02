# Build into an isolated directory. This does not change the running screen service.
set -eu
release=/home/xilinx/tcb705_releases/20261017_ethernet_preparation
archive=/home/xilinx/TCB705_20261017_ethernet_preparation.zip
test ! -e "$release"
mkdir -p "$release"
python3 - "$archive" "$release" <<'PY'
import hashlib,json,pathlib,sys,zipfile
archive,destination=map(pathlib.Path,sys.argv[1:])
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        if destination.resolve() not in (destination/item.filename).resolve().parents:
            raise ValueError('invalid archive path')
    z.extractall(destination)
root=destination/'ZYNQArm'
manifest=json.loads((root/'DELIVERY_SHA256.json').read_text())
for name,expected in manifest.items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('hash mismatch: '+name)
print('SOURCE_VERIFIED',len(manifest),flush=True)
PY
cd "$release/ZYNQArm"
runtimepython=/home/xilinx/ZYNQArm/.venv/bin/python
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
"$runtimepython" scripts/build_tcb705.py --sdk
ldd -r build/tcb705/tcb_commission_probe
ldd -r build/tcb705/libtcb_sdk_transport.so
build/tcb705/tcb_stream_selftest
# The no-argument usage check exits before any SDK initialization/connection.
if build/tcb705/tcb_commission_probe; then exit 1; else test "$?" -eq 2; fi
"$runtimepython" scripts/verify_tcb705.py --output build/tcb705/verification_ethernet_board
systemctl is-active tcb705-ui so101-md0700r so101-gt911

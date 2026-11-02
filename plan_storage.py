"""Durable execution artifacts and small, integrity-bound history references.

An execution JSON is published once. History owns only a manifest; pruning a
manifest must never remove a job artifact (including an unreferenced artifact).
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
import weakref


HISTORY_SCHEMA = 'so101-plan-reference-v1'
_receipts = {}
_receipt_lock = threading.Lock()


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise ValueError('ABORT: plan persistence cancelled')


def _json_bytes(doc, canonical=False):
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False, sort_keys=canonical).encode('utf-8')


def _sync_directory(directory):
    # Windows has no portable directory fsync. The file itself is always synced.
    if os.name == 'posix':
        fd = os.open(str(directory), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_write(path, data, cancelled=None, immutable=False):
    """Publish complete bytes only, and clean temporary files on every failure."""
    path = Path(path)
    _check_cancelled(cancelled)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(path.parent))
    tmp = Path(temporary)
    committed = False
    try:
        with os.fdopen(fd, 'wb') as stream:
            # Bound cancellation latency during a large write; JSON encoding is
            # intentionally done only once, before entering this function.
            for start in range(0, len(data), 1024 * 1024):
                _check_cancelled(cancelled)
                stream.write(data[start:start + 1024 * 1024])
            stream.flush()
            os.fsync(stream.fileno())
        _check_cancelled(cancelled)
        if immutable:
            # Same-filesystem link is an atomic create-if-absent on Linux/NTFS;
            # a duplicate job ID cannot overwrite an existing executable plan.
            os.link(str(tmp), str(path))
            tmp.unlink()
        else:
            tmp.replace(path)
        committed = True
        _sync_directory(path.parent)
    except Exception:
        if committed and not immutable:
            # A failed directory sync is not a successful history publication.
            # Immutable execution artifacts may remain orphaned for diagnosis.
            remove_history_manifest(path)
        raise
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _stat_signature(path):
    stat = Path(path).stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def remove_history_manifest(path):
    """Durably revoke a reference without touching the execution artifact."""
    path = Path(path)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _sync_directory(path.parent)


def _remember(result, receipt):
    key = id(result)
    def expired(ref):
        with _receipt_lock:
            current = _receipts.get(key)
            if current is not None and current[0] is ref:
                _receipts.pop(key, None)
    try:
        ref = weakref.ref(result, expired)
    except TypeError:
        # Legacy callers with non-weak-referenceable objects still get a receipt
        # back; no private field is ever injected into their serializable result.
        return
    with _receipt_lock:
        _receipts[key] = (ref, dict(receipt))


def get_execution_artifact(result):
    """Return this live result's receipt without changing vars(result)."""
    with _receipt_lock:
        entry = _receipts.get(id(result))
        if entry is not None and entry[0]() is result:
            return dict(entry[1])
    return None


def publish_execution_plan(path, result, cancelled=None):
    """Serialize once, fsync, and atomically publish one immutable plan.json.

    Failed planner results may be retained as diagnostics, but only OK results
    with commands can subsequently receive a history manifest.
    """
    _check_cancelled(cancelled)
    path = Path(path).resolve()
    payload = {key: value for key, value in vars(result).items() if not key.startswith('_')}
    data = _json_bytes(payload)
    _check_cancelled(cancelled)
    receipt = dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    _atomic_write(path, data, cancelled, immutable=True)
    _check_cancelled(cancelled)
    receipt['_stat'] = _stat_signature(path)
    _remember(result, receipt)
    return dict(receipt)


def publish_execution_plan_streamed(path, result, cancelled=None, checkpoint=None):
    """Background-only incremental JSON: no long C encoder GIL hold.

    The checkpoint cooperatively pauses serialization during motion. Atomic
    publication and receipts have the same integrity rules as the sync path.
    """
    _check_cancelled(cancelled)
    path = Path(path).resolve(); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=str(path.parent))
    tmp = Path(temporary); digest = hashlib.sha256(); size = 0
    payload = {key: value for key, value in vars(result).items() if not key.startswith('_')}
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    try:
        with os.fdopen(fd, 'wb') as stream:
            pending = []; count = 0
            for chunk in encoder.iterencode(payload):
                pending.append(chunk); count += len(chunk)
                if count >= 32768:
                    _check_cancelled(cancelled)
                    if checkpoint: checkpoint()
                    data = ''.join(pending).encode('utf-8')
                    stream.write(data); digest.update(data); size += len(data)
                    pending = []; count = 0
            _check_cancelled(cancelled)
            if checkpoint: checkpoint()
            data = ''.join(pending).encode('utf-8')
            stream.write(data); digest.update(data); size += len(data)
            stream.flush(); os.fsync(stream.fileno())
        _check_cancelled(cancelled)
        if checkpoint: checkpoint()
        os.link(str(tmp), str(path)); tmp.unlink(); _sync_directory(path.parent)
        receipt = dict(path=str(path), sha256=digest.hexdigest(), bytes=size, _stat=_stat_signature(path))
        _remember(result, receipt)
        return dict(receipt)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass


def _relative_artifact(path, data_root):
    root = Path(data_root).resolve()
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        raise ValueError('execution artifact is outside the data directory')


def save_history_manifest(path, metadata, result, data_root, cancelled=None):
    """Bind frozen context and hash to the existing execution artifact."""
    if getattr(result, 'status', None) != 'OK' or not getattr(result, 'commands', None):
        raise ValueError('only completed plans with commands can be saved')
    _check_cancelled(cancelled)
    path = Path(path)
    receipt = get_execution_artifact(result)
    if receipt is not None:
        try:
            relative = _relative_artifact(receipt['path'], data_root)
        except ValueError:
            receipt = None  # Legacy/imported results get one local artifact.
    if receipt is None:
        artifact = path.parent / 'artifacts' / (path.stem + '_' + uuid.uuid4().hex + '.json')
        receipt = publish_execution_plan(artifact, result, cancelled)
        relative = _relative_artifact(receipt['path'], data_root)
    # Publication generated this receipt in-process. Detect subsequent mutation
    # without reading and hashing the entire large JSON again during planning.
    if _stat_signature(receipt['path']) != receipt['_stat']:
        raise ValueError('execution artifact changed after publication')
    doc = dict(metadata)
    doc.update(schema=HISTORY_SCHEMA, status='OK', command_count=len(result.commands),
               artifact=dict(path=relative, sha256=receipt['sha256'], bytes=receipt['bytes']))
    doc['manifest_sha256'] = hashlib.sha256(_json_bytes(doc, canonical=True)).hexdigest()
    _atomic_write(path, _json_bytes(doc), cancelled)
    if cancelled is not None and cancelled():
        remove_history_manifest(path)
        raise ValueError('ABORT: plan persistence cancelled')
    return doc


def load_history_plan(path, data_root):
    """Verify references before exposing commands; continue reading legacy JSON."""
    path = Path(path)
    doc = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(doc, dict) or doc.get('job_id') != path.stem[5:]:
        raise ValueError('invalid history job identity')
    if 'schema' not in doc:
        if doc.get('status') != 'OK' or not doc.get('commands'):
            raise ValueError('incomplete legacy plan')
        return doc
    if doc['schema'] != HISTORY_SCHEMA:
        raise ValueError('unsupported plan history schema')
    expected = doc.get('manifest_sha256')
    unsigned = {key: value for key, value in doc.items() if key != 'manifest_sha256'}
    if expected != hashlib.sha256(_json_bytes(unsigned, canonical=True)).hexdigest():
        raise ValueError('plan history metadata checksum mismatch')
    ref = doc['artifact']
    relative = Path(ref['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('invalid execution artifact reference')
    artifact = Path(data_root).resolve() / relative
    _relative_artifact(artifact, data_root)  # Also reject symlinks outside root.
    if artifact.stat().st_size != ref['bytes']:
        raise ValueError('execution artifact size mismatch')
    raw = artifact.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('execution artifact checksum mismatch')
    source = json.loads(raw)
    if (doc.get('status') != 'OK' or source.get('status') != 'OK'
            or not source.get('commands') or len(source['commands']) != doc['command_count']):
        raise ValueError('incomplete execution artifact')
    doc.update(commands=source['commands'], trajectory_segments=source.get('trajectory_segments'),
               execution_contract=source.get('execution_contract'))
    return doc

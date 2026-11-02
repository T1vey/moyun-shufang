"""Cooperative, process-exclusive ownership of one physical planner IP.

Lock files must never be unlinked: replacing their inode defeats flock. An
in-flight marker survives process death and prohibits reuse during this boot.
It cannot keep userspace DMA memory alive after SIGKILL; recovery then requires
a platform reset/reboot, not removing the marker or downloading another overlay.
"""
import json
import os
from pathlib import Path
import stat
import threading
import time
import uuid
import weakref

DEFAULT_DIRECTORY = Path('/run/lock/so101-planner')


def _sync_directory(path):
    if os.name != 'nt':
        fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(fd)
        finally: os.close(fd)


class PlannerLease:
    def __init__(self, base, directory=None):
        if isinstance(base, bool) or int(base) != base or not 0 <= int(base) < 2**32:
            raise ValueError('invalid physical planner base address')
        self.base = int(base)
        self.pid = os.getpid()
        self._lock = threading.RLock()
        self._fd = None
        self._pending = False
        self._close_requested = False
        self._client = None
        directory = Path(directory) if directory is not None else DEFAULT_DIRECTORY
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionError('planner lease directory must not be a symlink')
        if os.name != 'nt' and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise PermissionError('planner lease directory must be owned and not writable by other users')
        self.path = directory / ('ip-%08x.lock' % self.base)
        self.marker = directory / ('ip-%08x.inflight.json' % self.base)
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            os.set_inheritable(fd, False)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PermissionError('invalid planner lease lock file')
            if os.name != 'nt' and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
                raise PermissionError('planner lease lock file must be private to its owner')
            if os.name == 'nt':
                import msvcrt
                if not info.st_size:
                    os.write(fd, b'\0')
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd = fd
            if os.path.lexists(self.marker):
                raise RuntimeError('planner has a stale in-flight marker; reset the platform and reboot before reuse')
        except BaseException:
            self._fd = None
            os.close(fd)
            raise

    @property
    def pending(self):
        return self._pending

    def assert_owned(self, base=None):
        self.assert_process()
        if self._fd is None:
            raise RuntimeError('planner lease is closed or inherited by another process')
        if base is not None and int(base) != self.base:
            raise ValueError('planner lease belongs to another physical IP')

    def assert_process(self):
        if self.pid != os.getpid():
            raise RuntimeError('planner lease inherited by another process; fork with PYNQ buffers is unsupported')

    def claim(self, client):
        """A borrowed loader lease cannot be shared by two live transports."""
        with self._lock:
            self.assert_owned()
            previous = self._client() if self._client is not None else None
            if previous is not None and previous is not client:
                raise RuntimeError('planner lease already belongs to a live transport')
            self._client = weakref.ref(client)

    def release_claim(self, client):
        with self._lock:
            if self._client is not None and self._client() is client:
                self._client = None

    def mark_inflight(self, job_id, generation):
        with self._lock:
            self.assert_owned()
            if self._pending or os.path.lexists(self.marker):
                raise RuntimeError('planner lease already has in-flight work')
            body = dict(schema='so101-planner-inflight-v1', base=self.base, pid=self.pid,
                        job_id=int(job_id), generation=int(generation), started_unix=time.time())
            boot = Path('/proc/sys/kernel/random/boot_id')
            if boot.exists(): body['boot_id'] = boot.read_text().strip()
            temporary = self.marker.with_name(self.marker.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with open(temporary, 'x', encoding='utf-8') as stream:
                    os.chmod(temporary, 0o600)
                    json.dump(body, stream, sort_keys=True)
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, self.marker)
                self._pending = True
                _sync_directory(self.marker.parent)
            finally:
                if temporary.exists(): temporary.unlink()

    def mark_drained(self):
        """Only the owner that has observed hardware idle may call this."""
        with self._lock:
            self.assert_owned()
            if self._pending:
                self.marker.unlink()
                _sync_directory(self.marker.parent)
                self._pending = False
            if self._close_requested: self.close()

    def close(self):
        with self._lock:
            if self._fd is None: return
            self.assert_owned()
            if self._pending:
                raise RuntimeError('planner lease still owns in-flight DDR; drain before close')
            fd, self._fd = self._fd, None
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            os.close(fd)

    def __enter__(self):
        self.assert_owned()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        with self._lock:
            if self._pending:
                # The transport guardian retains this object and closes after
                # an idle observation. Never hide the original failure.
                self._close_requested = True
            else:
                self.close()
        return False

    def __del__(self):
        try: self.close()
        except Exception: pass


def acquire_planner_lease(base, directory=None):
    return PlannerLease(base, directory)

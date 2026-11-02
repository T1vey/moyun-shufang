"""Small per-upload timing record, with monotonic durations and no image/keys."""
import json
import os
from pathlib import Path
import threading
import time


class Timeline:
    def __init__(self, folder):
        self.path = Path(folder) / 'timeline.json'
        self.lock = threading.RLock()
        self.events = {}
        self.error = None

    def mark(self, name, stamp=None):
        with self.lock:
            now = time.monotonic()
            stamp = now if stamp is None else stamp
            self.events.setdefault(name, dict(monotonic_s=stamp, unix_s=time.time()+stamp-now))
            self._save()

    def summary(self):
        with self.lock:
            def duration(a, b):
                if a in self.events and b in self.events:
                    return round(max(0., self.events[b]['monotonic_s']-self.events[a]['monotonic_s']), 3)
            fields = dict(validation_s=duration('upload_received', 'validated'),
                cloud_s=duration('cloud_sent', 'cloud_returned'),
                extraction_s=duration('extract_started' if 'extract_started' in self.events else 'cloud_returned', 'extract_done'),
                registration_s=duration('extract_done', 'registered'),
                planning_s=duration('registered', 'plan_all_ready'),
                preview_s=duration('plan_all_ready', 'preview_ready'),
                prepare_s=duration('upload_received', 'preview_ready'),
                confirmation_wait_s=duration('preview_ready', 'confirmed'),
                execution_entry_s=duration('execute_called', 'first_pen_down'))
            total = duration('upload_received', 'first_pen_down')
            wait = fields['confirmation_wait_s']
            if total is not None and wait is not None:
                fields['machine_to_first_draw_command_s'] = round(max(0., total-wait), 3)
            return {k: v for k, v in fields.items() if v is not None}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(dict(schema='so101-timeline-v1', events=self.events,
                durations=self.summary(), first_pen_down_scope='first successful DRAW serial write; not measured ink'),
                ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
            os.replace(str(tmp), str(self.path))
        except OSError as exc:
            # Timing diagnostics must never interrupt or replay an arm command.
            self.error = type(exc).__name__

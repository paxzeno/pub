"""Durable weekly wakeups, independent of the pipeline's exclusive lock."""
import os
import time
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from .io import policy_hash


def hourly_held(c, now=None):
    local = (now or datetime.now(ZoneInfo(c['timezone']))).astimezone(ZoneInfo(c['timezone']))
    return local.weekday() == 4 and local.hour in (10, 11, 12)


def queue_weekly(c):
    # O_EXCL creates a complete (empty) intent atomically, before pipeline locking.
    key = datetime.now(ZoneInfo(c['timezone'])).strftime('%G-W%V')
    path = Path(c['state_dir']) / ('weekly-request-' + key)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.fsync(fd)
        os.close(fd)
        fd = os.open(c['state_dir'], os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
    except FileExistsError:
        pass


def accept_weekly(c, store):
    from .automation import setup, save
    setup(store)
    for path in sorted(Path(c['state_dir']).glob('weekly-request-*')):
        key = path.name
        row = store.db.execute("SELECT state,body FROM automation_jobs WHERE name='weekly'").fetchone()
        body = json.loads(row[1]) if row else {}
        if body.get('request_key') == key:
            path.unlink()  # Already committed; crash before unlink is harmless.
            continue
        if row and row[0] != 'complete':
            return  # Preserve blocked/ambiguous/in-progress work, never overwrite it.
        save(store, 'weekly', 'pending', {'policy': policy_hash(c), 'started': time.time(), 'request_key': key})
        path.unlink()
        return

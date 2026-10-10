"""Serialise pubmail inference across runs, without changing the Ollama server."""
import fcntl, os
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def slot(c):
    root=c.get('state_dir')
    if not root:
        yield
        return
    path=Path(root)/'inference.lock'
    fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)

"""File-based locking to prevent concurrent backup executions."""

import fcntl
import os


class FileLock:
    """Context manager for file-based locking."""
    
    def __init__(self, lockfile_path):
        self.lockfile_path = lockfile_path
        self.lockfile = None
    
    def __enter__(self):
        self.lockfile = open(self.lockfile_path, 'w')
        try:
            fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lockfile.write(str(os.getpid()))
            self.lockfile.flush()
        except BlockingIOError:
            raise RuntimeError("Another backup instance is already running")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lockfile:
            fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_UN)
            self.lockfile.close()
            try:
                os.remove(self.lockfile_path)
            except OSError:
                pass


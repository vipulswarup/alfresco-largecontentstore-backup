"""File-based locking to prevent concurrent backup executions."""

import fcntl
import os
import tempfile
from pathlib import Path


class FileLock:
    """Context manager for file-based locking with atomic operations."""
    
    def __init__(self, lockfile_path):
        self.lockfile_path = Path(lockfile_path)
        self.lockfile = None
        self._acquired = False
    
    def __enter__(self):
        try:
            # Create lock file atomically
            self.lockfile = open(self.lockfile_path, 'w')
            fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # Write PID atomically
            self.lockfile.write(str(os.getpid()))
            self.lockfile.flush()
            os.fsync(self.lockfile.fileno())  # Ensure data is written to disk
            
            self._acquired = True
            return self
            
        except BlockingIOError:
            if self.lockfile:
                self.lockfile.close()
                self.lockfile = None
            raise RuntimeError("Another backup instance is already running")
        except Exception as e:
            if self.lockfile:
                self.lockfile.close()
                self.lockfile = None
            raise RuntimeError(f"Failed to acquire lock: {e}")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lockfile and self._acquired:
            try:
                fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                self.lockfile.close()
                self.lockfile = None
        
        # Remove lock file atomically
        if self._acquired:
            try:
                if self.lockfile_path.exists():
                    self.lockfile_path.unlink()
            except OSError:
                pass


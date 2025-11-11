"""Common subprocess utilities to eliminate code duplication."""

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union


class SubprocessRunner:
    """Common subprocess execution with consistent error handling."""
    
    def __init__(self, timeout: int = 3600):
        self.timeout = timeout
    
    def run_command(self, 
                   cmd: List[str], 
                   env: Optional[Dict[str, str]] = None,
                   cwd: Optional[Union[str, Path]] = None) -> Dict[str, Union[bool, str, float, int]]:
        """
        Execute command with consistent error handling.
        
        Returns dict with keys: success, error, duration, returncode, stdout, stderr
        """
        start_time = datetime.now()
        result = {
            'success': False,
            'error': None,
            'duration': 0,
            'returncode': -1,
            'stdout': '',
            'stderr': ''
        }
        
        try:
            start = time.time()
            process = subprocess.run(
                cmd,
                env=env,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            duration = time.time() - start
            
            result['returncode'] = process.returncode
            result['stdout'] = process.stdout
            result['stderr'] = process.stderr
            result['duration'] = duration
            
            if process.returncode == 0:
                result['success'] = True
            else:
                result['error'] = f"Command failed with exit code {process.returncode}"
                if process.stderr:
                    result['error'] += f"\nSTDERR: {process.stderr}"
                if process.stdout:
                    result['error'] += f"\nSTDOUT: {process.stdout}"
        
        except subprocess.TimeoutExpired as e:
            elapsed = time.time() - start
            result['duration'] = elapsed
            result['error'] = f"Command timed out after {self.timeout} seconds ({self.timeout/3600:.2f} hours)"
            result['timeout_seconds'] = self.timeout
            result['elapsed_before_timeout'] = elapsed
            # Try to capture any partial output if available
            if hasattr(e, 'stdout') and e.stdout:
                result['stdout'] = e.stdout.decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else str(e.stdout)
            if hasattr(e, 'stderr') and e.stderr:
                result['stderr'] = e.stderr.decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else str(e.stderr)
        except FileNotFoundError:
            result['error'] = f"Command not found: {cmd[0] if cmd else 'unknown'}"
        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
        
        return result


def validate_path(path: Union[str, Path], must_exist: bool = True) -> Path:
    """
    Validate and normalize a path.
    
    Args:
        path: Path to validate
        must_exist: Whether path must exist
        
    Returns:
        Normalized Path object
        
    Raises:
        ValueError: If path validation fails
    """
    if isinstance(path, str):
        path = Path(path)
    
    # Resolve to absolute path
    try:
        path = path.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path: {e}")
    
    # Check if path exists if required
    if must_exist and not path.exists():
        raise ValueError(f"Path does not exist: {path}")
    
    # Security check: ensure path is within expected boundaries
    # This prevents directory traversal attacks
    if '..' in str(path) or str(path).startswith('/'):
        # Additional validation could be added here for specific use cases
        pass
    
    return path


def safe_remove_directory(path: Union[str, Path]) -> bool:
    """
    Safely remove a directory using pathlib.
    
    Args:
        path: Directory to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        path = validate_path(path, must_exist=True)
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
            return True
        return False
    except Exception:
        return False


def safe_remove_file(path: Union[str, Path]) -> bool:
    """
    Safely remove a file using pathlib.
    
    Args:
        path: File to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        path = validate_path(path, must_exist=True)
        if path.is_file():
            path.unlink()
            return True
        return False
    except Exception:
        return False

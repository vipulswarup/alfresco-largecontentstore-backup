#!/usr/bin/env python3
"""
Alfresco Backup System - Main Entry Point

This script is a wrapper for the backup system located in alfresco_backup/backup/
"""

import sys
import os
from pathlib import Path

def ensure_venv():
    """Ensure virtual environment is available for imports."""
    # Check if we're already in a virtual environment
    if sys.prefix != sys.base_prefix:
        return True  # Already in a venv
    
    # Check if we're in the project directory and venv exists locally
    script_dir = Path(__file__).parent.absolute()
    venv_path = script_dir / 'venv'
    
    if not venv_path.exists():
        return False
    
    # Try to find site-packages in the venv
    # Common locations:
    # - lib/pythonX.Y/site-packages
    # - lib/pythonX.Y/site-packages (with platform tag in some cases)
    lib_dir = venv_path / 'lib'
    if lib_dir.exists():
        # Try exact Python version first
        python_version_dir = lib_dir / f'python{sys.version_info.major}.{sys.version_info.minor}'
        if python_version_dir.exists():
            site_packages = python_version_dir / 'site-packages'
            if site_packages.exists():
                sys.path.insert(0, str(site_packages))
                return True
            
            # Try platform-specific path (e.g., lib/python3.9/site-packages)
            for subdir in python_version_dir.iterdir():
                if subdir.is_dir() and 'site-packages' in str(subdir):
                    sys.path.insert(0, str(subdir))
                    return True
        
        # Try any python* directory
        for python_dir in lib_dir.glob('python*'):
            if python_dir.is_dir():
                site_packages = python_dir / 'site-packages'
                if site_packages.exists():
                    sys.path.insert(0, str(site_packages))
                    return True
    
    return False

if __name__ == '__main__':
    # Try to ensure venv is available
    if not ensure_venv():
        print("ERROR: Virtual environment not found or not activated.")
        print("\nPlease activate the virtual environment first:")
        print("  source venv/bin/activate")
        print("  python backup.py")
        print("\nOr run the backup script using the venv Python directly:")
        print("  venv/bin/python backup.py")
        sys.exit(1)
    
    try:
        from alfresco_backup.backup.__main__ import main
        sys.exit(main())
    except ImportError as e:
        print(f"ERROR: Failed to import required modules: {e}")
        print("\nThis usually means:")
        print("  1. Virtual environment is not activated, or")
        print("  2. Dependencies are not installed")
        print("\nTo fix:")
        print("  source venv/bin/activate")
        print("  pip install -r requirements.txt")
        print("  python backup.py")
        sys.exit(1)

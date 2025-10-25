#!/usr/bin/env python3
"""
Alfresco Restore System - Main Entry Point

This script is a wrapper for the restore system located in alfresco_backup/restore/
"""

import sys
from alfresco_backup.restore.__main__ import main

if __name__ == '__main__':
    sys.exit(main())

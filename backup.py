#!/usr/bin/env python3
"""
Alfresco Backup System - Main Entry Point

This script is a wrapper for the backup system located in alfresco_backup/backup/
"""

import sys
from alfresco_backup.backup.__main__ import main

if __name__ == '__main__':
    sys.exit(main())

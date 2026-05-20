#!/usr/bin/env python3
"""Alfresco backup entry point (restic multi-destination)."""

import sys


def main():
    from alfresco_backup.v2.__main__ import main as run_backup
    run_backup()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nBackup interrupted by user")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

"""Interactive destination management (used from setup.py)."""

from pathlib import Path

from .app_config import POLICIES_FILENAME
from .setup_wizard import (
    _add_filesystem_destination,
    _add_object_storage_destination,
    _init_repos,
    _load_policies,
    _save_policies,
    _show_policies,
    _validate_all,
    check_restic_installed,
    install_restic_ubuntu,
)
from .migration import migrate_legacy_env, needs_migration
import os


def manage_destinations_menu() -> None:
    print("\n" + "=" * 80)
    print("  Manage Backup Destinations (restic)")
    print("=" * 80)

    if not check_restic_installed():
        print("restic is not installed.")
        if input("Install restic via apt? [Y/n]: ").strip().lower() not in ('n', 'no'):
            if not install_restic_ubuntu(os.geteuid() != 0):
                print("Failed to install restic.")
                return
        else:
            return

    env_path = Path('.env')
    policies_path = Path(POLICIES_FILENAME)

    if not env_path.exists():
        print("Create .env first (setup menu: configure host / database).")
        return

    if needs_migration(env_path, policies_path):
        created, msg = migrate_legacy_env(env_path, policies_path)
        print(msg)

    while True:
        print("\n  1. Show backup-policies.yml")
        print("  2. Validate all destinations")
        print("  3. Initialize restic repositories")
        print("  4. Add filesystem destination")
        print("  5. Add object storage destination")
        print("  6. Remove a destination")
        print("  7. Back")
        choice = input("Choice: ").strip()
        if choice == '7':
            break
        if choice == '1':
            _show_policies(policies_path)
        elif choice == '2':
            _validate_all(env_path, policies_path)
        elif choice == '3':
            _init_repos(env_path, policies_path)
        elif choice == '4':
            _add_filesystem_destination(policies_path)
        elif choice == '5':
            _add_object_storage_destination(env_path, policies_path)
        elif choice == '6':
            _remove_destination(policies_path)
        else:
            print("Invalid choice")


def _remove_destination(policies_path: Path) -> None:
    doc = _load_policies(policies_path)
    policies = doc.get('backup_policies', [])
    if not policies:
        print("No destinations configured.")
        return
    for i, p in enumerate(policies, 1):
        print(f"  {i}. {p.get('name')}")
    choice = input("Remove which (number): ").strip()
    try:
        idx = int(choice) - 1
        removed = policies.pop(idx)
        doc['backup_policies'] = policies
        _save_policies(policies_path, doc)
        print(f"Removed {removed.get('name')}")
    except (ValueError, IndexError):
        print("Invalid selection")


def create_single_destination_policy(policies_path: Path, env_path: Path) -> None:
    """First-time setup: exactly one restic destination."""
    if policies_path.exists():
        doc = _load_policies(policies_path)
        if doc.get('backup_policies'):
            print("backup-policies.yml already has destinations. Use 'Manage destinations'.")
            return
    else:
        doc = _load_policies(policies_path)

    print("\nDestination type:")
    print("  1. Local filesystem (NAS/disk)")
    print("  2. Object storage (S3-compatible)")
    t = input("Choice [1]: ").strip() or '1'
    if t == '2':
        _add_object_storage_destination(env_path, policies_path)
    else:
        _add_filesystem_destination(policies_path)
    _init_repos(env_path, policies_path)


def create_multiple_destinations_policy(policies_path: Path, env_path: Path) -> None:
    """First-time setup: one or more restic destinations."""
    if not policies_path.exists():
        _save_policies(policies_path, _load_policies(policies_path))

    print("\nAdd destinations one at a time. Enter blank name to finish.")
    while True:
        name = input("\nDestination policy name (blank to finish): ").strip()
        if not name:
            break
        print("  1. Filesystem  2. Object storage")
        t = input("Type [1]: ").strip() or '1'
        if t == '2':
            _add_object_storage_destination(env_path, policies_path)
        else:
            _add_filesystem_destination(policies_path)

    _init_repos(env_path, policies_path)

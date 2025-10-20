#!/usr/bin/env python3
"""
Quick fix script for PostgreSQL 9.4 configuration issue.
This script fixes the wal_level setting and grants replication privileges.
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def print_info(message):
    print(f"\033[94m{message}\033[0m")

def print_success(message):
    print(f"\033[92m✓ {message}\033[0m")

def print_error(message):
    print(f"\033[91m✗ {message}\033[0m")

def print_warning(message):
    print(f"\033[93m⚠ {message}\033[0m")

def run_command(cmd, capture_output=True):
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, capture_output=capture_output, text=True, check=False)
        return result
    except Exception as e:
        print_error(f"Error running command: {e}")
        return None

def fix_postgresql_conf(alf_base_dir):
    """Fix postgresql.conf to use hot_standby instead of replica."""
    print_info("Fixing postgresql.conf for PostgreSQL 9.4...")
    
    # Find postgresql.conf
    possible_paths = [
        Path(alf_base_dir) / 'postgresql' / 'postgresql.conf',
        Path(alf_base_dir) / 'alf_data' / 'postgresql' / 'postgresql.conf',
    ]
    
    pg_conf = None
    for path in possible_paths:
        if path.exists():
            pg_conf = path
            break
    
    if not pg_conf:
        print_error(f"Could not find postgresql.conf in {alf_base_dir}")
        return False
    
    print_info(f"Found postgresql.conf: {pg_conf}")
    
    # Read the file
    try:
        with open(pg_conf, 'r') as f:
            content = f.read()
    except Exception as e:
        print_error(f"Error reading {pg_conf}: {e}")
        return False
    
    # Fix wal_level
    if 'wal_level = replica' in content:
        print_info("Fixing wal_level from 'replica' to 'hot_standby'...")
        content = content.replace('wal_level = replica', 'wal_level = hot_standby')
        
        # Write back
        try:
            with open(pg_conf, 'w') as f:
                f.write(content)
            print_success("postgresql.conf fixed successfully")
            return True
        except Exception as e:
            print_error(f"Error writing {pg_conf}: {e}")
            return False
    else:
        print_info("wal_level setting not found or already correct")
        return True

def restart_alfresco(alf_base_dir):
    """Restart Alfresco."""
    print_info("Restarting Alfresco...")
    
    alfresco_script = Path(alf_base_dir) / 'alfresco.sh'
    if not alfresco_script.exists():
        print_error(f"Alfresco script not found: {alfresco_script}")
        return False
    
    # Stop Alfresco
    print_info("Stopping Alfresco...")
    result = run_command([str(alfresco_script), 'stop'])
    if result and result.returncode != 0:
        print_warning(f"Alfresco stop returned exit code {result.returncode} (this is normal)")
    
    # Wait
    print_info("Waiting for processes to stop...")
    time.sleep(5)
    
    # Start Alfresco
    print_info("Starting Alfresco...")
    result = run_command([str(alfresco_script), 'start'])
    if result and result.returncode != 0:
        print_error(f"Alfresco start failed: {result.stderr}")
        return False
    
    print_success("Alfresco restarted successfully")
    return True

def grant_replication_privilege(pg_user):
    """Grant replication privilege to the user."""
    print_info(f"Granting replication privilege to {pg_user}...")
    
    # Try different methods
    methods = [
        ['psql', '-h', 'localhost', '-U', 'alfresco', '-d', 'postgres', '-c', f'ALTER USER {pg_user} REPLICATION;'],
        ['sudo', '-u', 'alfresco', 'psql', '-h', 'localhost', '-U', 'alfresco', '-d', 'postgres', '-c', f'ALTER USER {pg_user} REPLICATION;'],
    ]
    
    for i, method in enumerate(methods, 1):
        print_info(f"Trying method {i}...")
        result = run_command(method)
        
        if result and result.returncode == 0:
            print_success("Replication privilege granted successfully")
            return True
        else:
            print_warning(f"Method {i} failed")
            if result and result.stderr:
                print_warning(f"Error: {result.stderr.strip()}")
    
    print_error("Failed to grant replication privilege")
    print_info("Try manually:")
    print_info(f"  psql -h localhost -U alfresco -d postgres -c \"ALTER USER {pg_user} REPLICATION;\"")
    return False

def main():
    print("="*60)
    print("PostgreSQL 9.4 Configuration Fix")
    print("="*60)
    
    # Get configuration from .env file
    env_file = Path('.env')
    if not env_file.exists():
        print_error(".env file not found")
        print_info("Please run this script from the backup project directory")
        sys.exit(1)
    
    # Load .env
    config = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()
    
    alf_base_dir = config.get('ALF_BASE_DIR')
    pg_user = config.get('PGUSER', 'alfresco')
    
    if not alf_base_dir:
        print_error("ALF_BASE_DIR not found in .env file")
        sys.exit(1)
    
    print_info(f"Alfresco directory: {alf_base_dir}")
    print_info(f"PostgreSQL user: {pg_user}")
    
    # Step 1: Fix postgresql.conf
    if not fix_postgresql_conf(alf_base_dir):
        sys.exit(1)
    
    # Step 2: Restart Alfresco
    print_info("\n" + "="*40)
    print_info("RESTARTING ALFRESCO")
    print_info("="*40)
    
    if not restart_alfresco(alf_base_dir):
        sys.exit(1)
    
    # Step 3: Grant replication privilege
    print_info("\n" + "="*40)
    print_info("GRANTING REPLICATION PRIVILEGE")
    print_info("="*40)
    
    # Wait for PostgreSQL to be ready
    print_info("Waiting for PostgreSQL to be ready...")
    time.sleep(10)
    
    if not grant_replication_privilege(pg_user):
        sys.exit(1)
    
    print_success("\nPostgreSQL 9.4 configuration completed successfully!")
    print_info("You can now run the backup script.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print_info("\nScript interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)

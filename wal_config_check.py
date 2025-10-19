"""PostgreSQL WAL configuration validation."""

import re
from pathlib import Path


def check_wal_configuration(config):
    """
    Validate that PostgreSQL has proper WAL archiving settings enabled.
    
    Checks for:
    - wal_level = replica or logical (not minimal)
    - archive_mode = on
    - archive_command is set
    
    Returns dict with keys: success, error, warnings, config_file, settings
    """
    result = {
        'success': False,
        'error': None,
        'warnings': [],
        'config_file': None,
        'settings': {}
    }
    
    # Search for postgresql.conf in known locations
    search_paths = [
        config.alf_base_dir / 'alf_data' / 'postgresql' / 'postgresql.conf',
        config.alf_base_dir / 'postgresql' / 'postgresql.conf',
    ]
    
    config_file = None
    for path in search_paths:
        if path.exists() and path.is_file():
            config_file = path
            break
    
    if not config_file:
        result['error'] = (
            f"Could not find postgresql.conf in expected locations:\n"
            f"  - {search_paths[0]}\n"
            f"  - {search_paths[1]}\n"
            f"Please ensure PostgreSQL is properly configured for WAL archiving."
        )
        return result
    
    result['config_file'] = str(config_file)
    
    # Parse postgresql.conf
    try:
        with open(config_file, 'r') as f:
            content = f.read()
        
        settings = parse_postgresql_conf(content)
        result['settings'] = settings
        
        # Validate wal_level
        wal_level = settings.get('wal_level', '').lower()
        if not wal_level:
            result['warnings'].append("wal_level not explicitly set (using default)")
        elif wal_level == 'minimal':
            result['error'] = (
                f"wal_level is set to 'minimal' which does not support archiving.\n"
                f"Required: wal_level = 'replica' or 'logical'\n"
                f"Found in: {config_file}"
            )
            return result
        elif wal_level not in ['replica', 'logical']:
            result['warnings'].append(f"Unexpected wal_level value: {wal_level}")
        
        # Validate archive_mode
        archive_mode = settings.get('archive_mode', '').lower()
        if not archive_mode or archive_mode == 'off':
            result['error'] = (
                f"archive_mode is not enabled.\n"
                f"Required: archive_mode = on\n"
                f"Found in: {config_file}\n"
                f"Current value: {archive_mode or 'not set'}"
            )
            return result
        
        # Validate archive_command
        archive_command = settings.get('archive_command', '')
        if not archive_command or archive_command.strip() == '':
            result['error'] = (
                f"archive_command is not set.\n"
                f"Required: archive_command must specify where to copy WAL files\n"
                f"Found in: {config_file}"
            )
            return result
        
        # Success
        result['success'] = True
        
    except Exception as e:
        result['error'] = f"Error reading postgresql.conf: {str(e)}"
        return result
    
    return result


def parse_postgresql_conf(content):
    """
    Parse postgresql.conf content and extract key settings.
    
    Returns dict of setting_name -> value (ignoring comments and includes)
    """
    settings = {}
    
    # Pattern: setting_name = value
    # Handles quoted values and removes inline comments
    pattern = r"^\s*([a-zA-Z_]+)\s*=\s*(.+?)(?:\s*#.*)?$"
    
    for line in content.split('\n'):
        # Skip comment lines and empty lines
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        match = re.match(pattern, line)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            
            # Remove quotes if present
            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            
            # Store only relevant WAL settings
            if key in ['wal_level', 'archive_mode', 'archive_command', 'max_wal_senders']:
                settings[key] = value
    
    return settings


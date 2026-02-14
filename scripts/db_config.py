#!/usr/bin/env python3
"""
Database Configuration for Results Database

This module provides configuration for switching between SQLite and PostgreSQL databases.
It loads settings from environment variables or a .env file for secure credential management.

Usage:
    # Using environment variables:
    export DB_TYPE=postgresql
    export DB_HOST=localhost
    export DB_PORT=5432
    export DB_NAME=befaas_results
    export DB_USER=postgres
    export DB_PASSWORD=your_password
    python results_db.py import-all scripts/results

    # Or using a .env file (create .env in the scripts directory):
    DB_TYPE=postgresql
    DB_HOST=localhost
    DB_PORT=5432
    DB_NAME=befaas_results
    DB_USER=postgres
    DB_PASSWORD=your_password

    # Then use results_db.py without --db flag to use configured database:
    python results_db.py import-all scripts/results

    # Or directly specify the database URL:
    python results_db.py --db "postgresql://user:pass@host:5432/dbname" import-all scripts/results

Configuration Options:
    DB_TYPE:     Database type - 'sqlite' (default) or 'postgresql'
    DB_HOST:     PostgreSQL host (default: localhost)
    DB_PORT:     PostgreSQL port (default: 5432)
    DB_NAME:     PostgreSQL database name (default: befaas_results)
    DB_USER:     PostgreSQL username (default: postgres)
    DB_PASSWORD: PostgreSQL password (required for PostgreSQL)
    DB_SQLITE_PATH: SQLite database file path (default: results.db)

PostgreSQL Setup:
    1. Install PostgreSQL
    2. Create database: CREATE DATABASE befaas_results;
    3. Install psycopg2: pip install psycopg2-binary
    4. Configure environment variables or .env file
    5. Run: python results_db.py init
"""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus


def load_env_file(env_path: Optional[Path] = None) -> dict:
    """
    Load environment variables from a .env file.

    Args:
        env_path: Path to .env file. If None, looks in current directory and scripts directory.

    Returns:
        Dictionary of environment variables from the file
    """
    env_vars = {}

    # Try to find .env file
    search_paths = []
    if env_path:
        search_paths.append(env_path)
    else:
        # Look in common locations
        search_paths = [
            Path.cwd() / '.env',
            Path(__file__).parent / '.env',
            Path(__file__).parent.parent / '.env',
        ]

    for path in search_paths:
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    # Parse key=value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present
                        if value and value[0] in '"\'':
                            value = value[1:-1] if len(value) > 1 and value[-1] == value[0] else value[1:]
                        env_vars[key] = value
            break

    return env_vars


def get_config() -> dict:
    """
    Get database configuration from environment variables.

    Returns:
        Dictionary with database configuration
    """
    # Load .env file if present
    env_vars = load_env_file()

    # Helper to get config value (env var takes precedence over .env file)
    def get(key: str, default: str = None) -> Optional[str]:
        return os.environ.get(key, env_vars.get(key, default))

    return {
        'type': get('DB_TYPE', 'sqlite'),
        'host': get('DB_HOST', 'localhost'),
        'port': int(get('DB_PORT', '5432')),
        'name': get('DB_NAME', 'befaas_results'),
        'user': get('DB_USER', 'postgres'),
        'password': get('DB_PASSWORD', ''),
        'sqlite_path': get('DB_SQLITE_PATH', 'results.db'),
    }


def get_database_url(config: dict = None) -> str:
    """
    Generate database URL from configuration.

    Args:
        config: Configuration dictionary. If None, uses get_config().

    Returns:
        SQLAlchemy database URL string
    """
    if config is None:
        config = get_config()

    db_type = config.get('type', 'sqlite').lower()

    if db_type == 'sqlite':
        return f"sqlite:///{config.get('sqlite_path', 'results.db')}"

    elif db_type in ('postgresql', 'postgres', 'pg'):
        # URL-encode password to handle special characters
        password = quote_plus(config.get('password', ''))
        user = config.get('user', 'postgres')
        host = config.get('host', 'localhost')
        port = config.get('port', 5432)
        name = config.get('name', 'befaas_results')

        if password:
            return f"postgresql://{user}:{password}@{host}:{port}/{name}"
        else:
            return f"postgresql://{user}@{host}:{port}/{name}"

    else:
        raise ValueError(f"Unsupported database type: {db_type}. Use 'sqlite' or 'postgresql'.")


def print_config():
    """Print current database configuration (password masked)."""
    config = get_config()
    print("Database Configuration:")
    print(f"  Type: {config['type']}")

    if config['type'].lower() in ('postgresql', 'postgres', 'pg'):
        print(f"  Host: {config['host']}")
        print(f"  Port: {config['port']}")
        print(f"  Database: {config['name']}")
        print(f"  User: {config['user']}")
        print(f"  Password: {'*' * len(config['password']) if config['password'] else '(not set)'}")
    else:
        print(f"  SQLite Path: {config['sqlite_path']}")

    print(f"\nConnection URL: {get_database_url(config).replace(config['password'], '***') if config['password'] else get_database_url(config)}")


def create_env_template():
    """Create a template .env file with example configuration."""
    template = """# BeFaaS Results Database Configuration
# Copy this file to .env and fill in your values

# Database type: 'sqlite' or 'postgresql'
DB_TYPE=sqlite

# SQLite settings (only used when DB_TYPE=sqlite)
DB_SQLITE_PATH=results.db

# PostgreSQL settings (only used when DB_TYPE=postgresql)
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=befaas_results
# DB_USER=postgres
# DB_PASSWORD=your_password_here
"""

    env_path = Path(__file__).parent / '.env.template'
    with open(env_path, 'w') as f:
        f.write(template)
    print(f"Created template at: {env_path}")
    print("Copy to .env and configure your database settings.")


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'template':
        create_env_template()
    else:
        print_config()
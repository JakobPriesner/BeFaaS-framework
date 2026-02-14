"""
Database configuration for BeFaaS benchmark imports.

Edit the values below to configure your database connection.
"""

from urllib.parse import quote_plus

# =============================================================================
# DATABASE CONFIGURATION - Edit these values
# =============================================================================

# Database type: 'postgresql' (SQLite not supported by db_import)
DB_TYPE = "postgresql"

# PostgreSQL connection settings
DB_HOST = "192.168.178.22"
DB_PORT = 5437
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "jxmEaRj^R5@5wF1@SQvCPi4&eqdG7B3y"  # Set your password here

# =============================================================================
# Helper functions (no need to edit below)
# =============================================================================


def get_config() -> dict:
    """Get database configuration as a dictionary."""
    return {
        "type": DB_TYPE,
        "host": DB_HOST,
        "port": DB_PORT,
        "name": DB_NAME,
        "user": DB_USER,
        "password": DB_PASSWORD,
    }


def get_database_url() -> str:
    """Generate SQLAlchemy database URL from configuration."""
    if DB_TYPE.lower() not in ("postgresql", "postgres", "pg"):
        raise ValueError("Only PostgreSQL is supported. Set DB_TYPE='postgresql'")

    # URL-encode password to handle special characters
    password = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""

    if password:
        return f"postgresql://{DB_USER}:{password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    else:
        return f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def print_config():
    """Print current configuration (password masked)."""
    print("Database Configuration:")
    print(f"  Type:     {DB_TYPE}")
    print(f"  Host:     {DB_HOST}")
    print(f"  Port:     {DB_PORT}")
    print(f"  Database: {DB_NAME}")
    print(f"  User:     {DB_USER}")
    print(f"  Password: {'*' * len(DB_PASSWORD) if DB_PASSWORD else '(not set)'}")

    masked_url = get_database_url()
    if DB_PASSWORD:
        masked_url = masked_url.replace(quote_plus(DB_PASSWORD), "***")
    print(f"\nConnection URL: {masked_url}")


if __name__ == "__main__":
    print_config()
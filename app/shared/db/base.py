from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import MetaData, func
from sqlalchemy.types import TIMESTAMP

# Recommended naming convention for constraints (required for Alembic with SQLite/Postgres)
class Base(DeclarativeBase):
    pass

import os

def get_partition_args(strategy: str) -> dict:
    """
    Returns partitioning arguments for Postgres, or empty dict for SQLite/Testing.
    Avoids CompileError on SQLite.
    """
    db_url = os.environ.get("DATABASE_URL", "").lower()
    test_db_url = os.environ.get("TEST_DATABASE_URL", "").lower()
    
    # If testing with SQLite, skip partitioning
    if "sqlite" in db_url or "sqlite" in test_db_url:
        return {}
        
    return {"postgresql_partition_by": strategy}

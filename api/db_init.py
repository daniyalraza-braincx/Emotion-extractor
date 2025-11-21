"""
Database initialization script.
Creates all tables if they don't exist.
"""

import sys
from database import Base, engine

def init_db():
    """Initialize database schema by creating all tables."""
    print("Initializing database schema...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Database schema initialized successfully!")
        print("Tables created:")
        for table in Base.metadata.tables:
            print(f"  - {table}")
    except Exception as e:
        print(f"Error initializing database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_db()


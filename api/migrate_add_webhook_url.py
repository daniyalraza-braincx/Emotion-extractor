"""
Migration script to add webhook_url column to organizations table.

This script:
1. Adds the webhook_url column to the organizations table if it doesn't exist
2. The column is nullable, allowing organizations to optionally configure a webhook URL

Run this script once after updating the database schema.
"""

import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal

load_dotenv()


def migrate_organizations():
    """Add webhook_url column to organizations table."""
    db = SessionLocal()
    
    try:
        print("Starting migration to add webhook_url column to organizations...")
        
        # Check if webhook_url column exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='organizations' AND column_name='webhook_url'
        """))
        column_exists = result.fetchone() is not None
        
        if not column_exists:
            print("Adding webhook_url column to organizations table...")
            db.execute(text("""
                ALTER TABLE organizations 
                ADD COLUMN webhook_url VARCHAR(500) NULL
            """))
            db.commit()
            print("✓ Added webhook_url column")
        else:
            print("✓ webhook_url column already exists")
        
        print("\n✓ Migration complete!")
        print("\nNote: Organizations can now configure a webhook URL via the API:")
        print("  PUT /organizations/{org_id} with body: {\"webhook_url\": \"https://your-n8n-webhook-url\"}")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Error during migration: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_organizations()



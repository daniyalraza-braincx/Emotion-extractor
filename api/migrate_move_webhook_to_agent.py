"""
Migration script to move webhook_url from organizations to agents table.

This script:
1. Adds the webhook_url column to the agents table if it doesn't exist
2. Removes the webhook_url column from the organizations table (if it exists)

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


def migrate_webhook_to_agent():
    """Move webhook_url from organizations to agents table."""
    db = SessionLocal()
    
    try:
        print("Starting migration to move webhook_url from organizations to agents...")
        
        # Step 1: Check if webhook_url column exists in agents table
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='agents' AND column_name='webhook_url'
        """))
        agent_column_exists = result.fetchone() is not None
        
        if not agent_column_exists:
            print("Adding webhook_url column to agents table...")
            db.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN webhook_url VARCHAR(500) NULL
            """))
            db.commit()
            print("✓ Added webhook_url column to agents table")
        else:
            print("✓ webhook_url column already exists in agents table")
        
        # Step 2: Check if webhook_url column exists in organizations table
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='organizations' AND column_name='webhook_url'
        """))
        org_column_exists = result.fetchone() is not None
        
        if org_column_exists:
            print("\nRemoving webhook_url column from organizations table...")
            print("Note: Any existing organization webhook URLs will be lost.")
            print("      You should configure agent-specific webhooks instead.")
            
            db.execute(text("""
                ALTER TABLE organizations 
                DROP COLUMN IF EXISTS webhook_url
            """))
            db.commit()
            print("✓ Removed webhook_url column from organizations table")
        else:
            print("✓ webhook_url column does not exist in organizations table (already removed)")
        
        print("\n✓ Migration complete!")
        print("\nNote: Webhooks should now be configured per agent via:")
        print("  PUT /organizations/{org_id}/agents/{agent_id} with body: {\"webhook_url\": \"https://...\"}")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Error during migration: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_webhook_to_agent()



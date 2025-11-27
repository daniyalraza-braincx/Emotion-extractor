"""
Migration script to add org_id to existing organizations.

This script:
1. Adds the org_id column to the organizations table if it doesn't exist
2. Generates unique org_id values for all existing organizations that don't have one
3. Creates an index on org_id for performance

Run this script once after updating the database schema.
"""

import os
import sys
import secrets
from sqlalchemy import text
from dotenv import load_dotenv

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, Organization

load_dotenv()


def generate_organization_id() -> str:
    """Generate a unique organization ID in the format: org_<random_hex_string>"""
    random_hex = secrets.token_hex(12)  # 12 bytes = 24 hex characters
    return f"org_{random_hex}"


def migrate_organizations():
    """Add org_id to all existing organizations."""
    db = SessionLocal()
    
    try:
        print("Starting migration to add org_id to organizations...")
        
        # Check if org_id column exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='organizations' AND column_name='org_id'
        """))
        column_exists = result.fetchone() is not None
        
        if not column_exists:
            print("Adding org_id column to organizations table...")
            db.execute(text("""
                ALTER TABLE organizations 
                ADD COLUMN org_id VARCHAR(255)
            """))
            db.commit()
            print("✓ Added org_id column")
        else:
            print("✓ org_id column already exists")
        
        # Create unique index on org_id
        try:
            db.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_org_id 
                ON organizations(org_id)
            """))
            db.commit()
            print("✓ Created unique index on org_id")
        except Exception as e:
            print(f"Note: Index creation (may already exist): {e}")
            db.rollback()
        
        # Get all organizations without org_id
        orgs_without_id = db.query(Organization).filter(Organization.org_id == None).all()
        
        if not orgs_without_id:
            print("✓ All organizations already have org_id")
            return
        
        print(f"\nFound {len(orgs_without_id)} organizations without org_id. Generating unique IDs...")
        
        # Generate unique org_id for each organization
        for org in orgs_without_id:
            org_id = generate_organization_id()
            
            # Ensure uniqueness
            while db.query(Organization).filter(Organization.org_id == org_id).first():
                org_id = generate_organization_id()
            
            org.org_id = org_id
            print(f"  - Organization '{org.name}' (ID: {org.id}) -> org_id: {org_id}")
        
        db.commit()
        print(f"\n✓ Successfully added org_id to {len(orgs_without_id)} organizations")
        
        # Display all organizations with their org_id
        print("\nAll organizations:")
        all_orgs = db.query(Organization).all()
        for org in all_orgs:
            print(f"  - {org.name} (ID: {org.id}, org_id: {org.org_id})")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Error during migration: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_organizations()


"""
Migration script to convert existing database to multi-tenancy.

This script:
1. Creates new tables (users, organizations, user_organizations)
2. Creates a default admin user
3. Creates a default organization
4. Assigns all existing calls to the default organization
5. Creates user_organization entry for admin
"""

import sys
import os
from getpass import getpass
from dotenv import load_dotenv

load_dotenv()

from database import (
    Base, engine, SessionLocal, User, Organization, UserOrganization, Call
)

# Import password hashing function
# Use bcrypt directly to avoid passlib compatibility issues
try:
    import bcrypt
    
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt directly."""
        if not password:
            raise ValueError("Password cannot be empty")
        
        # Ensure password is bytes and not too long (bcrypt limit is 72 bytes)
        if isinstance(password, str):
            password_bytes = password.encode('utf-8')
        else:
            password_bytes = password
        
        if len(password_bytes) > 72:
            print(f"Warning: Password length ({len(password_bytes)} bytes) exceeds bcrypt limit (72 bytes), truncating")
            password_bytes = password_bytes[:72]
        
        # Generate salt and hash
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    # Test that bcrypt works
    test_hash = hash_password("test")
    print("Using bcrypt for password hashing (direct)")
    
except ImportError:
    # Fallback to passlib if bcrypt not available
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto", pbkdf2_sha256__rounds=29000)
        
        def hash_password(password: str) -> str:
            """Hash a password using pbkdf2_sha256."""
            if not password:
                raise ValueError("Password cannot be empty")
            return pwd_context.hash(password)
        
        print("Using pbkdf2_sha256 for password hashing (bcrypt not available)")
    except ImportError:
        raise ImportError("bcrypt or passlib is required. Install with: pip install bcrypt or pip install passlib")

def create_tables():
    """Create all new tables."""
    print("Creating new tables...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✓ Tables created successfully!")
        return True
    except Exception as e:
        print(f"✗ Error creating tables: {e}")
        return False

def add_columns_to_calls_table(db):
    """Add organization_id and created_by_user_id columns to existing calls table."""
    print("\nAdding new columns to calls table...")
    try:
        from sqlalchemy import text
        
        # Check if organization_id column already exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='calls' AND column_name='organization_id'
        """))
        org_col_exists = result.fetchone() is not None
        
        # Check if created_by_user_id column already exists
        result = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='calls' AND column_name='created_by_user_id'
        """))
        user_col_exists = result.fetchone() is not None
        
        if org_col_exists and user_col_exists:
            print("✓ Columns already exist in calls table")
            return True
        
        # Add organization_id column if it doesn't exist (nullable first, will be set later)
        if not org_col_exists:
            db.execute(text("""
                ALTER TABLE calls 
                ADD COLUMN organization_id INTEGER 
                REFERENCES organizations(id) ON DELETE CASCADE
            """))
            print("✓ Added organization_id column to calls table")
        
        # Add created_by_user_id column if it doesn't exist
        if not user_col_exists:
            db.execute(text("""
                ALTER TABLE calls 
                ADD COLUMN created_by_user_id INTEGER 
                REFERENCES users(id) ON DELETE SET NULL
            """))
            print("✓ Added created_by_user_id column to calls table")
        
        # Create index on organization_id
        try:
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_calls_organization_id ON calls(organization_id)"))
            print("✓ Created index on organization_id")
        except Exception:
            pass  # Index might already exist
        
        db.commit()
        print("✓ Successfully added columns to calls table")
        return True
    except Exception as e:
        db.rollback()
        print(f"✗ Error adding columns to calls table: {e}")
        import traceback
        traceback.print_exc()
        return False

def make_organization_id_required(db, default_org_id):
    """Make organization_id NOT NULL after all calls have been assigned."""
    print("\nMaking organization_id required...")
    try:
        from sqlalchemy import text
        
        # First, ensure all calls have an organization_id
        result = db.execute(text("""
            SELECT COUNT(*) 
            FROM calls 
            WHERE organization_id IS NULL
        """))
        null_count = result.scalar()
        
        if null_count > 0:
            print(f"⚠ Warning: {null_count} calls still have NULL organization_id, skipping NOT NULL constraint")
            return True
        
        # Check if column is already NOT NULL
        result = db.execute(text("""
            SELECT is_nullable 
            FROM information_schema.columns 
            WHERE table_name='calls' AND column_name='organization_id'
        """))
        row = result.fetchone()
        if row and row[0] == 'NO':
            print("✓ organization_id is already NOT NULL")
            return True
        
        # Make it NOT NULL
        db.execute(text("""
            ALTER TABLE calls 
            ALTER COLUMN organization_id SET NOT NULL
        """))
        db.commit()
        print("✓ Made organization_id required (NOT NULL)")
        return True
    except Exception as e:
        db.rollback()
        print(f"⚠ Warning: Could not make organization_id required: {e}")
        # This is not critical, so we continue
        return True

def create_admin_user(db, username, password, email=None):
    """Create the initial admin user."""
    print(f"\nCreating admin user '{username}'...")
    
    # Check if admin user already exists
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        print(f"✓ Admin user '{username}' already exists (ID: {existing.id})")
        return existing
    
    try:
        password_hash = hash_password(password)
        admin = User(
            username=username,
            password_hash=password_hash,
            role="admin",
            email=email,
            is_active=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print(f"✓ Admin user created successfully (ID: {admin.id})")
        return admin
    except Exception as e:
        db.rollback()
        print(f"✗ Error creating admin user: {e}")
        return None

def create_default_organization(db, admin_user):
    """Create a default organization owned by admin."""
    print("\nCreating default organization...")
    
    # Check if default organization already exists
    existing = db.query(Organization).filter(Organization.name == "Default Organization").first()
    if existing:
        print(f"✓ Default organization already exists (ID: {existing.id})")
        return existing
    
    try:
        default_org = Organization(
            name="Default Organization",
            owner_id=admin_user.id
        )
        db.add(default_org)
        db.commit()
        db.refresh(default_org)
        print(f"✓ Default organization created successfully (ID: {default_org.id})")
        return default_org
    except Exception as e:
        db.rollback()
        print(f"✗ Error creating default organization: {e}")
        return None

def assign_admin_to_organization(db, admin_user, organization):
    """Assign admin user to the default organization."""
    print("\nAssigning admin to default organization...")
    
    # Check if relationship already exists
    existing = db.query(UserOrganization).filter(
        UserOrganization.user_id == admin_user.id,
        UserOrganization.organization_id == organization.id
    ).first()
    if existing:
        print("✓ Admin already assigned to default organization")
        return True
    
    try:
        user_org = UserOrganization(
            user_id=admin_user.id,
            organization_id=organization.id,
            role="owner",
            is_active=True
        )
        db.add(user_org)
        db.commit()
        print("✓ Admin assigned to default organization")
        return True
    except Exception as e:
        db.rollback()
        print(f"✗ Error assigning admin to organization: {e}")
        return False

def assign_calls_to_organization(db, organization, admin_user):
    """Assign all existing calls to the default organization."""
    print("\nAssigning existing calls to default organization...")
    
    try:
        from sqlalchemy import text
        
        # Use raw SQL to update calls that don't have organization_id
        # This avoids the SQLAlchemy model issue if columns were just added
        result = db.execute(text("""
            UPDATE calls 
            SET organization_id = :org_id,
                created_by_user_id = COALESCE(created_by_user_id, :user_id)
            WHERE organization_id IS NULL
        """), {"org_id": organization.id, "user_id": admin_user.id})
        
        updated_count = result.rowcount
        db.commit()
        
        if updated_count > 0:
            print(f"✓ Assigned {updated_count} calls to default organization")
        else:
            print("✓ No calls need to be assigned (all calls already have organizations)")
        return True
    except Exception as e:
        db.rollback()
        print(f"✗ Error assigning calls: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main migration function."""
    print("=" * 60)
    print("Multi-Tenancy Migration Script")
    print("=" * 60)
    
    db = SessionLocal()
    
    try:
        # Step 1: Create tables
        if not create_tables():
            print("\n✗ Migration failed: Could not create tables")
            sys.exit(1)
        
        # Step 1.5: Add columns to existing calls table if it exists
        if not add_columns_to_calls_table(db):
            print("\n✗ Migration failed: Could not add columns to calls table")
            sys.exit(1)
        
        # Step 2: Get admin credentials
        print("\n" + "=" * 60)
        print("Admin User Setup")
        print("=" * 60)
        
        # Try to get from environment first
        admin_username = os.getenv("INITIAL_ADMIN_USERNAME")
        admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
        admin_email = os.getenv("INITIAL_ADMIN_EMAIL")
        
        if not admin_username:
            admin_username = input("Enter admin username (default: admin): ").strip() or "admin"
        
        if not admin_password:
            admin_password = getpass("Enter admin password: ").strip()
            if not admin_password:
                print("✗ Password is required")
                sys.exit(1)
        
        if not admin_email:
            admin_email_input = input("Enter admin email (optional, press Enter to skip): ").strip()
            admin_email = admin_email_input if admin_email_input else None
        
        # Step 3: Create admin user
        admin_user = create_admin_user(db, admin_username, admin_password, admin_email)
        if not admin_user:
            print("\n✗ Migration failed: Could not create admin user")
            sys.exit(1)
        
        # Step 4: Create default organization
        default_org = create_default_organization(db, admin_user)
        if not default_org:
            print("\n✗ Migration failed: Could not create default organization")
            sys.exit(1)
        
        # Step 5: Assign admin to organization
        if not assign_admin_to_organization(db, admin_user, default_org):
            print("\n✗ Migration failed: Could not assign admin to organization")
            sys.exit(1)
        
        # Step 6: Assign existing calls to default organization
        if not assign_calls_to_organization(db, default_org, admin_user):
            print("\n✗ Migration failed: Could not assign calls to organization")
            sys.exit(1)
        
        # Step 7: Make organization_id required (if all calls are assigned)
        make_organization_id_required(db, default_org.id)
        
        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)
        print(f"\nAdmin credentials:")
        print(f"  Username: {admin_username}")
        print(f"  Password: [hidden]")
        print(f"\nDefault organization ID: {default_org.id}")
        print(f"\nYou can now log in with the admin credentials.")
        
    except KeyboardInterrupt:
        print("\n\n✗ Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()


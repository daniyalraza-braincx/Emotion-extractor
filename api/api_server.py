
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Depends, status, Body, BackgroundTasks, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from passlib.context import CryptContext
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import and_

load_dotenv()

from extractor import (
    analyze_audio_files,
    derive_short_call_title,
    download_retell_recording,
    extract_retell_transcript_segments,
    generate_call_purpose_from_summary,
    get_openai_client,
    get_retell_call_details,
)
from database import (
    get_db, Call, EmotionSegment, EmotionPrediction, 
    TranscriptSegment, AnalysisSummary, User, Organization, UserOrganization, Agent,
    SessionLocal
)


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Authentication configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Password hashing
# Use bcrypt directly to avoid passlib compatibility issues with bcrypt 5.0.0+
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
            logger.warning(f"Password length ({len(password_bytes)} bytes) exceeds bcrypt limit (72 bytes), truncating")
            password_bytes = password_bytes[:72]
        
        # Generate salt and hash
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash using bcrypt."""
        if not plain_password or not hashed_password:
            return False
        
        # Ensure password is bytes and not too long
        if isinstance(plain_password, str):
            password_bytes = plain_password.encode('utf-8')
        else:
            password_bytes = plain_password
        
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        
        # Ensure hash is bytes
        if isinstance(hashed_password, str):
            hash_bytes = hashed_password.encode('utf-8')
        else:
            hash_bytes = hashed_password
        
        try:
            return bcrypt.checkpw(password_bytes, hash_bytes)
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False
    
    # Test that bcrypt works
    test_hash = hash_password("test")
    verify_password("test", test_hash)
    logger.info("Using bcrypt for password hashing (direct)")
    
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
        
        def verify_password(plain_password: str, hashed_password: str) -> bool:
            """Verify a password against its hash."""
            if not plain_password or not hashed_password:
                return False
            return pwd_context.verify(plain_password, hashed_password)
        
        logger.warning("Using pbkdf2_sha256 for password hashing (bcrypt not available)")
    except ImportError:
        raise ImportError("bcrypt is required. Install with: pip install bcrypt")

security = HTTPBearer()

RETELL_RESULTS_DIR = os.getenv("RETELL_RESULTS_DIR", "retell_results")

app = FastAPI(title="Hume Emotion Analysis API")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def generate_organization_id() -> str:
    """Generate a unique organization ID in the format: org_<random_hex_string>"""
    # Generate 24 random hex characters (similar to Retell agent IDs)
    random_hex = secrets.token_hex(12)  # 12 bytes = 24 hex characters
    return f"org_{random_hex}"


def create_access_token(user_id: int, username: str, role: str, organization_id: Optional[int] = None, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token with user information."""
    to_encode = {
        "sub": username,
        "user_id": user_id,
        "role": role,
    }
    if organization_id is not None:
        to_encode["organization_id"] = organization_id
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Verify JWT token and return payload"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.post("/auth/login")
async def login(credentials: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    """Authenticate user and return JWT token"""
    username = credentials.get("username")
    password = credentials.get("password")
    organization_id = credentials.get("organization_id")  # Optional for users
    
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required"
        )
    
    # Query user from database
    user = db.query(User).filter(User.username == username).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Verify password
    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    
    # Handle organization selection
    selected_org_id = None
    if user.role == "admin":
        # Admins don't need organization
        selected_org_id = None
    else:
        # For users, get their organizations
        user_orgs = db.query(UserOrganization).filter(
            UserOrganization.user_id == user.id,
            UserOrganization.is_active == True
        ).all()
        
        # Allow users to log in even if they have no organizations
        # They will be prompted to create one after login
        if not user_orgs:
            selected_org_id = None
        elif organization_id:
            # If organization_id provided, verify user has access
            org_access = db.query(UserOrganization).filter(
                UserOrganization.user_id == user.id,
                UserOrganization.organization_id == organization_id,
                UserOrganization.is_active == True
            ).first()
            if not org_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not have access to this organization"
                )
            selected_org_id = organization_id
        else:
            # Use first organization as default
            selected_org_id = user_orgs[0].organization_id
    
    # Create token
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        organization_id=selected_org_id
    )
    
    return JSONResponse(content={
        "success": True,
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "email": user.email,
        },
        "organization_id": selected_org_id
    })


@app.get("/auth/verify")
async def verify_auth(token_data: Dict[str, Any] = Depends(verify_token)):
    """Verify if the current token is valid"""
    return JSONResponse(content={
        "success": True,
        "authenticated": True,
        "username": token_data.get("sub"),
        "user_id": token_data.get("user_id"),
        "role": token_data.get("role"),
        "organization_id": token_data.get("organization_id")
    })


@app.post("/auth/logout")
async def logout():
    """Logout endpoint (client-side token removal)"""
    return JSONResponse(content={"success": True, "message": "Logged out successfully"})


# Helper functions for organization and authorization
def get_current_organization_id(token_data: Dict[str, Any]) -> Optional[int]:
    """Extract organization_id from JWT token data."""
    return token_data.get("organization_id")


def verify_user_has_org_access(db: Session, user_id: int, org_id: int) -> bool:
    """Check if user has access to organization."""
    user_org = db.query(UserOrganization).filter(
        UserOrganization.user_id == user_id,
        UserOrganization.organization_id == org_id,
        UserOrganization.is_active == True
    ).first()
    return user_org is not None


def get_user_organizations(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """Get all organizations user belongs to."""
    user_orgs = db.query(UserOrganization).filter(
        UserOrganization.user_id == user_id,
        UserOrganization.is_active == True
    ).all()
    
    result = []
    for uo in user_orgs:
        org = db.query(Organization).filter(Organization.id == uo.organization_id).first()
        if org:
            org_dict = org.to_dict()
            org_dict["user_role"] = uo.role
            result.append(org_dict)
    return result


def require_admin(token_data: Dict[str, Any] = Depends(verify_token)) -> Dict[str, Any]:
    """Dependency to require admin role."""
    role = token_data.get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return token_data


@app.get("/auth/me")
async def get_current_user(
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Get current user info and organizations."""
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    role = token_data.get("role")
    organizations = get_user_organizations(db, user_id)
    current_org = None
    org_id = token_data.get("organization_id")
    
    if org_id:
        # First try to find it in the user's organizations
        current_org = next((org for org in organizations if org["id"] == org_id), None)
        
        # For admins, if not found in user's organizations, fetch directly from database
        # This allows admins to switch to any organization, even ones they don't own
        if not current_org and role == "admin":
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org:
                current_org = org.to_dict()
    
    return JSONResponse(content={
        "success": True,
        "user": user.to_dict(),
        "organizations": organizations,
        "current_organization": current_org,
        "organization_id": org_id
    })


@app.post("/auth/switch-organization")
async def switch_organization(
    request: Dict[str, Any] = Body(...),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Switch current organization."""
    user_id = token_data.get("user_id")
    role = token_data.get("role")
    organization_id = request.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization_id is required"
        )
    
    # Verify organization exists
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    # For admins, allow switching to any organization
    # For regular users, verify they have access to the organization
    if role != "admin":
        if not verify_user_has_org_access(db, user_id, organization_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to this organization"
            )
    
    # Get user to create new token
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Create new token with updated organization
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        organization_id=organization_id
    )
    
    return JSONResponse(content={
        "success": True,
        "access_token": access_token,
        "token_type": "bearer",
        "organization": org.to_dict()
    })


# Admin endpoints
@app.post("/admin/users")
async def create_user(
    user_data: Dict[str, Any] = Body(...),
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new user (admin only)."""
    username = user_data.get("username")
    password = user_data.get("password")
    role = user_data.get("role", "user")
    email = user_data.get("email")
    
    # Normalize empty email to None (NULL) to avoid unique constraint violations
    if email is not None:
        if isinstance(email, str):
            email = email.strip()
            if not email:
                email = None
        elif email == '':
            email = None
    
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required"
        )
    
    if role not in ["admin", "user"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be 'admin' or 'user'"
        )
    
    # Check if username already exists
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Check if email already exists (if provided and not None)
    if email:
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists"
            )
    
    # Create user
    password_hash = hash_password(password)
    creator_id = token_data.get("user_id")
    
    new_user = User(
        username=username,
        password_hash=password_hash,
        role=role,
        email=email,  # Will be None if empty string was provided
        is_active=True,
        created_by=creator_id
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return JSONResponse(content={
        "success": True,
        "user": new_user.to_dict()
    })


@app.get("/admin/users")
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all users (admin only)."""
    query = db.query(User)
    
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    users = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    
    return JSONResponse(content={
        "success": True,
        "users": [user.to_dict() for user in users],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    })


@app.get("/admin/users/{user_id}/organizations")
async def get_user_organizations_admin(
    user_id: int,
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get organizations for a specific user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get all organizations owned by this user
    owned_orgs = db.query(Organization).filter(Organization.owner_id == user_id).all()
    
    # Get all UserOrganization entries for this user
    # For admin view, show ALL organizations including inactive UserOrganization entries
    user_orgs = db.query(UserOrganization).filter(
        UserOrganization.user_id == user_id
    ).all()
    
    # Build a dictionary to track organizations and their roles
    org_dict_map = {}
    
    # Add owned organizations first (always with "owner" role)
    for org in owned_orgs:
        org_dict = org.to_dict()
        org_dict["user_role"] = "owner"
        org_dict_map[org.id] = org_dict
    
    # Add organizations from UserOrganization table
    # Include all UserOrganization entries (both active and inactive) for admin view
    for uo in user_orgs:
        org = db.query(Organization).filter(Organization.id == uo.organization_id).first()
        if org:
            # If already in map as owner, keep owner role (don't override)
            if org.id not in org_dict_map:
                org_dict = org.to_dict()
                org_dict["user_role"] = uo.role
                org_dict_map[org.id] = org_dict
            # If already owner, keep it as owner (don't override)
            elif org_dict_map[org.id]["user_role"] != "owner":
                # Update role from UserOrganization if not already owner
                org_dict_map[org.id]["user_role"] = uo.role
    
    # Convert to list - sort by name for consistent ordering
    organizations = list(org_dict_map.values())
    organizations.sort(key=lambda x: (x.get('name') or '').lower())
    
    return JSONResponse(content={
        "success": True,
        "organizations": organizations
    })


@app.put("/admin/users/{user_id}")
async def update_user(
    user_id: int,
    user_data: Dict[str, Any] = Body(...),
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    if "username" in user_data:
        # Check if username already exists (excluding current user)
        existing = db.query(User).filter(
            User.username == user_data["username"],
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )
        user.username = user_data["username"]
    
    if "email" in user_data:
        # Normalize empty email to None (NULL) to avoid unique constraint violations
        email_value = user_data["email"]
        if email_value is not None:
            if isinstance(email_value, str):
                email_value = email_value.strip()
                if not email_value:
                    email_value = None
            elif email_value == '':
                email_value = None
        
        # Check if email already exists (excluding current user, only if email is not None)
        if email_value:
            existing = db.query(User).filter(
                User.email == email_value,
                User.id != user_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists"
                )
        user.email = email_value
    
    if "role" in user_data:
        if user_data["role"] not in ["admin", "user"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role must be 'admin' or 'user'"
            )
        user.role = user_data["role"]
    
    if "is_active" in user_data:
        user.is_active = user_data["is_active"]
    
    if "password" in user_data and user_data["password"]:
        user.password_hash = hash_password(user_data["password"])
    
    db.commit()
    db.refresh(user)
    
    return JSONResponse(content={
        "success": True,
        "user": user.to_dict()
    })


@app.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deactivate user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Soft delete
    user.is_active = False
    db.commit()
    
    return JSONResponse(content={
        "success": True,
        "message": "User deactivated"
    })


@app.get("/admin/organizations/all")
async def list_all_organizations_all(
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get all organizations without pagination (admin only, for organization switcher)."""
    orgs = db.query(Organization).order_by(Organization.name.asc()).all()
    
    # Return simple list for switcher
    organizations = [org.to_dict() for org in orgs]
    
    return JSONResponse(content={
        "success": True,
        "organizations": organizations
    })


@app.get("/admin/organizations")
async def list_all_organizations(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100),
    token_data: Dict[str, Any] = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all organizations (admin only)."""
    query = db.query(Organization)
    
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    orgs = query.order_by(Organization.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    
    # Enrich with member and call counts
    enriched_orgs = []
    for org in orgs:
        org_dict = org.to_dict()
        
        # Get member count
        member_count = db.query(UserOrganization).filter(
            UserOrganization.organization_id == org.id,
            UserOrganization.is_active == True
        ).count()
        org_dict["member_count"] = member_count
        
        # Get call count
        call_count = db.query(Call).filter(Call.organization_id == org.id).count()
        org_dict["call_count"] = call_count
        
        # Get owner info
        owner = db.query(User).filter(User.id == org.owner_id).first()
        if owner:
            org_dict["owner"] = owner.to_dict()
        
        enriched_orgs.append(org_dict)
    
    return JSONResponse(content={
        "success": True,
        "organizations": enriched_orgs,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    })


# Organization endpoints
@app.post("/organizations")
async def create_organization(
    org_data: Dict[str, Any] = Body(...),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Create a new organization."""
    name = org_data.get("name")
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name is required"
        )
    
    user_id = token_data.get("user_id")
    
    # Generate unique organization ID
    org_id = generate_organization_id()
    
    # Ensure uniqueness (very unlikely but check anyway)
    while db.query(Organization).filter(Organization.org_id == org_id).first():
        org_id = generate_organization_id()
    
    # Create organization
    new_org = Organization(
        name=name,
        owner_id=user_id,
        org_id=org_id
    )
    
    db.add(new_org)
    db.flush()  # Get the ID
    
    # Add user as owner
    user_org = UserOrganization(
        user_id=user_id,
        organization_id=new_org.id,
        role="owner",
        is_active=True
    )
    
    db.add(user_org)
    db.commit()
    db.refresh(new_org)
    
    # Get user to create new token with organization
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Create new token with the new organization
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        organization_id=new_org.id
    )
    
    return JSONResponse(content={
        "success": True,
        "organization": new_org.to_dict(),
        "access_token": access_token  # Return new token with organization
    })


@app.get("/organizations")
async def get_user_organizations_list(
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """List user's organizations."""
    user_id = token_data.get("user_id")
    organizations = get_user_organizations(db, user_id)
    return JSONResponse(content={
        "success": True,
        "organizations": organizations
    })


@app.put("/organizations/{org_id}")
async def update_organization(
    org_id: int,
    org_data: Dict[str, Any] = Body(...),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Update organization (owner only)."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    user_id = token_data.get("user_id")
    role = token_data.get("role")
    
    # Check if user is owner or admin
    if role != "admin":
        user_org = db.query(UserOrganization).filter(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == org_id,
            UserOrganization.role == "owner",
            UserOrganization.is_active == True
        ).first()
        if not user_org:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners can update organizations"
            )
    
    # Update name
    if "name" in org_data:
        org.name = org_data["name"]
        org.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(org)
    
    return JSONResponse(content={
        "success": True,
        "organization": org.to_dict()
    })


@app.delete("/organizations/{org_id}")
async def delete_organization(
    org_id: int,
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Delete organization (owner only)."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    user_id = token_data.get("user_id")
    role = token_data.get("role")
    
    # Check if user is owner or admin
    if role != "admin":
        user_org = db.query(UserOrganization).filter(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == org_id,
            UserOrganization.role == "owner",
            UserOrganization.is_active == True
        ).first()
        if not user_org:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners can delete organizations"
            )
    
    # Delete organization (cascade will handle related data)
    db.delete(org)
    db.commit()
    
    return JSONResponse(content={
        "success": True,
        "message": "Organization deleted"
    })


@app.get("/organizations/{org_id}/agents")
async def get_organization_agents(
    org_id: int,
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Get list of saved agents for the organization."""
    # Verify organization exists
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    user_id = token_data.get("user_id")
    role = token_data.get("role")
    
    # Verify user has access to organization (unless admin)
    if role != "admin":
        if not verify_user_has_org_access(db, user_id, org_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to this organization"
            )
    
    # Get saved agents for this organization
    agents = db.query(Agent).filter(Agent.organization_id == org_id).order_by(Agent.created_at.desc()).all()
    
    # Get call counts for each agent
    agents_with_counts = []
    for agent in agents:
        call_count = db.query(Call).filter(
            Call.organization_id == org_id,
            Call.agent_id == agent.agent_id
        ).count()
        
        agents_with_counts.append({
            "id": agent.id,
            "agent_id": agent.agent_id,
            "agent_name": agent.agent_name,
            "call_count": call_count,
            "created_at": agent.created_at.replace(microsecond=0).isoformat() + "Z" if agent.created_at else None,
        })
    
    return JSONResponse(content={
        "success": True,
        "organization_id": org_id,
        "agents": agents_with_counts
    })


@app.post("/organizations/{org_id}/agents")
async def add_organization_agent(
    org_id: int,
    agent_data: Dict[str, Any] = Body(...),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Add a new agent to the organization."""
    # Verify organization exists
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    user_id = token_data.get("user_id")
    role = token_data.get("role")
    
    # Verify user has access to organization (unless admin)
    if role != "admin":
        if not verify_user_has_org_access(db, user_id, org_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to this organization"
            )
    
    agent_id = agent_data.get("agent_id")
    agent_name = agent_data.get("agent_name")
    
    if not agent_id or not agent_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_id is required"
        )
    
    agent_id = agent_id.strip()
    
    # Check if agent already exists for this organization
    existing_agent = db.query(Agent).filter(
        Agent.organization_id == org_id,
        Agent.agent_id == agent_id
    ).first()
    
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent ID already exists for this organization"
        )
    
    # Create new agent
    new_agent = Agent(
        organization_id=org_id,
        agent_id=agent_id,
        agent_name=agent_name.strip() if agent_name else None,
        created_by_user_id=user_id
    )
    
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    
    return JSONResponse(content={
        "success": True,
        "agent": new_agent.to_dict()
    })


@app.delete("/organizations/{org_id}/agents/{agent_id}")
async def delete_organization_agent(
    org_id: int,
    agent_id: int,
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Delete an agent from the organization."""
    # Verify organization exists
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    user_id = token_data.get("user_id")
    role = token_data.get("role")
    
    # Verify user has access to organization (unless admin)
    if role != "admin":
        if not verify_user_has_org_access(db, user_id, org_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have access to this organization"
            )
    
    # Find the agent
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.organization_id == org_id
    ).first()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    db.delete(agent)
    db.commit()
    
    return JSONResponse(content={
        "success": True,
        "message": "Agent deleted"
    })


@app.post("/analyze")
async def analyze_audio(
    file: UploadFile = File(...), 
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Analyze audio file for emotion detection using Hume API.

    Returns:
        JSON with a top emotion per time segment for prosody and burst models.
    """
    # For users, verify they have an organization
    role = token_data.get("role")
    org_id = get_current_organization_id(token_data)
    user_id = token_data.get("user_id")
    
    if role == "user" and org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required for audio analysis"
        )
    
    try:
        # Read uploaded file
        file_content = await file.read()
        filename = file.filename or "uploaded_audio"

        file_contents = [(filename, file_content)]

        results = analyze_audio_files(file_contents, include_summary=True)

        if not results:
            raise HTTPException(
                status_code=404,
                detail="No emotion predictions found. The audio may not contain detectable speech.",
            )

        analysis_payload = results[0]
        analysis_payload.setdefault("metadata", {})["analysis_type"] = "custom_upload"
        if org_id:
            analysis_payload.setdefault("metadata", {})["organization_id"] = org_id

        return JSONResponse(
            content={
                "success": True,
                "filename": filename,
                "results": analysis_payload,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        # Include more detailed error info in development
        if hasattr(e, '__traceback__'):
            tb_str = traceback.format_exception(type(e), e, e.__traceback__)
            error_detail += f"\n\nTraceback:\n{''.join(tb_str)}"
        raise HTTPException(status_code=500, detail=f"Error processing audio: {error_detail}")

def _current_timestamp_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _get_all_calls_dict(db: Session) -> Dict[str, Any]:
    """Get all calls from database as dictionary format."""
    calls = db.query(Call).all()
    return {call.call_id: call.to_dict() for call in calls}


def _calculate_duration_ms(call_data: Dict[str, Any]) -> Optional[int]:
    duration_ms = call_data.get("duration_ms")
    if isinstance(duration_ms, (int, float)):
        return int(duration_ms)

    start_ts = call_data.get("start_timestamp")
    end_ts = call_data.get("end_timestamp")
    if isinstance(start_ts, (int, float)) and isinstance(end_ts, (int, float)):
        calculated = int(end_ts - start_ts)
        if calculated >= 0:
            return calculated
    return None


def _is_zero_duration_call(call_data: Dict[str, Any]) -> bool:
    """
    Check if a call has zero or negative duration.
    Returns False if duration is None (unknown) - only removes calls with explicitly zero/negative duration.
    """
    duration_ms = _calculate_duration_ms(call_data)
    # Only consider it zero-duration if we have an explicit value that is <= 0
    # Don't remove calls with None duration (unknown duration) as they might be valid
    if duration_ms is None:
        return False
    return duration_ms <= 0


# _save_retell_calls removed - using database directly


def _normalize_retell_payload(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Normalize Retell webhook payload to handle multiple formats:
    1. Direct Retell format with call wrapper: { "event": "call_analyzed", "call": {...} }
    2. Direct Retell format without wrapper: { "event": "call_analyzed", "call_id": "...", ... }
    3. n8n format: { "body": { "event": "call_analyzed", ...call data... } }
    
    Returns: (event, call_data) tuple
    """
    event = None
    call_data = None
    
    # Check for n8n format (body wrapper)
    if "body" in payload and isinstance(payload["body"], dict):
        body = payload["body"]
        event = body.get("event")
        # In n8n format, call data is directly in body - make a copy to avoid mutating original
        call_data = dict(body)
    else:
        # Direct Retell format
        event = payload.get("event")
        call_data_raw = payload.get("call")
        
        if isinstance(call_data_raw, dict):
            # Format 1: { "event": "call_analyzed", "call": {...} }
            call_data = dict(call_data_raw)
        elif "call_id" in payload or "recording_multi_channel_url" in payload:
            # Format 2: { "event": "call_analyzed", "call_id": "...", ... } - call data at top level
            call_data = dict(payload)
            # Remove event from call_data since it's not part of call metadata
            call_data.pop("event", None)
        else:
            # Fallback: use call_data_raw as-is (might be None)
            call_data = call_data_raw
    
    # Normalize call_data structure
    if isinstance(call_data, dict):
        # If in_voicemail is at top level, ensure it's in call_analysis
        if "in_voicemail" in call_data:
            if "call_analysis" not in call_data:
                call_data["call_analysis"] = {}
            if "in_voicemail" not in call_data["call_analysis"]:
                call_data["call_analysis"]["in_voicemail"] = call_data["in_voicemail"]
        
        # If call_summary is at top level, ensure it's in call_analysis (if call_analysis exists)
        if "call_summary" in call_data:
            if "call_analysis" not in call_data:
                call_data["call_analysis"] = {}
            # Only set if not already present in call_analysis
            if "call_summary" not in call_data["call_analysis"]:
                call_data["call_analysis"]["call_summary"] = call_data["call_summary"]
    
    return event, call_data


def _evaluate_call_constraints(call_data: Dict[str, Any]) -> Dict[str, Any]:
    """Determine if a call should be excluded from analysis."""
    call_analysis = call_data.get("call_analysis") or {}
    transcript_text = call_data.get("transcript") or ""
    disconnection_reason = (
        call_data.get("disconnection_reason")
        or call_data.get("end_reason")
        or ""
    )

    duration_ms = _calculate_duration_ms(call_data)

    too_short = duration_ms is not None and duration_ms < 15_000

    call_summary = ""
    if isinstance(call_analysis, dict):
        call_summary = call_analysis.get("call_summary") or ""

    transcript_lower = transcript_text.lower() if isinstance(transcript_text, str) else ""
    summary_lower = call_summary.lower() if isinstance(call_summary, str) else ""
    disconnection_lower = disconnection_reason.lower()

    transcript_mentions_voicemail = "voicemail" in transcript_lower
    summary_mentions_voicemail = "voicemail" in summary_lower
    disconnection_mentions_voicemail = "voicemail" in disconnection_lower

    transcript_mentions_leave_message = "leave a message" in transcript_lower or "leave me a message" in transcript_lower
    summary_mentions_leave_message = "leave a message" in summary_lower or "leave me a message" in summary_lower

    # Check both call_analysis.in_voicemail and top-level in_voicemail
    in_voicemail_flag = bool(
        call_analysis.get("in_voicemail") or call_data.get("in_voicemail")
    )
    # Check both call_analysis.in_voicemail and top-level in_voicemail
    in_voicemail_flag = bool(
        call_analysis.get("in_voicemail") or call_data.get("in_voicemail")
    )

    voicemail_detected = any([
        in_voicemail_flag,
        summary_mentions_voicemail,
        transcript_mentions_voicemail,
        disconnection_mentions_voicemail,
        transcript_mentions_leave_message,
        summary_mentions_leave_message,
    ])

    analysis_allowed = True
    block_reason = None
    if voicemail_detected:
        analysis_allowed = False
        block_reason = "Call reached voicemail; cannot analyze emotions."
    elif too_short:
        analysis_allowed = False
        block_reason = "Call too short, insufficient audio for analysis."

    constraints_detail = {
        "voicemail_detected": voicemail_detected,
        "voicemail_flags": {
            "in_voicemail": in_voicemail_flag,
            "summary_mentions_voicemail": summary_mentions_voicemail,
            "transcript_mentions_voicemail": transcript_mentions_voicemail,
            "disconnection_reason": disconnection_reason or None,
            "summary_mentions_leave_message": summary_mentions_leave_message,
            "transcript_mentions_leave_message": transcript_mentions_leave_message,
        },
        "too_short": too_short,
        "duration_ms": duration_ms,
    }

    return {
        "analysis_allowed": analysis_allowed,
        "analysis_block_reason": block_reason,
        "constraints": constraints_detail,
    }


def _strip_words_from_transcript(transcript_object: Any) -> Any:
    """Remove words array from transcript segments to reduce storage size.
    
    Keeps only essential fields: speaker, start, end, content/text, confidence.
    """
    if not isinstance(transcript_object, list):
        return transcript_object
    
    cleaned_transcript = []
    for segment in transcript_object:
        if not isinstance(segment, dict):
            cleaned_transcript.append(segment)
            continue
        
        # Create a copy without words array
        cleaned_segment = {k: v for k, v in segment.items() if k != "words"}
        cleaned_transcript.append(cleaned_segment)
    
    return cleaned_transcript


def _upsert_retell_call_metadata(db: Session, call_data: Dict[str, Any], status: Optional[str] = None, organization_id: Optional[int] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    call_id = call_data.get("call_id")
    if not call_id:
        raise ValueError("call_data must include call_id")

    # Get existing call or create new
    existing_call = db.query(Call).filter(Call.call_id == call_id).first()
    
    duration_ms = call_data.get("duration_ms")
    if duration_ms is None:
        duration_ms = _calculate_duration_ms(call_data)
    
    if duration_ms is not None and duration_ms <= 0:
        logger.info("Skipping Retell call %s due to zero duration", call_id)
        if existing_call:
            db.delete(existing_call)
            db.commit()
        return {
            "call_id": call_id,
            "duration_ms": 0,
            "analysis_allowed": False,
            "analysis_block_reason": "Call contains no audio (duration 0s).",
            "analysis_status": "blocked",
            "analysis_available": False,
            "error_message": None,
        }

    call_summary_text: Optional[str] = None
    call_analysis = call_data.get("call_analysis")
    if isinstance(call_analysis, dict):
        summary_candidate = call_analysis.get("call_summary") or call_analysis.get("summary")
        if isinstance(summary_candidate, str) and summary_candidate.strip():
            call_summary_text = summary_candidate.strip()
    if not call_summary_text:
        for key in ("summary", "call_summary"):
            summary_candidate = call_data.get(key)
            if isinstance(summary_candidate, str) and summary_candidate.strip():
                call_summary_text = summary_candidate.strip()
                break

    if existing_call:
        # Update existing call
        call = existing_call
        call.agent_id = call_data.get("agent_id") or call.agent_id
        call.agent_name = call_data.get("agent_name") or call.agent_name
        call.user_phone_number = call_data.get("user_phone_number") or call.user_phone_number
        call.start_timestamp = call_data.get("start_timestamp") or call.start_timestamp
        call.end_timestamp = call_data.get("end_timestamp") or call.end_timestamp
        call.recording_multi_channel_url = call_data.get("recording_multi_channel_url") or call.recording_multi_channel_url
        call.analysis_status = status or call.analysis_status
        call.duration_ms = duration_ms or call.duration_ms
        # Only update organization_id if provided and not already set
        if organization_id is not None and call.organization_id is None:
            call.organization_id = organization_id
        if user_id is not None and call.created_by_user_id is None:
            call.created_by_user_id = user_id
    else:
        # Create new call - organization_id is required
        if organization_id is None:
            raise ValueError("organization_id is required for new calls")
        call = Call(
            call_id=call_id,
            agent_id=call_data.get("agent_id"),
            agent_name=call_data.get("agent_name"),
            user_phone_number=call_data.get("user_phone_number"),
            start_timestamp=call_data.get("start_timestamp"),
            end_timestamp=call_data.get("end_timestamp"),
            recording_multi_channel_url=call_data.get("recording_multi_channel_url"),
            analysis_status=status or "pending",
            duration_ms=duration_ms,
            organization_id=organization_id,
            created_by_user_id=user_id,
        )
        db.add(call)

    if call_summary_text:
        call.call_summary = call_summary_text
        if not call.call_purpose:
            llm_client = get_openai_client()
            purpose = generate_call_purpose_from_summary(call_summary_text, openai_client=llm_client)
            if purpose:
                call.call_purpose = purpose

    if not call.call_title:
        call_title = derive_short_call_title(call_data, fallback_summary=call_summary_text)
        if call_title:
            call.call_title = call_title

    constraints = _evaluate_call_constraints(call_data)
    call.analysis_allowed = constraints["analysis_allowed"]
    call.analysis_block_reason = constraints["analysis_block_reason"]
    call.analysis_constraints = constraints["constraints"]
    if not constraints["analysis_allowed"]:
        call.analysis_status = "blocked"
        call.error_message = None

    # Store transcript_object if available
    transcript_object = call_data.get("transcript_object")
    if transcript_object is not None:
        call.transcript_available = True
        call.transcript_object = _strip_words_from_transcript(transcript_object)
    elif existing_call and existing_call.transcript_object is not None:
        call.transcript_object = _strip_words_from_transcript(existing_call.transcript_object)
        call.transcript_available = True

    db.commit()
    db.refresh(call)
    return call.to_dict()


def _update_retell_call_entry(db: Session, call_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if call is None:
        raise KeyError(f"Call {call_id} not found")

    # Update fields
    for key, value in updates.items():
        if hasattr(call, key):
            if value is not None or key in ["analysis_status", "error_message", "analysis_allowed", "analysis_block_reason"]:
                setattr(call, key, value)

    # analysis_available is set directly in updates, no need for filename check

    if call.analysis_allowed is False:
        call.analysis_status = "blocked"
        call.error_message = None

    db.commit()
    db.refresh(call)
    return call.to_dict()


def _get_retell_call_entry(db: Session, call_id: str) -> Optional[Dict[str, Any]]:
    call = db.query(Call).filter(Call.call_id == call_id).first()
    return call.to_dict() if call else None


def _refresh_call_metadata(db: Session, call_id: str) -> Dict[str, Any]:
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if call is None:
        raise KeyError(f"Call {call_id} not found")

    detailed_data = get_retell_call_details(call_id)
    constraint_info = _evaluate_call_constraints(detailed_data)

    call.agent_id = detailed_data.get("agent_id") or call.agent_id
    call.agent_name = detailed_data.get("agent_name") or call.agent_name
    call.user_phone_number = detailed_data.get("user_phone_number") or call.user_phone_number
    call.start_timestamp = detailed_data.get("start_timestamp") or call.start_timestamp
    call.end_timestamp = detailed_data.get("end_timestamp") or call.end_timestamp
    call.duration_ms = detailed_data.get("duration_ms") or call.duration_ms
    call.recording_multi_channel_url = detailed_data.get("recording_multi_channel_url") or call.recording_multi_channel_url
    call.analysis_allowed = constraint_info["analysis_allowed"]
    call.analysis_block_reason = constraint_info["analysis_block_reason"]
    call.analysis_constraints = constraint_info["constraints"]

    if not constraint_info["analysis_allowed"]:
        call.analysis_status = "blocked"
        call.error_message = None
    else:
        if call.analysis_status == "blocked":
            call.analysis_status = "pending"
        call.analysis_block_reason = None

    fallback_summary = None
    call_analysis = detailed_data.get("call_analysis")
    if isinstance(call_analysis, dict):
        fallback_summary = call_analysis.get("call_summary") or call_analysis.get("summary")

    if not fallback_summary:
        fallback_summary = detailed_data.get("call_summary") or detailed_data.get("summary")

    if fallback_summary:
        purpose = generate_call_purpose_from_summary(fallback_summary)
        if purpose:
            call.call_purpose = purpose

    db.commit()
    db.refresh(call)
    return call.to_dict()


def _persist_retell_results(db: Session, call_id: str, analysis_results: List[Dict[str, Any]], retell_metadata: Dict[str, Any]) -> None:
    """Persist processed Retell results to database."""
    try:
        # Delete existing analysis data for this call
        db.query(EmotionSegment).filter(EmotionSegment.call_id == call_id).delete()
        db.query(TranscriptSegment).filter(TranscriptSegment.call_id == call_id).delete()
        db.query(AnalysisSummary).filter(AnalysisSummary.call_id == call_id).delete()
        
        # Process each analysis result
        for result in analysis_results:
            if not isinstance(result, dict):
                continue
            
            # Migrate prosody segments
            prosody_segments = result.get("prosody", [])
            for segment_data in prosody_segments:
                _save_emotion_segment(db, call_id, segment_data, "prosody")
            
            # Migrate burst segments
            burst_segments = result.get("burst", [])
            for segment_data in burst_segments:
                _save_emotion_segment(db, call_id, segment_data, "burst")
            
            # Migrate transcript segments from metadata
            metadata = result.get("metadata", {})
            transcript_segments = metadata.get("retell_transcript_segments", [])
            for transcript_data in transcript_segments:
                _save_transcript_segment(db, call_id, transcript_data)
            
            # Migrate summary
            summary_text = result.get("summary")
            if summary_text:
                _save_analysis_summary(db, call_id, summary_text, "openai")
        
        db.commit()
        logger.info("Saved Retell analysis to database for call %s", call_id)
    except Exception as exc:  # pylint: disable=broad-except
        db.rollback()
        logger.error("Failed to save Retell results for %s: %s", call_id, exc)
        raise


def _save_emotion_segment(db: Session, call_id: str, segment_data: Dict[str, Any], segment_type: str):
    """Save a single emotion segment to database."""
    time_start = segment_data.get("time_start", 0.0)
    time_end = segment_data.get("time_end", 0.0)
    
    segment = EmotionSegment(
        call_id=call_id,
        segment_type=segment_type,
        time_start=float(time_start) if time_start is not None else 0.0,
        time_end=float(time_end) if time_end is not None else 0.0,
        speaker=segment_data.get("speaker"),
        text=segment_data.get("text"),
        transcript_text=segment_data.get("transcript_text"),
        primary_category=segment_data.get("primary_category"),
        source=segment_data.get("source", segment_type),
    )
    
    db.add(segment)
    db.flush()  # Flush to get segment.id
    
    # Save emotion predictions
    top_emotions = segment_data.get("top_emotions", [])
    for rank, emotion_data in enumerate(top_emotions, start=1):
        if not isinstance(emotion_data, dict):
            continue
        
        prediction = EmotionPrediction(
            segment_id=segment.id,
            emotion_name=emotion_data.get("name", "Unknown"),
            score=float(emotion_data.get("score", 0.0)),
            percentage=float(emotion_data.get("percentage", 0.0)),
            category=emotion_data.get("category", "neutral"),
            rank=rank,
        )
        db.add(prediction)


def _save_transcript_segment(db: Session, call_id: str, transcript_data: Dict[str, Any]):
    """Save a single transcript segment to database."""
    start_time = transcript_data.get("start", 0.0)
    end_time = transcript_data.get("end", 0.0)
    speaker = transcript_data.get("speaker")
    text = transcript_data.get("text", "")
    
    segment = TranscriptSegment(
        call_id=call_id,
        speaker=speaker or "Unknown",
        start_time=float(start_time) if start_time is not None else 0.0,
        end_time=float(end_time) if end_time is not None else 0.0,
        text=text,
        confidence=transcript_data.get("confidence"),
    )
    db.add(segment)


def _save_analysis_summary(db: Session, call_id: str, summary_text: str, summary_type: str):
    """Save analysis summary to database."""
    summary = AnalysisSummary(
        call_id=call_id,
        summary_text=summary_text,
        summary_type=summary_type,
    )
    db.add(summary)


def _extract_overall_emotion_from_results(
    analysis_results: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not analysis_results:
        return None

    for result in analysis_results:
        if not isinstance(result, dict):
            continue
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            continue
        overall_emotion = metadata.get("overall_call_emotion")
        if isinstance(overall_emotion, dict) and overall_emotion:
            return overall_emotion

        overall_status = metadata.get("overall_call_status")
        if isinstance(overall_status, dict) and overall_status:
            return overall_status

    return None


def _load_overall_emotion_for_call(db: Session, call_id: str) -> Optional[Dict[str, Any]]:
    """Load overall emotion from call's overall_emotion_json field."""
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if not call or not call.overall_emotion_json:
        return None
    return call.overall_emotion_json


def _process_retell_call(db: Session, call_payload: Dict[str, Any], organization_id: Optional[int] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    call_id = call_payload.get("call_id")
    if not call_id:
        logger.warning("Received Retell payload without call_id; skipping")
        raise ValueError("Missing call_id in Retell payload")

    try:
        call_data = dict(call_payload)
        detailed_data: Optional[Dict[str, Any]] = None
        try:
            detailed_data = get_retell_call_details(call_id)
        except Exception as fetch_exc:  # pylint: disable=broad-except
            logger.warning("Could not fetch detailed Retell data for %s: %s", call_id, fetch_exc)

        if detailed_data:
            merged_data = dict(detailed_data)
            # Only update with non-null values from call_data, preserving existing metadata
            merged_data.update({k: v for k, v in call_data.items() if v is not None})
            call_data = merged_data
        else:
            # If we can't fetch from Retell API, preserve existing metadata from call_payload
            # Don't overwrite existing values with nulls
            for key in ["start_timestamp", "end_timestamp", "duration_ms", "agent_id", "agent_name", "user_phone_number"]:
                if call_data.get(key) is None and call_payload.get(key) is not None:
                    call_data[key] = call_payload[key]

        call_summary_text: Optional[str] = None
        call_analysis = call_data.get("call_analysis")
        if isinstance(call_analysis, dict):
            summary_candidate = call_analysis.get("call_summary") or call_analysis.get("summary")
            if isinstance(summary_candidate, str) and summary_candidate.strip():
                call_summary_text = summary_candidate.strip()
        if not call_summary_text:
            for key in ("summary", "call_summary"):
                candidate = call_data.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    call_summary_text = candidate.strip()
                    break

        if not call_data.get("recording_multi_channel_url"):
            logger.error("No recording URL available for call %s", call_id)
            raise RuntimeError("No recording URL available for this call")

        constraint_info = _evaluate_call_constraints(call_data)
        
        # Get existing entry to preserve metadata
        existing_entry = _get_retell_call_entry(db, call_id)
        
        # Helper to preserve existing values if new value is None
        def preserve_or_update(key: str):
            new_val = call_data.get(key)
            if new_val is not None:
                return new_val
            if existing_entry and existing_entry.get(key) is not None:
                return existing_entry.get(key)
            return call_payload.get(key)  # Fallback to original payload
        
        metadata_updates = {
            "analysis_allowed": constraint_info["analysis_allowed"],
            "analysis_block_reason": constraint_info["analysis_block_reason"],
            "analysis_constraints": constraint_info["constraints"],
            # Only update timestamps/duration if we have valid values, otherwise preserve existing
            "start_timestamp": preserve_or_update("start_timestamp"),
            "end_timestamp": preserve_or_update("end_timestamp"),
            "duration_ms": preserve_or_update("duration_ms"),
            "agent_id": preserve_or_update("agent_id"),
            "agent_name": preserve_or_update("agent_name"),
        }

        if call_summary_text:
            metadata_updates["call_summary"] = call_summary_text
            purpose = generate_call_purpose_from_summary(call_summary_text)
            if purpose:
                metadata_updates["call_purpose"] = purpose

        call_title = derive_short_call_title(
            call_data,
            fallback_summary=call_summary_text,
        )
        if call_title:
            metadata_updates["call_title"] = call_title

        if not constraint_info["analysis_allowed"]:
            metadata_updates["analysis_status"] = "blocked"
            metadata_updates["error_message"] = None

        try:
            _update_retell_call_entry(db, call_id, metadata_updates)
        except KeyError:
            # Call not in metadata store - create it now, preserving metadata from call_payload
            logger.warning("Retell call %s not found in metadata store when updating constraints, creating entry", call_id)
            minimal_call_data = {
                "call_id": call_id,
                "recording_multi_channel_url": call_data.get("recording_multi_channel_url") or call_payload.get("recording_multi_channel_url"),
                "start_timestamp": call_data.get("start_timestamp") or call_payload.get("start_timestamp"),
                "end_timestamp": call_data.get("end_timestamp") or call_payload.get("end_timestamp"),
                "duration_ms": call_data.get("duration_ms") or call_payload.get("duration_ms"),
                "agent_id": call_data.get("agent_id") or call_payload.get("agent_id"),
                "agent_name": call_data.get("agent_name") or call_payload.get("agent_name"),
                "user_phone_number": call_data.get("user_phone_number") or call_payload.get("user_phone_number"),
            }
            _upsert_retell_call_metadata(db, minimal_call_data, status="processing", organization_id=organization_id, user_id=user_id)
            _update_retell_call_entry(db, call_id, metadata_updates)

        if not constraint_info["analysis_allowed"]:
            raise HTTPException(
                status_code=400,
                detail=constraint_info["analysis_block_reason"] or "Call cannot be analyzed.",
            )

        recording_url = call_data.get("recording_multi_channel_url")

        filename_hint = f"{call_id}.wav"
        audio_filename, audio_bytes = download_retell_recording(recording_url, filename_hint)

        # Submit combined audio to Hume - speaker labels will come from transcript matching
        file_contents = [(audio_filename, audio_bytes)]
        logger.info("Using combined audio for call %s (speaker labels from transcript)", call_id)

        # Extract transcript segments - but fetch fresh from API if stored one is incomplete
        # (stored transcript_object may have words stripped, which breaks extraction if segments lack start/end)
        transcript_segments = extract_retell_transcript_segments(call_data)
        if not transcript_segments:
            # Fallback: fetch fresh from Retell API to ensure we have complete transcript with words
            try:
                fresh_call_data = get_retell_call_details(call_id)
                transcript_segments = extract_retell_transcript_segments(fresh_call_data)
                logger.info("Fetched fresh transcript from Retell API for call %s", call_id)
            except Exception as exc:
                logger.warning("Could not fetch fresh transcript from Retell API for call %s: %s", call_id, exc)

        dynamic_variables = call_data.get("retell_llm_dynamic_variables") or {}
        retell_metadata = {
            "retell_call_id": call_id,
            "recording_multi_channel_url": recording_url,
            "start_timestamp": call_data.get("start_timestamp"),
            "end_timestamp": call_data.get("end_timestamp"),
            "duration_ms": call_data.get("duration_ms"),
            "agent": {
                "id": call_data.get("agent_id"),
                "name": call_data.get("agent_name"),
                "version": call_data.get("agent_version"),
            },
            "customer": {
                "first_name": dynamic_variables.get("first_name") or call_data.get("customer_name"),
                "program": dynamic_variables.get("program"),
                "lead_status": dynamic_variables.get("lead_status"),
                "university": dynamic_variables.get("university"),
            },
            "analysis_constraints": constraint_info["constraints"],
        }

        analysis_results = analyze_audio_files(
            file_contents,
            include_summary=True,
            retell_call_id=call_id,
            retell_transcript=transcript_segments,
            retell_metadata=retell_metadata,
        )

        overall_emotion = _extract_overall_emotion_from_results(analysis_results)

        analysis_summary: Optional[str] = None
        for result in analysis_results:
            if isinstance(result, dict):
                summary_candidate = result.get("summary")
                if isinstance(summary_candidate, str) and summary_candidate.strip():
                    analysis_summary = summary_candidate.strip()
                    break

        # Save analysis results to database
        _persist_retell_results(db, call_id, analysis_results, retell_metadata)
        
        try:
            final_updates: Dict[str, Any] = {
                "analysis_status": "completed",
                "analysis_available": True,
                "recording_multi_channel_url": recording_url,
            }

            if overall_emotion:
                final_updates["overall_emotion_json"] = overall_emotion
                final_updates["overall_emotion_label"] = overall_emotion.get("label")

            existing_entry = _get_retell_call_entry(db, call_id)

            openai_client = None
            fallback_summary = analysis_summary or call_summary_text

            if analysis_summary and (not existing_entry or not existing_entry.get("call_summary")):
                final_updates["call_summary"] = analysis_summary

            needs_title = not existing_entry or not existing_entry.get("call_title")
            if needs_title and fallback_summary:
                openai_client = openai_client or get_openai_client()
                derived_title = derive_short_call_title(
                    call_data,
                    fallback_summary=fallback_summary,
                    openai_client=openai_client,
                )
                if derived_title:
                    final_updates["call_title"] = derived_title

            needs_purpose = not existing_entry or not existing_entry.get("call_purpose")
            if needs_purpose and fallback_summary:
                openai_client = openai_client or get_openai_client()
                purpose = generate_call_purpose_from_summary(fallback_summary, openai_client=openai_client)
                if purpose:
                    final_updates["call_purpose"] = purpose

            # Preserve existing metadata in final_updates if not already set
            if existing_entry:
                if "start_timestamp" not in final_updates and existing_entry.get("start_timestamp"):
                    final_updates["start_timestamp"] = existing_entry.get("start_timestamp")
                if "end_timestamp" not in final_updates and existing_entry.get("end_timestamp"):
                    final_updates["end_timestamp"] = existing_entry.get("end_timestamp")
                if "duration_ms" not in final_updates and existing_entry.get("duration_ms"):
                    final_updates["duration_ms"] = existing_entry.get("duration_ms")
                if "agent_id" not in final_updates and existing_entry.get("agent_id"):
                    final_updates["agent_id"] = existing_entry.get("agent_id")
                if "agent_name" not in final_updates and existing_entry.get("agent_name"):
                    final_updates["agent_name"] = existing_entry.get("agent_name")
                if "user_phone_number" not in final_updates and existing_entry.get("user_phone_number"):
                    final_updates["user_phone_number"] = existing_entry.get("user_phone_number")
            
            _update_retell_call_entry(db, call_id, final_updates)
        except Exception as update_exc:  # pylint: disable=broad-except
            logger.error("Failed to update metadata store for call %s after analysis: %s", call_id, update_exc)

        # Return payload in same format as before for compatibility
        return {
            "call_id": call_id,
            "retell_metadata": retell_metadata,
            "analysis": analysis_results
        }

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Error processing Retell call %s: %s", call_id, exc)
        # Create a new session for error handling
        error_db = SessionLocal()
        try:
            try:
                _update_retell_call_entry(
                    error_db,
                    call_id,
                    {
                        "analysis_status": "error",
                        "error_message": str(exc),
                    },
                )
            except KeyError:
                # Call not in metadata store - create it with error status
                logger.warning("Retell call %s not found in metadata store while recording error, creating entry", call_id)
                minimal_call_data = {
                    "call_id": call_id,
                    "recording_multi_channel_url": call_payload.get("recording_multi_channel_url"),
                }
                # Get organization_id from existing call if available
                existing_call = error_db.query(Call).filter(Call.call_id == call_id).first()
                org_id = existing_call.organization_id if existing_call else None
                _upsert_retell_call_metadata(error_db, minimal_call_data, status="error", organization_id=org_id)
                _update_retell_call_entry(error_db, call_id, {
                    "error_message": str(exc),
                })
        except Exception as update_exc:  # pylint: disable=broad-except
            logger.error("Failed to update metadata store for call %s: %s", call_id, update_exc)
        finally:
            error_db.close()
        raise


@app.post("/{org_id}/{agent_id}/retell/webhook")
async def retell_webhook_with_org_and_agent(
    org_id: str = Path(..., min_length=1, description="Organization ID (unique identifier)"),
    agent_id: str = Path(..., min_length=1, description="Agent ID from the organization's agent list"),
    payload: Dict[str, Any] = Body(...), 
    db: Session = Depends(get_db)
):
    """
    Endpoint to receive Retell call events and register them for analysis.
    
    Organization ID and Agent ID are extracted from the URL path: /{org_id}/{agent_id}/retell/webhook
    This allows routing webhooks to the correct organization and agent.
    
    Supports two payload formats:
    1. Direct Retell format: { "event": "call_analyzed", "call": {...} }
    2. n8n format: { "body": { "event": "call_analyzed", ...call data... } }
    """
    # Find the organization by org_id
    organization = db.query(Organization).filter(Organization.org_id == org_id).first()
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization ID '{org_id}' not found."
        )
    
    organization_id = organization.id
    
    # Find the agent within this organization
    agent = db.query(Agent).filter(
        Agent.agent_id == agent_id,
        Agent.organization_id == organization_id
    ).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent ID '{agent_id}' not found in organization '{org_id}'. Please add this agent to the organization first."
        )
    
    event, call_data = _normalize_retell_payload(payload)

    if event != "call_analyzed" or not isinstance(call_data, dict):
        logger.info("Ignoring Retell event %s (call_data type: %s) for agent %s (org: %s)", event, type(call_data).__name__, agent_id, organization_id)
        if event == "call_analyzed" and not isinstance(call_data, dict):
            logger.warning("call_analyzed event received but call_data is not a dict. Payload keys: %s", list(payload.keys())[:10])
        return JSONResponse(content={"success": True, "ignored": True})

    call_id = call_data.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id in Retell payload")

    # Ensure the agent_id in the call_data matches the URL agent_id
    # This ensures consistency even if the payload has a different agent_id
    call_data["agent_id"] = agent_id

    logger.info("Received call_analyzed webhook for call %s (agent: %s, org_id: %s, org: %s)", call_id, agent_id, org_id, organization_id)
    try:
        metadata = _upsert_retell_call_metadata(db, call_data, status="pending", organization_id=organization_id)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to record Retell call metadata for %s: %s", call_id, exc)
        raise HTTPException(status_code=500, detail="Failed to record call metadata") from exc

    return JSONResponse(
        content={
            "success": True,
            "message": "Call registered",
            "call_id": call_id,
            "call_metadata": metadata,
            "agent_id": agent_id,
            "org_id": org_id,
            "organization_id": organization_id,
        }
    )


@app.post("/{agent_id}/retell/webhook")
async def retell_webhook_with_agent_legacy(
    agent_id: str = Path(..., min_length=1, description="Agent ID from the organization's agent list"),
    payload: Dict[str, Any] = Body(...), 
    db: Session = Depends(get_db)
):
    """
    Legacy endpoint to receive Retell call events (backward compatibility).
    
    This endpoint tries to determine organization_id from agent_id in payload.
    For production use, prefer /{org_id}/{agent_id}/retell/webhook instead.
    
    Supports two payload formats:
    1. Direct Retell format: { "event": "call_analyzed", "call": {...} }
    2. n8n format: { "body": { "event": "call_analyzed", ...call data... } }
    """
    # Find the agent to get the organization_id
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent ID '{agent_id}' not found. Please add this agent to an organization first."
        )
    
    organization_id = agent.organization_id
    event, call_data = _normalize_retell_payload(payload)

    if event != "call_analyzed" or not isinstance(call_data, dict):
        logger.info("Ignoring Retell event %s (call_data type: %s) for agent %s (org: %s)", event, type(call_data).__name__, agent_id, organization_id)
        if event == "call_analyzed" and not isinstance(call_data, dict):
            logger.warning("call_analyzed event received but call_data is not a dict. Payload keys: %s", list(payload.keys())[:10])
        return JSONResponse(content={"success": True, "ignored": True})

    call_id = call_data.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id in Retell payload")

    # Ensure the agent_id in the call_data matches the URL agent_id
    call_data["agent_id"] = agent_id

    logger.info("Received call_analyzed webhook for call %s (agent: %s, org: %s) via legacy endpoint", call_id, agent_id, organization_id)
    try:
        metadata = _upsert_retell_call_metadata(db, call_data, status="pending", organization_id=organization_id)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to record Retell call metadata for %s: %s", call_id, exc)
        raise HTTPException(status_code=500, detail="Failed to record call metadata") from exc

    return JSONResponse(
        content={
            "success": True,
            "message": "Call registered",
            "call_id": call_id,
            "call_metadata": metadata,
            "agent_id": agent_id,
            "organization_id": organization_id,
        }
    )


@app.post("/retell/webhook")
async def retell_webhook(
    payload: Dict[str, Any] = Body(...), 
    db: Session = Depends(get_db)
):
    """
    Legacy endpoint to receive Retell call events (backward compatibility).
    
    This endpoint tries to determine organization_id from agent_id in payload, 
    or from organization_id in payload, or uses the first organization.
    For production use, prefer /{org_id}/{agent_id}/retell/webhook instead.
    
    Supports two payload formats:
    1. Direct Retell format: { "event": "call_analyzed", "call": {...} }
    2. n8n format: { "body": { "event": "call_analyzed", ...call data... } }
    """
    event, call_data = _normalize_retell_payload(payload)

    if event != "call_analyzed" or not isinstance(call_data, dict):
        logger.info("Ignoring Retell event %s (call_data type: %s)", event, type(call_data).__name__)
        if event == "call_analyzed" and not isinstance(call_data, dict):
            logger.warning("call_analyzed event received but call_data is not a dict. Payload keys: %s", list(payload.keys())[:10])
        return JSONResponse(content={"success": True, "ignored": True})

    call_id = call_data.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id in Retell payload")

    # Determine organization_id
    # Priority 1: Try to get from agent_id in payload
    organization_id = None
    agent_id_from_payload = call_data.get("agent_id")
    if agent_id_from_payload:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id_from_payload).first()
        if agent:
            organization_id = agent.organization_id
            logger.info("Found organization %s from agent_id %s in payload", organization_id, agent_id_from_payload)
    
    # Priority 2: Try to get from payload metadata
    if organization_id is None:
        organization_id = call_data.get("organization_id")
    
    # Priority 3: Try to get from top-level payload
    if organization_id is None:
        organization_id = payload.get("organization_id")
    
    # Priority 4: Fallback to first organization (for migration/compatibility)
    if organization_id is None:
        first_org = db.query(Organization).first()
        if first_org:
            organization_id = first_org.id
            logger.warning("Using first organization %s as fallback for call %s", organization_id, call_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No organization available. Please create an organization first."
            )

    logger.info("Received call_analyzed webhook for call %s (org: %s) via legacy endpoint", call_id, organization_id)
    try:
        metadata = _upsert_retell_call_metadata(db, call_data, status="pending", organization_id=organization_id)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to record Retell call metadata for %s: %s", call_id, exc)
        raise HTTPException(status_code=500, detail="Failed to record call metadata") from exc

    return JSONResponse(
        content={
            "success": True,
            "message": "Call registered",
            "call_id": call_id,
            "call_metadata": metadata,
        }
    )


@app.get("/retell/calls")
async def list_retell_calls(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(15, ge=1, le=100, description="Number of items per page"),
    organization_id: Optional[int] = Query(None, description="Filter by organization (admin only)"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    analysis_status: Optional[str] = Query(None, description="Filter by analysis status (e.g., 'completed')"),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Return available Retell calls registered via webhook.
    
    Supports pagination via query parameters:
    - page: Page number (default: 1, minimum: 1)
    - per_page: Items per page (default: 15, minimum: 1, maximum: 100)
    - organization_id: Filter by organization (admin only, optional)
    - agent_id: Filter by agent ID (optional for admins, required for users)
    
    For users: returns calls from their current organization.
               If agent_id is provided, filters by that specific agent (must be in saved agents list).
               If agent_id is not provided, returns all calls for all agents in the organization.
    For admins: returns all calls, optionally filtered by organization_id and/or agent_id
    """
    role = token_data.get("role")
    user_id = token_data.get("user_id")
    user_org_id = get_current_organization_id(token_data)
    
    # Query calls, excluding zero-duration calls
    query = db.query(Call).filter(
        (Call.duration_ms.is_(None)) | (Call.duration_ms > 0)
    )
    
    # Apply organization filtering
    if role == "admin":
        # Determine which organization_id to use (query param takes precedence, then token)
        effective_org_id = organization_id if organization_id is not None else user_org_id
        
        # If admin has organization context (from token or query param), filter by it
        if effective_org_id is not None:
            query = query.filter(Call.organization_id == effective_org_id)
            
            # If admin has organization context and agent_id is provided,
            # verify agent belongs to that organization
            if agent_id is not None:
                saved_agent = db.query(Agent).filter(
                    Agent.organization_id == effective_org_id,
                    Agent.agent_id == agent_id
                ).first()
                
                if not saved_agent:
                    # Agent not in saved list, return empty
                    return JSONResponse(content={
                        "success": True,
                        "calls": [],
                        "pagination": {
                            "page": page,
                            "per_page": per_page,
                            "total": 0,
                            "total_pages": 1,
                            "has_next": False,
                            "has_prev": False,
                        }
                    })
                # Filter by the specific agent_id
                query = query.filter(Call.agent_id == agent_id)
        elif agent_id is not None:
            # Admin filtering by agent globally (no organization context)
            query = query.filter(Call.agent_id == agent_id)
    else:
        # Users only see calls from their current organization
        if user_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization context required"
            )
        query = query.filter(Call.organization_id == user_org_id)
        
        # If specific agent_id is provided, filter by it
        # (only show calls for agents that are saved in the organization)
        if agent_id is not None:
            # Verify agent is in saved list
            saved_agent = db.query(Agent).filter(
                Agent.organization_id == user_org_id,
                Agent.agent_id == agent_id
            ).first()
            
            if not saved_agent:
                # Agent not in saved list, return empty
                return JSONResponse(content={
                    "success": True,
                    "calls": [],
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": 0,
                        "total_pages": 1,
                        "has_next": False,
                        "has_prev": False,
                    }
                })
            # Filter by the specific agent_id
            query = query.filter(Call.agent_id == agent_id)
        # If agent_id is not provided, show all calls for the organization (all agents)
    
    # Apply analysis_status filtering if provided
    if analysis_status is not None:
        if analysis_status == "completed":
            # Only show calls that are fully analyzed - both status must be completed AND analysis_available must be True
            query = query.filter(
                Call.analysis_status == "completed",
                Call.analysis_available == True
            )
        else:
            query = query.filter(Call.analysis_status == analysis_status)
    
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    # Apply pagination and sorting
    calls = query.order_by(
        Call.start_timestamp.desc().nullslast()
    ).offset((page - 1) * per_page).limit(per_page).all()
    
    enriched_calls = []
    for call in calls:
        call_entry = call.to_dict()
        if call.analysis_status == "completed":
            overall_emotion = call_entry.get("overall_emotion")
            if not isinstance(overall_emotion, dict):
                overall_emotion = _load_overall_emotion_for_call(db, call.call_id)
                if overall_emotion:
                    call_entry["overall_emotion"] = overall_emotion
                    call_entry["overall_emotion_label"] = overall_emotion.get("label")
                    try:
                        _update_retell_call_entry(
                            db,
                            call.call_id,
                            {
                                "overall_emotion_json": overall_emotion,
                                "overall_emotion_label": overall_emotion.get("label"),
                            },
                        )
                    except KeyError:
                        logger.warning("Call %s missing when caching overall emotion", call.call_id)
            else:
                label = call_entry.get("overall_emotion_label")
                if not label:
                    call_entry["overall_emotion_label"] = overall_emotion.get("label")
        enriched_calls.append(call_entry)

    return JSONResponse(content={
        "success": True,
        "calls": enriched_calls,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    })


@app.post("/retell/calls/refresh")
async def refresh_retell_calls(
    call_id: Optional[str] = None, 
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Re-evaluate stored call metadata (voicemail detection, duration, etc.).
    If call_id is provided, refresh only that call; otherwise refresh all.
    """
    refreshed = []
    errors: Dict[str, str] = {}

    if call_id:
        target_ids = [call_id]
    else:
        # Get all call IDs from database
        calls = db.query(Call).all()
        target_ids = [call.call_id for call in calls]

    for cid in target_ids:
        try:
            entry = _refresh_call_metadata(db, cid)
            refreshed.append(entry)
        except Exception as exc:  # pylint: disable=broad-except
            errors[cid] = str(exc)

    return JSONResponse(
        content={
            "success": len(errors) == 0,
            "refreshed_count": len(refreshed),
            "errors": errors,
            "calls": refreshed if call_id else None,
        }
    )


def _ensure_call_registered(db: Session, call_id: str) -> Dict[str, Any]:
    call_entry = _get_retell_call_entry(db, call_id)
    if not call_entry:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    return call_entry


def _prepare_retell_call_payload(call_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare call payload for analysis, preserving all existing metadata."""
    payload: Dict[str, Any] = {
        "call_id": call_entry["call_id"],
        "recording_multi_channel_url": call_entry.get("recording_multi_channel_url"),
        # Preserve existing metadata to avoid overwriting with nulls
        "start_timestamp": call_entry.get("start_timestamp"),
        "end_timestamp": call_entry.get("end_timestamp"),
        "duration_ms": call_entry.get("duration_ms"),
        "agent_id": call_entry.get("agent_id"),
        "agent_name": call_entry.get("agent_name"),
        "user_phone_number": call_entry.get("user_phone_number"),
    }
    # Include transcript_object if available (from n8n or stored metadata)
    # NOTE: Do NOT strip words here - extract_retell_transcript_segments needs words
    # as fallback if segments don't have start/end timestamps
    transcript_object = call_entry.get("transcript_object")
    if transcript_object is not None:
        payload["transcript_object"] = transcript_object
    return payload


def _process_retell_call_background(call_id: str, call_payload: Dict[str, Any], organization_id: Optional[int] = None, user_id: Optional[int] = None) -> None:
    """Background task to process Retell call analysis without blocking the HTTP request."""
    db = SessionLocal()
    try:
        logger.info("Starting background analysis for call %s", call_id)
        analysis_payload = _process_retell_call(db, call_payload, organization_id=organization_id, user_id=user_id)
        logger.info("Completed background analysis for call %s", call_id)
    except HTTPException as exc:
        logger.error("HTTP error in background analysis for call %s: %s", call_id, exc.detail)
        try:
            _update_retell_call_entry(db, call_id, {
                "analysis_status": "error",
                "error_message": exc.detail
            })
        except KeyError:
            # Call not in metadata store - create it with error status
            logger.warning("Retell call %s not found in metadata store while recording HTTP error, creating entry", call_id)
            minimal_call_data = {
                "call_id": call_id,
                "recording_multi_channel_url": call_payload.get("recording_multi_channel_url"),
            }
            _upsert_retell_call_metadata(db, minimal_call_data, status="error", organization_id=organization_id, user_id=user_id)
            _update_retell_call_entry(db, call_id, {
                "error_message": exc.detail
            })
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to analyze Retell call %s in background: %s", call_id, exc)
        try:
            _update_retell_call_entry(db, call_id, {
                "analysis_status": "error",
                "error_message": str(exc)
            })
        except KeyError:
            # Call not in metadata store - create it with error status
            logger.warning("Retell call %s not found in metadata store while recording error, creating entry", call_id)
            minimal_call_data = {
                "call_id": call_id,
                "recording_multi_channel_url": call_payload.get("recording_multi_channel_url"),
            }
            _upsert_retell_call_metadata(db, minimal_call_data, status="error", organization_id=organization_id, user_id=user_id)
            _update_retell_call_entry(db, call_id, {
                "error_message": str(exc)
            })
    finally:
        db.close()


@app.post("/retell/calls/{call_id}/analyze")
async def analyze_retell_call(
    call_id: str, 
    force: bool = Query(False), 
    background_tasks: BackgroundTasks = BackgroundTasks(),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Trigger Hume analysis for a previously-registered Retell call.
    
    Returns immediately and processes in the background to avoid gateway timeouts.
    Use GET /retell/calls/{call_id}/analysis to check status and retrieve results.
    """
    # Verify organization access
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    
    role = token_data.get("role")
    user_org_id = get_current_organization_id(token_data)
    
    # Verify user has access to this call's organization
    if role == "user":
        if call.organization_id != user_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Call does not belong to your current organization"
            )
    # Admins can access any call
    
    call_entry = call.to_dict()
    if call_entry.get("analysis_allowed") is False:
        reason = call_entry.get("analysis_block_reason") or "Call cannot be analyzed."
        raise HTTPException(
            status_code=400,
            detail=reason,
        )

    # If analysis already exists and not forcing, return it immediately
    if not force:
        try:
            return await get_retell_call_analysis(call_id, token_data=token_data, db=db)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise

    # Check if already processing
    current_status = call_entry.get("analysis_status")
    if current_status == "processing":
        return JSONResponse(content={
            "success": True,
            "message": "Analysis already in progress",
            "call_id": call_id,
            "status": "processing"
        })

    if force:
        logger.info("Force re-running analysis for Retell call %s", call_id)

    # Mark as processing and start background task
    _update_retell_call_entry(db, call_id, {"analysis_status": "processing", "error_message": None})
    
    call_payload = _prepare_retell_call_payload(call_entry)
    org_id = call.organization_id
    user_id = token_data.get("user_id")
    background_tasks.add_task(_process_retell_call_background, call_id, call_payload, org_id, user_id)

    # Return immediately - processing happens in background
    return JSONResponse(content={
        "success": True,
        "message": "Analysis started in background",
        "call_id": call_id,
        "status": "processing",
        "note": "Use GET /retell/calls/{call_id}/analysis to check status and retrieve results when complete"
    })


def _reconstruct_analysis_from_db(db: Session, call_id: str) -> Optional[Dict[str, Any]]:
    """Reconstruct analysis results from database in the format expected by frontend."""
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if not call or not call.analysis_available:
        return None
    
    # Get emotion segments with predictions eagerly loaded
    prosody_segments = db.query(EmotionSegment).filter(
        EmotionSegment.call_id == call_id,
        EmotionSegment.segment_type == "prosody"
    ).order_by(EmotionSegment.time_start).all()
    
    burst_segments = db.query(EmotionSegment).filter(
        EmotionSegment.call_id == call_id,
        EmotionSegment.segment_type == "burst"
    ).order_by(EmotionSegment.time_start).all()
    
    # Load predictions for all segments
    segment_ids = [seg.id for seg in prosody_segments + burst_segments]
    if segment_ids:
        predictions = db.query(EmotionPrediction).filter(
            EmotionPrediction.segment_id.in_(segment_ids)
        ).all()
        # Group predictions by segment_id
        predictions_by_segment = {}
        for pred in predictions:
            if pred.segment_id not in predictions_by_segment:
                predictions_by_segment[pred.segment_id] = []
            predictions_by_segment[pred.segment_id].append(pred)
        
        # Attach predictions to segments
        for seg in prosody_segments + burst_segments:
            seg._predictions_cache = sorted(
                predictions_by_segment.get(seg.id, []),
                key=lambda x: x.rank
            )
    
    # Get transcript segments
    transcript_segments = db.query(TranscriptSegment).filter(
        TranscriptSegment.call_id == call_id
    ).order_by(TranscriptSegment.start_time).all()
    
    # Get summary
    summary_obj = db.query(AnalysisSummary).filter(
        AnalysisSummary.call_id == call_id
    ).order_by(AnalysisSummary.created_at.desc()).first()
    
    # Build metadata
    metadata: Dict[str, Any] = {
        "retell_call_id": call_id,
        "recording_multi_channel_url": call.recording_multi_channel_url,
        "start_timestamp": call.start_timestamp,
        "end_timestamp": call.end_timestamp,
        "duration_ms": call.duration_ms,
        "agent": {
            "id": call.agent_id,
            "name": call.agent_name,
        },
        "retell_transcript_available": call.transcript_available,
        "retell_transcript_segments": [seg.to_dict() for seg in transcript_segments],
    }
    
    if call.analysis_constraints:
        metadata["analysis_constraints"] = call.analysis_constraints
    
    # Count categories
    category_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for seg in prosody_segments:
        if seg.primary_category:
            category_counts[seg.primary_category] = category_counts.get(seg.primary_category, 0) + 1
    metadata["category_counts"] = category_counts
    
    if call.overall_emotion_json:
        metadata["overall_call_emotion"] = call.overall_emotion_json
    
    # Build result - manually construct segment dicts with predictions
    def segment_to_dict(seg):
        seg_dict = {
            "time_start": float(seg.time_start) if seg.time_start else 0.0,
            "time_end": float(seg.time_end) if seg.time_end else 0.0,
            "primary_category": seg.primary_category,
            "source": seg.source,
        }
        if seg.speaker:
            seg_dict["speaker"] = seg.speaker
        if seg.text:
            seg_dict["text"] = seg.text
        if seg.transcript_text:
            seg_dict["transcript_text"] = seg.transcript_text
        
        # Add predictions if available
        preds = getattr(seg, '_predictions_cache', [])
        if preds:
            seg_dict["top_emotions"] = [
                {
                    "name": pred.emotion_name,
                    "score": float(pred.score) if pred.score else 0.0,
                    "percentage": float(pred.percentage) if pred.percentage else 0.0,
                    "category": pred.category,
                }
                for pred in preds
            ]
        return seg_dict
    
    result = {
        "filename": f"{call_id}_combined",
        "prosody": [segment_to_dict(seg) for seg in prosody_segments],
        "burst": [segment_to_dict(seg) for seg in burst_segments],
        "metadata": metadata,
    }
    
    if summary_obj:
        result["summary"] = summary_obj.summary_text
    
    return result


@app.get("/retell/calls/{call_id}/analysis")
async def get_retell_call_analysis(
    call_id: str, 
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Return stored analysis for a Retell call if it has been processed.
    
    Returns status information if analysis is still processing or has errors.
    """
    # Verify organization access
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if not call:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    
    role = token_data.get("role")
    user_org_id = get_current_organization_id(token_data)
    
    # Verify user has access to this call's organization
    if role == "user":
        if call.organization_id != user_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Call does not belong to your current organization"
            )
    # Admins can access any call
    
    call_entry = call.to_dict()
    
    # Check if still processing
    analysis_status = call_entry.get("analysis_status")
    if analysis_status == "processing":
        return JSONResponse(content={
            "success": True,
            "call_id": call_id,
            "status": "processing",
            "message": "Analysis is still in progress. Please check again in a few moments."
        })
    
    # Check if there was an error
    if analysis_status == "error":
        error_message = call_entry.get("error_message", "Unknown error occurred")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "call_id": call_id,
                "status": "error",
                "error_message": error_message
            }
        )
    
    # Reconstruct analysis from database
    result = _reconstruct_analysis_from_db(db, call_id)
    if not result:
        raise HTTPException(status_code=404, detail="Analysis not available for this call")
    
    # Build retell_metadata from call
    call = db.query(Call).filter(Call.call_id == call_id).first()
    retell_metadata = {
        "retell_call_id": call_id,
        "recording_multi_channel_url": call.recording_multi_channel_url,
        "start_timestamp": call.start_timestamp,
        "end_timestamp": call.end_timestamp,
        "duration_ms": call.duration_ms,
    }

    return JSONResponse(
        content={
            "success": True,
            "call_id": call_id,
            "results": result,
            "retell_metadata": retell_metadata,
            "recording_url": call.recording_multi_channel_url,
        }
    )


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Hume Emotion Analysis API is running", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


"""
Authentication routes using MongoDB for TDSC Backend.
"""

from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId
import os
from dotenv import load_dotenv

from database import Database, get_db
from models.db_models import User
from tracing import get_trace_logger

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "tdsc_super_secret_key_change_in_production_2024")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

router = APIRouter(prefix="/auth", tags=["Authentication"])

# JWT Bearer scheme
security = HTTPBearer(auto_error=False)
trace_logger = get_trace_logger()


# Pydantic schemas
class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Database = Depends(get_db)
) -> Optional[dict]:
    """Get the current user from JWT token (returns None if not authenticated)"""
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        users = db.get_collection('users')
        user = users.find_one({"_id": ObjectId(user_id)})
        
        if user:
            return {
                "id": str(user["_id"]),
                "username": user["username"],
                "email": user["email"],
                "created_at": user["created_at"]
            }
        return None
    except JWTError:
        return None
    except Exception:
        return None


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Database = Depends(get_db)
) -> dict:
    """Require authentication - raises 401 if not authenticated"""
    user = get_current_user(credentials, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.post("/signup", response_model=Token)
def signup(user_data: UserCreate, db: Database = Depends(get_db), request: Request = None):
    """Register a new user"""
    request_id = getattr(request.state, 'request_id', None) if request else None
    trace_logger.log_operation("User Signup Attempt", {"username": user_data.username, "email": user_data.email}, request_id)
    
    users = db.get_collection('users')
    
    # Check if email already exists
    trace_logger.log_database_operation("Query", "users", f"email={user_data.email}", request_id)
    if users.find_one({"email": user_data.email}):
        trace_logger.log_auth_event("Signup Failed - Email Already Registered", user_data.email, request_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Check if username already exists
    trace_logger.log_database_operation("Query", "users", f"username={user_data.username}", request_id)
    if users.find_one({"username": user_data.username}):
        trace_logger.log_auth_event("Signup Failed - Username Taken", user_data.username, request_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
    
    # Create user
    hashed_pw = hash_password(user_data.password)
    new_user_doc = User.create_doc(user_data.username, user_data.email, hashed_pw)
    result = users.insert_one(new_user_doc)
    
    trace_logger.log_database_operation("Insert", "users", f"id={result.inserted_id}", request_id)
    
    # Get the created user
    created_user = users.find_one({"_id": result.inserted_id})
    user_response = User.to_response(created_user)
    
    # Create token
    access_token = create_access_token({"sub": str(created_user['_id'])})
    
    trace_logger.log_auth_event("User Signup Successful", user_data.email, request_id)
    
    return Token(
        access_token=access_token,
        user=UserResponse(**user_response)
    )


@router.post("/signin", response_model=Token)
def signin(credentials: UserLogin, db: Database = Depends(get_db), request: Request = None):
    """Sign in and get access token"""
    request_id = getattr(request.state, 'request_id', None) if request else None
    trace_logger.log_operation("User Signin Attempt", {"email": credentials.email}, request_id)
    
    users = db.get_collection('users')
    
    # Find user by email
    trace_logger.log_database_operation("Query", "users", f"email={credentials.email}", request_id)
    user = users.find_one({"email": credentials.email})
    if not user:
        trace_logger.log_auth_event("Signin Failed - User Not Found", credentials.email, request_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Verify password
    if not verify_password(credentials.password, user['hashed_password']):
        trace_logger.log_auth_event("Signin Failed - Invalid Password", credentials.email, request_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Create token
    user_response = User.to_response(user)
    access_token = create_access_token({"sub": str(user['_id'])})
    
    trace_logger.log_auth_event("User Signin Successful", credentials.email, request_id)
    
    return Token(
        access_token=access_token,
        user=UserResponse(**user_response)
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: dict = Depends(require_auth)):
    """Get current authenticated user"""
    return UserResponse(**current_user)

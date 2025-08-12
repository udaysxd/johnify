from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks, Depends
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Any, Optional

from ..database import get_db
from . import models, schemas, security
from .security import (
    get_password_hash,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_active_user,
    get_current_user
)

router = APIRouter(prefix="/auth", tags=["authentication"])

# Email configuration (placeholder - replace with actual email service)
EMAIL_SENDER = "noreply@yourdomain.com"
VERIFICATION_URL = "http://localhost:3000/verify-email"  # Update with your frontend URL

async def send_verification_email(email: str, token: str, username: str):
    """Send a verification email to the user"""
    # In a real application, you would use an email service like SendGrid, Mailgun, etc.
    verification_url = f"{VERIFICATION_URL}?token={token}"
    
    # This is a placeholder - replace with actual email sending logic
    print(f"Sending verification email to {email}")
    print(f"Verification URL: {verification_url}")
    
    # Example of what you might do with an email service:
    # await send_email(
    #     to_email=email,
    #     subject="Verify your email address",
    #     template="email_verification.html",
    #     context={"username": username, "verification_url": verification_url}
    # )

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: schemas.UserCreate, 
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """Register a new user"""
    # Check if user already exists
    db_user = db.query(models.User).filter(models.User.user_email == user_in.user_email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    user = models.User(
        user_email=user_in.user_email,
        user_name=user_in.user_name,
    )
    user.set_password(user_in.password)
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # No email verification needed, user is immediately active
    user.is_verified = True
    db.commit()
    db.refresh(user)
    
    # Generate access token for immediate login
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.user_email}, expires_delta=access_token_expires
    )
    
    # Return the token and user data in the expected format
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_email": user.user_email,
        "user_name": user.user_name,
        "user_id": user.user_id,
        "uuid": user.uuid,
        "is_verified": user.is_verified,
        "created_on": user.created_on,
        "updated_on": user.updated_on,
        "active": user.active
    }

@router.post("/login", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """OAuth2 compatible token login, get an access token for future requests"""
    user = db.query(models.User).filter(models.User.user_email == form_data.username).first()
    
    if not user or not user.check_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with expiration
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.user_id)},
        expires_delta=access_token_expires
    )
    
    # Calculate token expiration timestamp (in seconds since epoch)
    from datetime import datetime, timezone
    expires_at = int((datetime.now(timezone.utc) + access_token_expires).timestamp())
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "expires_in": int(access_token_expires.total_seconds()),
        "expires_at": expires_at
    }

@router.get("/verify-email", response_model=schemas.UserResponse)
async def verify_email(
    token: str,
    db: Session = Depends(get_db)
):
    """Verify user's email using the verification token"""
    user = db.query(models.User).filter(models.User.verification_token == token).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        )
    
    if user.verification_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token has expired"
        )
    
    # Mark user as verified
    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    
    db.commit()
    db.refresh(user)
    
    return user

@router.get("/me", response_model=schemas.UserResponse)
async def read_users_me(current_user: models.User = Depends(get_current_active_user)):
    """
    Get current user information
    """
    return current_user

@router.post("/logout")
async def logout(
    request: Request,
    current_user: models.User = Depends(security.get_current_active_user)
):
    """
    Logout the current user by invalidating the token.
    Note: For a more robust solution, you might want to implement a token blacklist.
    """
    # In a production environment, you would typically:
    # 1. Add the token to a blacklist (e.g., Redis)
    # 2. Set an appropriate expiration time for the blacklist entry
    # 3. Check the blacklist in the get_current_user dependency
    
    # For now, we'll just return a success message
    return {"message": "Successfully logged out"}

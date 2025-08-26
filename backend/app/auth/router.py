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
        data={"sub": str(user.user_id), "user_email": user.user_email, "user_id": user.user_id},
        expires_delta=access_token_expires
    )
    
    from fastapi import Response
    from datetime import datetime, timezone
    from ..auth.security import COOKIE_DOMAIN, COOKIE_SECURE, COOKIE_HTTP_ONLY, COOKIE_SAME_SITE
    
    # Create response with user data
    response_data = {
        "access_token": access_token,
        "token_type": "bearer",
        "user_email": user.user_email,
        "user_name": user.user_name,
        "user_id": user.user_id,
        "uuid": str(user.uuid) if user.uuid is not None else None,
        "is_verified": user.is_verified,
        "created_on": user.created_on.isoformat() if user.created_on else None,
        "updated_on": user.updated_on.isoformat() if user.updated_on else None,
        "active": user.active
    }
    
    # Create response with JSON data
    from fastapi.responses import JSONResponse
    response = JSONResponse(content=response_data)
    
    # Set HTTP-only cookie with the token
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=COOKIE_HTTP_ONLY,
        max_age=60 * 60 * 24 * 7,  # 7 days in seconds
        expires=datetime.now(timezone.utc) + timedelta(days=7),
        secure=COOKIE_SECURE,
        samesite='None' if COOKIE_SECURE else 'lax',
        domain=COOKIE_DOMAIN if COOKIE_DOMAIN != "localhost" else None,
        path="/"
    )
    
    return response

class LoginForm:
    def __init__(
        self,
        username: str,
        password: str,
    ):
        self.username = username
        self.password = password

@router.post("/login")
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """OAuth2 compatible token login, get an access token for future requests"""
    content_type = request.headers.get("content-type", "")
    
    # Handle both form data and JSON
    if "application/json" in content_type:
        try:
            json_data = await request.json()
            form_data = OAuth2PasswordRequestForm(
                username=json_data.get("username") or json_data.get("user_email"),
                password=json_data.get("password"),
                scope="",
                client_id="",
                client_secret=""
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON data"
            )
    
    user = db.query(models.User).filter(
        (models.User.user_email == form_data.username) | 
        (models.User.user_name == form_data.username)
    ).first()
    
    if not user or not user.check_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in"
        )
    
    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated"
        )
    
    from ..auth.security import COOKIE_DOMAIN, COOKIE_SECURE, COOKIE_HTTP_ONLY, COOKIE_SAME_SITE
    from datetime import datetime, timezone
    from fastapi.responses import JSONResponse

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        # Use user_id as sub for consistent lookups
        data={"sub": str(user.user_id), "user_email": user.user_email, "user_id": user.user_id},
        expires_delta=access_token_expires
    )
    
    expires_at = datetime.now(timezone.utc) + access_token_expires

    # Prepare response data
    response_data = {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "user_id": str(user.user_id),
            "user_email": user.user_email,
            "is_verified": user.is_verified
        },
        "expires_at": expires_at.isoformat()
    }
    
    response = JSONResponse(content=response_data)

    # Set HTTP-only cookie with the token
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=COOKIE_HTTP_ONLY,
        max_age=int(access_token_expires.total_seconds()),
        expires=expires_at,
        secure=COOKIE_SECURE,
        samesite='None' if COOKIE_SECURE else 'lax',
        domain=COOKIE_DOMAIN if COOKIE_DOMAIN != "localhost" else None,
        path="/"
    )

    return response

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

@router.put("/me/name", response_model=schemas.UserResponse)
async def update_user_name(
    payload: schemas.UserUpdateName,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Update the current user's display name."""
    try:
        current_user.user_name = payload.user_name
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
        return current_user
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.put("/me/password")
async def update_user_password(
    payload: schemas.PasswordUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Change current user's password after verifying current password."""
    # Verify current password
    if not current_user.check_password(payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    try:
        current_user.set_password(payload.new_password)
        db.add(current_user)
        db.commit()
        return {"message": "Password updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/logout")
async def logout(
    request: Request,
    current_user: models.User = Depends(security.get_current_active_user)
):
    """
    Logout the current user by clearing authentication cookies.
    """
    from fastapi.responses import JSONResponse
    from datetime import datetime, timezone
    
    # Create response with success message
    response = JSONResponse(content={"message": "Successfully logged out"})
    
    # Clear access token cookie
    response.set_cookie(
        key="access_token",
        value="",
        max_age=0,
        expires=0,  # Expire immediately
        path="/",
        domain=security.COOKIE_DOMAIN if security.IS_PRODUCTION else None,
        secure=security.COOKIE_SECURE,
        httponly=security.COOKIE_HTTP_ONLY,
        samesite=security.COOKIE_SAME_SITE
    )
    
    # Clear refresh token cookie if it exists
    response.set_cookie(
        key="refresh_token",
        value="",
        max_age=0,
        expires=0,  # Expire immediately
        path="/",
        domain=security.COOKIE_DOMAIN if security.IS_PRODUCTION else None,
        secure=security.COOKIE_SECURE,
        httponly=security.COOKIE_HTTP_ONLY,
        samesite=security.COOKIE_SAME_SITE
    )
    
    # In a production environment, you might also want to:
    # 1. Add the token to a blacklist (e.g., Redis)
    # 2. Set an appropriate expiration time for the blacklist entry
    # 3. Check the blacklist in the get_current_user dependency
    
    return response

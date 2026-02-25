from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks, Depends, Response
from starlette.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import timedelta
from urllib.parse import urlparse
from typing import Any, Optional
import os
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from ..database import get_db
from . import models, schemas
from .security import (
    get_password_hash,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_active_user,
    get_current_user,
    COOKIE_DOMAIN,
    COOKIE_SECURE,
    COOKIE_HTTP_ONLY,
    COOKIE_SAME_SITE,
    IS_PRODUCTION
)

router = APIRouter(prefix="/auth", tags=["authentication"])

RESET_TOKEN_TTL_MIN = int(os.getenv("RESET_TOKEN_TTL_MIN", "60"))
EMAIL_TOKEN_TTL_HOURS = int(os.getenv("EMAIL_TOKEN_TTL_HOURS", "48"))
# Prefer FRONTEND_URL for links that should open in the app/website; fall back to APP_BASE_URL; then to local dev.
FRONTEND_URL = (
    os.getenv("FRONTEND_URL")
    or os.getenv("APP_BASE_URL")
    or "http://localhost:3000"
).rstrip('/')

# In production (or Cloud Run), guard against misconfigured values like 0.0.0.0 or localhost
try:
    _fu = FRONTEND_URL
    _host = urlparse(_fu).hostname or ""
    # Detect Cloud Run by presence of service envs
    _is_cloud_run = bool(os.getenv("K_SERVICE") or os.getenv("K_REVISION") or os.getenv("K_CONFIGURATION"))
    if (IS_PRODUCTION or _is_cloud_run) and _host in {"0.0.0.0", "localhost"}:
        FRONTEND_URL = "https://johnify.com"
except Exception:
    # Fail-safe: keep existing FRONTEND_URL
    pass

try:
    print(f"🌐 FRONTEND_URL effective: {FRONTEND_URL}")
except Exception:
    pass

# Redirect handler so emailed links to backend /auth/reset still work.
# This forwards to the frontend app's reset page carrying the token.
@router.get("/reset")
async def reset_password_redirect(token: Optional[str] = None):
    try:
        base = FRONTEND_URL
    except Exception:
        base = "http://localhost:3000"
    target = f"{base}/auth/reset"
    if token:
        target = f"{target}?token={token}"
    return RedirectResponse(url=target, status_code=302)


def _validate_password(password: str) -> list:
    """Validate password against policy and return a list of failed criteria messages.

    Criteria:
    - Min 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    """
    failures = []
    if not isinstance(password, str) or not password:
        return ["Password is required"]
    if len(password) < 8:
        failures.append("At least 8 characters")
    if not any(c.isupper() for c in password):
        failures.append("At least one uppercase letter")
    if not any(c.islower() for c in password):
        failures.append("At least one lowercase letter")
    if not any(c.isdigit() for c in password):
        failures.append("At least one number")
    return failures

def _ensure_password_reset_table(db: Session) -> None:
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                token TEXT NOT NULL,
                expires_on TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                created_on TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token ON public.password_reset_tokens(token);
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

# --- Email verification helpers ---

def _ensure_email_verification_table(db: Session) -> None:
    try:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.email_verification_tokens (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                token TEXT NOT NULL,
                expires_on TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                used_on TIMESTAMP NULL,
                created_on TIMESTAMP DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_email_verification_token ON public.email_verification_tokens(token);
            CREATE INDEX IF NOT EXISTS idx_email_verification_user ON public.email_verification_tokens(user_id);
            
            -- Add used_on column if it doesn't exist
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_name='email_verification_tokens' AND column_name='used_on'
                ) THEN
                    ALTER TABLE public.email_verification_tokens ADD COLUMN used_on TIMESTAMP NULL;
                END IF;
            END $$;
            """
        ))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

def _send_verification_email(to_email: str, verify_link: str) -> None:
    from ..services.email_gmail import GmailEmailSender
    sender = GmailEmailSender()
    subject = "Verify your Johnify email"
    
    # HTML email with a button
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2>Welcome to Johnify!</h2>
        <p>Please confirm your email address by clicking the button below:</p>
        <div style="margin: 25px 0;">
            <a href="{verify_link}" 
               style="background-color: #4CAF50; color: white; padding: 12px 24px; 
                      text-decoration: none; border-radius: 4px; font-weight: bold;
                      display: inline-block; margin: 10px 0;">
                Verify Email
            </a>
        </div>
        <p>Or copy and paste this link into your browser:</p>
        <p style="word-break: break-all; color: #666;">{verify_link}</p>
        <p>This link expires in {EMAIL_TOKEN_TTL_HOURS} hours.</p>
        <p>If you didn't create this account, you can safely ignore this email.</p>
    </div>
    """
    
    # Plain text fallback
    text_content = (
        "Welcome to Johnify!\n\n"
        "Please confirm your email address by clicking the link below:\n"
        f"{verify_link}\n\n"
        f"This link expires in {EMAIL_TOKEN_TTL_HOURS} hours.\n\n"
        "If you didn't create this account, you can ignore this email."
    )
    sender.send_email(to_email, subject, text_content, html_content)

def _send_reset_email(to_email: str, reset_link: str, ttl_minutes: int = RESET_TOKEN_TTL_MIN) -> None:
    """Send a password reset email using GmailEmailSender."""
    from ..services.email_gmail import GmailEmailSender
    sender = GmailEmailSender()
    subject = "Reset your Johnify password"

    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2>Password reset request</h2>
        <p>We received a request to reset your Johnify password. If you made this request, click the button below:</p>
        <div style="margin: 25px 0;">
            <a href="{reset_link}"
               style="background-color: #4CAF50; color: white; padding: 12px 24px;
                      text-decoration: none; border-radius: 4px; font-weight: bold;
                      display: inline-block; margin: 10px 0;">
                Reset Password
            </a>
        </div>
        <p>Or copy and paste this link into your browser:</p>
        <p style="word-break: break-all; color: #666;">{reset_link}</p>
        <p>This link expires in {ttl_minutes} minutes.</p>
        <p>If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    text_content = (
        "Password reset request\n\n"
        "If you requested a password reset, open this link:\n"
        f"{reset_link}\n\n"
        f"This link expires in {ttl_minutes} minutes.\n\n"
        "If you didn't request this, you can ignore this email."
    )

    sender.send_email(to_email, subject, text_content, html_content)

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
    # Validate password and return actionable error details
    pw_failures = _validate_password(user_in.password)
    if pw_failures:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Password does not meet the required criteria",
                "errors": pw_failures,
            },
        )
    
    # Create new user (unverified by default)
    user = models.User(
        user_email=user_in.user_email,
        user_name=user_in.user_name,
        is_verified=False,
    )
    user.set_password(user_in.password)
    
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create verification token row and send email in background
    def _issue_and_send_verification(uid: int, email: str):
        local_db: Session = next(get_db())  # create short-lived session
        try:
            _ensure_email_verification_table(local_db)
            
            # Delete any existing tokens for this user
            local_db.execute(text(
                """
                DELETE FROM public.email_verification_tokens 
                WHERE user_id = :uid
                """
            ), {"uid": int(uid)})
            
            # Create new token
            token = secrets.token_urlsafe(32)
            expires_on = datetime.utcnow() + timedelta(hours=EMAIL_TOKEN_TTL_HOURS)
            
            local_db.execute(text(
                """
                INSERT INTO public.email_verification_tokens (user_id, token, expires_on, used)
                VALUES (:uid, :tok, :exp, FALSE)
                """
            ), {"uid": int(uid), "tok": token, "exp": expires_on})
            local_db.commit()
            
            # Create verification link with full URL pointing to the frontend page
            # Frontend page at /auth/verify-email will call its API to complete verification
            verify_link = f"{FRONTEND_URL}/auth/verify-email?token={token}"
            
            try:
                _send_verification_email(email, verify_link)
                print(f"✅ Verification email sent to {email}")
            except Exception as e:
                print(f"❌ Failed to send verification email to {email}: {str(e)}")
                # Don't fail the registration if email sending fails
        except Exception:
            try:
                local_db.rollback()
            except Exception:
                pass
        finally:
            try:
                local_db.close()
            except Exception:
                pass

    if background_tasks is not None:
        background_tasks.add_task(_issue_and_send_verification, int(user.user_id), user.user_email)
    else:
        _issue_and_send_verification(int(user.user_id), user.user_email)
    
    # Generate access token for immediate login (user remains unverified until clicking the link)
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
    
    # Respect "active" even if stored as a string in DB
    def _is_active(val) -> bool:
        if isinstance(val, bool):
            return val
        if val is None:
            return True
        try:
            return str(val).strip().lower() in {"true", "1", "t", "yes", "y"}
        except Exception:
            return True

    if not _is_active(user.active):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is no longer active. Reach out to customer support at hello@johnify.com"
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

@router.get("/verify-email")
async def verify_email(
    token: str,
    db: Session = Depends(get_db),
    request: Request = None
):
    """Verify user's email using the verification token and redirect to frontend with auth tokens."""
    print(f"🔍 Verifying email with token: {token}")
    _ensure_email_verification_table(db)
    
    try:
        # Start a transaction
        db.begin()
        
        # First, check if token exists and is valid
        token_row = db.execute(text(
            """
            SELECT id, user_id, expires_on, used
            FROM public.email_verification_tokens
            WHERE token = :token
            AND used = FALSE
            AND expires_on > NOW()
            FOR UPDATE  -- Lock the row for update
            """
        ), {"token": token}).fetchone()

        if not token_row:
            print("❌ Token not found, already used, or expired")
            # Check if token exists but is already used or expired
            used_token = db.execute(text(
                """
                SELECT id, user_id, expires_on, used
                FROM public.email_verification_tokens
                WHERE token = :token
                """
            ), {"token": token}).fetchone()
            
            db.rollback()  # Rollback the transaction
            
            if used_token:
                print(f"ℹ️ Token found but used={used_token.used}, expires_on={used_token.expires_on}")
                if used_token.used:
                    error_reason = "already_used"
                elif used_token.expires_on <= datetime.utcnow():
                    error_reason = "expired"
                else:
                    error_reason = "invalid"
            else:
                error_reason = "not_found"
                
            # Prefer building redirect base from incoming request host/proto when available
            try:
                scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme) if request else None
                host = (request.headers.get("x-forwarded-host") or request.headers.get("host")) if request else None
                if scheme and host and host not in {"localhost", "127.0.0.1", "0.0.0.0"}:
                    base = f"{scheme}://{host}"
                else:
                    base = FRONTEND_URL
            except Exception:
                base = FRONTEND_URL
            error_url = f"{base}/auth/verify-email?error={error_reason}"
            return RedirectResponse(url=error_url, status_code=303)

        print(f"✅ Valid token found for user_id: {token_row.user_id}")
        
        # Get the user
        user = db.query(models.User).filter(
            models.User.user_id == token_row.user_id,
            models.User.is_verified == False  # Only verify if not already verified
        ).with_for_update().first()  # Lock the user row
        
        if not user:
            print(f"❌ User not found or already verified for user_id: {token_row.user_id}")
            db.rollback()  # Rollback the transaction
            error_url = f"{FRONTEND_URL}/auth/verify-email?error=user_not_found_or_already_verified"
            return RedirectResponse(url=error_url, status_code=303)

        print(f"✅ User found: {user.user_email}")

        # Mark token as used
        db.execute(text(
            """
            UPDATE public.email_verification_tokens
            SET used = TRUE, used_on = NOW()
            WHERE id = :id
            """
        ), {"id": int(token_row.id)})
        
        # Mark user as verified
        user.is_verified = True
        db.commit()  # Commit the transaction
        print(f"✅ User {user.user_email} verified successfully")

        # Generate JWT tokens with a short expiration
        access_token_expires = timedelta(minutes=15)  # Short-lived token for security
        access_token = create_access_token(
            data={"sub": user.user_email, "user_id": user.user_id},
            expires_delta=access_token_expires
        )
        
        # Build safe frontend base for redirects using incoming host/proto when possible
        try:
            scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme) if request else None
            host = (request.headers.get("x-forwarded-host") or request.headers.get("host")) if request else None
            if scheme and host and host not in {"localhost", "127.0.0.1", "0.0.0.0"}:
                base = f"{scheme}://{host}"
            else:
                base = FRONTEND_URL
        except Exception:
            base = FRONTEND_URL

        # Set cookie with token
        response = RedirectResponse(
            url=f"{base}/preferences",
            status_code=303
        )
        
        # Set secure cookie with token (store bare token without 'Bearer ' prefix for frontend middleware compatibility)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=COOKIE_HTTP_ONLY,
            max_age=60 * 15,  # 15 minutes
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAME_SITE,
            domain=COOKIE_DOMAIN if COOKIE_DOMAIN != 'localhost' else None
        )
        
        print(f"🔑 Set access token cookie for {user.user_email}")
        return response
        
    except Exception as e:
        print(f"❌ Error in verify_email: {str(e)}")
        import traceback
        traceback.print_exc()
        error_url = f"{FRONTEND_URL}/auth/verify-email?error=server_error"
        return RedirectResponse(url=error_url, status_code=303)

@router.post("/verify-email/complete")
async def verify_email_complete(payload: dict, db: Session = Depends(get_db)):
    """Complete email verification for mobile clients and return a normal JWT.

    Request body: { "token": string }
    Response 200: { access_token, token_type, user: { user_id, user_email, is_verified }, expires_at }
    """
    token = (payload or {}).get("token")
    if not token or not isinstance(token, str):
        raise HTTPException(status_code=400, detail="token is required")

    _ensure_email_verification_table(db)
    try:
        # Begin transaction to safely mark token used and user verified
        db.begin()

        row = db.execute(text(
            """
            SELECT id, user_id, expires_on, used
            FROM public.email_verification_tokens
            WHERE token = :token
            FOR UPDATE
            """
        ), {"token": token}).mappings().first()

        if not row:
            db.rollback()
            raise HTTPException(status_code=401, detail="invalid")

        is_used = bool(row.get("used"))
        expires_on = row.get("expires_on")
        # Distinguish already used vs expired for better UX
        if is_used:
            db.rollback()
            raise HTTPException(status_code=401, detail="already_used")
        if expires_on and expires_on <= datetime.utcnow():
            db.rollback()
            raise HTTPException(status_code=401, detail="expired")

        # Fetch user
        user = db.query(models.User).filter(models.User.user_id == int(row["user_id"])) .with_for_update().first()
        if not user:
            db.rollback()
            raise HTTPException(status_code=401, detail="invalid token user")

        # Mark token used and user verified (idempotent safety)
        db.execute(text(
            """
            UPDATE public.email_verification_tokens
            SET used = TRUE, used_on = NOW()
            WHERE id = :id
            """
        ), {"id": int(row["id"])})
        if not user.is_verified:
            user.is_verified = True
            db.add(user)

        db.commit()

        # Issue JWT like normal login (use user_id as sub for consistency)
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user.user_id), "user_email": user.user_email, "user_id": user.user_id},
            expires_delta=access_token_expires,
        )
        expires_at = (datetime.now(timezone.utc) + access_token_expires).isoformat()

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "user_id": str(user.user_id),
                "user_email": user.user_email,
                "is_verified": True,
            },
            "expires_at": expires_at,
        }
    except HTTPException:
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Server error")

@router.post("/resend-verification")
async def resend_verification(
    payload: dict,
    db: Session = Depends(get_db)
):
    """Resend verification email for a given email, if user exists and not verified."""
    try:
        email = (payload or {}).get("user_email")
        if not email:
            raise HTTPException(status_code=400, detail="user_email is required")
        user = db.query(models.User).filter(models.User.user_email == email).first()
        if not user:
            # Avoid email enumeration; respond success
            return {"message": "If the email exists, a verification link has been sent."}
        if user.is_verified:
            return {"message": "Email is already verified."}
        _ensure_email_verification_table(db)
        # Invalidate previous unused tokens for this user (optional best practice)
        db.execute(text(
            """
            UPDATE public.email_verification_tokens
            SET used = TRUE
            WHERE user_id = :uid AND used = FALSE
            """
        ), {"uid": int(user.user_id)})
        token = secrets.token_urlsafe(32)
        expires_on = datetime.utcnow() + timedelta(hours=EMAIL_TOKEN_TTL_HOURS)
        db.execute(text(
            """
            INSERT INTO public.email_verification_tokens (user_id, token, expires_on, used)
            VALUES (:uid, :tok, :exp, FALSE)
            """
        ), {"uid": int(user.user_id), "tok": token, "exp": expires_on})
        db.commit()
        # Send users to the frontend page which will complete verification
        verify_link = f"{FRONTEND_URL}/auth/verify-email?token={token}"
        try:
            _send_verification_email(user.user_email, verify_link)
        except Exception:
            pass
        return {"message": "If the email exists, a verification link has been sent."}
    except HTTPException:
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to resend verification")

@router.get("/me", response_model=schemas.UserResponse)
async def read_users_me(current_user: models.User = Depends(get_current_active_user)):
    """
    Get current user information
    """
    def _is_active(val) -> bool:
        if isinstance(val, bool):
            return val
        if val is None:
            return True
        try:
            return str(val).strip().lower() in {"true", "1", "t", "yes", "y"}
        except Exception:
            return True
    return {
        "user_id": int(getattr(current_user, "user_id", 0) or 0),
        "user_email": getattr(current_user, "user_email", "") or "",
        "user_name": getattr(current_user, "user_name", None) or getattr(current_user, "user_email", ""),
        "profile_pic_url": getattr(current_user, "profile_pic_url", None),
        "is_verified": bool(getattr(current_user, "is_verified", True)),
        "created_on": getattr(current_user, "created_on", None),
        "updated_on": getattr(current_user, "updated_on", None),
        "uuid": getattr(current_user, "uuid", None),
        "active": _is_active(getattr(current_user, "active", True)),
    }

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

        # Normalize response (active -> bool) to satisfy schema
        def _is_active(val) -> bool:
            if isinstance(val, bool):
                return val
            if val is None:
                return True
            try:
                return str(val).strip().lower() in {"true", "1", "t", "yes", "y"}
            except Exception:
                return True

        return {
            "user_id": int(getattr(current_user, "user_id", 0) or 0),
            "user_email": getattr(current_user, "user_email", "") or "",
            "user_name": getattr(current_user, "user_name", None) or getattr(current_user, "user_email", ""),
            "profile_pic_url": getattr(current_user, "profile_pic_url", None),
            "is_verified": bool(getattr(current_user, "is_verified", True)),
            "created_on": getattr(current_user, "created_on", None),
            "updated_on": getattr(current_user, "updated_on", None),
            "uuid": getattr(current_user, "uuid", None),
            "active": _is_active(getattr(current_user, "active", True)),
        }
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
        pw_failures = _validate_password(payload.new_password)
        if pw_failures:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Password does not meet the required criteria",
                    "errors": pw_failures,
                },
            )
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
    current_user: models.User = Depends(get_current_active_user)
):
    """
    Logout the current user by clearing authentication cookies.
    Returns a 200 OK with a success message and redirect URL.
    """
    from fastapi.responses import JSONResponse
    
    # Always return JSON with redirect URL for consistency
    frontend_url = FRONTEND_URL
    response = JSONResponse(
        status_code=200,
        content={
            "message": "Successfully logged out",
            "redirect_url": f"{frontend_url}/signin"
        }
    )
    
    # Clear access token cookie
    response.set_cookie(
        key="access_token",
        value="",
        max_age=0,
        expires=0,  # Expire immediately
        path="/",
        domain=COOKIE_DOMAIN if IS_PRODUCTION else None,
        secure=COOKIE_SECURE,
        httponly=COOKIE_HTTP_ONLY,
        samesite=COOKIE_SAME_SITE
    )
    
    # Clear refresh token cookie if it exists
    response.set_cookie(
        key="refresh_token",
        value="",
        max_age=0,
        expires=0,  # Expire immediately
        path="/",
        domain=COOKIE_DOMAIN if IS_PRODUCTION else None,
        secure=COOKIE_SECURE,
        httponly=COOKIE_HTTP_ONLY,
        samesite=COOKIE_SAME_SITE
    )
    
    # In a production environment, you might also want to:
    # 1. Add the token to a blacklist (e.g., Redis)
    # 2. Set an appropriate expiration time for the blacklist entry
    # 3. Check the blacklist in the get_current_user dependency
    
    return response


@router.post("/me/deactivate")
async def deactivate_account(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Deactivate the current user's account by setting active=false (string-safe) and clear cookies."""
    from fastapi.responses import JSONResponse

    try:
        # Delete related data for this user; commit once at end
        uid = int(current_user.user_id)

        # 1) Delete likes on this user's posts
        try:
            db.execute(text(
                """
                DELETE FROM public.user_posts_likes
                WHERE post_id IN (
                    SELECT post_id FROM public.user_posts WHERE user_id = :uid
                )
                """
            ), {"uid": uid})
        except Exception:
            # continue; cleanup best-effort
            pass

        # 2) Delete user's posts
        try:
            db.execute(text(
                """
                DELETE FROM public.user_posts
                WHERE user_id = :uid
                """
            ), {"uid": uid})
        except Exception:
            pass

        # 3) Delete user preferences
        try:
            db.execute(text(
                """
                DELETE FROM public.user_preferences
                WHERE user_id = :uid
                """
            ), {"uid": uid})
        except Exception:
            pass

        # 4) Delete lites sub-topics then topics (sub-topics have ON DELETE CASCADE but handle explicitly too)
        try:
            db.execute(text(
                """
                DELETE FROM public.lites_sub_topics
                WHERE topic_id IN (
                    SELECT topic_id FROM public.lites_topics WHERE user_id = :uid
                )
                """
            ), {"uid": uid})
        except Exception:
            pass
        try:
            db.execute(text(
                """
                DELETE FROM public.lites_topics
                WHERE user_id = :uid
                """
            ), {"uid": uid})
        except Exception:
            pass

        # 5) Deactivate the user account (soft delete)
        current_user.active = 'false'
        db.add(current_user)
        db.commit()
        db.refresh(current_user)

        # Prepare response
        response = JSONResponse(
            status_code=200,
            content={
                "message": "Account deactivated successfully",
                "user_id": int(current_user.user_id),
            },
        )

        # Clear access token cookie
        response.set_cookie(
            key="access_token",
            value="",
            max_age=0,
            expires=0,
            path="/",
            domain=COOKIE_DOMAIN if IS_PRODUCTION else None,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTP_ONLY,
            samesite=COOKIE_SAME_SITE,
        )

        # Clear refresh token cookie if present
        response.set_cookie(
            key="refresh_token",
            value="",
            max_age=0,
            expires=0,
            path="/",
            domain=COOKIE_DOMAIN if IS_PRODUCTION else None,
            secure=COOKIE_SECURE,
            httponly=COOKIE_HTTP_ONLY,
            samesite=COOKIE_SAME_SITE,
        )

        return response
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to deactivate account")

@router.post("/forgot-password")
async def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db), request: Request = None):
    """Start password reset: create token and email user via Gmail API."""
    # Always respond success to prevent email enumeration, but only send if user exists
    user = db.query(models.User).filter(models.User.user_email == payload.user_email).first()
    resp_obj = {"message": "If the email exists, a reset link has been sent."}
    if user:
        try:
            _ensure_password_reset_table(db)
            # Basic rate limiting and deduplication to prevent repeated emails
            # 1) If an unused, unexpired token exists very recently, reuse it (do not send another email)
            recent_row = db.execute(text(
                """
                SELECT token, created_on
                FROM public.password_reset_tokens
                WHERE user_id = :uid AND used = FALSE AND expires_on > NOW()
                ORDER BY created_on DESC
                LIMIT 1
                """
            ), {"uid": int(user.user_id)}).mappings().first()

            # 2) Cap total number of resets to 3 per hour per user
            hourly_count = db.execute(text(
                """
                SELECT COUNT(*) AS cnt
                FROM public.password_reset_tokens
                WHERE user_id = :uid AND created_on > NOW() - INTERVAL '1 hour'
                """
            ), {"uid": int(user.user_id)}).scalar() or 0

            # Determine requester IP for logging (best-effort)
            try:
                fwd_for = request.headers.get("x-forwarded-for") if request else None
                client_ip = (fwd_for.split(",")[0].strip() if fwd_for else (request.client.host if request and request.client else "unknown"))
            except Exception:
                client_ip = "unknown"

            if recent_row:
                # If the most recent token was created within 15 minutes, do not issue another
                reuse_recent = False
                try:
                    created_on = recent_row.get("created_on")
                    if created_on and (datetime.utcnow() - created_on).total_seconds() <= 15 * 60:
                        reuse_recent = True
                except Exception:
                    pass
                if reuse_recent:
                    try:
                        print(f"[auth] Skipping new reset token: recent valid token exists for {user.user_email} from {client_ip}")
                    except Exception:
                        pass
                    # Do not include debug link to avoid leaking tokens; response stays generic
                    return resp_obj

            if hourly_count >= 3:
                try:
                    print(f"[auth] Rate limit hit: skipping reset email for {user.user_email} from {client_ip} (last hour count={hourly_count})")
                except Exception:
                    pass
                return resp_obj

            # Otherwise, issue a new token and send email
            token = secrets.token_urlsafe(32)
            expires_on = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MIN)
            db.execute(text(
                """
                INSERT INTO public.password_reset_tokens (user_id, token, expires_on, used)
                VALUES (:uid, :tok, :exp, FALSE)
                """
            ), {"uid": int(user.user_id), "tok": token, "exp": expires_on})
            db.commit()
            # Always build reset link to the FRONTEND_URL where the reset UI lives
            base = FRONTEND_URL
            reset_link = f"{base}/auth/reset?token={token}"
            try:
                print(f"[gmail] Sending reset email to {user.user_email} from {client_ip} -> {reset_link}")
                _send_reset_email(user.user_email, reset_link)
            except Exception:
                # Don't expose email errors to client
                pass
            # In non-production, include the reset link to make local testing easier
            try:
                if not IS_PRODUCTION:
                    resp_obj["debug_reset_link"] = reset_link
            except Exception:
                pass
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            # Even on error, do not leak details
    return resp_obj


@router.post("/forgot-password-direct")
async def forgot_password_direct(payload: schemas.ForgotPasswordDirectRequest, db: Session = Depends(get_db)):
    """Directly set a new password if the user email exists.

    This endpoint is intended for simplified flows: it validates the new password
    and updates the user's password when the email exists. Otherwise, returns 404.
    """
    try:
        user = db.query(models.User).filter(models.User.user_email == payload.user_email).first()
        if not user:
            raise HTTPException(status_code=404, detail="Email does not exist")
        # Validate new password
        pw_failures = _validate_password(payload.new_password)
        if pw_failures:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Password does not meet the required criteria",
                    "errors": pw_failures,
                },
            )
        user.set_password(payload.new_password)
        db.add(user)
        db.commit()
        return {"message": "Password updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to update password")


@router.post("/reset-password")
async def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    """Complete password reset using the token."""
    try:
        _ensure_password_reset_table(db)
        row = db.execute(text(
            """
            SELECT id, user_id, expires_on, used
            FROM public.password_reset_tokens
            WHERE token = :tok
            LIMIT 1
            """
        ), {"tok": payload.token}).mappings().first()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired token")
        if bool(row["used"]):
            raise HTTPException(status_code=400, detail="Token already used")
        if row["expires_on"] < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Token expired")

        user = db.query(models.User).filter(models.User.user_id == int(row["user_id"])) .first()
        if not user:
            raise HTTPException(status_code=400, detail="Invalid token user")

        # Update password (with validation)
        pw_failures = _validate_password(payload.new_password)
        if pw_failures:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Password does not meet the required criteria",
                    "errors": pw_failures,
                },
            )
        user.set_password(payload.new_password)
        db.add(user)
        # Mark token used
        db.execute(text(
            """
            UPDATE public.password_reset_tokens
            SET used = TRUE
            WHERE id = :id
            """
        ), {"id": int(row["id"])})
        db.commit()
        return {"message": "Password has been reset successfully"}
    except HTTPException:
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to reset password")

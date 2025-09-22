from datetime import datetime, timedelta
SECURITY_IMPL_VERSION = "auth-security-v2-2025-08-17-1450"
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ..database import get_db
from . import models, schemas

# Configuration
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).resolve().parents[2] / '.env'
load_dotenv(dotenv_path=env_path)

# Get environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

# Get secret key from environment - this must match between frontend and backend
SECRET_KEY = os.getenv("JWT_SECRET") or "12345abcde12345"  # In production, this should be a strong secret
print(f"🔑 Using JWT_SECRET: {SECRET_KEY[:5]}...{SECRET_KEY[-5:]}" if SECRET_KEY else "⚠️  No JWT_SECRET set")

# Token configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Cookie configuration
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "localhost")
COOKIE_SECURE = IS_PRODUCTION
COOKIE_HTTP_ONLY = True
COOKIE_SAME_SITE = "lax" if IS_PRODUCTION else "lax"  # or "none" if you need cross-site cookies

print(f"🔒 Security config - Environment: {ENVIRONMENT}, Secure Cookies: {COOKIE_SECURE}, Domain: {COOKIE_DOMAIN}")
print(f"🧩 Auth security module version: {SECURITY_IMPL_VERSION}")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_token_from_cookie(request: Request) -> Optional[str]:
    # Debug: log incoming cookie header and parsed cookie
    try:
        raw_cookie = request.headers.get('cookie', '')
        if raw_cookie:
            print(f"🍪 Incoming Cookie header: {raw_cookie[:200]}{'...' if len(raw_cookie) > 200 else ''}")
            
        # Try to get token from cookies
        token = request.cookies.get("access_token")
        
        # If not in cookies, check Authorization header as fallback
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1] if len(auth_header.split(" ")) > 1 else None
                print(f"🔑 Found token in Authorization header")
        
        if token:
            # Clean up the token
            token = token.strip()
            
            # Remove surrounding quotes if present
            if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
                token = token[1:-1].strip()
                
            print(f"🔑 Extracted token: {token[:10]}...")
            return token
            
        print("❌ No valid token found in cookies or Authorization header")
        return None
        
    except Exception as e:
        print(f"⚠️  Error processing request cookies/headers: {str(e)}")
        return None

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token with the given data.
    
    Args:
        data: Dictionary containing the JWT claims
        expires_delta: Optional timedelta for token expiration
        
    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),  # Issued at
        "iss": "johnify-backend",  # Issuer
        "aud": "johnify-frontend",  # Audience
        "env": "production" if IS_PRODUCTION else "development"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(
    db: Session = Depends(get_db),
    token_from_header: Optional[str] = Depends(oauth2_scheme),
    token_from_cookie: Optional[str] = Depends(get_token_from_cookie)
):
    print(f"🛂 Enter get_current_user() | {SECURITY_IMPL_VERSION}")
    token = token_from_header or token_from_cookie

    if token is None:
        try:
            auth_hdr = None
            # In FastAPI/Starlette, Request isn't directly here, so log hints only
            # OAuth2PasswordBearer already attempted to parse Authorization header.
            print("❌ No token from header or cookie. Authorization or Cookie missing/invalid.")
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    print(f"🔑 Validating token: {token[:10]}...")  # Log first 10 chars of token
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Ensure token is not empty
        if not token or not isinstance(token, str):
            print("❌ Empty or invalid token provided")
            raise credentials_exception
            
        # Clean and validate token format
        token = token.strip()
        
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token[7:].strip()
        
        # Remove surrounding quotes if present
        if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
            token = token[1:-1].strip()
            
        if not token:
            print("❌ Empty token after cleaning")
            raise credentials_exception
            
        print(f"🔍 Cleaned token: {token[:10]}...")
            
        try:
            # First, get and verify the header
            try:
                unverified_header = jwt.get_unverified_header(token)
                if not unverified_header or 'alg' not in unverified_header:
                    print("❌ Invalid token header")
                    raise credentials_exception
                    
                print(f"🔍 Token algorithm: {unverified_header.get('alg')}")
                
                # Now verify the token with the secret key
                payload = jwt.decode(
                    token=token,
                    key=SECRET_KEY,
                    algorithms=[ALGORITHM],
                    options={
                        "verify_exp": True,
                        "verify_aud": False,
                        "verify_iss": False,
                        "verify_sub": False
                    }
                )
                print(f"✅ Token verified successfully")
                
            except jwt.ExpiredSignatureError:
                print("❌ Token has expired")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            except jwt.JWTError as e:
                print(f"❌ JWT validation error: {str(e)}")
                raise credentials_exception
                
        except Exception as e:
            print(f"❌ Unexpected error during token validation: {str(e)}")
            raise credentials_exception
        
        print(f"✅ Verified token payload: {payload}")

        # Prefer 'sub' as subject; support both email and numeric IDs. Also accept explicit 'user_id'.
        subject = payload.get("sub")
        explicit_user_id = payload.get("user_id")

        if not subject and not explicit_user_id:
            print("❌ No 'sub' or 'user_id' claim in token")
            raise credentials_exception

        user = None

        # Always try email lookup first if sub looks like an email
        user = None
        subj_str = str(subject) if subject is not None else None
        
        # 1. First try email lookup if sub looks like an email
        if subj_str and ('@' in subj_str or any(not ch.isdigit() for ch in subj_str)):
            print(f"🔎 [auth] sub looks like email -> lookup by email: {subj_str}")
            user = db.query(models.User).filter(models.User.user_email == subj_str).first()
            if user:
                print(f"✅ Found user by email: id={user.user_id}")
                return user
        
        # 2. If not found by email and sub is numeric, try user_id
        if not user and subj_str and subj_str.isdigit():
            try:
                uid_int = int(subj_str)
                print(f"🔎 [auth] sub is numeric -> lookup by user_id: {uid_int}")
                user = db.query(models.User).filter(models.User.user_id == uid_int).first()
                if user:
                    print(f"✅ Found user by numeric sub (user_id): {user.user_id}")
                    return user
            except ValueError as ve:
                print(f"⚠️ [auth] Error converting sub to int: {ve}")
        
        # 3. If still not found, try explicit user_id from token if it exists
        if not user and explicit_user_id is not None:
            try:
                uid_int = int(str(explicit_user_id))
                print(f"🔎 [auth] explicit user_id claim provided -> lookup by user_id: {uid_int}")
                user = db.query(models.User).filter(models.User.user_id == uid_int).first()
                if user:
                    print(f"✅ Found user by explicit user_id: {user.user_id}")
                    return user
            except ValueError as ve:
                print(f"⚠️ [auth] explicit user_id claim not an integer: {explicit_user_id}, error: {ve}")

        if not user:
            print(f"❌ User not found with provided token claims. sub={subject}, user_id={explicit_user_id}")
            raise credentials_exception

        print(f"✅ Found user: id={user.user_id}, email={user.user_email}")
        return user
        
    except JWTError as e:
        error_msg = str(e)
        print(f"❌ JWT validation error: {error_msg}")
        print(f"❌ Token: {token}")
        print(f"❌ Using secret key: {SECRET_KEY[:5]}...{SECRET_KEY[-5:] if SECRET_KEY else ''}")
        
        # Check if token is expired
        try:
            # Try to decode without verification to check expiration
            payload = jwt.decode(
                token, 
                options={"verify_signature": False, "verify_exp": True}
            )
            print(f"🔍 Token payload (unverified): {payload}")
            if 'exp' in payload:
                from datetime import datetime
                exp_time = datetime.fromtimestamp(payload['exp'])
                print(f"⏰ Token expired at: {exp_time}")
        except Exception as decode_error:
            print(f"⚠️ Could not decode token for additional info: {decode_error}")
        
        # Provide more helpful error message
        detail = "Invalid or expired token. Please log in again."
        if "expired" in error_msg.lower():
            detail = "Your session has expired. Please log in again."
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        # Any other error during token processing should not 500; treat as auth failure
        print(f"❌ Unexpected auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_verified:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

# Optional variant: returns None when no/invalid token instead of raising 401.
async def get_current_user_optional(
    db: Session = Depends(get_db),
    token_from_header: Optional[str] = Depends(oauth2_scheme),
    token_from_cookie: Optional[str] = Depends(get_token_from_cookie)
):
    try:
        token = token_from_header or token_from_cookie
        if not token:
            return None
        # Reuse core logic from get_current_user but swallow auth failures
        unverified = jwt.get_unverified_claims(token)
        subject = unverified.get("sub")
        explicit_user_id = unverified.get("user_id")
        # Verify token
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": True, "verify_aud": False},
        )
        subject = payload.get("sub")
        explicit_user_id = payload.get("user_id")
        user = None
        subj_str = str(subject) if subject is not None else None
        if subj_str and ('@' in subj_str or any(not ch.isdigit() for ch in subj_str)):
            user = db.query(models.User).filter(models.User.user_email == subj_str).first()
            if user:
                return user
        if not user and subj_str and subj_str.isdigit():
            try:
                uid_int = int(subj_str)
                user = db.query(models.User).filter(models.User.user_id == uid_int).first()
                if user:
                    return user
            except ValueError:
                pass
        if not user and explicit_user_id is not None:
            try:
                uid_int = int(str(explicit_user_id))
                user = db.query(models.User).filter(models.User.user_id == uid_int).first()
                if user:
                    return user
            except ValueError:
                pass
        return None
    except Exception:
        # On any error, treat as unauthenticated for optional flow
        return None

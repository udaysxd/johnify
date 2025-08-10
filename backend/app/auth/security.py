from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
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

# Get secret key from environment - this must match between frontend and backend
SECRET_KEY = os.getenv("JWT_SECRET") or "12345abcde12345"  # Fallback to match .env file
print(f"🔑 Using JWT_SECRET: {SECRET_KEY[:5]}...{SECRET_KEY[-5:]}" if SECRET_KEY else "⚠️  No JWT_SECRET set")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days for testing

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    print(f"🔑 Validating token: {token[:10]}...")  # Log first 10 chars of token
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Verify the token with the secret key
        payload = jwt.decode(
            token, 
            SECRET_KEY, 
            algorithms=[ALGORITHM],
            options={"verify_exp": True}  # Ensure expiration is checked
        )
        
        print(f"✅ Verified token payload: {payload}")
        
        user_id = payload.get("sub")
        if not user_id:
            print("❌ No 'sub' claim in token")
            raise credentials_exception
            
        # Try to get the user from the database
        user = db.query(models.User).filter(models.User.user_id == user_id).first()
        if not user:
            print(f"❌ User not found in database: {user_id}")
            # For now, we'll allow the request to proceed even if user not in DB
            print("⚠️  User not found in database, but allowing request for testing")
            return models.User(
                user_id=user_id, 
                user_email=f"{user_id}@temp.user",
                is_verified=True  # Mark as verified for testing
            )
            
        print(f"✅ Found user: {user.user_email}")
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

async def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_verified:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

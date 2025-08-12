from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Any

from ..auth.security import get_current_active_user
from ..database import get_db
from . import schemas
from ..auth import models

router = APIRouter()

@router.get("/me", response_model=schemas.UserResponse)
async def read_users_me(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> Any:
    """
    Get current user information
    """
    # Return the current user's information
    return current_user

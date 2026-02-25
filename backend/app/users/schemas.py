from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from uuid import UUID

class UserBase(BaseModel):
    user_email: EmailStr
    user_name: str

class UserResponse(UserBase):
    user_id: int
    uuid: UUID
    is_verified: bool
    created_on: datetime
    updated_on: datetime
    active: bool
    # Optional profile fields
    profile_pic_url: Optional[str] = None
    bio: Optional[str] = None
    link: Optional[str] = None
    user_uid: Optional[str] = None

    class Config:
        orm_mode = True


class UserProfileUpdate(BaseModel):
    bio: Optional[str] = None
    link: Optional[str] = None
    user_uid: Optional[str] = None

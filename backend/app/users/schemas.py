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

    class Config:
        orm_mode = True

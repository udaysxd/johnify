from datetime import datetime, time, timedelta
from uuid import uuid4
from sqlalchemy import Column, Integer, String, DateTime, Time, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import bcrypt
import secrets

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'public'}
    
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    user_name = Column(String(100), nullable=True)
    user_email = Column(String(255), nullable=True)
    user_password = Column(String(255), nullable=True)
    active = Column(String(50), default='true', nullable=True)
    is_verified = Column(Boolean, default=False, nullable=True)
    verification_token = Column(String(100), nullable=True)
    created_on = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_on = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)
    uuid = Column(UUID(as_uuid=True), default=uuid4, nullable=False, unique=True)
    
    # Relationship to user_posts
    posts = relationship("UserPost", back_populates="user")
    
    def set_password(self, password: str):
        """Hash and set the user's password"""
        salt = bcrypt.gensalt()
        self.user_password = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def check_password(self, password: str) -> bool:
        """Check if the provided password matches the stored hash"""
        return bcrypt.checkpw(password.encode('utf-8'), self.user_password.encode('utf-8'))
    
    def generate_verification_token(self, expires_in_hours: int = 24) -> str:
        """Generate a verification token that expires in the specified hours"""
        self.verification_token = secrets.token_urlsafe(32)
        self.verification_token_expires = datetime.utcnow() + timedelta(hours=expires_in_hours)
        return self.verification_token


class UserPost(Base):
    __tablename__ = 'user_posts'
    __table_args__ = {'schema': 'public'}
    
    post_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('public.users.user_id'), nullable=True)
    post_path = Column(String(500), nullable=True)
    created_on = Column(DateTime, default=datetime.utcnow, nullable=True)
    post_topic = Column(String(255), nullable=True)
    
    # Relationship to user
    user = relationship("User", back_populates="posts")
    
    # Relationship to user
    user = relationship("User", back_populates="posts")

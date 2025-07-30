import os
import sys
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Add the backend directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.database import Base, get_db
from backend.app.auth import models

# Database URL - update this if your database URL is different
DATABASE_URL = "sqlite:///./test.db"

# Create a new SQLAlchemy engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_videos():
    db = SessionLocal()
    try:
        # Get all user posts
        posts = db.query(models.UserPost).all()
        
        print(f"Found {len(posts)} posts in the database:")
        for post in posts:
            print(f"\nPost ID: {post.post_id}")
            print(f"User ID: {post.user_id}")
            print(f"Topic: {post.post_topic}")
            print(f"Path: {post.post_path}")
            print(f"Created: {post.created_on}")
            
            # Check if the video file exists
            if post.post_path:
                video_path = os.path.join("generated", post.post_path)
                video_file = os.path.join(video_path, f"{post.post_topic}_explanation.mp4" if post.post_topic else "final_video.mp4")
                thumbnail_file = os.path.join(video_path, "thumbnail.jpg")
                
                print(f"\nChecking files for post {post.post_id}:")
                print(f"Video path: {video_file}")
                print(f"Exists: {os.path.exists(video_file)}")
                print(f"Thumbnail: {thumbnail_file}")
                print(f"Exists: {os.path.exists(thumbnail_file)}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_videos()

import os
import sys
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Add the backend directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Try to import the database models
try:
    from backend.app.database import Base, get_db
    from backend.app.auth import models
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please make sure you're running this from the project root directory.")
    sys.exit(1)

def list_videos():
    # Try to get database URL from environment or use default SQLite
    db_url = os.getenv("DATABASE_URL", "sqlite:///./test.db")
    print(f"Using database: {db_url}")
    
    # Create SQLAlchemy engine
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if UserPost table exists
        if not engine.dialect.has_table(engine, 'user_posts'):
            print("Error: 'user_posts' table does not exist in the database.")
            return
            
        # Get all user posts
        posts = db.query(models.UserPost).all()
        
        if not posts:
            print("No video posts found in the database.")
            return
            
        print(f"\nFound {len(posts)} video posts in the database:")
        print("-" * 80)
        
        for i, post in enumerate(posts, 1):
            print(f"\n[{i}] Post ID: {post.post_id}")
            print(f"   User ID: {post.user_id}")
            print(f"   Topic: {post.post_topic or 'No topic'}")
            print(f"   Path: {post.post_path or 'No path'}")
            print(f"   Created: {post.created_on}")
            
            # Check if the video file exists
            if post.post_path:
                video_dir = os.path.join("generated", post.post_path)
                video_file = os.path.join(video_dir, f"{post.post_topic}_explanation.mp4" if post.post_topic else "final_video.mp4")
                thumbnail_file = os.path.join(video_dir, "thumbnail.jpg")
                
                print(f"\n   Checking files:")
                print(f"   - Video: {video_file}")
                print(f"     Exists: {os.path.exists(video_file)}")
                print(f"   - Thumbnail: {thumbnail_file}")
                print(f"     Exists: {os.path.exists(thumbnail_file)}")
                
                # If files don't exist, check for any video files in the directory
                if not os.path.exists(video_file) and os.path.exists(video_dir):
                    print("\n   Looking for video files in the directory:")
                    for root, _, files in os.walk(video_dir):
                        for file in files:
                            if file.endswith(('.mp4', '.mov', '.avi', '.mkv')):
                                print(f"   - Found video: {os.path.join(root, file)}")
                        
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    list_videos()

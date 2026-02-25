from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
import os

def setup_cors(app):
    """
    Configure CORS middleware with security best practices
    """
    # List of allowed origins - update these with your mobile app domains
    allowed_origins = [
        "http://localhost:3000",  # Web frontend
        "http://localhost:19006",  # Expo web
        "exp://*",
        "http://*",
        "https://*"
    ]
    
    # Environment variable override for production
    if os.getenv('ALLOWED_ORIGINS'):
        allowed_origins.extend(os.getenv('ALLOWED_ORIGINS').split(','))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Type", "Set-Cookie", "Authorization"],
        max_age=600,  # 10 minutes
    )

    @app.middleware("http")
    async def add_cors_header(request: Request, call_next):
        """
        Add CORS headers to all responses
        """
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response

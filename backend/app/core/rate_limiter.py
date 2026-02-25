from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os

class RateLimiter:
    def __init__(self, max_requests: int = 3000, window: int = 60):
        """
        Initialize rate limiter
        
        Args:
            max_requests: Maximum number of requests allowed in the time window
            window: Time window in seconds
        """
        self.max_requests = int(os.getenv('RATE_LIMIT_MAX_REQUESTS', max_requests))
        self.window = int(os.getenv('RATE_LIMIT_WINDOW', window))
        self.requests: Dict[str, List[datetime]] = {}
        self.whitelist = self._get_whitelist()
        
    def _get_whitelist(self) -> set:
        """Get whitelisted IPs from environment variable"""
        whitelist = os.getenv('RATE_LIMIT_WHITELIST', '')
        return set(ip.strip() for ip in whitelist.split(',') if ip.strip())
        
    def is_rate_limited(self, client_ip: str) -> Optional[Dict]:
        """
        Check if the client has exceeded the rate limit
        
        Returns:
            Dict with retry_after if rate limited, None otherwise
        """
        if client_ip in self.whitelist:
            return None
            
        now = datetime.utcnow()
        
        # Remove old timestamps outside the current window
        if client_ip in self.requests:
            self.requests[client_ip] = [
                ts for ts in self.requests[client_ip]
                if now - ts < timedelta(seconds=self.window)
            ]
        else:
            self.requests[client_ip] = []
        
        # Check if rate limit exceeded
        if len(self.requests[client_ip]) >= self.max_requests:
            oldest_request = min(self.requests[client_ip])
            retry_after = (oldest_request + timedelta(seconds=self.window) - now).seconds
            return {
                "retry_after": retry_after,
                "limit": self.max_requests,
                "remaining": 0
            }
            
        # Add current request
        self.requests[client_ip].append(now)
        return None

# Global rate limiter instance
rate_limiter = RateLimiter()

def get_client_ip(request: Request) -> str:
    """Get client IP address from request"""
    if request.client is None:
        return "unknown"
    
    # Get IP from X-Forwarded-For if behind a proxy
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.client.host or "unknown"

async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware"""
    # Skip rate limiting for certain paths
    if request.url.path.startswith(('/docs', '/redoc', '/openapi.json')):
        return await call_next(request)
    
    client_ip = get_client_ip(request)
    rate_limit = rate_limiter.is_rate_limited(client_ip)
    
    if rate_limit:
        response = JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Too many requests",
                "retry_after": rate_limit["retry_after"],
                "limit": rate_limit["limit"],
                "remaining": rate_limit["remaining"]
            }
        )
        response.headers["Retry-After"] = str(rate_limit["retry_after"])
        response.headers["X-RateLimit-Limit"] = str(rate_limit["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_limit["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_limit["retry_after"])
        return response
        
    response = await call_next(request)
    
    # Add rate limit headers to all responses
    response.headers["X-RateLimit-Limit"] = str(rate_limiter.max_requests)
    response.headers["X-RateLimit-Remaining"] = str(
        max(0, rate_limiter.max_requests - len(rate_limiter.requests.get(client_ip, [])))
    )
    
    return response

import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';

// Define types for our session and API response
interface SessionWithToken {
  accessToken?: string;
  [key: string]: unknown;
}

interface VideoItem {
  id: string;
  title: string;
  url: string;
  thumbnail?: string;
  duration?: number;
  createdAt: string;
  [key: string]: unknown;
}

// Get the secret from environment variables
const secret = process.env.NEXTAUTH_SECRET;
if (!secret) {
  console.error('NEXTAUTH_SECRET is not set in environment variables');
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Helper function to handle errors
function createErrorResponse(message: string, status: number, details?: unknown): NextResponse {
  console.error(`[API Error] ${message}`, details || '');
  
  // Create the response object without spread
  const responseBody: { error: string; details?: unknown } = { error: message };
  if (details !== undefined) {
    responseBody.details = details;
  }
  
  return new NextResponse(
    JSON.stringify(responseBody), 
    { 
      status,
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );
}

export async function GET(req: Request): Promise<NextResponse> {
  try {
    // Verify the token from the Authorization header
    const authHeader = req.headers.get('authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return createErrorResponse('No token provided', 401);
    }
    
    if (!secret) {
      return createErrorResponse('Server configuration error', 500, 'Authentication is not properly configured');
    }
    
    const session = await getToken({ req, secret }) as SessionWithToken | null;
    
    if (!session) {
      return createErrorResponse('Unauthorized', 401);
    }

    const accessToken = session.accessToken;
    if (!accessToken) {
      return createErrorResponse('No access token found in session', 401);
    }

    try {
      // Fetch user's videos from the backend
      const response = await fetch(`${API_BASE_URL}/api/videos/my-videos`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Accept': 'application/json',
        },
        cache: 'no-store',
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        console.error('Error fetching videos from backend:', error);
        return createErrorResponse(
          'Failed to fetch videos', 
          response.status, 
          error.detail || 'Backend returned an error'
        );
      }

      const videos = await response.json();
      
      // Transform the backend response to match the frontend's expected format
      const transformedVideos = Array.isArray(videos) ? videos.map(video => ({
        id: video.id || '',
        title: video.title || 'Untitled Video',
        thumbnailUrl: video.thumbnail_url || '',
        videoUrl: video.video_url || '',
        createdAt: video.created_at || new Date().toISOString(),
        status: 'completed' // Default status since the backend doesn't provide it
      })) : [];
      
      return NextResponse.json(transformedVideos);
      
    } catch (error) {
      console.error('Error in videos API route:', error);
      return createErrorResponse(
        'Failed to fetch videos', 
        500, 
        error instanceof Error ? error.message : 'Unknown error'
      );
    }
    
  } catch (error) {
    console.error('Unexpected error in videos API route:', error);
    return createErrorResponse(
      'Internal server error', 
      500, 
      error instanceof Error ? error.message : 'Unknown error'
    );
  }
}

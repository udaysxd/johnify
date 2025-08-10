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
    if (!secret) {
      return createErrorResponse('Server configuration error', 500, 'Authentication is not properly configured');
    }
    
    // Get the session token from cookies
    const session = await getToken({ req, secret }) as SessionWithToken | null;
    const accessToken = session?.accessToken;
    
    if (!accessToken) {
      console.error('No access token in session');
      return createErrorResponse('Unauthorized - No session token', 401);
    }

    try {
      // Call the backend API with the user's access token
      const backendResponse = await fetch(`${API_BASE_URL}/api/videos/my-videos`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });

      if (!backendResponse.ok) {
        const errorData = await backendResponse.json().catch(() => ({}));
        console.error('Error fetching videos from backend:', errorData);
        return createErrorResponse(
          errorData.detail || 'Failed to fetch videos',
          backendResponse.status
        );
      }

      const data = await backendResponse.json();
      
      // Define the expected shape of video data from the backend
      interface BackendVideoItem {
        id?: string;
        title?: string;
        url?: string;
        thumbnail?: string;
        duration?: number;
        created_at?: string;
      }
      
      // Transform the response to match the expected format
      const videos: VideoItem[] = Array.isArray(data) ? data.map((video: BackendVideoItem) => ({
        id: video.id || '',
        title: video.title || 'Untitled Video',
        url: video.url || '',
        thumbnail: video.thumbnail || '',
        duration: video.duration || 0,
        createdAt: video.created_at || new Date().toISOString(),
      })) : [];
      
      return NextResponse.json(videos);
      
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

import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  try {
    const { url } = await request.json();
    
    if (!url) {
      return NextResponse.json(
        { error: 'Missing URL parameter' },
        { status: 400 }
      );
    }

    console.log('Debugging video URL:', url);
    
    // Try a HEAD request first to check if the URL is accessible
    const headResponse = await fetch(url, { 
      method: 'HEAD',
      cache: 'no-store',
      redirect: 'follow'
    });

    const headResult = {
      status: headResponse.status,
      statusText: headResponse.statusText,
      headers: Object.fromEntries(headResponse.headers.entries()),
      ok: headResponse.ok,
      redirected: headResponse.redirected,
      type: headResponse.type,
      url: headResponse.url,
    };

    console.log('HEAD request result:', headResult);

    // If HEAD request fails, try a GET request to get more details
    let getResult = null;
    if (!headResponse.ok) {
      console.log('HEAD request failed, trying GET request...');
      try {
        const getResponse = await fetch(url, { 
          cache: 'no-store',
          redirect: 'follow'
        });
        
        const responseText = await getResponse.text();
        
        getResult = {
          status: getResponse.status,
          statusText: getResponse.statusText,
          headers: Object.fromEntries(getResponse.headers.entries()),
          ok: getResponse.ok,
          redirected: getResponse.redirected,
          type: getResponse.type,
          url: getResponse.url,
          bodyPreview: responseText.substring(0, 500), // First 500 chars of response
        };

        console.log('GET request result:', getResult);
      } catch (getError) {
        console.error('GET request failed:', getError);
        getResult = { error: String(getError) };
      }
    }

    return NextResponse.json({
      url,
      head: headResult,
      get: getResult,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('Debug error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to debug video URL',
        message: error instanceof Error ? error.message : String(error)
      },
      { status: 500 }
    );
  }
}

// Enable CORS preflight
export async function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    },
  });
}

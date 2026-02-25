import { NextRequest, NextResponse } from "next/server";

function getBackendUrl() {
  const isProduction = process.env.NODE_ENV === 'production';
  const envUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (envUrl && envUrl.trim()) return envUrl;
  if (isProduction) return 'https://johnify-backend-873155673176.us-central1.run.app';
  return 'http://localhost:8000';
}

export async function PUT(req: NextRequest) {
  try {
    const url = `${getBackendUrl()}/api/users/me/profile`;
    const init: RequestInit = {
      method: "PUT",
      // Forward JSON body and auth cookie
      headers: {
        "Content-Type": req.headers.get("content-type") || "application/json",
        Accept: req.headers.get("accept") || "application/json",
        Cookie: req.headers.get("cookie") || "",
        Authorization: req.headers.get("authorization") || req.headers.get("Authorization") || "",
      },
      body: await req.text(),
      // Do not forward credentials mode; cookies are sent via header above
    };
    const resp = await fetch(url, init);

    // Pass through status and body
    const contentType = resp.headers.get("content-type") || "application/json";
    const bodyText = await resp.text();
    return new NextResponse(bodyText, {
      status: resp.status,
      headers: {
        "content-type": contentType,
      },
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Proxy error";
    return NextResponse.json({ detail: msg }, { status: 500 });
  }
}


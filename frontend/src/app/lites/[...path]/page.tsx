import LiteVideoClient from "./LiteVideoClient";

function getBackendBase(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || "http://localhost:8000";
}

function buildVideoUrls(pathParts: string[]): { videoUrl: string; thumbnailUrl: string; relPath: string } {
  const relPath = pathParts.join("/");
  const base = getBackendBase().replace(/\/$/, "");
  const videoUrl = `${base}/videos/${relPath}`;
  const dir = relPath.split("/").slice(0, -1).join("/");
  const thumbnailUrl = dir ? `${base}/videos/${dir}/thumbnail.jpg` : `${base}/videos/thumbnail.jpg`;
  return { videoUrl, thumbnailUrl, relPath };
}

type PageProps = {
  params: { path: string[] };
  searchParams: { [key: string]: string | string[] | undefined };
};

export default async function LiteVideoPage({
  params,
  searchParams,
}: {
  params: Promise<{ path: string[] }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  // In Next.js 15, we need to await both params and searchParams
  const resolvedParams = await params;
  const resolvedSearch = await searchParams;
  
  const pathParts = resolvedParams.path || [];
  const tParam = typeof resolvedSearch.t === 'string' ? resolvedSearch.t : undefined;
  const { videoUrl, thumbnailUrl, relPath } = buildVideoUrls(pathParts);
  const title = tParam || (pathParts[pathParts.length - 1] || "Lite Video");
  const canonical = `https://johnify.com/lites/${relPath}`;

  return (
    <LiteVideoClient
      title={title}
      canonical={canonical}
      videoUrl={videoUrl}
      thumbnailUrl={thumbnailUrl}
    />
  );
}

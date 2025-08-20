/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  images: {
    unoptimized: true, // Disable image optimization for static export
  },
  // Environment variables are automatically loaded from:
  // - .env.local (for local development)
  // - .env.production (for production build)
  // - Environment variables set in Cloud Run
  env: {
    // This ensures the variable is available at build time
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL,
  },
  // Configure server external packages (moved from experimental)
  serverExternalPackages: ['@prisma/client'],
  // Optional: Add a trailing slash to all paths
  trailingSlash: true,
  // Note: Avoid catch-all API rewrites so local App Router API routes
  // (e.g., /api/quiz, /api/learn) are handled by Next.js instead of being
  // proxied to the backend.
  async redirects() {
    return [
      {
        source: '/home',
        destination: '/my-learning',
        permanent: true,
      },
      {
        source: '/home/',
        destination: '/my-learning/',
        permanent: true,
      },
    ];
  },
}

module.exports = nextConfig

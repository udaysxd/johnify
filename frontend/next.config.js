/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  images: {
    unoptimized: true, // Disable image optimization for static export
  },
  // Environment variables
  env: {
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000',
  },
  // Disable static export since we have API routes
  // output: 'export', // Commented out to disable static export
  // Optional: Add a trailing slash to all paths
  trailingSlash: true,
  // Configure API routes to work with standalone output
  async rewrites() {
    return [
      // Don't rewrite NextAuth.js API routes
      {
        source: '/api/auth/:path*',
        destination: '/api/auth/:path*',
      },
      // Rewrite other API requests to the backend
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/:path*`,
      },
    ];
  },
}

module.exports = nextConfig

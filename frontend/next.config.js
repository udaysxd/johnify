/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
        os: false,
      };
    }
    return config;
  },
  reactStrictMode: true,
  experimental: {
    // Enable server actions if needed
    serverActions: true,
  },
  // Add environment variables that should be available on the client
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },
  // Ensure proper handling of API routes
  async rewrites() {
    return [
      // Don't rewrite API auth routes
      {
        source: '/api/auth/:path*',
        destination: '/api/auth/:path*',
      },
      // Rewrite other API routes to the backend
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;

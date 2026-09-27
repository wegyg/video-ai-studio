/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    // Proxy API + generated media to the FastAPI backend.
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;

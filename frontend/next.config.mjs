/** @type {import('next').NextConfig} */

// Where the FastAPI backend lives. Rewrites are baked in at build time, so this
// has to be set when the build runs, not just at runtime.
const BACKEND = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;

// On a hosted build, falling back to localhost would produce a site whose every
// API call fails with nothing explaining why. Fail the build instead and say so.
if (!BACKEND && process.env.VERCEL) {
  throw new Error(
    "BACKEND_URL is not set. Add it in Vercel under Settings -> Environment " +
      "Variables, pointing at your backend, e.g. https://your-api.onrender.com",
  );
}

const target = BACKEND || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    // Proxy API + generated media to the FastAPI backend. Because the browser
    // only ever talks to this site's own origin, no CORS setup is needed.
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
};

export default nextConfig;

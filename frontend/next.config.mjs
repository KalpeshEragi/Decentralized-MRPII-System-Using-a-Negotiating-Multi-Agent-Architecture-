/** @type {import('next').NextConfig} */
// The browser calls /backend/... on the panel's own address; Next.js forwards it to the FastAPI backend, so the
// panel works on any port without cross-origin setup.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${BACKEND_URL}/:path*` }];
  },
};
export default nextConfig;

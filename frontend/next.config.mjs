/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    if (process.env.VERCEL === "1") {
      return [];
    }

    return [
      {
        source: "/api/:path*",
        destination: `${process.env.DRAGONISLES_API_URL || "http://127.0.0.1:8125"}/api/:path*`
      }
    ];
  }
};

export default nextConfig;

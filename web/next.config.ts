import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable strict mode double-rendering in dev
  reactStrictMode: false,
  // Enable standalone output for Docker deployments
  output: "standalone",
};

export default nextConfig;

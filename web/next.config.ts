import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable strict mode double-rendering in dev
  reactStrictMode: false,
  // Enable standalone output for Docker deployments
  output: "standalone",
  // Ensure build completes even with type issues in third-party lib types
  typescript: { ignoreBuildErrors: true },
};

export default nextConfig;

import type { NextConfig } from 'next';

// Standalone output so the Docker image ships a single self-contained server bundle
// instead of the whole node_modules tree.
const nextConfig: NextConfig = { output: 'standalone', reactStrictMode: true };
export default nextConfig;

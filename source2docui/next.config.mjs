/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  turbopack: {
    root: process.cwd(),
  },
  // Memory optimizations for resource-constrained environments
  experimental: {
    webpackBuildWorker: true,
    webpackMemoryOptimizations: true,
  },
}

export default nextConfig

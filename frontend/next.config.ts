import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // Allow images from localhost (for future avatar/icon needs)
  images: { remotePatterns: [{ hostname: "localhost" }] },
}

export default nextConfig

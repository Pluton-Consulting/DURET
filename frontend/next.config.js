/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Lint = tâche dev/CI, pas nécessaire au build de prod → évite d'embarquer le
  // toolchain eslint (et ses vulnérabilités transitives) dans le build Docker.
  eslint: { ignoreDuringBuilds: true },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },
}

module.exports = nextConfig

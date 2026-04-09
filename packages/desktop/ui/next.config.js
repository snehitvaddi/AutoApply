/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — produces plain HTML/CSS/JS in /out
  // No Node.js server needed at runtime; FastAPI serves these files
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

module.exports = nextConfig;

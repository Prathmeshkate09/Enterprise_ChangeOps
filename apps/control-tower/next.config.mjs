import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(currentDirectory, "../.."),
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    serverActions: {
      // The authenticated `gcloud run services proxy` forwards the browser's
      // local origin while Cloud Run retains its managed host.
      allowedOrigins: ["127.0.0.1:3000", "localhost:3000"],
    },
  },
};

export default nextConfig;

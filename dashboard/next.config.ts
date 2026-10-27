import type { NextConfig } from "next";

// Static export for Firebase Hosting (project ozi-care): `npm run build`
// writes plain HTML/JS to out/, served as-is. Everything talks to the API
// from the browser, so no server runtime is needed.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;

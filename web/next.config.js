const { thinHubRedirects } = require("./hub-redirects.cjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: false
  },
  async redirects() {
    return thinHubRedirects;
  }
};

module.exports = nextConfig;


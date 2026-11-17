// Hubs with reviewed guides, but fewer than MIN_INDEXABLE_HUB (3).
// A 301 sends the old URL to the guides index. Empty categories still 404.
module.exports = {
  thinHubRedirects: [
    { source: "/blog/formats", destination: "/blog", statusCode: 301 },
    { source: "/blog/strategy", destination: "/blog", statusCode: 301 },
  ],
};

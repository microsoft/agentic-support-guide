// Serves the built SPA and forwards /api/* to the API.
//
// This exists so the API key never reaches the browser. A React bundle cannot
// hold a secret - anything it uses is visible in DevTools - so the key is
// attached here, server-side, where the client cannot read or override it.
//
// Deliberately dependency-free. It handles exactly two things (static files
// and a JSON reverse proxy to one known upstream), and the node: built-ins
// cover both. Learners read this file; an express + http-proxy-middleware
// tree would be more to audit and more for Oryx to build.

import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.PORT ?? 8080);
const API_ORIGIN = (process.env.API_ORIGIN ?? "").replace(/\/$/, "");
const API_KEY = process.env.API_SHARED_KEY ?? "";
const ROOT = resolve(fileURLToPath(new URL("./dist", import.meta.url)));

// Longer than the API's 120s orchestration budget, so a slow but legitimate
// four-agent request is not cut off by the proxy instead of the API.
const UPSTREAM_TIMEOUT_MS = 180_000;

// Nothing this app sends is large. A saved plan carries a full recommendation,
// hence kilobytes rather than bytes, but not megabytes.
const MAX_BODY_BYTES = 256 * 1024;

// The front door is anonymous, so this is the only thing standing between a
// stranger with the URL and the model quota. Deliberately enforced here and
// not in the API, so that a caller holding the shared key is not throttled by
// a limit meant for the anonymous front door.
//
// Per instance and in memory. One B1 instance serves this app, so that is the
// whole picture; scaling out would multiply the effective limit by the
// instance count. Raise the limits for a demo where you click repeatedly, or
// when a room of people shares one outbound address.
const WINDOW_MS = 60_000;
const LIMIT_PER_IP = Number(process.env.RATE_LIMIT_PER_MIN ?? 30);
const EXPENSIVE_LIMIT_PER_IP = Number(process.env.RECOMMENDATION_LIMIT_PER_MIN ?? 10);
const MAX_CONCURRENT_EXPENSIVE = Number(process.env.MAX_CONCURRENT_RECOMMENDATIONS ?? 4);
// Each of these is four model calls.
const EXPENSIVE = /^\/api\/recommendations\//;

const hits = new Map();
let activeExpensive = 0;

function clientIp(req) {
  // App Service puts the real address first; the socket is the load balancer.
  const forwarded = (req.headers["x-forwarded-for"] ?? "").split(",")[0].trim();
  return forwarded || req.socket.remoteAddress || "unknown";
}

function overRateLimit(req, pathname) {
  const now = Date.now();
  const ip = clientIp(req);
  const seen = (hits.get(ip) ?? []).filter((t) => now - t < WINDOW_MS);
  seen.push(now);
  hits.set(ip, seen);

  // Unbounded otherwise: every distinct source address would be retained.
  // Drop entries once their timestamps have all aged out, rather than only
  // when every timestamp is old, which never fires for a returning caller.
  if (hits.size > 5000) {
    for (const [key, times] of hits) {
      const live = times.filter((t) => now - t < WINDOW_MS);
      if (live.length === 0) hits.delete(key);
      else hits.set(key, live);
    }
  }

  const limit = EXPENSIVE.test(pathname) ? EXPENSIVE_LIMIT_PER_IP : LIMIT_PER_IP;
  return seen.length > limit;
}

// Connection-scoped headers must not be forwarded. Passing them through is how
// a proxy and its upstream end up disagreeing about message framing.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
};

function send(res, status, body, headers = {}) {
  setSecurityHeaders(res);
  res.writeHead(status, { "content-type": "text/plain; charset=utf-8", ...headers });
  res.end(body);
}

function json(res, status, payload) {
  send(res, status, JSON.stringify(payload), {
    "content-type": "application/json; charset=utf-8",
  });
}

function setSecurityHeaders(res) {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  // The SPA loads its own hashed bundle and talks only to this origin.
  // 'unsafe-inline' for styles because the bundler injects a style element.
  res.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
      "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
  );
}

function proxy(req, res, url, expensive) {
  const upstream = new URL(API_ORIGIN + url.pathname + url.search);
  const headers = {};
  for (const [name, value] of Object.entries(req.headers)) {
    const key = name.toLowerCase();
    // `host` must name the upstream, not us. Dropping the inbound key is what
    // stops a client supplying its own and choosing its own credential.
    if (HOP_BY_HOP.has(key) || key === "host" || key === "x-api-key") continue;
    headers[name] = value;
  }
  headers.host = upstream.host;
  if (API_KEY) headers["x-api-key"] = API_KEY;

  let released = false;
  const release = () => {
    if (expensive && !released) {
      released = true;
      activeExpensive -= 1;
    }
  };

  const call = upstream.protocol === "https:" ? httpsRequest : httpRequest;
  const forwarded = call(
    upstream,
    { method: req.method, headers, timeout: UPSTREAM_TIMEOUT_MS },
    (upstreamRes) => {
      const out = {};
      for (const [name, value] of Object.entries(upstreamRes.headers)) {
        if (!HOP_BY_HOP.has(name.toLowerCase())) out[name] = value;
      }
      setSecurityHeaders(res);
      res.writeHead(upstreamRes.statusCode ?? 502, out);
      upstreamRes.pipe(res);
      upstreamRes.on("end", release);
      upstreamRes.on("error", release);
    },
  );

  forwarded.on("timeout", () => forwarded.destroy(new Error("upstream timeout")));
  forwarded.on("error", (err) => {
    release();
    if (!res.headersSent) {
      json(res, 502, { detail: `Upstream request failed: ${err.message}` });
    } else {
      res.destroy();
    }
  });
  // If the browser goes away mid-orchestration, stop waiting on the API too.
  req.on("aborted", () => {
    release();
    forwarded.destroy();
  });
  res.on("close", release);

  // The content-length check upstream only sees requests that declare one.
  // A chunked request carries no length, so count the bytes as they arrive
  // rather than streaming an unbounded body to the API.
  let received = 0;
  req.on("data", (chunk) => {
    received += chunk.length;
    if (received > MAX_BODY_BYTES) {
      release();
      forwarded.destroy();
      if (!res.headersSent) {
        json(res, 413, { detail: "Request body too large." });
      } else {
        res.destroy();
      }
    }
  });
  req.pipe(forwarded);
}

async function serveStatic(req, res, url) {
  let requested;
  try {
    requested = normalize(decodeURIComponent(url.pathname));
  } catch {
    // A lone '%' is a malformed request, not a server fault. Without this it
    // surfaces as a 500 and looks like the site is broken.
    return send(res, 400, "Bad request");
  }
  let filePath = resolve(join(ROOT, requested));

  // Containment check: normalize() resolves ".." before we ever touch disk,
  // and this rejects anything that still escaped the root.
  if (filePath !== ROOT && !filePath.startsWith(ROOT + sep)) {
    return send(res, 403, "Forbidden");
  }

  let info = await stat(filePath).catch(() => null);
  if (info?.isDirectory()) {
    filePath = join(filePath, "index.html");
    info = await stat(filePath).catch(() => null);
  }
  if (!info?.isFile()) {
    // SPA fallback, so a refresh on /supports serves the app rather than 404.
    filePath = join(ROOT, "index.html");
    info = await stat(filePath).catch(() => null);
    if (!info?.isFile()) return send(res, 404, "Not found");
  }

  const type = MIME[extname(filePath).toLowerCase()] ?? "application/octet-stream";
  // Hashed asset filenames are immutable; index.html must never be pinned or
  // a deploy leaves browsers on the previous bundle.
  const cache = filePath.endsWith("index.html")
    ? "no-cache"
    : "public, max-age=31536000, immutable";

  setSecurityHeaders(res);
  res.writeHead(200, { "content-type": type, "cache-control": cache });
  if (req.method === "HEAD") return res.end();
  createReadStream(filePath).pipe(res);
}

const server = createServer((req, res) => {
  let url;
  try {
    url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  } catch {
    // A hostile Host header or request target must not take the server down.
    return send(res, 400, "Bad request");
  }

  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
    if (!API_ORIGIN) {
      return json(res, 502, { detail: "API_ORIGIN is not configured." });
    }
    if (Number(req.headers["content-length"] ?? 0) > MAX_BODY_BYTES) {
      return json(res, 413, { detail: "Request body too large." });
    }
    if (overRateLimit(req, url.pathname)) {
      return json(res, 429, { detail: "Too many requests. Wait a minute and try again." });
    }

    const expensive = EXPENSIVE.test(url.pathname);
    if (expensive) {
      if (activeExpensive >= MAX_CONCURRENT_EXPENSIVE) {
        return json(res, 429, {
          detail: "The app is already running its maximum number of recommendations.",
        });
      }
      activeExpensive += 1;
    }
    return proxy(req, res, url, expensive);
  }

  if (req.method !== "GET" && req.method !== "HEAD") {
    return send(res, 405, "Method not allowed", { allow: "GET, HEAD" });
  }
  serveStatic(req, res, url).catch(() => send(res, 500, "Internal error"));
});

// An unhandled error in a callback would otherwise take the process down and
// leave the site returning 503 until App Service restarts it.
process.on("uncaughtException", (err) => console.error("uncaught:", err));
process.on("unhandledRejection", (err) => console.error("unhandled rejection:", err));

server.listen(PORT, () => {
  console.log(`web tier listening on ${PORT}`);
  console.log(`  static root : ${ROOT}`);
  console.log(`  api origin  : ${API_ORIGIN || "(unset)"}`);
  console.log(`  api key     : ${API_KEY ? "configured" : "NOT SET - API will reject calls"}`);
});

import { createReadStream, existsSync } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer, request as httpRequest } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.join(__dirname, "frontend", "dist");
const backendOrigin = process.env.BACKEND_ORIGIN || "http://127.0.0.1:8000";
const port = Number(process.env.SHARE_PORT || 4174);

const types = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
};

function send(res, status, body, headers = {}) {
  res.writeHead(status, headers);
  res.end(body);
}

function proxy(req, res) {
  const target = new URL(req.url, backendOrigin);
  const headers = { ...req.headers, host: target.host };
  const proxyReq = httpRequest(
    target,
    { method: req.method, headers },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );
  proxyReq.on("error", () => send(res, 502, "Backend is not reachable"));
  req.pipe(proxyReq);
}

async function staticFile(req, res) {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const requested = decodeURIComponent(url.pathname);
  const candidate = path.resolve(distDir, `.${requested}`);
  const indexFile = path.join(distDir, "index.html");
  const file = candidate.startsWith(distDir) && existsSync(candidate) && (await stat(candidate)).isFile() ? candidate : indexFile;

  try {
    const info = await stat(file);
    if (!info.isFile()) return send(res, 404, "Not found");
    res.writeHead(200, {
      "Content-Length": info.size,
      "Content-Type": types[path.extname(file)] || "application/octet-stream",
      "Cache-Control": file === indexFile ? "no-store" : "public, max-age=3600",
    });
    createReadStream(file).pipe(res);
  } catch {
    send(res, 404, "Build frontend first with: cd frontend && npm run build");
  }
}

createServer((req, res) => {
  if (req.url?.startsWith("/api") || req.url?.startsWith("/docs") || req.url?.startsWith("/openapi.json")) {
    proxy(req, res);
    return;
  }
  staticFile(req, res);
}).listen(port, "0.0.0.0", () => {
  console.log(`Share server running at http://127.0.0.1:${port}`);
  console.log(`Proxying backend from ${backendOrigin}`);
});

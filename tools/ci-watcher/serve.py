#!/usr/bin/env python3
import http.server
import socketserver
import argparse
import shutil
from pathlib import Path
from urllib.parse import urlparse

class CIStatsHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/snapshot":
            snapshot_path = Path(self.directory) / "snapshot.json"
            if snapshot_path.exists():
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                with open(snapshot_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"snapshot not found"}')
            return

        if parsed_path.path == "/timeline":
            timeline_path = Path(self.directory) / "timeline.ndjson"
            if timeline_path.exists():
                self.send_response(200)
                self.send_header("Content-type", "application/x-ndjson")
                self.end_headers()
                with open(timeline_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"timeline not found"}')
            return

        if parsed_path.path == "/":
            self.path = "/index.html"

        return super().do_GET()

def html_template(pr_num: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>CI Live Stats - PR #{pr_num}</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 24px;
      background: #ffffff;
      color: #111111;
    }}
    h1, h2 {{
      margin-bottom: 8px;
    }}
    .section {{
      margin-bottom: 24px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 8px;
    }}
    th, td {{
      border: 1px solid #cccccc;
      padding: 8px;
      text-align: left;
      font-size: 14px;
    }}
    th {{
      background: #f3f3f3;
    }}
  </style>
</head>
<body>
  <h1>CI Live Stats - PR #{pr_num}</h1>
  <div class="section">
    <div><strong>Stage:</strong> <span id="stage">Loading...</span></div>
    <div><strong>Timestamp:</strong> <span id="ts">Loading...</span></div>
    <div><strong>Tick:</strong> <span id="tick">0</span></div>
  </div>

  <div class="section">
    <h2>Filesystem</h2>
    <table>
      <thead>
        <tr>
          <th>Mount</th>
          <th>Use %</th>
          <th>Used KB</th>
          <th>Available KB</th>
        </tr>
      </thead>
      <tbody id="fs-body">
        <tr><td colspan="4">Loading...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Docker Summary</h2>
    <table>
      <tbody id="docker-body">
        <tr><td>Loading...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Containers <span id="c-count">(0)</span></h2>
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>CPU</th>
          <th>RAM</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="container-body">
        <tr><td colspan="4">Loading...</td></tr>
      </tbody>
    </table>
  </div>

  <script>
    async function loadSnapshot() {{
      try {{
        const res = await fetch("./snapshot.json");
        if (!res.ok) {{
          throw new Error("snapshot not ready");
        }}

        const data = await res.json();

        document.getElementById("stage").textContent = data.stage || "";
        document.getElementById("ts").textContent = data.ts || "";
        document.getElementById("tick").textContent = data.tick ?? 0;

        const fsBody = document.getElementById("fs-body");
        if (data.fs && data.fs.length > 0) {{
          fsBody.innerHTML = data.fs.map(f => `
            <tr>
              <td>${{f.mount}}</td>
              <td>${{f.pct}}%</td>
              <td>${{f.used_kb}}</td>
              <td>${{f.avail_kb}}</td>
            </tr>
          `).join("");
        }} else {{
          fsBody.innerHTML = '<tr><td colspan="4">No filesystem data</td></tr>';
        }}

        const dockerBody = document.getElementById("docker-body");
        const d = data.docker_df || {{}};
        dockerBody.innerHTML = `
          <tr><th>Images</th><td>${{d.images_total || "?"}}</td><th>Reclaimable</th><td>${{d.images_reclaimable || "?"}}</td></tr>
          <tr><th>Containers</th><td>${{d.containers_total || "?"}}</td><th>Reclaimable</th><td>${{d.containers_reclaimable || "?"}}</td></tr>
          <tr><th>Volumes</th><td>${{d.volumes_total || "?"}}</td><th>Reclaimable</th><td>${{d.volumes_reclaimable || "?"}}</td></tr>
          <tr><th>Build Cache</th><td>${{d.build_cache_total || "?"}}</td><th>Reclaimable</th><td>${{d.build_cache_reclaimable || "?"}}</td></tr>
        `;

        const containers = data.containers || [];
        document.getElementById("c-count").textContent = `(${containers.length})`;

        const containerBody = document.getElementById("container-body");
        if (containers.length > 0) {{
          containerBody.innerHTML = containers.map(c => `
            <tr>
              <td>${{c.name || ""}}</td>
              <td>${{c.cpu_pct || ""}}</td>
              <td>${{c.mem_usage || ""}}</td>
              <td>${{c.status || ""}}</td>
            </tr>
          `).join("");
        }} else {{
          containerBody.innerHTML = '<tr><td colspan="4">No containers running</td></tr>';
        }}
      }} catch (err) {{
        console.log("Snapshot load error:", err);
      }}
    }}

    setInterval(loadSnapshot, 10000);
    loadSnapshot();
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5999)
    parser.add_argument("--pr", type=str, required=True)
    parser.add_argument("--stats-dir", type=str, required=True)
    args = parser.parse_args()

    target_dir = Path(args.stats_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    schema_source = Path(__file__).with_name("live-schema.json")
    if schema_source.exists():
        shutil.copy2(schema_source, target_dir / "live-schema.json")

    with open(target_dir / "index.html", "w", encoding="utf-8") as f:
      f.write(html_template(args.pr))

    socketserver.TCPServer.allow_reuse_address = True
    handler = lambda *a, **kw: CIStatsHandler(*a, directory=str(target_dir), **kw)

    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Server started at port {args.port} serving {target_dir}")
        httpd.serve_forever()

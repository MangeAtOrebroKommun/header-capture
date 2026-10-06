"""
header-capture: en liten testapplikation som simulerar en mottagande Bifrost-server.

Tar emot HTTP-anrop på /capture, sparar dem persistent i SQLite under DATA_DIR
(standard /data) och visar de senaste anropen på /.
"""

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "requests.db")
MAX_DISPLAY = int(os.environ.get("MAX_DISPLAY", "100"))
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(1024 * 1024)))  # 1 MiB

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Databas
# --------------------------------------------------------------------------- #
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with closing(get_conn()) as conn, conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                method      TEXT NOT NULL,
                path        TEXT NOT NULL,
                query       TEXT NOT NULL,
                headers     TEXT NOT NULL,
                body        TEXT NOT NULL,
                body_size   INTEGER NOT NULL,
                truncated   INTEGER NOT NULL DEFAULT 0,
                remote_addr TEXT
            )
            """
        )


init_db()


def client_ip() -> str:
    """Remote IP. Visar även X-Forwarded-For om anropet gått via proxy."""
    remote = request.remote_addr or ""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return f"{remote} (X-Forwarded-For: {xff})"
    return remote


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/capture", methods=METHODS)
@app.route("/capture/<path:subpath>", methods=METHODS)
def capture(subpath=None):
    raw = request.get_data(cache=False) or b""
    truncated = len(raw) > MAX_BODY_BYTES
    body = raw[:MAX_BODY_BYTES].decode("utf-8", errors="replace")

    query = {k: request.args.getlist(k) for k in request.args.keys()}
    headers = [[k, v] for k, v in request.headers.items()]
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    with closing(get_conn()) as conn, conn:
        cur = conn.execute(
            """INSERT INTO requests
               (timestamp, method, path, query, headers, body, body_size, truncated, remote_addr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                request.method,
                request.path,
                json.dumps(query, ensure_ascii=False),
                json.dumps(headers, ensure_ascii=False),
                body,
                len(raw),
                int(truncated),
                client_ip(),
            ),
        )
        req_id = cur.lastrowid

    if request.method == "OPTIONS":
        resp = app.make_response(("", 204))
        resp.headers["Allow"] = ", ".join(METHODS)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = ", ".join(METHODS)
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    return jsonify({"status": "captured", "id": req_id, "timestamp": ts}), 200


@app.post("/clear")
def clear():
    with closing(get_conn()) as conn, conn:
        conn.execute("DELETE FROM requests")
    if "text/html" in request.headers.get("Accept", ""):
        return redirect(url_for("index"), code=303)
    return jsonify({"status": "cleared"})


@app.get("/api/requests")
def api_requests():
    limit = min(int(request.args.get("limit", MAX_DISPLAY)), 1000)
    return jsonify(load_requests(limit))


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


def load_requests(limit: int):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    items = []
    for r in rows:
        body = r["body"]
        pretty = body
        try:
            if body.strip():
                pretty = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except (ValueError, TypeError):
            pass
        items.append(
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "method": r["method"],
                "path": r["path"],
                "query": json.loads(r["query"]),
                "headers": json.loads(r["headers"]),
                "body": pretty,
                "body_size": r["body_size"],
                "truncated": bool(r["truncated"]),
                "remote_addr": r["remote_addr"],
            }
        )
    return {"total": total, "requests": items}


PAGE = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>header-capture</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#c9d1d9;
          --muted:#8b949e; --accent:#58a6ff; --key:#d2a8ff; }
  * { box-sizing:border-box; }
  body { margin:0; padding:1.5rem; background:var(--bg); color:var(--fg);
         font:13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  header { display:flex; flex-wrap:wrap; gap:1rem; align-items:center;
           justify-content:space-between; margin-bottom:1.25rem; }
  h1 { font-size:1.1rem; margin:0; color:var(--accent); }
  .meta { color:var(--muted); }
  button { font:inherit; background:#21262d; color:var(--fg); border:1px solid var(--border);
           padding:.35rem .8rem; border-radius:6px; cursor:pointer; }
  button:hover { border-color:var(--muted); }
  button.danger:hover { border-color:#f85149; color:#f85149; }
  .req { background:var(--panel); border:1px solid var(--border); border-radius:8px;
         padding:.9rem 1rem; margin-bottom:1rem; }
  .line { display:flex; flex-wrap:wrap; gap:.75rem; align-items:baseline; }
  .method { font-weight:700; padding:.05rem .45rem; border-radius:4px; color:#0d1117; }
  .GET{background:#3fb950} .POST{background:#58a6ff} .PUT{background:#d29922}
  .PATCH{background:#a371f7} .DELETE{background:#f85149} .OPTIONS,.HEAD{background:#8b949e}
  .path { color:#fff; font-weight:600; word-break:break-all; }
  h3 { margin:.8rem 0 .3rem; font-size:.8rem; text-transform:uppercase;
       letter-spacing:.05em; color:var(--muted); font-weight:600; }
  table { border-collapse:collapse; width:100%; }
  td { padding:.1rem .6rem .1rem 0; vertical-align:top; word-break:break-all; }
  td.k { color:var(--key); white-space:nowrap; width:1%; }
  pre { margin:0; padding:.6rem; background:#0b0f14; border:1px solid var(--border);
        border-radius:6px; overflow-x:auto; white-space:pre-wrap; word-break:break-all; }
  .empty { color:var(--muted); font-style:italic; }
</style>
</head>
<body>
<header>
  <div>
    <h1>header-capture</h1>
    <div class="meta">Visar {{ data.requests|length }} av {{ data.total }} sparade anrop
      · senaste först · skicka till <code>/capture</code></div>
  </div>
  <div class="line">
    <button onclick="location.reload()">Uppdatera</button>
    <label class="meta"><input type="checkbox" id="auto"> auto (5 s)</label>
    <form method="post" action="/clear" style="margin:0" id="clear-form">
      <button class="danger" type="submit">Rensa historik</button>
    </form>
  </div>
</header>

{% if not data.requests %}
  <p class="empty">Inga anrop ännu.</p>
{% endif %}

{% for r in data.requests %}
<div class="req">
  <div class="line">
    <span class="meta">#{{ r.id }}</span>
    <span class="method {{ r.method }}">{{ r.method }}</span>
    <span class="path">{{ r.path }}</span>
  </div>
  <div class="line meta">
    <span>timestamp: {{ r.timestamp }}</span>
    <span>remote: {{ r.remote_addr }}</span>
  </div>

  <h3>Query parameters</h3>
  {% if r.query %}
  <table>{% for k, vals in r.query.items() %}{% for v in vals %}
    <tr><td class="k">{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}{% endfor %}
  </table>
  {% else %}<span class="empty">(inga)</span>{% endif %}

  <h3>Headers ({{ r.headers|length }})</h3>
  <table>{% for k, v in r.headers %}
    <tr><td class="k">{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}
  </table>

  <h3>Body ({{ r.body_size }} bytes{% if r.truncated %}, trunkerad{% endif %})</h3>
  {% if r.body %}<pre>{{ r.body }}</pre>{% else %}<span class="empty">(tom)</span>{% endif %}
</div>
{% endfor %}

<script>
  const box = document.getElementById('auto');
  box.checked = location.hash === '#auto';
  box.onchange = () => { location.hash = box.checked ? 'auto' : ''; };

  // Medan bekräftelsedialogen är öppen, och medan rensningen skickas, får
  // auto-uppdateringen inte ladda om sidan. Ett reload() avbryter annars
  // formulärets POST /clear innan det hunnit skickas.
  let clearing = false;
  document.getElementById('clear-form').addEventListener('submit', (e) => {
    clearing = true;
    if (!confirm('Rensa all historik?')) {
      clearing = false;
      e.preventDefault();
    }
  });
  setInterval(() => { if (box.checked && !clearing) location.reload(); }, 5000);
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE, data=load_requests(MAX_DISPLAY))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

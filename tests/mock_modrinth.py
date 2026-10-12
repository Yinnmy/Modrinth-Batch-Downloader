"""Servidor HTTP local que imita os endpoints do Modrinth usados pelo MBD (só para testes)."""
import hashlib
import io
import json
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_jar(mod_id, version="1.0.0", loader="fabric", extra=b""):
    """Cria um .jar (zip) mínimo com metadados do loader."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if loader == "fabric":
            zf.writestr("fabric.mod.json", json.dumps({"id": mod_id, "name": mod_id.title(), "version": version}))
        elif loader == "forge":
            zf.writestr("META-INF/mods.toml", f'[[mods]]\nmodId="{mod_id}"\nversion="{version}"\n')
        zf.writestr("data.bin", extra or mod_id.encode())
    return buf.getvalue()


class MockModrinth:
    def __init__(self, file_delay=0.0):
        self.projects = {}       # slug -> project dict
        self.versions = {}       # project_id -> [version dicts]
        self.files = {}          # filename -> bytes
        self.file_delay = file_delay
        self.flaky = {}          # chave -> quantas respostas de erro ainda devem ser dadas
        self.hits = []           # log de requisições (path)
        self.corrupt = set()     # nomes de arquivos entregues corrompidos
        self.lock = threading.Lock()
        self.server = None

    # ------------------------------------------------------------------ montagem de dados
    def add_project(self, slug, title=None, ptype="mod", loaders=("fabric",), icon=False):
        pid = "P" + slug.upper().replace("-", "")[:7].ljust(7, "X")
        self.projects[slug] = {"id": pid, "slug": slug, "title": title or slug.title(), "project_type": ptype,
                               "loaders": list(loaders), "icon_url": self.url + f"/icons/{slug}.png" if icon else None}
        self.versions[pid] = []
        return pid

    def add_version(self, slug, number, vtype="release", date="2025-01-01T00:00:00Z", games=("1.21.1",),
                    loaders=("fabric",), deps=(), content=None, filename=None):
        project = self.projects[slug]
        loader = loaders[0] if loaders and loaders[0] in ("fabric", "forge") else "fabric"
        data = content if content is not None else make_jar(slug, number, loader, extra=number.encode())
        fname = filename or f"{slug}-{number}.jar"
        self.files[fname] = data
        version = {"id": f"V{project['id']}{number}", "project_id": project["id"], "version_number": number,
                   "version_type": vtype, "date_published": date, "game_versions": list(games), "loaders": list(loaders),
                   "dependencies": [{"project_id": d, "dependency_type": "required"} for d in deps],
                   "files": [{"hashes": {"sha1": hashlib.sha1(data).hexdigest(), "sha512": hashlib.sha512(data).hexdigest()},
                              "url": f"{self.url}/files/{fname}", "filename": fname, "primary": True, "size": len(data)}]}
        self.versions[project["id"]].append(version)
        return version

    # ------------------------------------------------------------------ servidor
    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}" if self.server else ""

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json", headers=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj).encode())

            def _maybe_flaky(self, key):
                with outer.lock:
                    left = outer.flaky.get(key, 0)
                    if left > 0:
                        outer.flaky[key] = left - 1
                        return True
                return False

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                path, q = url.path, urllib.parse.parse_qs(url.query)
                with outer.lock:
                    outer.hits.append(path)
                if path.startswith("/files/"):
                    name = urllib.parse.unquote(path[len("/files/"):])
                    if self._maybe_flaky("file503"):
                        return self._send(503, b"busy")
                    if self._maybe_flaky("file429"):
                        return self._send(429, b"slow down", headers={"Retry-After": "0"})
                    data = outer.files.get(name)
                    if data is None:
                        return self._send(404, b"nope")
                    if name in outer.corrupt:
                        data = bytes([data[0] ^ 0xFF]) + data[1:]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    step = max(1, len(data) // 4)
                    for i in range(0, len(data), step):
                        self.wfile.write(data[i:i + step])
                        self.wfile.flush()
                        if outer.file_delay:
                            time.sleep(outer.file_delay / 4)
                    return
                if path.startswith("/icons/"):
                    return self._send(200, b"\x89PNG fake", "image/png")
                if self._maybe_flaky("api429") and path.startswith("/v2/"):
                    return self._send(429, b"{}", headers={"Retry-After": "0"})
                if path == "/v2/tag/game_version":
                    return self._json([
                        {"version": "1.21.1", "version_type": "release", "date": "2024-08-08T00:00:00Z", "major": False},
                        {"version": "25w01a", "version_type": "snapshot", "date": "2025-01-02T00:00:00Z", "major": False},
                        {"version": "1.20.1", "version_type": "release", "date": "2023-06-12T00:00:00Z", "major": True},
                        {"version": "26.1", "version_type": "release", "date": "2026-03-01T00:00:00Z", "major": True}])
                if path == "/v2/projects":
                    ids = json.loads(q.get("ids", ["[]"])[0])
                    found = []
                    for ref in ids:
                        for p in outer.projects.values():
                            if ref.lower() in (p["slug"].lower(), p["id"].lower()):
                                found.append(p)
                    return self._json(found)
                if path == "/v2/search":
                    term = q.get("query", [""])[0].lower()
                    hits = [{"project_id": p["id"], "slug": p["slug"], "title": p["title"]}
                            for p in outer.projects.values() if term in p["slug"].lower() or term in p["title"].lower()]
                    return self._json({"hits": hits})
                parts = [p for p in path.split("/") if p]
                if len(parts) == 3 and parts[1] == "project":
                    ref = urllib.parse.unquote(parts[2])
                    for p in outer.projects.values():
                        if ref.lower() in (p["slug"].lower(), p["id"].lower()):
                            return self._json(p)
                    return self._json({"error": "not_found"}, 404)
                if len(parts) == 4 and parts[1] == "project" and parts[3] == "version":
                    pid = next((p["id"] for p in outer.projects.values()
                                if urllib.parse.unquote(parts[2]).lower() in (p["slug"].lower(), p["id"].lower())), None)
                    games = json.loads(q.get("game_versions", ["[]"])[0])
                    loaders = json.loads(q.get("loaders", ["[]"])[0])
                    out = [v for v in outer.versions.get(pid, [])
                           if (not games or set(games) & set(v["game_versions"])) and (not loaders or set(loaders) & set(v["loaders"]))]
                    return self._json(out)
                self._json({"error": "unknown", "path": path}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                path = urllib.parse.urlparse(self.path).path
                with outer.lock:
                    outer.hits.append(path)
                by_hash = {}
                for versions in outer.versions.values():
                    for v in versions:
                        for f in v["files"]:
                            by_hash[f["hashes"]["sha1"]] = v
                if path == "/v2/version_files":
                    return self._json({h: by_hash[h] for h in body["hashes"] if h in by_hash})
                if path == "/v2/version_files/update":
                    out = {}
                    for h in body["hashes"]:
                        cur = by_hash.get(h)
                        if not cur:
                            continue
                        cands = [v for v in outer.versions[cur["project_id"]]
                                 if set(body.get("loaders") or v["loaders"]) & set(v["loaders"])
                                 and set(body.get("game_versions") or v["game_versions"]) & set(v["game_versions"])
                                 and (not body.get("version_types") or v["version_type"] in body["version_types"])]
                        if cands:
                            out[h] = sorted(cands, key=lambda v: v["date_published"])[-1]
                    return self._json(out)
                self._json({"error": "unknown"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

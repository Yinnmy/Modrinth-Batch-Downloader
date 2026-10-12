"""Núcleo do Modrinth Batch Downloader (sem Tkinter, portanto testável sem interface).

Conteúdo
  1. HTTP/SSL, retry com backoff e acesso à API do Modrinth
  2. Hashes (SHA-1 / SHA-512) e leitura de metadados dos JARs
  3. Tipos de projeto (mod, shader, resourcepack, datapack…) e escolha de versão
  4. download() em blocos, com progresso, velocidade e verificação de hash
  5. Engine: pipeline paralelo (ThreadPoolExecutor) com dependências, conversão e relatório
  6. Utilitários: conflitos de mods, verificação de atualizações, pré-visualização, versões do jogo
  7. Sistema: abrir pasta, notificação do Windows

Eventos que a Engine envia para a interface (tuplas, via ``emit``):
  ("log", kind, texto)                      kind ∈ ok|err|warn|info|accent|muted
  ("progress", feitos, total, ativos, bytes_por_s, bytes_baixados)
  ("file", chave, nome, baixado, total, bytes_por_s)   progresso de UM arquivo
  ("file_done", chave)
  ("manifests", [manifest, ...])           JARs locais lidos
  ("finished", Report)
"""
import base64
import hashlib
import http.client
import io
import json
import os
import random
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from i18n import tr

APP_NAME = "Modrinth Batch Downloader"
APP_VERSION = "5.0.0"
API = "https://api.modrinth.com/v2"
USER_AGENT = f"ModrinthBatchDownloader/{APP_VERSION} (Windows desktop app)"
# Troque SEU_USUARIO/SEU_REPO pelo repositório onde você publica as versões (releases do GitHub)
# ou aponte para qualquer JSON {"version": "5.1.0", "url": "https://..."}.
UPDATE_URL_DEFAULT = "https://api.github.com/repos/SEU_USUARIO/modrinth-batch-downloader/releases/latest"

LOADERS = ("fabric", "forge", "neoforge", "quilt")

TRUSTSTORE_ACTIVE = False
try:
    import truststore
    truststore.inject_into_ssl()
    TRUSTSTORE_ACTIVE = True
except Exception:
    pass
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl.create_default_context()


# =============================================================================================
# 1. HTTP, retry e API
# =============================================================================================
class Cancelled(Exception):
    """Operação cancelada pelo usuário (durante uma espera de retry, por exemplo)."""


class HashMismatch(Exception):
    """O hash do arquivo baixado não bate com o publicado pelo Modrinth (falha de segurança)."""

    def __init__(self, algo, expected, actual):
        super().__init__(f"{algo} mismatch: expected {expected}, got {actual}")
        self.algo, self.expected, self.actual = algo, expected, actual


RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def open_https(request, timeout=35):
    context = ssl.create_default_context() if TRUSTSTORE_ACTIVE else SSL_CONTEXT
    return urllib.request.urlopen(request, timeout=timeout, context=context)


def is_retryable(exc):
    """Erros de rede e limites da API valem nova tentativa; erro de certificado ou 4xx comum, não."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_STATUS
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
            return False
        return True
    if isinstance(exc, ssl.SSLCertVerificationError):
        return False
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, ssl.SSLError))


def retry_delay(attempt, exc, base):
    """Espera crescente: base·2^tentativa (+ jitter). Em 429, respeita Retry-After / X-Ratelimit-Reset."""
    delay = base * (2 ** attempt) + random.uniform(0, min(0.4, base))
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        hint = exc.headers.get("Retry-After") or exc.headers.get("X-Ratelimit-Reset")
        try:
            delay = max(delay, min(float(hint), 60.0))
        except (TypeError, ValueError):
            pass
    return delay


def short_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)[:80]
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    return (str(exc) or exc.__class__.__name__)[:80]


def with_retry(func, retries=3, base_delay=1.0, cancel=None, on_retry=None):
    """Executa ``func`` e tenta de novo (até ``retries`` vezes) em erros transitórios, com backoff."""
    attempt = 0
    while True:
        try:
            return func()
        except Exception as exc:
            if isinstance(exc, (Cancelled, HashMismatch)) or attempt >= retries or not is_retryable(exc):
                raise
            delay = retry_delay(attempt, exc, base_delay)
            attempt += 1
            if on_retry:
                on_retry(attempt, retries, delay, exc)
            if cancel is not None:
                if cancel.wait(delay):
                    raise Cancelled()
            else:
                time.sleep(delay)


# O Modrinth limita ~300 requisições/min por IP e informa o saldo nos cabeçalhos X-Ratelimit-*.
_rate = {"remaining": None, "reset_at": 0.0}


def _rate_gate():
    """Se o saldo da API estiver quase no fim, espera o reset em vez de levar 429."""
    remaining, reset_at = _rate["remaining"], _rate["reset_at"]
    if remaining is not None and remaining <= 2:
        wait = reset_at - time.monotonic()
        if 0 < wait <= 60:
            time.sleep(wait)


def _rate_update(headers):
    try:
        _rate["remaining"] = int(headers.get("X-Ratelimit-Remaining"))
        _rate["reset_at"] = time.monotonic() + float(headers.get("X-Ratelimit-Reset") or 0)
    except (TypeError, ValueError):
        pass


def api_json(url, data=None, **retry):
    """GET (ou POST JSON quando ``data`` é dado) na API, com retry/backoff."""
    def call():
        _rate_gate()
        body, headers = None, {"User-Agent": USER_AGENT}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers)
        with open_https(req) as response:
            _rate_update(response.headers)
            return json.loads(response.read().decode("utf-8"))
    return with_retry(call, **retry)


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def human_speed(bps):
    return f"{(bps or 0) / (1024 * 1024):.1f} MB/s"


# =============================================================================================
# 2. Hashes e metadados dos JARs
# =============================================================================================
_hash_cache = {}
_hash_lock = threading.Lock()


def file_hash(path, algo="sha1"):
    """Hash de um arquivo local (em blocos). SHA-1 fica em cache por (caminho, tamanho, mtime)."""
    path = Path(path)
    key = None
    if algo == "sha1":
        try:
            st = path.stat()
            key = (str(path), st.st_size, st.st_mtime_ns)
            with _hash_lock:
                if key in _hash_cache:
                    return _hash_cache[key]
        except OSError:
            key = None
    digest = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    if key:
        with _hash_lock:
            _hash_cache[key] = value
    return value


def _toml_blocks(txt, header):
    """Blocos de um array de tabelas TOML (ex.: ``[[mods]]``) sem depender de bibliotecas externas."""
    pattern = r"(?ms)^\s*\[\[\s*" + re.escape(header) + r"\s*\]\](.*?)(?=^\s*\[|\Z)"
    return re.findall(pattern, txt)


def _id_list(value):
    """Lista de ids de um campo 'provides' (strings ou objetos {"id": ...})."""
    out = []
    for item in value or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("id"):
            out.append(item["id"])
    return out


def _satisfied_ids(zf, depth=0):
    """Todos os IDs que um JAR "fornece": id próprio, apelidos ('provides') e mods embutidos (jar-in-jar).

    É assim que o Fabric API (que embute dezenas de módulos 'fabric-*-v0') ou o Cloth Config
    (id 'cloth-config', provides 'cloth-config2') satisfazem dependências com outros nomes."""
    ids, nested = set(), []
    names = zf.namelist()
    try:
        if "fabric.mod.json" in names:
            data = json.loads(zf.read("fabric.mod.json").decode("utf-8-sig"))
            ids.add(data.get("id"))
            ids.update(_id_list(data.get("provides")))
            nested += [j.get("file") for j in data.get("jars") or [] if isinstance(j, dict)]
        elif "quilt.mod.json" in names:
            q = (json.loads(zf.read("quilt.mod.json").decode("utf-8-sig"))).get("quilt_loader") or {}
            ids.add(q.get("id"))
            ids.update(_id_list(q.get("provides")))
            nested += list((q.get("jars") or []) if isinstance(q.get("jars"), list) else [])
        else:
            for toml in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                if toml in names:
                    txt = zf.read(toml).decode("utf-8", "replace")
                    for block in _toml_blocks(txt, "mods"):
                        m = re.search(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)', block)
                        if m:
                            ids.add(m.group(1))
                    break
        nested += [n for n in names if n.startswith(("META-INF/jars/", "META-INF/jarjar/")) and n.endswith(".jar")]
        if depth < 2:
            for path in list(dict.fromkeys(n for n in nested if isinstance(n, str)))[:300]:
                try:
                    if zf.getinfo(path).file_size > 30 * 1024 * 1024:
                        continue
                    with zipfile.ZipFile(io.BytesIO(zf.read(path))) as inner:
                        ids |= _satisfied_ids(inner, depth + 1)
                except Exception:
                    continue
    except Exception:
        pass
    return {i for i in ids if i}


def read_manifest(jar_path):
    """Lê id/nome/versão/loader/dependências de um JAR (Fabric, Quilt, Forge ou NeoForge) e o SHA-1."""
    jar_path = Path(jar_path)
    result = {"file": str(jar_path), "name": jar_path.stem, "id": None, "all_ids": [], "version": None,
              "required": [], "optional": [], "loader": None, "error": None, "hash": None,
              "satisfies": [], "library": False, "entrypoints": False}
    try:
        result["hash"] = file_hash(jar_path)
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            if "fabric.mod.json" in names:
                data = json.loads(zf.read("fabric.mod.json").decode("utf-8-sig"))
                result.update(id=data.get("id"), name=data.get("name") or data.get("id") or jar_path.stem,
                              version=str(data.get("version") or ""), loader="fabric")
                deps, opt = data.get("depends") or {}, data.get("recommends") or {}
                result["required"] = [k for k, v in deps.items()
                                      if k not in ("minecraft", "java", "fabricloader") and v is not False]
                badges = (((data.get("custom") or {}).get("modmenu") or {}).get("badges")) or []
                result["library"] = "library" in badges          # selo "Library" do Mod Menu
                eps = data.get("entrypoints") or {}
                result["entrypoints"] = any(k in eps for k in ("main", "client", "server"))
                result["optional"] = [k for k in opt if k not in ("minecraft", "java", "fabricloader")]
            elif "quilt.mod.json" in names:
                data = json.loads(zf.read("quilt.mod.json").decode("utf-8-sig"))
                q = data.get("quilt_loader") or {}
                meta = q.get("metadata") or {}
                result.update(id=q.get("id"), name=meta.get("name") or q.get("id") or jar_path.stem,
                              version=str(q.get("version") or ""), loader="quilt")
                result["entrypoints"] = any(k in (q.get("entrypoints") or {}) for k in ("init", "client_init", "server_init"))
                for dep in q.get("depends", []):
                    dep_id = dep.get("id") if isinstance(dep, dict) else dep
                    if dep_id and dep_id not in ("minecraft", "quilt_loader", "java"):
                        optional = isinstance(dep, dict) and dep.get("optional") is True
                        (result["optional"] if optional else result["required"]).append(dep_id)
            elif "META-INF/mods.toml" in names or "META-INF/neoforge.mods.toml" in names:
                manifest_name = "META-INF/neoforge.mods.toml" if "META-INF/neoforge.mods.toml" in names else "META-INF/mods.toml"
                txt = zf.read(manifest_name).decode("utf-8", "replace")
                ids = []
                for block in _toml_blocks(txt, "mods"):
                    m = re.search(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)', block)
                    if m:
                        ids.append(m.group(1))
                if not ids:  # TOML fora do padrão: cai no comportamento antigo (primeiro modId do arquivo)
                    ids = re.findall(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)', txt)[:1]
                if ids:
                    result.update(id=ids[0], name=ids[0], all_ids=ids,
                                  loader="neoforge" if "neoforge" in manifest_name else "forge")
                    ver = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)', (_toml_blocks(txt, "mods") or [""])[0])
                    if ver:
                        result["version"] = ver.group(1)
                for block in re.findall(r'(?is)\[\[dependencies\.[^]]+\]\](.*?)(?=\[\[|\Z)', txt):
                    mid = re.search(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)', block)
                    mandatory = re.search(r'(?m)^\s*mandatory\s*=\s*(true|false)', block)
                    if mid and mid.group(1) not in ("minecraft", "forge", "neoforge"):
                        required = not mandatory or mandatory.group(1).lower() == "true"
                        (result["required"] if required else result["optional"]).append(mid.group(1))
            else:
                result["error"] = "no_metadata"
            result["satisfies"] = sorted({i.lower() for i in _satisfied_ids(zf)})
    except Exception as exc:
        result["error"] = str(exc)
    if result["id"] and not result["all_ids"]:
        result["all_ids"] = [result["id"]]
    result["required"] = sorted(set(x for x in result["required"] if x))
    result["optional"] = sorted(set(x for x in result["optional"] if x))
    return result


def manifest_error(m):
    """Mensagem (traduzida) do erro de leitura de um JAR."""
    return tr("err.no_metadata") if m.get("error") == "no_metadata" else str(m.get("error"))


def _display_name(m):
    return m.get("name") or m.get("id") or Path(m["file"]).name


def analyze_dependencies(manifests):
    """Cruza o que cada JAR exige com o que a pasta fornece.

    Retorna:
      requires    {arquivo: [(dependência, JAR_que_fornece | None), ...]}
      required_by {arquivo_do_fornecedor: [nomes dos mods que o exigem]}
      missing     {dependência: [mods que a exigem]}   (só o que realmente não existe na pasta)
      libraries   {arquivos} considerados bibliotecas (selo Library do Mod Menu, ou exigido por outro mod
                  e sem entrypoint próprio)
    """
    providers = {}
    for m in manifests:
        for i in (m.get("satisfies") or [x.lower() for x in (m.get("all_ids") or [])]):
            providers.setdefault(i.lower(), m)
    fabric_api = providers.get("fabric-api")

    def provider(dep):
        found = providers.get(dep.lower())
        # Reserva: módulos 'fabric-*' vêm do Fabric API mesmo se não deu para ler os jars embutidos
        return found or (fabric_api if fabric_api and dep.lower().startswith("fabric-") else None)

    requires, required_by, missing = {}, defaultdict(set), defaultdict(set)
    for m in manifests:
        for dep in m.get("required") or []:
            prov = provider(dep)
            requires.setdefault(m["file"], []).append((dep, prov))
            if prov is None:
                missing[dep].add(_display_name(m))
            elif prov["file"] != m["file"]:
                required_by[prov["file"]].add(_display_name(m))
    libraries = set()
    for m in manifests:
        used = m["file"] in required_by
        if m.get("library") or (used and not m.get("entrypoints")):
            libraries.add(m["file"])
    return {"requires": requires, "required_by": {k: sorted(v) for k, v in required_by.items()},
            "missing": {d: sorted(o) for d, o in sorted(missing.items())}, "libraries": libraries}


def missing_dependencies(manifests):
    """Dependências obrigatórias que nenhum JAR da lista fornece: {dependência: [mods que a exigem]}."""
    return analyze_dependencies(manifests)["missing"]


def detect_conflicts(manifests):
    """Procura (1) o mesmo mod ID em dois JARs e (2) JARs de loaders diferentes na mesma pasta."""
    conflicts = []
    by_id = defaultdict(list)
    for m in manifests:
        for mod_id in m.get("all_ids") or ([m["id"]] if m.get("id") else []):
            by_id[mod_id.lower()].append(m)
    for mod_id, group in sorted(by_id.items()):
        files = sorted({Path(m["file"]).name for m in group})
        if len(files) > 1:
            conflicts.append({"kind": "duplicate_id", "id": mod_id, "files": files,
                              "versions": [m.get("version") or "?" for m in group]})
    loaders = Counter(m["loader"] for m in manifests if m.get("loader"))
    if len(loaders) > 1:
        conflicts.append({"kind": "mixed_loaders", "loaders": dict(loaders),
                          "files": {ld: sorted(Path(m["file"]).name for m in manifests if m.get("loader") == ld)
                                    for ld in loaders}})
    return conflicts


# =============================================================================================
# 3. Tipos de projeto e escolha de versão
# =============================================================================================
# Subpasta (dentro da pasta de destino) de cada tipo de projeto. Mods ficam na raiz, como sempre.
PROJECT_FOLDERS = {"mod": "", "shader": "shaderpacks", "resourcepack": "resourcepacks",
                   "datapack": "datapacks", "plugin": "plugins", "modpack": "modpacks"}
URL_KINDS = {"mod": "mod", "shader": "shader", "resourcepack": "resourcepack", "datapack": "datapack",
             "plugin": "plugin", "modpack": "modpack", "project": None}
MOD_LOADERS = {"fabric", "forge", "neoforge", "quilt", "liteloader", "modloader", "rift"}
PLUGIN_LOADERS = {"bukkit", "spigot", "paper", "purpur", "folia", "sponge", "bungeecord", "velocity", "waterfall"}
_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?modrinth\.com/([A-Za-z]+)/([^\s/?#]+)", re.I)


def parse_project_url(raw):
    """Extrai (tipo_na_url, slug) de um link do Modrinth. O texto pode ter mais coisa na linha."""
    raw = raw.strip()
    match = _URL_RE.search(raw)
    if not match:
        raise ValueError(tr("err.bad_link") if "modrinth.com" in raw.lower() else tr("err.bad_domain"))
    kind, slug = match.group(1).lower(), match.group(2).strip(".,;)>\"'")
    if kind not in URL_KINDS or not slug:
        raise ValueError(tr("err.bad_link"))
    return URL_KINDS[kind], urllib.parse.unquote(slug)


def project_kind(project, url_hint=None):
    """Tipo real do projeto. No Modrinth, datapacks e plugins são projetos "mod" com loaders próprios."""
    types = {str(project.get("project_type") or "")} | {str(t) for t in (project.get("project_types") or [])}
    loaders = set(project.get("loaders") or [])
    for kind in ("resourcepack", "shader", "modpack"):
        if kind in types:
            return kind
    if "datapack" in types or ("datapack" in loaders and not loaders & MOD_LOADERS):
        return "datapack"
    if "plugin" in types or (loaders & PLUGIN_LOADERS and not loaders & MOD_LOADERS):
        return "plugin"
    return "mod"


def folder_for(kind, root):
    sub = PROJECT_FOLDERS.get(kind, "")
    return Path(root) / sub if sub else Path(root)


def compatible_versions(project_id, game_version, loader, kind="mod", **retry):
    """Versões do projeto para o jogo (e o loader, só para mods), da mais nova para a mais antiga."""
    params = {"game_versions": json.dumps([game_version])}
    if kind == "mod" and loader:
        params["loaders"] = json.dumps([loader])
    url = f"{API}/project/{urllib.parse.quote(str(project_id), safe='')}/version?{urllib.parse.urlencode(params)}"
    versions = api_json(url, **retry)
    versions.sort(key=lambda v: v.get("date_published", ""), reverse=True)
    return versions


def pick_version(versions, stable_only=False):
    """Escolhe a versão. Com ``stable_only``: release → beta → alpha. Retorna (versão, tipo_do_fallback|None)."""
    if not versions:
        return None, None
    ordered = sorted(versions, key=lambda v: v.get("date_published", ""), reverse=True)
    if stable_only:
        for kind in ("release", "beta", "alpha"):
            match = [v for v in ordered if v.get("version_type") == kind]
            if match:
                return match[0], (None if kind == "release" else kind)
    return ordered[0], None


def choose_file(version):
    files = version.get("files") or []
    return next((f for f in files if f.get("primary")), files[0] if files else None)


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "download.bin"


# =============================================================================================
# 4. Download em blocos com progresso e verificação de hash
# =============================================================================================
def download(url, destination, progress=None, expected=None, expected_size=0, cancel=None,
             retries=3, base_delay=1.0, on_retry=None, chunk_size=64 * 1024):
    """Baixa ``url`` para ``destination`` lendo em blocos.

    - ``progress(baixado, total, bytes_por_s)`` é chamado ~8x/s (velocidade suavizada).
    - ``expected`` = {"sha1": ..., "sha512": ...}; se algum não bater, lança HashMismatch e descarta o arquivo.
    - Erros de rede / 429 / 5xx são repetidos ``retries`` vezes com espera crescente (backoff).
    - O arquivo vai para ``.part`` e só vira o definitivo depois de verificado.
    Retorna {"sha1", "sha512", "size"}.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(destination) + ".part")
    expected = {k: (v or "").lower() for k, v in (expected or {}).items() if v}

    def attempt():
        sha1, sha512 = hashlib.sha1(), hashlib.sha512()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        done = 0
        speed = 0.0
        t_start = last_emit = window_t = time.monotonic()
        window_bytes = 0
        try:
            with open_https(req, timeout=60) as response, open(temp, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0) or int(expected_size or 0)
                read = getattr(response, "read1", response.read)   # devolve o que já chegou, sem esperar o bloco cheio
                while True:
                    chunk = read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    sha1.update(chunk)
                    sha512.update(chunk)
                    done += len(chunk)
                    window_bytes += len(chunk)
                    now = time.monotonic()
                    if now - window_t >= 0.25:  # velocidade: média móvel exponencial sobre janelas de 250 ms
                        inst = window_bytes / (now - window_t)
                        speed = inst if speed == 0 else 0.6 * speed + 0.4 * inst
                        window_t, window_bytes = now, 0
                    if progress and now - last_emit >= 0.12:
                        progress(done, total, speed)
                        last_emit = now
            header_total = int(response.headers.get("Content-Length") or 0)
            if header_total and done != header_total:
                raise http.client.IncompleteRead(b"", header_total - done)
            elapsed = max(time.monotonic() - t_start, 1e-6)
            if progress:
                progress(done, done, done / elapsed)
            got = {"sha1": sha1.hexdigest(), "sha512": sha512.hexdigest()}
            for algo, want in expected.items():
                if got.get(algo) and got[algo] != want:
                    raise HashMismatch(algo, want, got[algo])
            os.replace(temp, destination)
            return {**got, "size": done}
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass

    return with_retry(attempt, retries=retries, base_delay=base_delay, cancel=cancel, on_retry=on_retry)


# =============================================================================================
# 5. Relatório e Engine paralela
# =============================================================================================
@dataclass
class Settings:
    game_version: str
    loader: str
    folder: Path
    auto_deps: bool = True
    stable_only: bool = False
    workers: int = 4
    retries: int = 3
    backoff: float = 1.0
    source_version: str = ""


class Report:
    """Resultado de uma execução: itens por status + log + conflitos."""

    def __init__(self, cfg):
        self.game_version, self.loader, self.folder = cfg.game_version, cfg.loader, str(cfg.folder)
        self.items, self.log_lines, self.conflicts = [], [], []
        self.started, self.finished, self.stopped = time.time(), None, False

    def add(self, status, title, slug="", kind="mod", detail="", filename="", version=""):
        item = {"status": status, "title": title, "slug": slug, "kind": kind, "detail": detail,
                "filename": filename, "version": version}
        self.items.append(item)
        return item

    def by_status(self, status):
        return [i for i in self.items if i["status"] == status]

    @property
    def counts(self):
        c = Counter(i["status"] for i in self.items)
        return {"downloaded": c["downloaded"], "skipped": c["skipped"], "incompatible": c["incompatible"],
                "failed": c["failed"] + c["corrupted"], "corrupted": c["corrupted"]}

    @staticmethod
    def project_url(item):
        slug = item.get("slug") or ""
        return f"https://modrinth.com/{item.get('kind') or 'mod'}/{slug}" if slug else ""

    def incompatible_lines(self):
        """Uma linha "Título — link" por projeto incompatível (o app aceita colar isso de volta como links)."""
        lines = []
        for i in self.by_status("incompatible"):
            url = self.project_url(i)
            lines.append(f"{i['title']} — {url}" if url else i["title"])
        return lines

    def log_text(self):
        return "\n".join(text for _, text in self.log_lines)

    def to_dict(self, max_log=400):
        return {"game_version": self.game_version, "loader": self.loader, "folder": self.folder,
                "items": self.items, "conflicts": self.conflicts, "stopped": self.stopped,
                "started": self.started, "finished": self.finished,
                "log": [[k, t] for k, t in self.log_lines[-max_log:]]}

    @classmethod
    def from_dict(cls, data):
        rep = cls(Settings(data.get("game_version", ""), data.get("loader", ""), Path(data.get("folder", "."))))
        rep.items, rep.conflicts = data.get("items", []), data.get("conflicts", [])
        rep.stopped, rep.started, rep.finished = data.get("stopped", False), data.get("started"), data.get("finished")
        rep.log_lines = [tuple(x) for x in data.get("log", [])]
        return rep


class FolderIndex:
    """Arquivos já presentes numa pasta: SHA-1 → caminho e projeto → arquivos (via /version_files)."""

    def __init__(self):
        self.by_hash = {}
        self.by_project = defaultdict(list)


class Engine:
    """Resolve projetos, dependências e conversões e baixa tudo em paralelo (ThreadPoolExecutor)."""

    def __init__(self, cfg, emit, stop):
        self.cfg, self.emit, self.stop = cfg, emit, stop
        self.report = Report(cfg)
        self.pool = None
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._index_lock = threading.Lock()
        self._pending = 0
        self._keys, self._pids = set(), set()
        self._total_jobs = self._done_jobs = 0
        self._frac, self._speed, self._bytes = {}, {}, {}
        self._active = set()
        self._bytes_finished = 0
        self._last_progress = 0.0
        self._indexes = {}

    # ------------------------------------------------------------------ log / progresso
    def log(self, level, key, **params):
        """Registra uma linha de log traduzida. ``level`` (ok|err|warn|info|accent|muted) define a cor na tela."""
        text = tr(key, **params)
        self.report.log_lines.append((level, text))
        self.emit(("log", level, text))

    def emit_progress(self, force=False):
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_progress < 0.1:
                return
            self._last_progress = now
            done = self._done_jobs + sum(self._frac.values())
            total = max(1, self._total_jobs)
            speed = sum(self._speed.values())
            size = self._bytes_finished + sum(self._bytes.values())
            active = len(self._active)
        self.emit(("progress", min(done, total), total, active, speed, size))

    def _on_retry(self, what):
        return lambda n, mx, delay, exc: self.log("warn", "log.retry", what=what, n=n, max=mx, delay=delay, err=short_error(exc))

    def api(self, path, data=None, what=""):
        """Chamada à API respeitando as tentativas/backoff configurados."""
        return api_json(f"{API}{path}", data, retries=self.cfg.retries, base_delay=self.cfg.backoff,
                        cancel=self.stop, on_retry=self._on_retry(what or path))

    # ------------------------------------------------------------------ fila de jobs
    def _submit(self, key, fn, *args):
        with self._lock:
            if self.stop.is_set() or key in self._keys:
                return False
            self._keys.add(key)
            self._pending += 1
            self._total_jobs += 1
        self.pool.submit(self._run_job, key, fn, *args)
        return True

    def _run_job(self, key, fn, *args):
        first = args[0] if args else None
        if isinstance(first, dict):   # job de conversão: usa o nome do JAR
            label = first.get("name") or Path(first.get("file", key)).name
        else:
            label = str(first if isinstance(first, str) else key)
        try:
            if not self.stop.is_set():
                fn(key, *args)
        except HashMismatch:
            pass  # já tratado dentro do job
        except Cancelled:
            pass
        except urllib.error.HTTPError as exc:
            self.report.add("failed", label, kind="mod", detail=f"HTTP {exc.code}")
            self.log("err", "log.http_err", code=exc.code, src=label)
        except urllib.error.URLError as exc:
            reason = exc.reason
            self.report.add("failed", label, detail=str(reason))
            if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
                self.log("err", "log.ssl_err", slug=label, err=reason)
            else:
                self.log("err", "log.net_err", slug=label, err=reason)
        except Exception as exc:
            self.report.add("failed", label, detail=str(exc))
            self.log("err", "log.err", slug=label, err=exc)
        finally:
            with self._cv:
                self._frac.pop(key, None)
                self._speed.pop(key, None)
                self._bytes.pop(key, None)
                self._active.discard(key)
                self._done_jobs += 1
                self._pending -= 1
                self._cv.notify_all()
            self.emit(("file_done", key))
            self.emit_progress(force=True)

    def _wait(self):
        with self._cv:
            while self._pending > 0:
                self._cv.wait(0.25)

    # ------------------------------------------------------------------ execução principal
    def run(self, links, local_paths=(), convert=False, auto_deps_for_local=True, refs=()):
        """Executa tudo e devolve o Report (também enviado como evento "finished").

        ``links``: URLs do Modrinth; ``refs``: IDs/slugs de projeto diretos (usado por "Atualizar todos")."""
        cfg = self.cfg
        try:
            cfg.folder.mkdir(parents=True, exist_ok=True)
            self.pool = ThreadPoolExecutor(max_workers=max(1, min(8, cfg.workers)), thread_name_prefix="mbd")
            manifests = self._read_local(local_paths)

            for raw in links:
                try:
                    hint, slug = parse_project_url(raw)
                except ValueError as exc:
                    self.report.add("failed", raw, detail=str(exc))
                    self.log("err", "log.invalid_link", raw=raw, err=exc)
                    continue
                if not self._submit(slug.lower(), self._project_job, slug, hint, None):
                    self.log("warn", "log.dup_link", slug=slug)

            for ref in refs:
                self._submit(str(ref).lower(), self._project_job, str(ref), None, None)

            if convert and manifests:
                self.log("accent", "log.convert_start", n=len(manifests), mc=cfg.game_version, loader=cfg.loader)
                for manifest in manifests:
                    self._submit("convert:" + manifest["file"], self._convert_job, manifest)

            self._queue_missing_local_deps(manifests, cfg.auto_deps and auto_deps_for_local)
            self._wait()
            if self.stop.is_set():
                self.log("warn", "log.stop")
        except Exception as exc:
            self.report.add("failed", "?", detail=str(exc))
            self.log("err", "log.fatal", err=exc)
            self.report.log_lines.append(("muted", traceback.format_exc()))
        finally:
            if self.pool:
                self.pool.shutdown(wait=True)
            try:
                self._final_conflict_check()
            except Exception:
                pass
            self.report.finished = time.time()
            self.report.stopped = self.stop.is_set()
            self.emit(("finished", self.report))
        return self.report

    def _read_local(self, local_paths):
        manifests = []
        if not local_paths:
            return manifests
        self.log("muted", "log.reading_jars")
        for jar in local_paths:
            if self.stop.is_set():
                break
            m = read_manifest(jar)
            manifests.append(m)
            self.log("muted", "log.jar", name=Path(jar).name, id=m.get("id") or tr("md.unknown_id"),
                     ver=m.get("version") or "?", loader=m.get("loader") or "?",
                     req=", ".join(m["required"]) or tr("log.none"))
            if m.get("error"):
                self.log("warn", "log.warn", msg=manifest_error(m))
        self.emit(("manifests", manifests))
        return manifests

    def _queue_missing_local_deps(self, manifests, resolve):
        if not manifests:
            return
        missing = missing_dependencies(manifests)
        if not missing:
            self.log("info", "log.missing_none")
            return
        self.log("warn", "log.missing_header")
        for dep, owners in missing.items():
            self.log("warn", "log.missing_item", dep=dep, owner=", ".join(owners))
        if resolve:
            for dep, owners in missing.items():
                self._submit("dep:" + dep.lower(), self._local_dep_job, dep, ", ".join(owners))

    def _final_conflict_check(self):
        """Depois de baixar mods, confere a pasta de destino (IDs duplicados / loaders misturados)."""
        if not any(i["kind"] == "mod" and i["status"] == "downloaded" for i in self.report.items):
            return
        jars = sorted(Path(self.cfg.folder).glob("*.jar"))
        if len(jars) < 2:
            return
        self.report.conflicts = detect_conflicts([read_manifest(j) for j in jars])
        log_conflicts(self.report.conflicts, self.log)

    # ------------------------------------------------------------------ jobs
    def _project_job(self, key, ref, hint, parent):
        project = self.api(f"/project/{urllib.parse.quote(str(ref), safe='')}", what=str(ref))
        self._process_project(key, project, hint, parent)

    def _convert_job(self, key, manifest):
        name = manifest.get("name") or Path(manifest["file"]).name
        if not manifest.get("id") and not manifest.get("name"):
            self.report.add("skipped", name, detail=tr("reason.unknown"))
            self.log("warn", "log.convert_skip", name=Path(manifest["file"]).name)
            return
        try:
            hit, candidates = self._find_project_for_manifest(manifest)
            if not hit:
                self.report.add("skipped", name, detail=tr("reason.unknown"))
                self.log("warn", "log.convert_unknown", name=name)
                if candidates:
                    self.log("muted", "log.suggestions", items=", ".join((h.get("title") or h.get("slug") or "?") for h in candidates[:5]))
                return
            self.log("accent", "log.convert_map", name=name, title=hit.get("title"), slug=hit.get("slug"))
            project = self.api(f"/project/{urllib.parse.quote(str(hit.get('project_id') or hit.get('slug')), safe='')}", what=name)
            self._process_project(key, project, "mod", None)
        except (urllib.error.URLError, HashMismatch, Cancelled):
            raise
        except Exception as exc:
            self.report.add("failed", name, detail=str(exc))
            self.log("err", "log.convert_err", name=name, err=exc)

    def _local_dep_job(self, key, dep, owner):
        try:
            hit, candidates = self._find_project(dep)
        except Exception as exc:
            self.log("err", "log.dep_lookup_fail", dep=dep, err=exc)
            return
        if not hit:
            self.log("warn", "log.dep_not_found", dep=dep)
            if candidates:
                self.log("muted", "log.suggestions", items=", ".join(h.get("title", "?") for h in candidates[:4]))
            return
        self.log("info", "log.dep_added", title=hit.get("title") or hit.get("slug"), owner=owner)
        project = self.api(f"/project/{urllib.parse.quote(str(hit.get('project_id') or hit.get('slug')), safe='')}", what=dep)
        self._process_project(key, project, "mod", None)

    def _queue_dependencies(self, version, parent_title):
        for dep in version.get("dependencies") or []:
            if dep.get("dependency_type") != "required":
                continue
            ref = dep.get("project_id")
            if not ref and dep.get("version_id"):
                try:
                    ref = self.api(f"/version/{dep['version_id']}", what="dependency").get("project_id")
                except Exception as exc:
                    self.log("warn", "log.dep_query_fail", dep=dep.get("version_id"), err=exc)
                    continue
            if ref:
                self._submit(str(ref).lower(), self._project_job, ref, None, parent_title)

    # ------------------------------------------------------------------ coração: um projeto
    def _process_project(self, key, project, hint, parent):
        cfg = self.cfg
        pid = project.get("id")
        if not pid:
            raise ValueError("API não retornou ID do projeto")
        with self._lock:
            if pid in self._pids:      # mesmo projeto já tratado por outro link/dependência
                return
            self._pids.add(pid)
        slug = project.get("slug") or pid
        title = project.get("title") or slug
        kind = project_kind(project, hint)
        if parent:
            self.log("info", "log.dep_needs", parent=parent, title=title)

        target_label = f"{cfg.game_version} + {cfg.loader}" if kind == "mod" else cfg.game_version
        versions = compatible_versions(pid, cfg.game_version, cfg.loader, kind, retries=cfg.retries,
                                       base_delay=cfg.backoff, cancel=self.stop, on_retry=self._on_retry(title))
        chosen, fallback = pick_version(versions, cfg.stable_only)
        if not chosen:
            self.report.add("incompatible", title, slug, kind, tr("reason.no_version", target=target_label))
            self.log("warn", "log.incompatible", title=title, target=target_label)
            return
        if fallback:
            self.log("warn", "log.stable_fallback", title=title, target=target_label, kind=fallback)
        if cfg.auto_deps:
            self._queue_dependencies(chosen, title)

        fileinfo = choose_file(chosen)
        if not fileinfo or not fileinfo.get("url"):
            self.report.add("failed", title, slug, kind, tr("reason.no_file"))
            self.log("err", "log.no_file", title=title)
            return
        version_label = chosen.get("version_number", "?")
        filename = safe_filename(fileinfo.get("filename") or f"{slug}.jar")
        folder = folder_for(kind, cfg.folder)
        target = folder / filename
        hashes = fileinfo.get("hashes") or {}
        want_sha1 = (hashes.get("sha1") or "").lower()

        # --- atualização inteligente: compara o SHA-1 do que já existe com o do Modrinth
        index = self._folder_index(folder)
        if want_sha1 and want_sha1 in index.by_hash:
            existing = index.by_hash[want_sha1]
            same_name = existing.name == filename
            self.log("warn", "log.exists_identical" if same_name else "log.exists_renamed", name=existing.name, title=title)
            self.report.add("skipped", title, slug, kind, tr("reason.exists"), existing.name, version_label)
            return
        if target.exists():
            if not want_sha1:
                self.log("warn", "log.exists_identical", name=filename)
                self.report.add("skipped", title, slug, kind, tr("reason.exists"), filename, version_label)
                return
            self.log("warn", "log.exists_differs", name=filename)

        self.log("accent", "log.downloading", title=title, ver=version_label, name=filename)
        with self._lock:
            self._active.add(key)
        self.emit(("file", key, filename, 0, fileinfo.get("size") or 0, 0.0))
        self.emit_progress(force=True)

        def on_progress(done, total, speed):
            with self._lock:
                self._frac[key] = (done / total) if total else 0.0
                self._speed[key], self._bytes[key] = speed, done
            self.emit(("file", key, filename, done, total, speed))
            self.emit_progress()

        try:
            result = download(fileinfo["url"], target, progress=on_progress,
                              expected={"sha1": hashes.get("sha1"), "sha512": hashes.get("sha512")},
                              expected_size=fileinfo.get("size") or 0, cancel=self.stop,
                              retries=cfg.retries, base_delay=cfg.backoff, on_retry=self._on_retry(filename))
        except HashMismatch as hm:
            self.log("err", "log.hash_bad", name=filename, algo=hm.algo.upper(), exp=hm.expected[:12], got=hm.actual[:12])
            self.report.add("corrupted", title, slug, kind, tr("reason.hash", algo=hm.algo.upper()), filename, version_label)
            raise
        with self._lock:
            self._bytes_finished += result["size"]
            self._bytes.pop(key, None)
            self._speed.pop(key, None)
            self._active.discard(key)
        if hashes.get("sha1") or hashes.get("sha512"):
            self.log("ok", "log.ok", name=target.name)
        else:
            self.log("warn", "log.ok_nohash", name=target.name)
        self.report.add("downloaded", title, slug, kind, "", filename, version_label)
        index.by_hash[result["sha1"]] = target
        self._retire_old_versions(index, pid, target)

    def _retire_old_versions(self, index, pid, keep):
        """Versão nova baixada: renomeia a(s) antiga(s) do mesmo projeto para ``.old`` (evita ID duplicado)."""
        for old in list(index.by_project.get(pid, [])):
            if old == keep or not old.exists():
                continue
            backup = old.with_name(old.name + ".old")
            try:
                if backup.exists():
                    backup.unlink()
                old.rename(backup)
                self.log("muted", "log.old_moved", name=backup.name)
                index.by_hash = {h: p for h, p in index.by_hash.items() if p != old}
            except OSError as exc:
                self.log("warn", "log.old_fail", name=old.name, err=exc)
        index.by_project[pid] = [keep]

    def _folder_index(self, folder):
        """Indexa (uma vez por pasta) o que já existe: hash → arquivo e projeto → arquivos."""
        with self._index_lock:
            if folder in self._indexes:
                return self._indexes[folder]
            index = FolderIndex()
            self._indexes[folder] = index
            files = []
            if folder.is_dir():
                files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jar", ".zip", ".mrpack")]
            by_path = {}
            for path in files:
                try:
                    h = file_hash(path)
                except OSError:
                    continue
                index.by_hash[h] = path
                by_path[h] = path
            if by_path:
                try:
                    found = self.api("/version_files", {"hashes": list(by_path), "algorithm": "sha1"}, what="version_files")
                    for h, version in (found or {}).items():
                        if h in by_path and version.get("project_id"):
                            index.by_project[version["project_id"]].append(by_path[h])
                except Exception as exc:
                    self.log("warn", "log.index_fail", err=exc)
            return index

    # ------------------------------------------------------------------ busca (conversão / dependências locais)
    def _find_project(self, dep_id):
        """Procura um projeto por ID/slug direto; se falhar, pela busca aceitando só correspondência exata."""
        try:
            direct = self.api(f"/project/{urllib.parse.quote(dep_id, safe='')}", what=dep_id)
            if direct.get("id") and project_kind(direct) == "mod":
                return {"project_id": direct["id"], "slug": direct.get("slug"), "title": direct.get("title")}, []
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 410):
                raise
        query = urllib.parse.urlencode({"query": dep_id, "limit": 30, "facets": json.dumps([["project_type:mod"]])})
        hits = self.api(f"/search?{query}", what=dep_id).get("hits", [])
        norm = re.sub(r"[^a-z0-9]", "", dep_id.lower())
        exact = {}
        for hit in hits:
            vals = [str(hit.get(k) or "") for k in ("slug", "project_id", "title")]
            if any(v.lower() == dep_id.lower() or (norm and re.sub(r"[^a-z0-9]", "", v.lower()) == norm) for v in vals):
                exact[hit.get("project_id")] = hit
        return (next(iter(exact.values())) if len(exact) == 1 else None), hits[:5]

    def _find_project_for_manifest(self, manifest):
        """Mapeia um JAR local para um projeto do Modrinth (ID direto, busca exata ou título único)."""
        local_id = str(manifest.get("id") or "").strip()
        if local_id:
            try:
                direct = self.api(f"/project/{urllib.parse.quote(local_id, safe='')}", what=local_id)
                if direct.get("id") and project_kind(direct) == "mod":
                    return {"project_id": direct["id"], "slug": direct.get("slug"), "title": direct.get("title")}, []
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 410):
                    raise
        queries = []
        for q in (manifest.get("id"), manifest.get("name"), Path(manifest["file"]).stem):
            if q and q not in queries:
                queries.append(q)
        all_hits, exact_hits = {}, {}
        for q in queries:
            try:
                query = urllib.parse.urlencode({"query": q, "limit": 20, "facets": json.dumps([["project_type:mod"]])})
                hits = self.api(f"/search?{query}", what=q).get("hits", [])
            except Exception as exc:
                self.log("warn", "log.search_fail", q=q, err=exc)
                continue
            norm = re.sub(r"[^a-z0-9]", "", q.lower())
            for hit in hits:
                pid = hit.get("project_id")
                if pid:
                    all_hits[pid] = hit
                fields = [str(hit.get(k) or "") for k in ("slug", "project_id", "title")]
                if any(v.lower() == q.lower() or (norm and re.sub(r"[^a-z0-9]", "", v.lower()) == norm) for v in fields):
                    exact_hits[pid] = hit
        if len(exact_hits) == 1:
            return next(iter(exact_hits.values())), list(all_hits.values())[:5]
        name = (manifest.get("name") or "").strip().lower()
        title_matches = [h for h in all_hits.values() if name and str(h.get("title", "")).strip().lower() == name]
        if len(title_matches) == 1:
            return title_matches[0], list(all_hits.values())[:5]
        return None, list(all_hits.values())[:5]


# =============================================================================================
# 6. Utilitários de apoio à interface
# =============================================================================================
def log_conflicts(conflicts, log):
    """Despeja conflitos no log (``log(kind, chave_i18n, **params)``)."""
    for c in conflicts:
        if c["kind"] == "duplicate_id":
            log("warn", "log.conflict_dup", id=c["id"], files=", ".join(c["files"]))
        else:
            log("warn", "log.conflict_loaders", loaders=", ".join(f"{k} ({v})" for k, v in c["loaders"].items()))


def conflict_text(c):
    """Texto legível (traduzido) de um conflito, para banners e relatórios."""
    if c["kind"] == "duplicate_id":
        return tr("md.conflict_dup", id=c["id"], files=", ".join(c["files"]))
    return tr("md.conflict_loaders", loaders=", ".join(f"{k}: {v}" for k, v in c["loaders"].items()))


def fetch_game_versions(include_snapshots=False, **retry):
    """Lista de versões do jogo vinda da API (mais novas primeiro)."""
    data = api_json(f"{API}/tag/game_version", **retry)
    data = sorted(data, key=lambda v: v.get("date", ""), reverse=True)
    out = []
    for v in data:
        if v.get("version") and (include_snapshots or v.get("version_type") == "release"):
            out.append(v["version"])
    return out


def fetch_previews(refs, game_version, loader, stable_only, cache, workers=4, **retry):
    """Dados para a pré-visualização de links: nome, ícone e versão compatível de cada projeto.

    ``refs`` = [(tipo_na_url, slug), ...]; ``cache`` é um dict compartilhado (projetos e ícones).
    """
    slugs = [s for _, s in refs]
    missing = [s for s in slugs if ("p", s.lower()) not in cache]
    if missing:
        projects = api_json(f"{API}/projects?{urllib.parse.urlencode({'ids': json.dumps(missing)})}", **retry)
        for p in projects:
            cache[("p", (p.get("slug") or "").lower())] = p
            cache[("p", (p.get("id") or "").lower())] = p
        for s in missing:
            cache.setdefault(("p", s.lower()), None)

    def one(item):
        hint, slug = item
        project = cache.get(("p", slug.lower()))
        row = {"slug": slug, "title": slug, "kind": "mod", "icon": None, "version": "", "vtype": "", "status": "notfound"}
        if not project:
            return row
        kind = project_kind(project, hint)
        row.update(slug=project.get("slug") or slug, title=project.get("title") or slug, kind=kind, status="ok")
        icon_url = project.get("icon_url")
        if icon_url:
            if ("i", icon_url) not in cache:
                try:
                    req = urllib.request.Request(icon_url, headers={"User-Agent": USER_AGENT})
                    with open_https(req, timeout=10) as r:
                        cache[("i", icon_url)] = r.read(400_000)
                except Exception:
                    cache[("i", icon_url)] = None
            row["icon"] = cache[("i", icon_url)]
        try:
            versions = compatible_versions(project["id"], game_version, loader, kind, **retry)
            chosen, _ = pick_version(versions, stable_only)
            if chosen:
                row.update(version=chosen.get("version_number", ""), vtype=chosen.get("version_type", ""))
            else:
                row["status"] = "incompatible"
        except Exception:
            row["status"] = "error"
        return row

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, refs))


def check_mod_updates(manifests, game_version, loader, stable_only=False, **retry):
    """Atualização inteligente por SHA-1: pergunta ao Modrinth qual versão cada JAR é e qual é a mais nova.

    Só considera arquivos do MESMO jogo e do MESMO loader (os demais ficam como "other_target"/"wrong_loader").
    status ∈ update | current | unknown | other_target | wrong_loader | none_for_target
    """
    hashes = [m["hash"] for m in manifests if m.get("hash")]
    current = api_json(f"{API}/version_files", {"hashes": hashes, "algorithm": "sha1"}, **retry) if hashes else {}
    results, eligible = [], []
    for m in manifests:
        cur = current.get(m.get("hash") or "")
        r = {"manifest": m, "status": "unknown", "current": cur, "latest": None}
        if cur:
            if loader not in (cur.get("loaders") or []):
                r["status"] = "wrong_loader"
            elif game_version not in (cur.get("game_versions") or []):
                r["status"] = "other_target"
            else:
                r["status"] = "pending"
                eligible.append(m["hash"])
        results.append(r)
    latest = {}
    if eligible:
        body = {"hashes": eligible, "algorithm": "sha1", "loaders": [loader], "game_versions": [game_version]}
        url = f"{API}/version_files/update"
        if stable_only:
            latest.update(api_json(url, {**body, "version_types": ["release"]}, **retry) or {})
            rest = [h for h in eligible if h not in latest]
            if rest:  # sem release estável: aceita beta/alpha
                latest.update(api_json(url, {**body, "hashes": rest, "version_types": ["release", "beta", "alpha"]}, **retry) or {})
        else:
            latest = api_json(url, body, **retry) or {}
    for r in results:
        if r["status"] != "pending":
            continue
        new, cur = latest.get(r["manifest"]["hash"]), r["current"]
        r["latest"] = new
        if not new:
            r["status"] = "none_for_target"
        elif new.get("id") != cur.get("id") and new.get("date_published", "") > cur.get("date_published", ""):
            r["status"] = "update"
        else:
            r["status"] = "current"
    return results


def parse_version(text):
    return tuple(int(x) for x in re.findall(r"\d+", str(text or "").lstrip("vV"))[:4])


def check_app_update(url, current=APP_VERSION):
    """Compara a versão do app com a mais nova publicada (GitHub releases ou JSON simples)."""
    data = api_json(url, retries=1, base_delay=0.5)
    latest = str(data.get("tag_name") or data.get("version") or data.get("name") or "")
    link = data.get("html_url") or data.get("url") or data.get("download_url") or ""
    return {"latest": latest.lstrip("vV"), "current": current, "url": link,
            "newer": bool(latest) and parse_version(latest) > parse_version(current)}


# =============================================================================================
# 7. Sistema: abrir pasta e notificação do Windows
# =============================================================================================
def open_folder(path):
    """Abre a pasta no Explorer (ou no gerenciador de arquivos do sistema). Retorna False se não existir."""
    path = str(path)
    if not os.path.isdir(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - abre no Explorer
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def toast_script(title, message):
    """Script PowerShell que mostra um toast nativo do Windows 10/11 (texto escapado para XML)."""
    def q(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
        "$n = $t.GetElementsByTagName('text')\n"
        f"$n.Item(0).AppendChild($t.CreateTextNode('{q(title)}')) | Out-Null\n"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{q(message)}')) | Out-Null\n"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($t)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)\n"
    )


def notify_windows(title, message):
    """Notificação do Windows (toast) sem dependências extras; falha em silêncio fora do Windows."""
    if sys.platform != "win32":
        return False
    try:
        encoded = base64.b64encode(toast_script(title, message).encode("utf-16-le")).decode("ascii")
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                          "-EncodedCommand", encoded], creationflags=0x08000000,  # CREATE_NO_WINDOW
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        return True
    except Exception:
        return False

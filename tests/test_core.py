"""Testes do núcleo (sem interface). Rode:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402
import i18n  # noqa: E402
from mock_modrinth import MockModrinth, make_jar  # noqa: E402


def run_engine(cfg, links, local=(), convert=False):
    events, stop = [], threading.Event()
    engine = core.Engine(cfg, events.append, stop)
    report = engine.run(links, list(local), convert)
    return report, events


class BaseCase(unittest.TestCase):
    def setUp(self):
        i18n.set_language("pt")
        self.mock = MockModrinth().start()
        core.API = self.mock.url + "/v2"
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.mock.stop()

    def cfg(self, **kw):
        base = dict(game_version="1.21.1", loader="fabric", folder=self.tmp / "out", workers=4, retries=3, backoff=0.02)
        base.update(kw)
        return core.Settings(**base)


class ParsingTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(core.parse_project_url("https://modrinth.com/mod/sodium"), ("mod", "sodium"))
        self.assertEqual(core.parse_project_url("modrinth.com/shader/complementary-reimagined/versions"), ("shader", "complementary-reimagined"))
        self.assertEqual(core.parse_project_url("https://www.modrinth.com/resourcepack/faithful-32x?x=1"), ("resourcepack", "faithful-32x"))
        self.assertEqual(core.parse_project_url("https://modrinth.com/datapack/vanilla-tweaks"), ("datapack", "vanilla-tweaks"))
        self.assertEqual(core.parse_project_url("https://modrinth.com/project/AANobbMI"), (None, "AANobbMI"))
        # linha no formato do botão "Copiar incompatíveis"
        self.assertEqual(core.parse_project_url("Sodium — https://modrinth.com/mod/sodium"), ("mod", "sodium"))
        with self.assertRaises(ValueError):
            core.parse_project_url("https://example.com/mod/sodium")
        with self.assertRaises(ValueError):
            core.parse_project_url("https://modrinth.com/user/jellysquid")

    def test_project_kind(self):
        self.assertEqual(core.project_kind({"project_type": "shader"}), "shader")
        self.assertEqual(core.project_kind({"project_type": "resourcepack"}), "resourcepack")
        self.assertEqual(core.project_kind({"project_type": "mod", "loaders": ["datapack"]}), "datapack")
        self.assertEqual(core.project_kind({"project_type": "mod", "loaders": ["fabric", "datapack"]}), "mod")
        self.assertEqual(core.project_kind({"project_type": "mod", "loaders": ["paper", "spigot"]}), "plugin")
        self.assertEqual(core.project_kind({"project_type": "mod", "loaders": ["fabric"]}), "mod")

    def test_pick_version_stable(self):
        vs = [{"id": "a", "version_type": "beta", "date_published": "2025-03"},
              {"id": "b", "version_type": "release", "date_published": "2025-01"},
              {"id": "c", "version_type": "alpha", "date_published": "2025-04"}]
        self.assertEqual(core.pick_version(vs, False)[0]["id"], "c")
        self.assertEqual(core.pick_version(vs, True), (vs[1], None))
        only_beta = [vs[0], vs[2]]
        v, fb = core.pick_version(only_beta, True)
        self.assertEqual((v["id"], fb), ("a", "beta"))
        self.assertEqual(core.pick_version([], True), (None, None))

    def test_retry_classification(self):
        import urllib.error
        self.assertTrue(core.is_retryable(urllib.error.HTTPError("u", 429, "x", {}, None)))
        self.assertTrue(core.is_retryable(urllib.error.HTTPError("u", 503, "x", {}, None)))
        self.assertFalse(core.is_retryable(urllib.error.HTTPError("u", 404, "x", {}, None)))
        self.assertTrue(core.is_retryable(urllib.error.URLError("conn refused")))
        self.assertTrue(core.is_retryable(TimeoutError()))

    def test_toast_script_escapes(self):
        script = core.toast_script("A'B", "<x> & y")
        self.assertIn("A''B", script)
        self.assertIn("&lt;x&gt; &amp; y", script)

    def test_conflicts(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "a.jar").write_bytes(make_jar("sodium", "1.0"))
        (tmp / "a-old.jar").write_bytes(make_jar("sodium", "0.9"))
        (tmp / "f.jar").write_bytes(make_jar("create", "1.0", "forge"))
        found = core.detect_conflicts([core.read_manifest(p) for p in sorted(tmp.glob("*.jar"))])
        kinds = {c["kind"] for c in found}
        self.assertEqual(kinds, {"duplicate_id", "mixed_loaders"})
        dup = next(c for c in found if c["kind"] == "duplicate_id")
        self.assertEqual(dup["id"], "sodium")
        self.assertEqual(dup["files"], ["a-old.jar", "a.jar"])

    def test_forge_toml_ignores_dependency_ids(self):
        import zipfile
        tmp = Path(tempfile.mkdtemp()) / "m.jar"
        toml = ('[[mods]]\nmodId="alpha"\nversion="2.0"\n[[mods]]\nmodId="beta"\n'
                '[[dependencies.alpha]]\nmodId="forge"\nmandatory=true\n[[dependencies.alpha]]\nmodId="lib"\nmandatory=true\n')
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("META-INF/mods.toml", toml)
        m = core.read_manifest(tmp)
        self.assertEqual((m["id"], m["all_ids"], m["loader"], m["required"]), ("alpha", ["alpha", "beta"], "forge", ["lib"]))


class DependencyAnalysisTests(unittest.TestCase):
    """Cenário real: módulos embutidos do Fabric API, apelidos 'provides' e separação mod x biblioteca."""

    def setUp(self):
        import io, json, zipfile
        self.tmp = Path(tempfile.mkdtemp())

        def jar(name, meta, nested=None):
            with zipfile.ZipFile(self.tmp / name, "w") as zf:
                zf.writestr("fabric.mod.json", json.dumps(meta))
                for path, inner in (nested or {}).items():
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w") as nz:
                        nz.writestr("fabric.mod.json", json.dumps(inner))
                    zf.writestr(path, buf.getvalue())

        jar("fabric-api.jar", {"id": "fabric-api", "name": "Fabric API", "version": "0.1", "provides": ["fabric"],
                               "jars": [{"file": "META-INF/jars/fabric-resource-loader-v0.jar"}]},
            {"META-INF/jars/fabric-resource-loader-v0.jar": {"id": "fabric-resource-loader-v0", "version": "1"},
             "META-INF/jars/fabric-api-base.jar": {"id": "fabric-api-base", "version": "1"}})
        jar("cloth.jar", {"id": "cloth-config", "name": "Cloth Config", "version": "1", "provides": ["cloth-config2"],
                          "custom": {"modmenu": {"badges": ["library"]}}})
        jar("balm.jar", {"id": "balm", "name": "Balm", "version": "1", "provides": ["balm-fabric"]})
        jar("bclib.jar", {"id": "bclib", "name": "BCLib", "version": "1", "depends": {"fabric-api-base": "*"}})
        jar("nether.jar", {"id": "betternether", "name": "Better Nether", "version": "1", "entrypoints": {"main": ["x.Y"]},
                           "depends": {"bclib": "*", "wunderlib": "*", "fabric-resource-loader-v0": "*", "fabricloader": "*"}})
        jar("slabs.jar", {"id": "kleeslabs", "name": "KleeSlabs", "version": "1", "entrypoints": {"main": ["x.Y"]},
                          "depends": {"balm-fabric": "*", "cloth-config2": "*", "fabric": "*"}})
        jar("camera.jar", {"id": "camera", "name": "CameraOverhaul", "version": "1", "entrypoints": {"client": ["x.Y"]},
                           "depends": {"fabric-command-api-v2": "*", "ghost-lib": "*"}})
        self.manifests = [core.read_manifest(p) for p in sorted(self.tmp.glob("*.jar"))]
        self.info = core.analyze_dependencies(self.manifests)

    def test_provides_and_nested_jars_are_not_missing(self):
        # só o que realmente não existe aparece como ausente
        self.assertEqual(self.info["missing"], {"ghost-lib": ["CameraOverhaul"], "wunderlib": ["Better Nether"]})

    def test_fabric_api_module_fallback(self):
        # 'fabric-command-api-v2' não está embutido no jar de teste, mas o Fabric API está instalado
        self.assertNotIn("fabric-command-api-v2", self.info["missing"])

    def test_fabric_api_missing_is_reported_when_not_installed(self):
        only = [m for m in self.manifests if m["name"] == "KleeSlabs"]
        self.assertEqual(core.analyze_dependencies(only)["missing"].keys(), {"balm-fabric", "cloth-config2", "fabric"})

    def test_libraries_vs_mods(self):
        names = {Path(m["file"]).name: m for m in self.manifests}
        libs = {Path(f).name for f in self.info["libraries"]}
        self.assertEqual(libs, {"cloth.jar", "bclib.jar", "balm.jar", "fabric-api.jar"})
        self.assertNotIn("nether.jar", libs)
        by = self.info["required_by"]
        self.assertEqual(by[names["bclib.jar"]["file"]], ["Better Nether"])
        self.assertEqual(by[names["balm.jar"]["file"]], ["KleeSlabs"])

    def test_nested_ids_do_not_create_false_duplicates(self):
        self.assertEqual([c for c in core.detect_conflicts(self.manifests) if c["kind"] == "duplicate_id"], [])


class DownloadTests(BaseCase):
    def _file(self, name="x.jar", content=b"hello world" * 5000):
        self.mock.files[name] = content
        import hashlib
        return (f"{self.mock.url}/files/{name}", {"sha1": hashlib.sha1(content).hexdigest(),
                                                  "sha512": hashlib.sha512(content).hexdigest()}, content)

    def test_progress_and_hash_ok(self):
        url, hashes, content = self._file()
        self.mock.file_delay = 0.6
        ticks = []
        res = core.download(url, self.tmp / "x.jar", progress=lambda d, t, s: ticks.append((d, t, s)), expected=hashes)
        self.assertEqual((self.tmp / "x.jar").read_bytes(), content)
        self.assertEqual(res["size"], len(content))
        self.assertGreaterEqual(len(ticks), 3)                       # progresso em tempo real
        self.assertEqual(ticks[-1][0], ticks[-1][1])                 # termina em 100%
        self.assertTrue(any(s > 0 for _, _, s in ticks))             # velocidade medida
        self.assertFalse((self.tmp / "x.jar.part").exists())

    def test_hash_mismatch_discards_file(self):
        url, hashes, _ = self._file()
        self.mock.corrupt.add("x.jar")
        with self.assertRaises(core.HashMismatch) as ctx:
            core.download(url, self.tmp / "x.jar", expected=hashes)
        self.assertEqual(ctx.exception.algo, "sha1")
        self.assertFalse((self.tmp / "x.jar").exists())
        self.assertFalse((self.tmp / "x.jar.part").exists())

    def test_retry_on_503_and_429(self):
        url, hashes, content = self._file()
        self.mock.flaky["file503"] = 1
        self.mock.flaky["file429"] = 1
        retries = []
        core.download(url, self.tmp / "x.jar", expected=hashes, retries=3, base_delay=0.02,
                      on_retry=lambda n, m, d, e: retries.append((n, round(d, 2), core.short_error(e))))
        self.assertEqual((self.tmp / "x.jar").read_bytes(), content)
        self.assertEqual([r[2] for r in retries], ["HTTP 503", "HTTP 429"])
        self.assertLess(retries[0][1], retries[1][1] + 0.5)           # espera cresce (backoff)

    def test_retry_gives_up(self):
        url, hashes, _ = self._file()
        self.mock.flaky["file503"] = 99
        with self.assertRaises(Exception):
            core.download(url, self.tmp / "x.jar", expected=hashes, retries=2, base_delay=0.01)
        self.assertEqual(self.mock.hits.count("/files/x.jar"), 3)     # 1 tentativa + 2 retries

    def test_404_is_not_retried(self):
        with self.assertRaises(Exception):
            core.download(self.mock.url + "/files/nothing.jar", self.tmp / "n.jar", retries=3, base_delay=0.01)
        self.assertEqual(self.mock.hits.count("/files/nothing.jar"), 1)

    def test_backoff_growth(self):
        d = [core.retry_delay(i, ValueError(), 1.0) for i in range(3)]
        self.assertTrue(1.0 <= d[0] < 1.5 and 2.0 <= d[1] < 2.5 and 4.0 <= d[2] < 4.5)


class EngineTests(BaseCase):
    def populate(self, n=10):
        lib = self.mock.add_project("fabric-api", "Fabric API")
        self.mock.add_version("fabric-api", "0.1.0")
        for i in range(n):
            slug = f"mod{i}"
            self.mock.add_project(slug)
            self.mock.add_version(slug, "1.0.0", deps=[lib])
        return lib

    def test_parallel_is_faster_and_correct(self):
        self.populate(12)
        self.mock.file_delay = 0.4
        links = [f"https://modrinth.com/mod/mod{i}" for i in range(12)]
        t0 = time.time()
        r1, _ = run_engine(self.cfg(workers=1, folder=self.tmp / "seq"), links)
        seq = time.time() - t0
        t0 = time.time()
        r4, ev = run_engine(self.cfg(workers=4, folder=self.tmp / "par"), links)
        par = time.time() - t0
        self.assertEqual(r4.counts["downloaded"], 13)                  # 12 mods + Fabric API (dependência única)
        self.assertEqual(r4.counts["failed"], 0)
        self.assertEqual(len(list((self.tmp / "par").glob("*.jar"))), 13)
        self.assertLess(par, seq * 0.55, f"paralelo {par:.2f}s vs sequencial {seq:.2f}s")
        progress = [e for e in ev if e[0] == "progress"]
        self.assertTrue(progress)
        values = [p[1] for p in progress]
        self.assertLessEqual(max(values), progress[-1][2] + 1e-9)
        self.assertAlmostEqual(progress[-1][1], progress[-1][2], places=3)   # 100% no fim
        self.assertTrue(any(p[3] > 1 for p in progress), "nunca houve mais de 1 download ativo")
        self.assertTrue(any(e[0] == "file" for e in ev))

    def test_dependency_not_downloaded_twice(self):
        self.populate(3)
        rep, _ = run_engine(self.cfg(), [f"https://modrinth.com/mod/mod{i}" for i in range(3)] + ["https://modrinth.com/mod/fabric-api"])
        self.assertEqual(rep.counts["downloaded"], 4)
        self.assertEqual(self.mock.hits.count("/files/fabric-api-0.1.0.jar"), 1)

    def test_no_auto_deps(self):
        self.populate(2)
        rep, _ = run_engine(self.cfg(auto_deps=False), ["https://modrinth.com/mod/mod0"])
        self.assertEqual(rep.counts["downloaded"], 1)
        self.assertFalse((self.tmp / "out" / "fabric-api-0.1.0.jar").exists())

    def test_incompatible_failed_corrupted_and_report(self):
        self.mock.add_project("oldmod")
        self.mock.add_version("oldmod", "1.0.0", games=("1.19",))
        self.mock.add_project("bad")
        self.mock.add_version("bad", "1.0.0")
        self.mock.corrupt.add("bad-1.0.0.jar")
        self.mock.add_project("good")
        self.mock.add_version("good", "1.0.0")
        rep, ev = run_engine(self.cfg(), ["https://modrinth.com/mod/oldmod", "https://modrinth.com/mod/bad",
                                          "https://modrinth.com/mod/good", "https://modrinth.com/mod/ghost",
                                          "https://example.com/x", "https://modrinth.com/mod/good"])
        c = rep.counts
        self.assertEqual((c["downloaded"], c["incompatible"], c["corrupted"]), (1, 1, 1))
        self.assertEqual(c["failed"], 3)                              # corrompido + ghost(404) + link inválido
        self.assertFalse((self.tmp / "out" / "bad-1.0.0.jar").exists())
        self.assertEqual(rep.incompatible_lines(), ["Oldmod — https://modrinth.com/mod/oldmod"])
        self.assertTrue(any("FALHA DE SEGURANÇA" in t for k, t in rep.log_lines if k == "err"))
        fin = [e for e in ev if e[0] == "finished"]
        self.assertEqual(len(fin), 1)

    def test_other_project_types_go_to_right_folders(self):
        self.mock.add_project("shady", ptype="shader", loaders=("iris",))
        self.mock.add_version("shady", "1.0.0", loaders=("iris",), content=b"shaderzip", filename="shady.zip")
        self.mock.add_project("pretty", ptype="resourcepack", loaders=("minecraft",))
        self.mock.add_version("pretty", "1.0.0", loaders=("minecraft",), content=b"rpzip", filename="pretty.zip")
        self.mock.add_project("tweaks", ptype="mod", loaders=("datapack",))
        self.mock.add_version("tweaks", "1.0.0", loaders=("datapack",), content=b"dpzip", filename="tweaks.zip")
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0")
        rep, _ = run_engine(self.cfg(), ["https://modrinth.com/shader/shady", "https://modrinth.com/resourcepack/pretty",
                                         "https://modrinth.com/datapack/tweaks", "https://modrinth.com/project/sodium"])
        out = self.tmp / "out"
        self.assertEqual(rep.counts["downloaded"], 4, rep.log_text())
        self.assertTrue((out / "shaderpacks" / "shady.zip").exists())
        self.assertTrue((out / "resourcepacks" / "pretty.zip").exists())
        self.assertTrue((out / "datapacks" / "tweaks.zip").exists())
        self.assertTrue((out / "sodium-1.0.0.jar").exists())
        self.assertEqual({i["kind"] for i in rep.items}, {"shader", "resourcepack", "datapack", "mod"})

    def test_stable_only_with_fallback(self):
        self.mock.add_project("stab")
        self.mock.add_version("stab", "1.0.0", "release", "2025-01-01T00:00:00Z")
        self.mock.add_version("stab", "2.0.0-beta", "beta", "2025-06-01T00:00:00Z")
        self.mock.add_project("betaonly")
        self.mock.add_version("betaonly", "0.1-beta", "beta", "2025-06-01T00:00:00Z")
        rep, _ = run_engine(self.cfg(stable_only=True), ["https://modrinth.com/mod/stab", "https://modrinth.com/mod/betaonly"])
        names = {p.name for p in (self.tmp / "out").glob("*.jar")}
        self.assertEqual(names, {"stab-1.0.0.jar", "betaonly-0.1-beta.jar"})
        self.assertTrue(any("sem release estável" in t for _, t in rep.log_lines))
        rep2, _ = run_engine(self.cfg(stable_only=False, folder=self.tmp / "out2"), ["https://modrinth.com/mod/stab"])
        self.assertEqual({p.name for p in (self.tmp / "out2").glob("*.jar")}, {"stab-2.0.0-beta.jar"})

    def test_smart_update_skip_then_replace_old(self):
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0", date="2025-01-01T00:00:00Z")
        cfg = self.cfg()
        r1, _ = run_engine(cfg, ["https://modrinth.com/mod/sodium"])
        self.assertEqual(r1.counts["downloaded"], 1)
        r2, _ = run_engine(cfg, ["https://modrinth.com/mod/sodium"])           # nada mudou: SHA-1 idêntico
        self.assertEqual((r2.counts["downloaded"], r2.counts["skipped"]), (0, 1))
        self.assertEqual(self.mock.hits.count("/files/sodium-1.0.0.jar"), 1)
        self.mock.add_version("sodium", "2.0.0", date="2025-06-01T00:00:00Z")   # versão nova publicada
        r3, _ = run_engine(cfg, ["https://modrinth.com/mod/sodium"])
        self.assertEqual(r3.counts["downloaded"], 1)
        out = self.tmp / "out"
        self.assertTrue((out / "sodium-2.0.0.jar").exists())
        self.assertTrue((out / "sodium-1.0.0.jar.old").exists())                # antiga guardada como .old
        self.assertFalse((out / "sodium-1.0.0.jar").exists())
        self.assertEqual(r3.conflicts, [])                                      # sem ID duplicado

    def test_same_filename_different_hash_is_redownloaded(self):
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0")
        out = self.tmp / "out"
        out.mkdir()
        (out / "sodium-1.0.0.jar").write_bytes(b"tampered")
        rep, _ = run_engine(self.cfg(), ["https://modrinth.com/mod/sodium"])
        self.assertEqual(rep.counts["downloaded"], 1)
        self.assertNotEqual((out / "sodium-1.0.0.jar").read_bytes(), b"tampered")

    def test_conflict_detected_after_download(self):
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0")
        out = self.tmp / "out"
        out.mkdir()
        (out / "manual-sodium.jar").write_bytes(make_jar("sodium", "0.0.1"))      # mesmo ID, arquivo desconhecido
        (out / "forgey.jar").write_bytes(make_jar("forgey", "1", "forge"))
        rep, _ = run_engine(self.cfg(), ["https://modrinth.com/mod/sodium"])
        kinds = {c["kind"] for c in rep.conflicts}
        self.assertEqual(kinds, {"duplicate_id", "mixed_loaders"})
        self.assertTrue(any("CONFLITO" in t for _, t in rep.log_lines))

    def test_api_429_is_retried(self):
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0")
        self.mock.flaky["api429"] = 2
        rep, _ = run_engine(self.cfg(), ["https://modrinth.com/mod/sodium"])
        self.assertEqual(rep.counts["downloaded"], 1)
        self.assertTrue(any("RETRY" in t for _, t in rep.log_lines))

    def test_convert_and_local_missing_deps(self):
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0")
        self.mock.add_project("libx", "Libx")
        self.mock.add_version("libx", "1.0.0")
        src = self.tmp / "src"
        src.mkdir()
        import zipfile, json
        with zipfile.ZipFile(src / "sodium-old.jar", "w") as zf:
            zf.writestr("fabric.mod.json", json.dumps({"id": "sodium", "name": "Sodium", "version": "0.1",
                                                       "depends": {"libx": "*", "fabricloader": "*"}}))
        rep, _ = run_engine(self.cfg(), [], [src / "sodium-old.jar"], convert=True)
        self.assertEqual(rep.counts["downloaded"], 2, rep.log_text())          # sodium convertido + libx (dep. ausente)
        self.assertTrue((self.tmp / "out" / "libx-1.0.0.jar").exists())

    def test_stop_before_work(self):
        self.populate(3)
        events, stop = [], threading.Event()
        stop.set()
        rep = core.Engine(self.cfg(), events.append, stop).run(["https://modrinth.com/mod/mod0"])
        self.assertTrue(rep.stopped)
        self.assertEqual(rep.counts["downloaded"], 0)


class ApiHelpersTests(BaseCase):
    def test_game_versions(self):
        self.assertEqual(core.fetch_game_versions(False), ["26.1", "1.21.1", "1.20.1"])
        self.assertEqual(core.fetch_game_versions(True)[:2], ["26.1", "25w01a"])

    def test_previews(self):
        self.mock.add_project("sodium", "Sodium", icon=True)
        self.mock.add_version("sodium", "0.6.0")
        self.mock.add_project("shady", "Shady", ptype="shader", loaders=("iris",))
        self.mock.add_version("shady", "2.0", loaders=("iris",))
        self.mock.add_project("oldy", "Oldy")
        self.mock.add_version("oldy", "1.0", games=("1.8",))
        rows = core.fetch_previews([("mod", "sodium"), ("shader", "shady"), ("mod", "oldy"), ("mod", "ghost")],
                                   "1.21.1", "fabric", False, {}, retries=1, base_delay=0.01)
        by = {r["slug"]: r for r in rows}
        self.assertEqual((by["sodium"]["title"], by["sodium"]["version"], by["sodium"]["status"]), ("Sodium", "0.6.0", "ok"))
        self.assertTrue(by["sodium"]["icon"])
        self.assertEqual((by["shady"]["kind"], by["shady"]["status"]), ("shader", "ok"))
        self.assertEqual(by["oldy"]["status"], "incompatible")
        self.assertEqual(by["ghost"]["status"], "notfound")

    def test_check_mod_updates(self):
        for slug in ("sodium", "lithium", "iris", "other"):
            self.mock.add_project(slug)
        self.mock.add_version("sodium", "1.0.0", date="2025-01-01T00:00:00Z")
        self.mock.add_version("sodium", "2.0.0", date="2025-06-01T00:00:00Z")
        self.mock.add_version("lithium", "1.0.0", date="2025-01-01T00:00:00Z")           # já atual
        self.mock.add_version("iris", "1.0.0", date="2025-01-01T00:00:00Z", games=("1.20.1",))   # outro jogo
        self.mock.add_version("other", "1.0.0", loaders=("forge",))                      # outro loader
        folder = self.tmp / "mods"
        folder.mkdir()
        for name in ("sodium-1.0.0.jar", "lithium-1.0.0.jar", "iris-1.0.0.jar", "other-1.0.0.jar"):
            (folder / name).write_bytes(self.mock.files[name])
        (folder / "unknown.jar").write_bytes(make_jar("mystery"))
        manifests = [core.read_manifest(p) for p in sorted(folder.glob("*.jar"))]
        res = {Path(r["manifest"]["file"]).name: r for r in core.check_mod_updates(manifests, "1.21.1", "fabric", retries=1)}
        self.assertEqual(res["sodium-1.0.0.jar"]["status"], "update")
        self.assertEqual(res["sodium-1.0.0.jar"]["latest"]["version_number"], "2.0.0")
        self.assertEqual(res["lithium-1.0.0.jar"]["status"], "current")
        self.assertEqual(res["iris-1.0.0.jar"]["status"], "other_target")
        self.assertEqual(res["other-1.0.0.jar"]["status"], "wrong_loader")
        self.assertEqual(res["unknown.jar"]["status"], "unknown")

    def test_check_mod_updates_stable_only(self):
        self.mock.add_project("sodium")
        self.mock.add_version("sodium", "1.0.0", "release", "2025-01-01T00:00:00Z")
        self.mock.add_version("sodium", "2.0.0-beta", "beta", "2025-06-01T00:00:00Z")
        m = [core.read_manifest(self._write("sodium-1.0.0.jar"))]
        r = core.check_mod_updates(m, "1.21.1", "fabric", stable_only=True, retries=1)[0]
        self.assertEqual(r["status"], "current")                                  # beta ignorada
        r = core.check_mod_updates(m, "1.21.1", "fabric", stable_only=False, retries=1)[0]
        self.assertEqual(r["status"], "update")

    def _write(self, name):
        p = self.tmp / name
        p.write_bytes(self.mock.files[name])
        return p

    def test_version_compare(self):
        self.assertTrue(core.parse_version("v5.1.0") > core.parse_version("5.0.9"))
        self.assertFalse(core.parse_version("5.0.0") > core.parse_version("5.0.0"))
        self.assertTrue(core.parse_version("10.0") > core.parse_version("9.9.9"))


if __name__ == "__main__":
    unittest.main()

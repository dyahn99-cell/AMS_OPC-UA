"""Reproducible Python checks in a guarded, synthetic temporary checkout.

Run this script, not unittest/import bridge in the live installation. This is an
accidental-I/O guard for trusted tests, NOT an OS sandbox for hostile Python/native
code. It does not start a server, worker, Node, or packaging subprocess.
"""
from __future__ import annotations

import argparse
import concurrent.futures.thread
import contextlib
import ctypes  # Load stdlib support before prohibiting later native-library access.
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import traceback
import unittest
from urllib.parse import urlsplit
from urllib.request import url2pathname


ROOT = Path(__file__).resolve().parents[1]
SCOPE = {
    "active_sources": "root Python/JS/HTML/BAT/spec/manifests/docs; app/tests/scripts *.py; assets text code",
    "state": "root config/nodes/runtime_state/schedules including backups; db/logs/iodd_library files",
    "git": ".git/index and .git/HEAD (or .git pointer file)",
    "excluded": "node_modules, vendor, build, dist, bytecode, source backups, binary assets; NOT a full-repo hash",
}


def walk_files(directory):
    if not directory.exists():
        return
    if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
        raise RuntimeError(f"Refusing linked directory: {directory}")
    for parent, directories, files in os.walk(directory, followlinks=False):
        directories[:] = sorted(name for name in directories if name != "__pycache__")
        for name in directories + files:
            item = Path(parent) / name
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise RuntimeError(f"Refusing linked artifact: {item}")
        yield from (Path(parent) / name for name in sorted(files))


def meaningful_files():
    for path in sorted(ROOT.iterdir()):
        if path.is_file() and (
            path.suffix in {".py", ".js", ".html", ".bat", ".spec", ".json", ".txt", ".md", ".lock"}
            or path.name in {".gitignore", ".git"}
            or path.name.startswith(("config.json.", "nodes.json.", "runtime_state.json.", "schedules.json."))
        ):
            yield path
    for folder in ("app", "tests", "scripts"):
        yield from (p for p in walk_files(ROOT / folder) if p.suffix == ".py")
    yield from (p for p in walk_files(ROOT / "assets") if p.suffix in {".js", ".css", ".html", ".json", ".svg"})
    for folder in ("db", "logs", "iodd_library"):
        yield from walk_files(ROOT / folder)
    for name in ("index", "HEAD"):
        path = ROOT / ".git" / name
        if path.is_file():
            yield path


def integrity_snapshot():
    result = {}
    for path in meaningful_files():
        if path.is_symlink():
            raise RuntimeError(f"Refusing linked artifact: {path}")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"Artifact changed while hashing: {path.relative_to(ROOT)}")
        result[str(path.relative_to(ROOT))] = (digest.hexdigest(), after.st_size, after.st_mtime_ns)
    return result


class OfflineViolation(PermissionError):
    pass


class OfflineGuard:
    def __init__(self, sandbox, scratch):
        self.sandbox, self.scratch = sandbox.resolve(), scratch.resolve()
        self.events = []
        self.phase = "selfcheck"
        self.integrity_read = False
        self.cleaning = False
        self.thread_entry = threading.local()

    def reject(self, event, args=()):
        # Avoid recording config contents, process environments, or passwords.
        self.events.append({"phase": self.phase, "event": event})
        raise OfflineViolation(f"OFFLINE GUARD: {event}")

    def path(self, value):
        if value is None or isinstance(value, int):
            return None
        try:
            text = os.fsdecode(value)
            if text.startswith("file:"):
                uri = urlsplit(text)
                if uri.netloc:
                    return None
                text = url2pathname(uri.path)
            if text.startswith(("\\\\", "//")):
                return None  # UNC/device paths can reach outside the machine.
            return Path(text).resolve()
        except (ValueError, TypeError, OSError):
            return None

    def writable(self, value):
        path = self.path(value)
        root = self.scratch if self.cleaning else self.sandbox
        return path is not None and path.is_relative_to(root)

    def audit(self, event, args):
        if event.startswith("socket."):
            if self.phase == "imports" and event == "socket.__new__":
                frame = sys._getframe(1)
                while frame is not None:
                    if (frame.f_globals.get("__name__") == "urllib3.util.connection"
                            and frame.f_code.co_name == "_has_ipv6"):
                        self.reject("socket.__new__:urllib3-ipv6-probe")
                    frame = frame.f_back
            self.reject(event)
        if event in {
            "subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
            "os.exec", "os.startfile", "os.startfile/2", "os.kill", "os.killpg",
            "ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.call_function",
            "sqlite3.enable_load_extension", "sqlite3.load_extension", "os.link", "os.symlink",
        }:
            self.reject(event)
        if event == "open":
            path, mode, flags = args
            writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                       or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writing and not self.writable(path):
                self.reject("open:outside-write")
            if not writing and not isinstance(path, int):
                resolved = self.path(path)
                if resolved is None:
                    self.reject("open:nonlocal-read")
                if resolved.is_relative_to(ROOT) and not self.integrity_read:
                    self.reject("open:original-read")
        directory_fd = {"os.mkdir": 2, "os.remove": 1, "os.rmdir": 1, "os.chmod": 2,
                        "os.utime": 3, "os.chown": 3}
        if event in {*directory_fd, "os.truncate", "os.rename"}:
            paths = args[:2] if event == "os.rename" else args[:1]
            if any(not self.writable(path) for path in paths):
                self.reject(event + ":outside-write")
            indexes = (2, 3) if event == "os.rename" else (directory_fd[event],) if event in directory_fd else ()
            if any(len(args) > i and args[i] not in (None, -1) for i in indexes):
                self.reject(event + ":dir-fd")
        if event == "sqlite3.connect":
            if args[0] != ":memory:" and not self.writable(args[0]):
                self.reject("sqlite3.connect:outside")

    def install(self):
        sys.addaudithook(self.audit)
        original_connect = sqlite3.connect

        def connect(*args, **kwargs):
            conn = original_connect(*args, **kwargs)
            # SQLite's native temporary-file writes do not raise Python open events.
            conn.execute("PRAGMA temp_store=MEMORY")

            def authorize(action, first, second, database, trigger):
                if action == sqlite3.SQLITE_ATTACH:
                    self.events.append({"phase": self.phase, "event": "sqlite3.attach"})
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_PRAGMA and str(first).lower() in {"temp_store_directory", "data_store_directory"}:
                    self.events.append({"phase": self.phase, "event": "sqlite3.pragma-directory"})
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            conn.set_authorizer(authorize)
            return conn

        sqlite3.connect = sqlite3.dbapi2.connect = connect
        original_start = threading.Thread.start

        def start(thread, *args, **kwargs):
            if getattr(thread, "_target", None) is not concurrent.futures.thread._worker:
                self.reject("thread.start")
            self.thread_entry.allowed = True
            try:
                return original_start(thread, *args, **kwargs)
            finally:
                self.thread_entry.allowed = False

        threading.Thread.start = start
        import _thread
        for module in (_thread, threading):
            for name in ("start_new_thread", "start_joinable_thread", "_start_new_thread", "_start_joinable_thread"):
                original = getattr(module, name, None)
                if original is None:
                    continue

                def guarded_start(*args, _original=original, **kwargs):
                    if not getattr(self.thread_entry, "allowed", False):
                        self.reject("thread.raw-start")
                    return _original(*args, **kwargs)

                setattr(module, name, guarded_start)

    def selfcheck(self, protected):
        probe = self.sandbox / "probe"
        probe.mkdir()
        local = probe / "local.txt"
        local.write_text("synthetic", encoding="utf-8")
        checks = {
            "socket creation": (lambda: socket.socket(), OfflineViolation),
            "DNS getaddrinfo": (lambda: socket.getaddrinfo("offline.invalid", 9), OfflineViolation),
            "DNS gethostbyname": (lambda: socket.gethostbyname("offline.invalid"), OfflineViolation),
            "child process": (lambda: subprocess.Popen([sys.executable, "-c", "raise SystemExit(99)"]), OfflineViolation),
            "shell process": (lambda: os.system("exit 99"), OfflineViolation),
            "outside write": (lambda: protected.write_text("must not change", encoding="utf-8"), OfflineViolation),
            "outside os.open": (lambda: os.open(protected, os.O_WRONLY), OfflineViolation),
            "outside mkdir": (lambda: (protected.parent / "new-directory").mkdir(), OfflineViolation),
            "outside unlink": (lambda: protected.unlink(), OfflineViolation),
            "outside rename destination": (lambda: os.replace(local, protected), OfflineViolation),
            "outside rename source": (lambda: os.replace(protected, local), OfflineViolation),
            "original read": (lambda: (ROOT / "README_CLEAN.md").read_bytes(), OfflineViolation),
            "outside sqlite": (lambda: sqlite3.connect(str(protected)), OfflineViolation),
            "outside sqlite URI": (lambda: sqlite3.connect(protected.as_uri() + "?mode=ro", uri=True), OfflineViolation),
            "background thread": (lambda: threading.Thread(target=lambda: None).start(), OfflineViolation),
        }
        import _thread
        checks["raw background thread"] = (lambda: _thread.start_new_thread(lambda: None, ()), OfflineViolation)
        for label, (action, error) in checks.items():
            event_count = len(self.events)
            try:
                result = action()
            except error:
                if len(self.events) != event_count + 1:
                    raise RuntimeError(f"Selfcheck did not reach guard: {label}")
            else:
                if hasattr(result, "close"):
                    result.close()
                raise RuntimeError(f"Guard selfcheck failed: {label}")
        sqlite_checks = [
            ("ATTACH DATABASE ? AS outside", (str(protected),), "sqlite3.attach"),
            ("VACUUM INTO ?", (str(protected.parent / "vacuum.db"),), "sqlite3.attach"),
            ("PRAGMA temp_store_directory='.'", (), "sqlite3.pragma-directory"),
        ]
        with contextlib.closing(sqlite3.connect(":memory:")) as conn:
            for sql, params, event in sqlite_checks:
                event_count = len(self.events)
                try:
                    conn.execute(sql, params)
                except sqlite3.DatabaseError:
                    if len(self.events) != event_count + 1 or self.events[-1]["event"] != event:
                        raise
                else:
                    raise RuntimeError(f"Guard selfcheck failed: {sql}")
        with contextlib.closing(sqlite3.connect(probe / "allowed.db")) as conn:
            conn.execute("CREATE TABLE fixture(value INTEGER)")
            conn.execute("INSERT INTO fixture VALUES(7)")
            conn.commit()
        with contextlib.closing(sqlite3.connect((probe / "allowed.db").as_uri() + "?mode=ro", uri=True)) as conn:
            assert conn.execute("SELECT value FROM fixture").fetchone() == (7,)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(abs, [-1, -2])) == [1, 2]
        assert protected.read_text(encoding="utf-8") == "protected fixture"
        shutil.rmtree(probe)
        return {"blocked_checks_passed": len(checks) + len(sqlite_checks), "allowed_sqlite_and_threadpool": True}


def copy_sources(work):
    for folder in ("app", "tests", "scripts"):
        for source in walk_files(ROOT / folder):
            if source.suffix == ".py":
                target = work / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    for source in ROOT.glob("*.py"):
        if source.is_symlink():
            raise RuntimeError(f"Refusing linked source: {source}")
        shutil.copyfile(source, work / source.name)


def report(label, value):
    print(label, json.dumps(value, ensure_ascii=True), flush=True)


def main():
    # Windows redirected output may default to cp949; diagnostics must not turn
    # an intentionally injected storage failure into a second encoding failure.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regressions-only", action="store_true",
                        help="Run only established regressions; explicitly omit stage-1 contract reproducers")
    parser.add_argument("--pattern", default="test_*.py", help="Explicit unittest filename pattern; all I/O guards remain active")
    args = parser.parse_args()
    report("TEST_PATTERN", args.pattern)
    sys.dont_write_bytecode = True
    if any(name == "app" or name.startswith("app.") or name == "bridge" for name in sys.modules):
        raise RuntimeError("Application already imported; use a fresh Python process")
    report("PYTHON", sys.version)
    report("INTEGRITY_SCOPE", SCOPE)
    before = integrity_snapshot()
    scratch = Path(tempfile.mkdtemp(prefix="ams-offline-")).resolve()
    sandbox = scratch / "sandbox"
    work = sandbox / "checkout"
    work.mkdir(parents=True)
    protected = scratch / "protected.txt"
    protected.write_text("protected fixture", encoding="utf-8")
    original_cwd = Path.cwd()
    guard = None
    passed = False
    changed = []
    try:
        copy_sources(work)
        temp = sandbox / "tmp"
        temp.mkdir()
        tempfile.tempdir = str(temp)
        os.environ.update(TMP=str(temp), TEMP=str(temp), TMPDIR=str(temp))
        # Do not leave the original checkout, script folder, or PYTHONPATH in import search.
        sys.path[:] = [str(work / "tests"), str(work)] + [entry for entry in sys.path if entry and not Path(entry).resolve().is_relative_to(ROOT)]
        os.chdir(work)
        guard = OfflineGuard(sandbox, scratch)
        guard.install()
        report("TEMP_CHECKOUT", str(work))
        report("GUARD_SELFCHECK", guard.selfcheck(protected))
        guard.phase = "fixtures"
        from offline_fixtures import write_synthetic_inputs
        write_synthetic_inputs(work)
        sys._ams_offline_checkout = str(work)
        compiled = 0
        for path in walk_files(work):
            if path.suffix == ".py":
                compile(path.read_bytes(), str(path), "exec")
                compiled += 1
        report("PYTHON_SYNTAX", {"compiled_in_memory": compiled, "bytecode_written": False})
        # Import under the guard; urllib3 may probe IPv6 socket availability and
        # receive PermissionError. Report that blocked dependency probe separately.
        guard.phase = "imports"
        from offline_fixtures import guarded_runtime
        runtime = guarded_runtime()
        import bridge
        assert bridge.app is runtime.app
        report("IMPORT_SMOKE", {"runtime_from_temporary_copy": True, "routes": len(runtime.app.routes), "lifespan_started": False})
        import_events = [e for e in guard.events if e["phase"] == "imports"]
        report("BLOCKED_IMPORT_PROBES", import_events)
        # Only the known dependency IPv6 availability probe is a tolerated blocked import.
        if any(e["event"] != "socket.__new__:urllib3-ipv6-probe" for e in import_events):
            raise RuntimeError("Unexpected I/O attempted during guarded imports")
        summaries = {}
        groups = [("regressions", work / "tests", args.pattern)]
        if not args.regressions_only:
            groups.append(("stage1_contracts", work / "tests" / "contracts", "stage1_*.py"))
        for label, directory, pattern in groups:
            guard.phase = label
            suite = unittest.TestLoader().discover(str(directory), pattern=pattern)
            result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
            summaries[label] = {
                "run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
                "unexpected_successes": len(result.unexpectedSuccesses), "ok": result.wasSuccessful(),
            }
            report(label.upper() + "_SUMMARY", summaries[label])
        # Even if a test catches an I/O violation, an unmocked attempt is not a pass.
        unexpected = [e for e in guard.events if e["phase"] not in {"selfcheck", "imports"}]
        passed = all(item["ok"] and item["run"] and not item["skipped"] and not item["expected_failures"]
                     for item in summaries.values()) and not unexpected
        report("UNEXPECTED_BLOCKED_ATTEMPTS", unexpected)
        report("NOT_RUN", (["stage1 contracts (explicit --regressions-only)"] if args.regressions_only else []) + [
            "ASGI/lifespan integration", "browser/UI", "Node syntax/fake session", "source launcher/frozen package smoke", "device/network tests"])
    except BaseException:
        traceback.print_exc()
        passed = False
    finally:
        if guard:
            guard.phase = "integrity"
            guard.integrity_read = True
        try:
            after = integrity_snapshot()
            changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
            report("ORIGINAL_INTEGRITY", {"files_before": len(before), "files_after": len(after), "changed": changed,
                                           "hash": "SHA-256 plus size/mtime; scoped, not full repository"})
        except BaseException:
            traceback.print_exc()
            passed = False
        finally:
            if guard:
                guard.integrity_read = False
                guard.cleaning = True
        if guard:
            report("BLOCKED_EVENTS", guard.events)
        os.chdir(original_cwd)
        try:
            shutil.rmtree(scratch)
            report("TEMP_CLEANUP", {"removed": True})
        except BaseException:
            traceback.print_exc()
            passed = False
    report("OFFLINE_RESULT", {"ok": passed and not changed, "scope": "regressions_only" if args.regressions_only else "regressions_and_stage1_contracts"})
    return 0 if passed and not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())

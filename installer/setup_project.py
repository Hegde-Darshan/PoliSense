#!/usr/bin/env python3
"""
PoliSense GUI Installer
Requires Python 3.10+ (tkinter from stdlib).

Usage:
  python installer/setup_project.py     (development)
  PoliSense-Setup.exe                   (built with PyInstaller, placed in project root)
"""

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── Project root detection ──────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    # Running as a PyInstaller .exe — the exe must be placed in the project root
    ROOT = Path(sys.executable).parent.resolve()
else:
    # installer/setup_project.py → one level up is the project root
    ROOT = Path(__file__).parent.parent.resolve()

# ── Version (read from pyproject.toml) ─────────────────────────────────────

def _read_version() -> str:
    try:
        text = (ROOT / "pyproject.toml").read_text("utf-8")
        m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return m.group(1) if m else "1.0.0"
    except Exception:
        return "1.0.0"

VERSION = _read_version()

# ── Steps ───────────────────────────────────────────────────────────────────

STEPS = [
    "Check Python version",
    "Set up environment files",
    "Create virtual environment",
    "Install dependencies",
    "Start PostgreSQL",
    "Wait for database",
    "Apply schema",
    "Import data",
]

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# ── Helpers ─────────────────────────────────────────────────────────────────

def parse_env_file(path: Path) -> dict:
    """Parse a .env file without the dotenv package."""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        value = raw.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        result[key.strip()] = value
    return result


def venv_executable(name: str) -> Path:
    if sys.platform == "win32":
        return ROOT / ".venv" / "Scripts" / f"{name}.exe"
    return ROOT / ".venv" / "bin" / name


def find_python() -> str:
    """Find the system Python when running as a frozen exe."""
    if getattr(sys, "frozen", False):
        for candidate in ("python", "python3", "python3.12", "python3.11", "python3.10"):
            found = shutil.which(candidate)
            if found:
                return found
        return "python"
    return sys.executable


def stream_subprocess(cmd, cwd: Path, on_line) -> int:
    """Run cmd and call on_line(text) for each stdout/stderr line."""
    proc = subprocess.Popen(
        cmd, cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        on_line(line.rstrip())
    proc.wait()
    return proc.returncode


# ── GUI ─────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk


class InstallerApp:
    C_HEADER_BG = "#1e2a4a"
    C_HEADER_FG = "#ffffff"
    C_HEADER_SUB = "#94a3b8"
    C_BG        = "#f7f8fc"
    C_PANEL_BG  = "#eef0f8"
    C_ACCENT    = "#2563eb"
    C_SUCCESS   = "#16a34a"
    C_ERROR     = "#dc2626"
    C_WARN_BG   = "#fffbeb"
    C_WARN_FG   = "#92400e"
    C_WARN_BTN  = "#d97706"
    C_LOG_BG    = "#0f172a"
    C_LOG_FG    = "#94a3b8"
    C_LOG_OK    = "#4ade80"
    C_LOG_ERR   = "#f87171"
    C_LOG_WARN  = "#fbbf24"
    C_LOG_HL    = "#38bdf8"
    C_STEP_IDLE = "#9ca3af"
    C_STEP_ACT  = "#2563eb"
    C_STEP_DONE = "#16a34a"
    C_STEP_ERR  = "#dc2626"
    C_SEP       = "#dde1ed"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"PoliSense Setup  —  v{VERSION}")
        self.root.geometry("720x570")
        self.root.resizable(False, False)
        self.root.configure(bg=self.C_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._q: queue.Queue = queue.Queue()
        self._secrets_ready = threading.Event()
        self._data_imported = False

        self._step_icon: list[tk.Label] = []
        self._step_lbl:  list[tk.Label] = []
        self._spinner_step = -1
        self._spinner_idx  = 0

        self._build()
        self._start_drain()
        self._pre_check()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build(self):
        self._build_header()
        self._build_body()
        self._build_progressbar()
        self._build_footer()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=self.C_HEADER_BG, height=70)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="P O L I S E N S E   —   S E T U P   I N S T A L L E R",
            bg=self.C_HEADER_BG, fg=self.C_HEADER_FG,
            font=("Segoe UI", 12, "bold"),
        ).pack(pady=(14, 2))
        tk.Label(
            hdr, text="RAG Pipeline for Policy Documents",
            bg=self.C_HEADER_BG, fg=self.C_HEADER_SUB,
            font=("Segoe UI", 9),
        ).pack()

    def _build_body(self):
        body = tk.Frame(self.root, bg=self.C_BG)
        body.pack(fill=tk.BOTH, expand=True)

        # Left: steps panel
        left = tk.Frame(body, bg=self.C_PANEL_BG, width=195)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        tk.Label(
            left, text="INSTALLATION STEPS",
            bg=self.C_PANEL_BG, fg="#64748b",
            font=("Segoe UI", 7, "bold"),
        ).pack(anchor=tk.W, padx=16, pady=(16, 10))

        for name in STEPS:
            row = tk.Frame(left, bg=self.C_PANEL_BG)
            row.pack(fill=tk.X, padx=10, pady=3)
            icon = tk.Label(
                row, text="○", width=2,
                bg=self.C_PANEL_BG, fg=self.C_STEP_IDLE,
                font=("Segoe UI", 11),
            )
            icon.pack(side=tk.LEFT, padx=(4, 0))
            lbl = tk.Label(
                row, text=name,
                bg=self.C_PANEL_BG, fg=self.C_STEP_IDLE,
                font=("Segoe UI", 9), anchor=tk.W,
            )
            lbl.pack(side=tk.LEFT, padx=6)
            self._step_icon.append(icon)
            self._step_lbl.append(lbl)

        # Vertical separator
        tk.Frame(body, bg=self.C_SEP, width=1).pack(side=tk.LEFT, fill=tk.Y)

        # Right: log panel
        right = tk.Frame(body, bg=self.C_LOG_BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._log_hdr = tk.Label(
            right, text="Installation Log",
            bg=self.C_LOG_BG, fg="#475569",
            font=("Segoe UI", 8, "bold"),
        )
        self._log_hdr.pack(anchor=tk.W, padx=14, pady=(10, 4))

        # Warning panel (created but not packed until needed)
        self._warn_frame = tk.Frame(right, bg=self.C_WARN_BG)
        self._warn_lbl = tk.Label(
            self._warn_frame, text="",
            bg=self.C_WARN_BG, fg=self.C_WARN_FG,
            font=("Segoe UI", 8), wraplength=420,
            justify=tk.LEFT, anchor=tk.NW, padx=14, pady=8,
        )
        self._warn_lbl.pack(fill=tk.X)
        _wb = tk.Frame(self._warn_frame, bg=self.C_WARN_BG)
        _wb.pack(anchor=tk.W, padx=14, pady=(0, 10))
        tk.Button(
            _wb, text="Open .env.secrets",
            bg=self.C_WARN_BTN, fg="white", relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"), padx=10, pady=5,
            cursor="hand2", command=self._open_env_secrets,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            _wb, text="Continue  →",
            bg=self.C_ACCENT, fg="white", relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"), padx=10, pady=5,
            cursor="hand2", command=self._on_continue,
        ).pack(side=tk.LEFT)

        # Log container (scrollbar + text)
        self._log_container = tk.Frame(right, bg=self.C_LOG_BG)
        self._log_container.pack(fill=tk.BOTH, expand=True)

        self._log = tk.Text(
            self._log_container, bg=self.C_LOG_BG, fg=self.C_LOG_FG,
            font=("Consolas", 9), relief=tk.FLAT,
            wrap=tk.WORD, state=tk.DISABLED,
            padx=14, pady=4,
        )
        _sb = ttk.Scrollbar(self._log_container, command=self._log.yview)
        self._log.configure(yscrollcommand=_sb.set)
        _sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._log.tag_configure("ok",   foreground=self.C_LOG_OK)
        self._log.tag_configure("err",  foreground=self.C_LOG_ERR)
        self._log.tag_configure("warn", foreground=self.C_LOG_WARN)
        self._log.tag_configure("hl",   foreground=self.C_LOG_HL)

    def _build_progressbar(self):
        pf = tk.Frame(self.root, bg=self.C_BG, height=42)
        pf.pack(fill=tk.X)
        pf.pack_propagate(False)

        tk.Frame(pf, bg=self.C_SEP, height=1).pack(fill=tk.X)

        inner = tk.Frame(pf, bg=self.C_BG)
        inner.pack(fill=tk.X, padx=16, pady=(6, 0))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "PoliSense.Horizontal.TProgressbar",
            troughcolor="#dde1ed", background=self.C_ACCENT,
            thickness=8, borderwidth=0,
        )
        self._pbar = ttk.Progressbar(
            inner, style="PoliSense.Horizontal.TProgressbar",
            maximum=len(STEPS), mode="determinate",
        )
        self._pbar.pack(fill=tk.X)

        self._plbl = tk.Label(
            pf, text="Ready to install.",
            bg=self.C_BG, fg="#64748b", font=("Segoe UI", 8),
        )
        self._plbl.pack(anchor=tk.W, padx=16)

    def _build_footer(self):
        ftr = tk.Frame(self.root, bg=self.C_BG, height=52)
        ftr.pack(fill=tk.X)
        ftr.pack_propagate(False)

        tk.Frame(ftr, bg=self.C_SEP, height=1).pack(fill=tk.X)
        btns = tk.Frame(ftr, bg=self.C_BG)
        btns.pack(anchor=tk.E, padx=16, pady=12)

        self._cancel_btn = tk.Button(
            btns, text="Cancel",
            bg="#e2e8f0", fg="#374151", relief=tk.FLAT,
            font=("Segoe UI", 9), padx=16, pady=6,
            cursor="hand2", command=self._on_close,
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=(0, 10))

        self._install_btn = tk.Button(
            btns, text="Install  →",
            bg=self.C_ACCENT, fg="white", relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"), padx=16, pady=6,
            cursor="hand2", command=self._start_install,
        )
        self._install_btn.pack(side=tk.LEFT)

    # ── Pre-check ────────────────────────────────────────────────────────────

    def _pre_check(self):
        self._write("── Before you click Install ────────────────────────────────\n", "hl")
        self._write("  Required on this machine:\n")
        self._write("    • Python 3.10+\n")
        self._write("    • Docker Desktop  —  installed and running\n")
        self._write("    • .env.secrets    —  GOOGLE_API_KEY, POSTGRES_USER, POSTGRES_PASSWORD\n")
        self._write("\n  Optional (for migrating data from another machine):\n")
        self._write("    • exports/polisense_db.sql   DB dump from 'make db-export'\n")
        self._write("    • exports/files_read.json    ingestion state files\n")
        self._write("    • exports/files_skipped.json\n")
        self._write("\n  Without exports/ the DB will be empty — run the ingestion\n")
        self._write("  pipeline after setup to populate it.\n")
        self._write("────────────────────────────────────────────────────────────\n\n")

        v = sys.version_info
        if v < (3, 10):
            self._set_step(0, "err")
            self._write(f"✗ Python {v.major}.{v.minor} — requires 3.10+\n", "err")
            self._write("  Download: https://www.python.org/downloads/\n", "warn")
            self._install_btn.config(state=tk.DISABLED, text="Python too old")
            return
        self._set_step(0, "done")
        self._write(f"✓ Python {v.major}.{v.minor}.{v.micro} — OK\n", "ok")

        if not (ROOT / "pyproject.toml").exists():
            self._write(
                f"\n⚠ pyproject.toml not found at:\n  {ROOT}\n\n"
                "  Place PoliSense-Setup.exe in the PoliSense project root and retry.\n",
                "warn",
            )
            self._install_btn.config(state=tk.DISABLED, text="Wrong directory")

    # ── Install ──────────────────────────────────────────────────────────────

    def _start_install(self):
        # Reset steps 1-6
        for i in range(1, len(STEPS)):
            self._step_icon[i].config(text="○", fg=self.C_STEP_IDLE)
            self._step_lbl[i].config(fg=self.C_STEP_IDLE)
        self._spinner_step = -1
        self._pbar["value"] = 1
        ttk.Style().configure("PoliSense.Horizontal.TProgressbar", background=self.C_ACCENT)
        self._plbl.config(text="Installing…", fg="#64748b")
        self._log.config(state=tk.NORMAL)
        self._log.delete("2.0", tk.END)
        self._log.config(state=tk.DISABLED)
        self._hide_warn()

        self._install_btn.config(state=tk.DISABLED, text="Installing…")
        self._cancel_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self._install()
        except Exception as exc:
            self._q.put(("fatal", f"Unexpected error: {exc}", ""))

    def _install(self):
        q = self._q
        done = 1  # step 0 (Python check) already completed

        def log(text, tag=""): q.put(("log", text, tag))
        def activate(i):       q.put(("step_start", i))
        def finish(i):
            nonlocal done
            done += 1
            q.put(("step_done", i, True, ""))
            q.put(("progress", done, STEPS[i]))
        def fatal(msg, hint=""): q.put(("fatal", msg, hint))

        # ── Step 2: env files ─────────────────────────────────────────────
        activate(1)
        log("── Environment files ──────────────────────────────────────\n", "hl")
        env_path = ROOT / ".env"
        sec_path = ROOT / ".env.secrets"
        for src, dst in [(ROOT / ".env.example", env_path),
                         (ROOT / ".env.secrets.example", sec_path)]:
            if dst.exists():
                log(f"  {dst.name}  —  already exists\n")
            elif src.exists():
                shutil.copy2(src, dst)
                log(f"  Copied {src.name}  →  {dst.name}\n", "ok")
            else:
                log(f"  ⚠ {src.name} not found\n", "warn")

        PLACEHOLDERS = ["your_google_api_key_here", "your_db_username", "your_db_password"]
        if sec_path.exists() and any(p in sec_path.read_text("utf-8") for p in PLACEHOLDERS):
            log("\n  ⚠ Credentials have placeholder values — fill them in before continuing.\n\n", "warn")
            self._secrets_ready.clear()
            q.put((
                "warn_secrets",
                "Fill in your credentials in .env.secrets before continuing.\n\n"
                "Required:   GOOGLE_API_KEY,  POSTGRES_USER,  POSTGRES_PASSWORD\n"
                "Optional:   LANGSMITH_API_KEY,  Zoho credentials",
            ))
            self._secrets_ready.wait()
            if any(p in sec_path.read_text("utf-8") for p in PLACEHOLDERS):
                fatal("Credentials still contain placeholder values.",
                      "Edit .env.secrets and click Install again.")
                return
            log("  ✓ Credentials filled — continuing\n", "ok")
        finish(1)

        # ── Step 3: venv ──────────────────────────────────────────────────
        activate(2)
        log("\n── Virtual environment ────────────────────────────────────\n", "hl")
        venv_dir = ROOT / ".venv"
        if venv_dir.exists():
            log("  .venv/  —  already exists, skipping\n")
        else:
            log("  Creating .venv/ ...\n")
            python_exe = find_python()
            r = subprocess.run(
                [python_exe, "-m", "venv", str(venv_dir)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                fatal("Failed to create virtual environment.", r.stderr.strip())
                return
            log("  ✓ .venv/ created\n", "ok")
        finish(2)

        # ── Step 4: install deps ──────────────────────────────────────────
        activate(3)
        log("\n── Installing dependencies ────────────────────────────────\n", "hl")
        log("  (may take several minutes on first run)\n\n")
        pip = venv_executable("pip")
        if not pip.exists():
            fatal("pip not found in .venv/", "Delete .venv/ and retry.")
            return
        subprocess.run(
            [str(pip), "install", "--upgrade", "pip", "-q"],
            capture_output=True, cwd=str(ROOT),
        )
        rc = stream_subprocess(
            [str(pip), "install", "-e", ".", "--no-warn-script-location"],
            cwd=ROOT,
            on_line=lambda line: log(f"  {line}\n"),
        )
        if rc != 0:
            fatal("pip install failed.", "See the log above for details.")
            return
        finish(3)

        # ── Step 5: docker up ─────────────────────────────────────────────
        activate(4)
        log("\n── Starting PostgreSQL ────────────────────────────────────\n", "hl")
        if not shutil.which("docker"):
            fatal(
                "Docker not found on PATH.",
                "Install Docker Desktop:  https://www.docker.com/products/docker-desktop\n"
                "  Ensure it is running, then retry.",
            )
            return
        r = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        if r.returncode != 0:
            fatal("docker compose up failed.", r.stderr.strip())
            return
        for line in r.stdout.splitlines():
            if line.strip():
                log(f"  {line}\n")
        log("  ✓ Container started\n", "ok")
        finish(4)

        # ── Step 6: wait for postgres ─────────────────────────────────────
        activate(5)
        log("\n── Waiting for PostgreSQL ─────────────────────────────────\n", "hl")
        env    = parse_env_file(ROOT / ".env")
        secret = parse_env_file(ROOT / ".env.secrets")
        pg_user = secret.get("POSTGRES_USER") or env.get("POSTGRES_USER", "postgres")
        pg_db   = env.get("POSTGRES_DB", "polisense_db_dev")
        log(f"  Polling pg_isready  (user={pg_user}, db={pg_db})\n")

        deadline = time.time() + 60
        healthy  = False
        while time.time() < deadline:
            r = subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres",
                 "pg_isready", "-U", pg_user, "-d", pg_db],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            if r.returncode == 0:
                healthy = True
                break
            log("  ·")
            time.sleep(3)
        log("\n")

        if not healthy:
            logs = subprocess.run(
                ["docker", "compose", "logs", "--tail=20", "postgres"],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            if logs.stdout:
                log("\n  Last 20 lines of container output:\n", "warn")
                for line in logs.stdout.splitlines():
                    log(f"    {line}\n")
            fatal(
                "PostgreSQL did not become healthy within 60 seconds.",
                "Check the container logs above.\n"
                "  Common cause: wrong POSTGRES_USER or POSTGRES_PASSWORD in .env.secrets",
            )
            return
        log("  ✓ PostgreSQL is healthy\n", "ok")
        finish(5)

        # ── Step 7: schema ────────────────────────────────────────────────
        activate(6)
        log("\n── Applying schema ────────────────────────────────────────\n", "hl")
        schema_path = ROOT / "db" / "schema.sql"
        if not schema_path.exists():
            fatal(f"Schema file not found: db/schema.sql")
            return
        sql = schema_path.read_text("utf-8")
        r = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres",
             "psql", "-U", pg_user, "-d", pg_db],
            input=sql, cwd=str(ROOT), capture_output=True, text=True,
        )
        if r.returncode != 0:
            fatal("Schema application failed.", r.stderr.strip())
            return
        for line in r.stdout.splitlines():
            if line.strip():
                log(f"  {line}\n")
        log("  ✓ Schema applied  (policies, policy_documents, review_queue)\n", "ok")
        finish(6)

        # ── Step 8: import data ───────────────────────────────────────────
        activate(7)
        log("\n── Import data ─────────────────────────────────────────────\n", "hl")
        dump_path = ROOT / "exports" / "polisense_db.sql"
        if dump_path.exists():
            log(f"  Found exports/polisense_db.sql — importing...\n")
            sql = dump_path.read_text("utf-8", errors="replace")
            r = subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres",
                 "psql", "-U", pg_user, "-d", pg_db],
                input=sql, cwd=str(ROOT), capture_output=True, text=True,
            )
            if r.returncode != 0:
                fatal("Data import failed.", r.stderr.strip())
                return
            for line in r.stdout.splitlines():
                if line.strip():
                    log(f"  {line}\n")
            log("  ✓ Database data imported\n", "ok")
            for fname in ("files_read.json", "files_skipped.json"):
                src = ROOT / "exports" / fname
                dst = ROOT / "documents" / fname
                if src.exists():
                    shutil.copy2(src, dst)
                    log(f"  ✓ Restored documents/{fname}\n", "ok")
            self._data_imported = True
        else:
            log("  No exports/polisense_db.sql found — skipping.\n")
            log("  Run 'make db-export' on the source machine to create a dump,\n", "warn")
            log("  place exports/ in the project root, then retry.\n", "warn")
            self._data_imported = False
        finish(7)

        q.put(("done", None))

    # ── Queue drain ──────────────────────────────────────────────────────────

    def _start_drain(self):
        self.root.after(80, self._drain)

    def _drain(self):
        try:
            while True:
                self._handle(self._q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "log":
            self._write(msg[1], msg[2] if len(msg) > 2 else "")
        elif kind == "step_start":
            self._set_step(msg[1], "spin")
        elif kind == "step_done":
            self._set_step(msg[1], "done" if msg[2] else "err")
        elif kind == "progress":
            self._pbar["value"] = msg[1]
            self._plbl.config(text=f"Step {msg[1]} of {len(STEPS)}  —  {msg[2]}")
        elif kind == "warn_secrets":
            self._show_warn(msg[1])
        elif kind == "fatal":
            self._on_fatal(msg[1], msg[2] if len(msg) > 2 else "")
        elif kind == "done":
            self._on_done()

    # ── Step animations ──────────────────────────────────────────────────────

    def _set_step(self, idx: int, state: str):
        icon = self._step_icon[idx]
        lbl  = self._step_lbl[idx]
        if state == "done":
            icon.config(text="✓", fg=self.C_STEP_DONE)
            lbl.config(fg="#1e293b")
            if self._spinner_step == idx:
                self._spinner_step = -1
        elif state == "err":
            icon.config(text="✗", fg=self.C_STEP_ERR)
            lbl.config(fg=self.C_STEP_ERR)
            if self._spinner_step == idx:
                self._spinner_step = -1
        elif state == "spin":
            self._spinner_step = idx
            icon.config(fg=self.C_STEP_ACT)
            lbl.config(fg=self.C_STEP_ACT)
            self._tick()

    def _tick(self):
        if self._spinner_step < 0:
            return
        self._step_icon[self._spinner_step].config(
            text=SPINNER[self._spinner_idx % len(SPINNER)]
        )
        self._spinner_idx += 1
        self.root.after(80, self._tick)

    # ── Log ──────────────────────────────────────────────────────────────────

    def _write(self, text: str, tag: str = ""):
        self._log.config(state=tk.NORMAL)
        if tag:
            self._log.insert(tk.END, text, tag)
        else:
            self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    # ── Warn panel ───────────────────────────────────────────────────────────

    def _show_warn(self, text: str):
        self._warn_lbl.config(text=f"⚠   {text}")
        self._warn_frame.pack(fill=tk.X, before=self._log_container)

    def _hide_warn(self):
        self._warn_frame.pack_forget()

    def _open_env_secrets(self):
        try:
            os.startfile(str(ROOT / ".env.secrets"))
        except Exception:
            pass

    def _on_continue(self):
        self._hide_warn()
        self._secrets_ready.set()

    # ── Outcome ──────────────────────────────────────────────────────────────

    def _on_fatal(self, msg: str, hint: str = ""):
        self._write(f"\n✗  {msg}\n", "err")
        if hint:
            self._write(f"   {hint}\n\n", "warn")
        ttk.Style().configure("PoliSense.Horizontal.TProgressbar", background=self.C_ERROR)
        self._plbl.config(text="Installation failed — see log for details.", fg=self.C_ERROR)
        self._install_btn.config(state=tk.NORMAL, text="Retry  →",
                                  bg=self.C_ACCENT, command=self._start_install)
        self._cancel_btn.config(state=tk.NORMAL)

    def _on_done(self):
        self._pbar["value"] = len(STEPS)
        ttk.Style().configure("PoliSense.Horizontal.TProgressbar", background=self.C_SUCCESS)
        self._plbl.config(text="Installation complete!", fg=self.C_SUCCESS)
        self._write("\n")
        self._write("✓  PoliSense is ready!\n\n", "ok")
        self._write("Next steps:\n", "hl")
        self._write("  1. Activate the virtual environment:\n")
        self._write("       PowerShell:  .venv\\Scripts\\Activate.ps1\n")
        self._write("       Git Bash:    source .venv/Scripts/activate\n\n")
        if self._data_imported:
            self._write("  2. Run the retrieval pipeline:\n")
            self._write("       python polisense_core/retrieval_pipeline.py\n\n")
            self._write("  3. Stop the database when done:\n")
            self._write("       docker compose down\n")
        else:
            self._write("  2. Run the ingestion pipeline:\n")
            self._write("       python polisense_core/ingestion_pipeline.py\n\n")
            self._write("  3. Run the retrieval pipeline:\n")
            self._write("       python polisense_core/retrieval_pipeline.py\n\n")
            self._write("  4. Stop the database when done:\n")
            self._write("       docker compose down\n")
        self._install_btn.config(
            state=tk.NORMAL, text="Close",
            bg=self.C_SUCCESS, command=self.root.destroy,
        )
        self._cancel_btn.config(state=tk.NORMAL)

    # ── Window close ─────────────────────────────────────────────────────────

    def _on_close(self):
        self._secrets_ready.set()  # unblock any waiting thread
        self.root.destroy()

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    try:
        app = InstallerApp()
        app.run()
    except tk.TclError as exc:
        print(f"Error: Cannot start GUI — {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

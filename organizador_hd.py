from __future__ import annotations

import csv
import difflib
import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import Counter, defaultdict
from fractions import Fraction


class HashCancelled(Exception):
    """Leitura de hash interrompida pelo usuário; nunca deve ser gravada como válida."""

from datetime import datetime
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, TOP, X, Y, BOTTOM, BooleanVar, PhotoImage, StringVar, Tk, Toplevel, filedialog, messagebox, simpledialog
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

APP_NAME = "Organizador HD Local"
APP_VERSION = "1.0.0"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts", ".vob", ".ogv", ".rm", ".rmvb"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".raw", ".svg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".aiff"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".rtf", ".odt", ".ods", ".odp"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"}
EXECUTABLE_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".jar"}
SKIP_DIR_NAMES = {
    "_organizador_hd_quarentena",
    ".organizador_hd",
    # Controle de versão
    ".git",
    ".hg",
    ".svn",
    # JavaScript / Node
    "node_modules",
    "bower_components",
    ".npm",
    ".yarn",
    ".pnpm-store",
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    # PHP / Composer
    "vendor",
    ".composer",
    # Python
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    # Java / Gradle / Maven
    ".gradle",
    ".m2",
    # Rust / Dart / iOS
    ".cargo",
    "target",
    ".dart_tool",
    ".pub-cache",
    "pods",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    value = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    while abs(value) >= 1024 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:,.2f} {units[index]}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_date(value: float | int | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromtimestamp(value).strftime("%d/%m/%Y %H:%M")
    except (OSError, ValueError, OverflowError):
        return "—"


def row_get(row, key: str, default=None):
    try:
        if isinstance(row, sqlite3.Row):
            return row[key] if key in row.keys() else default
        return row.get(key, default)
    except (KeyError, TypeError, IndexError):
        return default


def format_duration(value) -> str:
    if value in (None, "", "N/A"):
        return "—"
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def format_resolution(row) -> str:
    width = row_get(row, "video_width")
    height = row_get(row, "video_height")
    return f"{width}×{height}" if width and height else "—"


def format_video_codec(row) -> str:
    video = row_get(row, "video_codec") or ""
    audio = row_get(row, "audio_codec") or ""
    if video and audio:
        return f"{video} / {audio}"
    return video or audio or "—"


def parse_fps(value):
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def locate_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    if local_app.exists():
        for candidate in local_app.glob(f"Microsoft/WinGet/Packages/*/{name}.exe"):
            return str(candidate)
        for candidate in local_app.glob(f"Microsoft/WinGet/Packages/*/*/bin/{name}.exe"):
            return str(candidate)
    return None


def probe_payload(path: Path, ffprobe: str) -> dict:
    command = [ffprobe, "-v", "error", "-show_entries", "format=duration,bit_rate,format_name:stream=codec_type,codec_name,width,height,r_frame_rate", "-of", "json", str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffprobe falhou")
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    fmt = payload.get("format", {})
    duration = fmt.get("duration")
    bitrate = fmt.get("bit_rate")
    return {
        "duration": float(duration) if duration not in (None, "", "N/A") else None,
        "width": int(video["width"]) if video.get("width") else None,
        "height": int(video["height"]) if video.get("height") else None,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "container": fmt.get("format_name"),
        "fps": parse_fps(video.get("r_frame_rate")),
        "bitrate": int(bitrate) if bitrate not in (None, "", "N/A") else None,
    }


def category_for(extension: str) -> str:
    ext = extension.lower()
    if ext in VIDEO_EXTENSIONS:
        return "Vídeos"
    if ext in IMAGE_EXTENSIONS:
        return "Imagens"
    if ext in AUDIO_EXTENSIONS:
        return "Áudios"
    if ext in DOCUMENT_EXTENSIONS:
        return "Documentos"
    if ext in ARCHIVE_EXTENSIONS:
        return "Compactados"
    if ext in EXECUTABLE_EXTENSIONS:
        return "Executáveis"
    return "Outros"


def normalized_name(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", stem)
    stem = re.sub(r"(?:^|[\s_.-])(?:copy|copia|copiar|novo|new|old|old2|v\d+)(?=$|[\s_.-])", " ", stem)
    stem = re.sub(r"\b\d{2,4}[-_. ]\d{1,2}[-_. ]\d{1,4}\b", " ", stem)
    stem = re.sub(r"\b\d+\b", " ", stem)
    stem = re.sub(r"[^a-z0-9áàâãéêíóôõúçü]+", " ", stem, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", stem).strip()


def name_similarity(a: str, b: str) -> float:
    na = normalized_name(a)
    nb = normalized_name(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def db_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "OrganizadorHD"
    base.mkdir(parents=True, exist_ok=True)
    return base / "index.sqlite3"


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.initialize()

    def initialize(self) -> None:
        with self.lock, self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    category TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    sha256 TEXT,
                    hash_size INTEGER,
                    hash_mtime REAL,
                    indexed_at TEXT NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS video_metadata (
                    path TEXT PRIMARY KEY,
                    file_size INTEGER NOT NULL,
                    file_mtime REAL NOT NULL,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    video_codec TEXT,
                    audio_codec TEXT,
                    container TEXT,
                    fps REAL,
                    bitrate INTEGER,
                    analyzed_at TEXT NOT NULL,
                    error TEXT,
                    thumbnail_path TEXT
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_video_metadata_error ON video_metadata(error)")
            video_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(video_metadata)").fetchall()}
            for column, definition in [("thumbnail_path", "TEXT"), ("error", "TEXT")]:
                if column not in video_columns:
                    self.conn.execute(f"ALTER TABLE video_metadata ADD COLUMN {column} {definition}")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_root ON files(root)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(size)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256)")
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(files)").fetchall()}
            if "hash_size" not in columns:
                self.conn.execute("ALTER TABLE files ADD COLUMN hash_size INTEGER")
            if "hash_mtime" not in columns:
                self.conn.execute("ALTER TABLE files ADD COLUMN hash_mtime REAL")

    def clear_root(self, root: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM video_metadata WHERE path IN (SELECT path FROM files WHERE root = ?)", (root,))
            self.conn.execute("DELETE FROM files WHERE root = ?", (root,))

    def insert_batch(self, rows: list[tuple]) -> None:
        with self.lock, self.conn:
            self.conn.executemany("""
                INSERT INTO files(root,path,name,extension,category,size,mtime,sha256,hash_size,hash_mtime,indexed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    root=excluded.root, name=excluded.name, extension=excluded.extension,
                    category=excluded.category, size=excluded.size, mtime=excluded.mtime,
                    sha256=NULL, hash_size=NULL, hash_mtime=NULL, indexed_at=excluded.indexed_at
            """, rows)

    def update_hash(self, path: str, sha: str) -> None:
        stat = Path(path).stat()
        with self.lock, self.conn:
            self.conn.execute("UPDATE files SET sha256=?, hash_size=?, hash_mtime=?, indexed_at=? WHERE path=?", (sha, int(stat.st_size), float(stat.st_mtime), now_iso(), path))

    def refresh_stale_metadata(self, root: str) -> int:
        with self.lock:
            rows = list(self.conn.execute("SELECT path,size,mtime FROM files WHERE root=?", (root,)).fetchall())
        updates = []
        for row in rows:
            path = Path(row["path"])
            try:
                stat = path.stat()
                if int(stat.st_size) != int(row["size"]) or abs(float(stat.st_mtime) - float(row["mtime"])) >= 0.000001:
                    updates.append((int(stat.st_size), float(stat.st_mtime), None, None, None, now_iso(), str(path)))
            except OSError:
                updates.append((0, 0.0, None, None, None, now_iso(), str(path)))
        if updates:
            with self.lock, self.conn:
                self.conn.executemany("UPDATE files SET size=?,mtime=?,sha256=?,hash_size=?,hash_mtime=?,indexed_at=? WHERE path=?", updates)
        return len(updates)

    def hash_candidates(self, root: str, force: bool = False) -> list[sqlite3.Row]:
        self.refresh_stale_metadata(root)
        with self.lock:
            if force:
                return list(self.conn.execute("""
                    SELECT f.* FROM files f
                    JOIN (SELECT size FROM files WHERE root=? GROUP BY size HAVING COUNT(*)>1) s ON s.size=f.size
                    WHERE f.root=? ORDER BY f.size DESC, f.name COLLATE NOCASE ASC
                """, (root, root)).fetchall())
            return list(self.conn.execute("""
                SELECT f.* FROM files f
                JOIN (SELECT size FROM files WHERE root=? GROUP BY size HAVING COUNT(*)>1) s ON s.size=f.size
                WHERE f.root=? AND (
                    f.sha256 IS NULL OR f.hash_size IS NULL OR f.hash_size<>f.size OR
                    f.hash_mtime IS NULL OR ABS(f.hash_mtime-f.mtime)>=0.000001
                )
                ORDER BY f.size DESC, f.name COLLATE NOCASE ASC
            """, (root, root)).fetchall())

    def upsert_video_metadata(self, path: str, file_size: int, file_mtime: float, metadata: dict | None = None, error: str | None = None) -> None:
        metadata = metadata or {}
        with self.lock, self.conn:
            previous = self.conn.execute("SELECT thumbnail_path,file_size,file_mtime FROM video_metadata WHERE path=?", (path,)).fetchone()
            thumbnail_path = previous[0] if previous and int(previous[1]) == int(file_size) and abs(float(previous[2]) - float(file_mtime)) < 0.000001 else None
            self.conn.execute("""
                INSERT INTO video_metadata(path,file_size,file_mtime,duration,width,height,video_codec,audio_codec,container,fps,bitrate,analyzed_at,error,thumbnail_path)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    file_size=excluded.file_size, file_mtime=excluded.file_mtime,
                    duration=excluded.duration, width=excluded.width, height=excluded.height,
                    video_codec=excluded.video_codec, audio_codec=excluded.audio_codec,
                    container=excluded.container, fps=excluded.fps, bitrate=excluded.bitrate,
                    analyzed_at=excluded.analyzed_at, error=excluded.error
            """, (path, file_size, file_mtime, metadata.get("duration"), metadata.get("width"), metadata.get("height"), metadata.get("video_codec"), metadata.get("audio_codec"), metadata.get("container"), metadata.get("fps"), metadata.get("bitrate"), now_iso(), error, thumbnail_path))

    def set_thumbnail_path(self, path: str, thumbnail_path: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE video_metadata SET thumbnail_path=? WHERE path=?", (thumbnail_path, path))

    def video_metadata_candidates(self, root: str, paths: list[str] | None = None, force: bool = False) -> list[sqlite3.Row]:
        self.refresh_stale_metadata(root)
        rows = self.all_rows(root)
        selected = set(paths or [])
        candidates = []
        for row in rows:
            if row_get(row, "category") != "Vídeos":
                continue
            if selected and row_get(row, "path") not in selected:
                continue
            if force or row_get(row, "video_analyzed_at") is None or row_get(row, "video_file_size") != row_get(row, "size") or row_get(row, "video_file_mtime") is None or abs(float(row_get(row, "video_file_mtime", 0)) - float(row_get(row, "mtime", 0))) >= 0.000001:
                candidates.append(row)
        return candidates

    def rows_for_paths(self, paths: list[str]) -> list[sqlite3.Row]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        sql = f"SELECT f.*, v.file_size AS video_file_size, v.file_mtime AS video_file_mtime, v.duration AS video_duration, v.width AS video_width, v.height AS video_height, v.video_codec, v.audio_codec, v.container AS video_container, v.fps AS video_fps, v.bitrate AS video_bitrate, v.analyzed_at AS video_analyzed_at, v.error AS video_error, v.thumbnail_path FROM files f LEFT JOIN video_metadata v ON v.path=f.path WHERE f.path IN ({placeholders})"
        with self.lock:
            return list(self.conn.execute(sql, tuple(paths)).fetchall())

    def update_path(self, old_path: str, new_path: str) -> None:
        stat = Path(new_path).stat()
        with self.lock, self.conn:
            self.conn.execute("UPDATE files SET path=?, name=?, mtime=?, indexed_at=? WHERE path=?", (new_path, Path(new_path).name, float(stat.st_mtime), now_iso(), old_path))
            self.conn.execute("UPDATE video_metadata SET path=? WHERE path=?", (new_path, old_path))

    def delete_file(self, path: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM video_metadata WHERE path=?", (path,))
            self.conn.execute("DELETE FROM files WHERE path=?", (path,))

    def query(self, root: str, search: str = "", category: str = "Todos", sort_column: str = "size", descending: bool = True) -> list[sqlite3.Row]:
        allowed = {"name": "f.name", "extension": "f.extension", "category": "f.category", "size": "f.size", "mtime": "f.mtime", "path": "f.path"}
        order = allowed.get(sort_column, "f.size")
        direction = "DESC" if descending else "ASC"
        clauses = ["f.root = ?"]
        args: list = [root]
        if search.strip():
            term = f"%{search.strip()}%"
            clauses.append("(f.name LIKE ? OR f.path LIKE ? OR f.extension LIKE ?)")
            args.extend([term, term, term])
        if category and category != "Todos":
            clauses.append("f.category = ?")
            args.append(category)
        select = "SELECT f.*, v.file_size AS video_file_size, v.file_mtime AS video_file_mtime, v.duration AS video_duration, v.width AS video_width, v.height AS video_height, v.video_codec, v.audio_codec, v.container AS video_container, v.fps AS video_fps, v.bitrate AS video_bitrate, v.analyzed_at AS video_analyzed_at, v.error AS video_error, v.thumbnail_path"
        sql = f"{select} FROM files f LEFT JOIN video_metadata v ON v.path=f.path WHERE {' AND '.join(clauses)} ORDER BY {order} {direction}, f.name COLLATE NOCASE ASC"
        with self.lock:
            return list(self.conn.execute(sql, args).fetchall())

    def all_rows(self, root: str) -> list[sqlite3.Row]:
        select = "SELECT f.*, v.file_size AS video_file_size, v.file_mtime AS video_file_mtime, v.duration AS video_duration, v.width AS video_width, v.height AS video_height, v.video_codec, v.audio_codec, v.container AS video_container, v.fps AS video_fps, v.bitrate AS video_bitrate, v.analyzed_at AS video_analyzed_at, v.error AS video_error, v.thumbnail_path"
        with self.lock:
            return list(self.conn.execute(f"{select} FROM files f LEFT JOIN video_metadata v ON v.path=f.path WHERE f.root=? ORDER BY f.size DESC", (root,)).fetchall())

    def summary(self, root: str) -> dict:
        self.refresh_stale_metadata(root)
        with self.lock:
            total = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM files WHERE root=?", (root,)).fetchone()
            categories = list(self.conn.execute("SELECT category, COUNT(*), COALESCE(SUM(size),0) FROM files WHERE root=? GROUP BY category ORDER BY SUM(size) DESC", (root,)).fetchall())
            extensions = list(self.conn.execute("SELECT extension, COUNT(*), COALESCE(SUM(size),0) FROM files WHERE root=? GROUP BY extension ORDER BY COUNT(*) DESC LIMIT 20", (root,)).fetchall())
            largest = list(self.conn.execute("SELECT name,path,size,mtime,category FROM files WHERE root=? ORDER BY size DESC LIMIT 15", (root,)).fetchall())
            duplicates = self.conn.execute("SELECT COUNT(*) FROM (SELECT sha256 FROM files WHERE root=? AND sha256 IS NOT NULL AND hash_size=size AND hash_mtime IS NOT NULL AND ABS(hash_mtime-mtime)<0.000001 GROUP BY sha256 HAVING COUNT(*)>1)", (root,)).fetchone()[0]
            pending_hashes = self.conn.execute("""
                SELECT COUNT(*) FROM files f
                JOIN (SELECT size FROM files WHERE root=? GROUP BY size HAVING COUNT(*)>1) s ON s.size=f.size
                WHERE f.root=? AND (f.sha256 IS NULL OR f.hash_size IS NULL OR f.hash_size<>f.size OR f.hash_mtime IS NULL OR ABS(f.hash_mtime-f.mtime)>=0.000001)
            """, (root, root)).fetchone()[0]
            return {"count": total[0], "size": total[1], "categories": categories, "extensions": extensions, "largest": largest, "duplicate_groups": duplicates, "pending_hashes": pending_hashes}

    def duplicate_groups(self, root: str) -> list[list[sqlite3.Row]]:
        self.refresh_stale_metadata(root)
        with self.lock:
            groups = []
            for row in self.conn.execute("SELECT sha256 FROM files WHERE root=? AND sha256 IS NOT NULL AND hash_size=size AND hash_mtime IS NOT NULL AND ABS(hash_mtime-mtime)<0.000001 GROUP BY sha256 HAVING COUNT(*)>1 ORDER BY COUNT(*) DESC", (root,)):
                select = "SELECT f.*, v.file_size AS video_file_size, v.file_mtime AS video_file_mtime, v.duration AS video_duration, v.width AS video_width, v.height AS video_height, v.video_codec, v.audio_codec, v.container AS video_container, v.fps AS video_fps, v.bitrate AS video_bitrate, v.analyzed_at AS video_analyzed_at, v.error AS video_error, v.thumbnail_path"
                group = list(self.conn.execute(f"{select} FROM files f LEFT JOIN video_metadata v ON v.path=f.path WHERE f.root=? AND f.sha256=? ORDER BY f.size DESC, f.mtime DESC", (root, row[0])).fetchall())
                groups.append(group)
            return groups

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class OrganizadorApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(f"{APP_NAME} — Manus 1.6")
        self.root.geometry("1450x860")
        self.root.minsize(1100, 700)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.db = Database(db_path())
        self.ffprobe_path = locate_tool("ffprobe")
        self.ffmpeg_path = locate_tool("ffmpeg")
        self.thumbnail_cache_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "OrganizadorHD" / "thumbnails"
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.root_path = ""
        self.current_rows: dict[str, sqlite3.Row] = {}
        self.quarantine_rows: list[dict] = []
        self.sort_column = "size"
        self.sort_desc = True
        self.total_scanned = 0
        self.total_indexed = 0
        self.started_at = 0.0
        self.folder_usage_path = ""
        self.folder_usage_data: dict[str, dict] = {}

        self.path_var = StringVar()
        self.search_var = StringVar()
        self.category_var = StringVar(value="Todos")
        self.status_var = StringVar(value="Escolha uma pasta para começar. A análise inicial é somente leitura.")
        self.summary_var = StringVar(value="Nenhum índice carregado")
        self.include_hidden_var = BooleanVar(value=False)
        self.only_videos_var = BooleanVar(value=False)
        self.include_hidden_scan = False

        self.setup_style()
        self.build_ui()
        self.root.after(120, self.process_events)

    def setup_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", foreground="#53606e")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Danger.TButton", foreground="#a51d2d")
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 14, 18, 8))
        header.pack(fill=X)
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side=LEFT)
        ttk.Label(header, text="Organização segura de milhares de arquivos • Manus 1.6", style="Sub.TLabel").pack(side=LEFT, padx=(16, 0), pady=(5, 0))

        path_frame = ttk.LabelFrame(self.root, text="Pasta analisada", padding=10)
        path_frame.pack(fill=X, padx=18, pady=(0, 8))
        ttk.Entry(path_frame, textvariable=self.path_var).pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        ttk.Button(path_frame, text="Escolher pasta…", command=self.choose_folder).pack(side=LEFT, padx=(0, 6))
        self.scan_button = ttk.Button(path_frame, text="Analisar HD", style="Primary.TButton", command=self.start_scan)
        self.scan_button.pack(side=LEFT, padx=(0, 6))
        self.stop_button = ttk.Button(path_frame, text="Parar", command=self.stop_worker, state="disabled")
        self.stop_button.pack(side=LEFT)

        toolbar = ttk.Frame(self.root, padding=(18, 0, 18, 8))
        toolbar.pack(fill=X)
        ttk.Label(toolbar, text="Buscar:").pack(side=LEFT)
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=28)
        search_entry.pack(side=LEFT, padx=(6, 12))
        search_entry.bind("<Return>", lambda _event: self.refresh_files())
        ttk.Button(toolbar, text="Filtrar", command=self.refresh_files).pack(side=LEFT, padx=(0, 12))
        ttk.Label(toolbar, text="Categoria:").pack(side=LEFT)
        category = ttk.Combobox(toolbar, textvariable=self.category_var, values=["Todos", "Vídeos", "Imagens", "Áudios", "Documentos", "Compactados", "Executáveis", "Outros"], state="readonly", width=14)
        category.pack(side=LEFT, padx=(6, 12))
        category.bind("<<ComboboxSelected>>", lambda _event: self.refresh_files())
        ttk.Checkbutton(toolbar, text="Somente vídeos", variable=self.only_videos_var, command=self.toggle_video_filter).pack(side=LEFT, padx=(0, 12))
        ttk.Button(toolbar, text="Exportar CSV", command=self.export_csv).pack(side=RIGHT)
        ttk.Button(toolbar, text="Relatório", command=self.show_report).pack(side=RIGHT, padx=(0, 6))

        info = ttk.Frame(self.root, padding=(18, 0, 18, 8))
        info.pack(fill=X)
        ttk.Label(info, textvariable=self.summary_var, style="Sub.TLabel").pack(side=LEFT)
        ttk.Checkbutton(info, text="Incluir arquivos ocultos", variable=self.include_hidden_var).pack(side=RIGHT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=18, pady=(0, 8))
        self.files_tab = ttk.Frame(self.notebook, padding=8)
        self.folder_usage_tab = ttk.Frame(self.notebook, padding=8)
        self.duplicates_tab = ttk.Frame(self.notebook, padding=8)
        self.similar_tab = ttk.Frame(self.notebook, padding=8)
        self.quarantine_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.files_tab, text="Arquivos")
        self.notebook.add(self.folder_usage_tab, text="Uso por pasta")
        self.notebook.add(self.duplicates_tab, text="Duplicados exatos")
        self.notebook.add(self.similar_tab, text="Nomes similares")
        self.notebook.add(self.quarantine_tab, text="Quarentena / restauração")
        self.build_files_tab()
        self.build_folder_usage_tab()
        self.build_duplicates_tab()
        self.build_similar_tab()
        self.build_quarantine_tab()

        status_bar = ttk.Frame(self.root, padding=(18, 4, 18, 10))
        status_bar.pack(fill=X)
        self.progress = ttk.Progressbar(status_bar, mode="determinate")
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(0, 12))
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=LEFT)

    def build_files_tab(self) -> None:
        actions = ttk.Frame(self.files_tab)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Button(actions, text="Comparar selecionados", command=self.compare_selected).pack(side=LEFT)
        ttk.Button(actions, text="Renomear selecionados", command=self.rename_selected).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Enviar para quarentena", command=self.quarantine_selected, style="Danger.TButton").pack(side=LEFT)
        ttk.Button(actions, text="Abrir pasta do arquivo", command=self.open_selected_folder).pack(side=LEFT)
        ttk.Button(actions, text="Analisar vídeos selecionados", command=self.analyze_selected_videos).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Analisar todos os vídeos", command=self.analyze_all_videos).pack(side=LEFT)
        ttk.Label(actions, text="Metadados não alteram os vídeos. Miniaturas são geradas somente na comparação.", style="Sub.TLabel").pack(side=RIGHT)

        columns = [("name", "Nome", 240), ("category", "Tipo", 85), ("extension", "Extensão", 80), ("size", "Tamanho", 105), ("resolution", "Resolução", 100), ("duration", "Duração", 85), ("codec", "Codec", 125), ("mtime", "Modificado", 140), ("path", "Caminho", 420)]
        self.files_tree = ttk.Treeview(self.files_tab, columns=[x[0] for x in columns], show="headings", selectmode="extended")
        for key, title, width in columns:
            self.files_tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            self.files_tree.column(key, width=width, minwidth=60, anchor="w")
        scroll_y = ttk.Scrollbar(self.files_tab, orient="vertical", command=self.files_tree.yview)
        scroll_x = ttk.Scrollbar(self.files_tab, orient="horizontal", command=self.files_tree.xview)
        self.files_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.files_tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll_y.pack(side=RIGHT, fill=Y)
        scroll_x.pack(side=BOTTOM, fill=X)
        self.files_tree.bind("<Double-1>", lambda _event: self.open_selected_folder())

    def build_folder_usage_tab(self) -> None:
        actions = ttk.Frame(self.folder_usage_tab)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Button(actions, text="Medir raiz analisada", style="Primary.TButton", command=self.reset_folder_usage).pack(side=LEFT)
        ttk.Button(actions, text="Subir um nível", command=self.folder_usage_parent).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Entrar na pasta", command=self.enter_selected_folder_usage).pack(side=LEFT)
        ttk.Button(actions, text="Abrir no Explorer", command=self.open_folder_usage_path).pack(side=LEFT, padx=6)
        ttk.Label(actions, text="Somente leitura: mede o tamanho real sem adicionar os arquivos ao índice principal.", style="Sub.TLabel").pack(side=RIGHT)

        self.folder_usage_path_var = StringVar(value="Nenhuma pasta medida")
        ttk.Label(self.folder_usage_tab, textvariable=self.folder_usage_path_var, style="Sub.TLabel").pack(fill=X, pady=(0, 8))

        columns = [
            ("name", "Nome", 330),
            ("kind", "Tipo", 150),
            ("size", "Tamanho", 125),
            ("files", "Arquivos", 90),
            ("dirs", "Subpastas", 90),
            ("path", "Caminho", 560),
        ]
        tree_frame = ttk.Frame(self.folder_usage_tab)
        tree_frame.pack(fill=BOTH, expand=True)
        self.folder_usage_tree = ttk.Treeview(tree_frame, columns=[x[0] for x in columns], show="headings", selectmode="browse")
        for key, title, width in columns:
            self.folder_usage_tree.heading(key, text=title)
            self.folder_usage_tree.column(key, width=width, minwidth=70, anchor="w")
        scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.folder_usage_tree.yview)
        scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.folder_usage_tree.xview)
        self.folder_usage_tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.folder_usage_tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.folder_usage_tree.bind("<Double-1>", lambda _event: self.enter_selected_folder_usage())

    def reset_folder_usage(self) -> None:
        if not self.root_path or not Path(self.root_path).is_dir():
            messagebox.showinfo(APP_NAME, "Escolha uma pasta válida primeiro.")
            return
        self.start_folder_usage(self.root_path)

    def start_folder_usage(self, path: str | None = None) -> None:
        if not self.root_path or not Path(self.root_path).is_dir():
            messagebox.showinfo(APP_NAME, "Escolha uma pasta válida primeiro.")
            return
        if self.worker and self.worker.is_alive():
            return
        root = Path(self.root_path).resolve()
        target = Path(path or self.folder_usage_path or self.root_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            target = root
        if not target.is_dir():
            messagebox.showwarning(APP_NAME, "A pasta selecionada não está mais disponível.")
            return

        self.folder_usage_path = str(target)
        self.folder_usage_path_var.set(f"Medindo: {self.folder_usage_path}")
        self.folder_usage_data = {}
        for item in self.folder_usage_tree.get_children():
            self.folder_usage_tree.delete(item)

        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.stop()
        self.progress.configure(value=0, mode="determinate")
        self.status_var.set(f"Calculando uso de disco em {target}…")
        self.worker = threading.Thread(target=self.folder_usage_worker, args=(str(target),), daemon=True)
        self.worker.start()

    def folder_usage_worker(self, root: str) -> None:
        try:
            target = Path(root)
            rows: list[dict] = []
            inaccessible = 0
            try:
                with os.scandir(target) as iterator:
                    entries = list(iterator)
            except (OSError, PermissionError) as exc:
                self.events.put(("error", f"Não foi possível ler a pasta: {exc}"))
                return

            total = len(entries)
            for index, entry in enumerate(entries, 1):
                if self.cancel_event.is_set():
                    break
                try:
                    if entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        kind = "Arquivo do sistema" if entry.name.lower() in {"pagefile.sys", "hiberfil.sys", "swapfile.sys"} else "Arquivo"
                        rows.append({
                            "name": entry.name,
                            "kind": kind,
                            "size": int(stat.st_size),
                            "files": 1,
                            "dirs": 0,
                            "path": entry.path,
                            "is_dir": False,
                        })
                    elif entry.is_dir(follow_symlinks=False):
                        size, files, dirs, errors = self.measure_directory_usage(Path(entry.path))
                        inaccessible += errors
                        kind = "Dependência/cache" if entry.name.lower() in SKIP_DIR_NAMES else "Pasta"
                        rows.append({
                            "name": entry.name,
                            "kind": kind,
                            "size": size,
                            "files": files,
                            "dirs": dirs,
                            "path": entry.path,
                            "is_dir": True,
                        })
                except (OSError, PermissionError):
                    inaccessible += 1
                self.events.put(("folder_usage_progress", index, total, entry.name))

            rows.sort(key=lambda row: (-int(row["size"]), row["name"].lower()))
            self.events.put(("folder_usage_done", root, rows, self.cancel_event.is_set(), inaccessible))
        except Exception as exc:
            self.events.put(("error", f"Falha ao calcular uso por pasta: {exc}"))

    def measure_directory_usage(self, root: Path) -> tuple[int, int, int, int]:
        total_size = 0
        file_count = 0
        dir_count = 0
        errors = 0
        stack = [root]
        while stack and not self.cancel_event.is_set():
            current = stack.pop()
            try:
                with os.scandir(current) as iterator:
                    for entry in iterator:
                        if self.cancel_event.is_set():
                            break
                        try:
                            if getattr(entry, "is_junction", lambda: False)():
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total_size += int(entry.stat(follow_symlinks=False).st_size)
                                file_count += 1
                            elif entry.is_dir(follow_symlinks=False):
                                dir_count += 1
                                stack.append(Path(entry.path))
                        except (OSError, PermissionError):
                            errors += 1
            except (OSError, PermissionError):
                errors += 1
        return total_size, file_count, dir_count, errors

    def enter_selected_folder_usage(self) -> None:
        selected = self.folder_usage_tree.selection()
        if not selected:
            return
        row = self.folder_usage_data.get(selected[0])
        if not row or not row.get("is_dir"):
            return
        self.start_folder_usage(row["path"])

    def folder_usage_parent(self) -> None:
        if not self.root_path:
            return
        root = Path(self.root_path).resolve()
        current = Path(self.folder_usage_path or self.root_path).resolve()
        if current == root:
            return
        parent = current.parent
        try:
            parent.relative_to(root)
        except ValueError:
            parent = root
        self.start_folder_usage(str(parent))

    def open_folder_usage_path(self) -> None:
        selected = self.folder_usage_tree.selection()
        row = self.folder_usage_data.get(selected[0]) if selected else None
        path = Path(row["path"]) if row else Path(self.folder_usage_path or self.root_path)
        folder = path if path.is_dir() else path.parent
        try:
            os.startfile(str(folder))
        except (AttributeError, OSError) as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível abrir a pasta: {exc}")

    def build_duplicates_tab(self) -> None:
        actions = ttk.Frame(self.duplicates_tab)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Button(actions, text="Calcular hashes SHA-256", style="Primary.TButton", command=self.start_hashing).pack(side=LEFT)
        ttk.Button(actions, text="Recalcular todos", command=lambda: self.start_hashing(force=True)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Atualizar grupos", command=self.refresh_duplicates).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Comparar grupo", command=self.compare_duplicate_group).pack(side=LEFT)
        ttk.Button(actions, text="Selecionar tudo", command=lambda: self.select_all_tree(self.duplicates_tree)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Limpar seleção", command=lambda: self.clear_tree_selection(self.duplicates_tree)).pack(side=LEFT)
        ttk.Button(actions, text="Quarentena dos duplicados", command=self.quarantine_selected_duplicate_groups).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Excluir duplicados", command=self.delete_selected_duplicate_groups, style="Danger.TButton").pack(side=LEFT)
        ttk.Label(actions, text="Ações em massa mantêm automaticamente o maior arquivo de cada grupo.", style="Sub.TLabel").pack(side=RIGHT)
        self.duplicates_tree = ttk.Treeview(self.duplicates_tab, columns=("group", "count", "space", "best", "files"), show="headings", selectmode="extended")
        for key, title, width in [("group", "Grupo", 90), ("count", "Arquivos", 90), ("space", "Espaço total", 125), ("best", "Recomendação", 170), ("files", "Arquivos do grupo", 750)]:
            self.duplicates_tree.heading(key, text=title)
            self.duplicates_tree.column(key, width=width, minwidth=60, anchor="w")
        self.duplicates_tree.pack(fill=BOTH, expand=True)
        self.duplicates_tree.bind("<Double-1>", lambda _event: self.compare_duplicate_group())

    def build_similar_tab(self) -> None:
        actions = ttk.Frame(self.similar_tab)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Button(actions, text="Encontrar nomes similares", style="Primary.TButton", command=self.refresh_similar).pack(side=LEFT)
        ttk.Button(actions, text="Comparar grupo", command=self.compare_similar_group).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Selecionar tudo", command=lambda: self.select_all_tree(self.similar_tree)).pack(side=LEFT)
        ttk.Button(actions, text="Limpar seleção", command=lambda: self.clear_tree_selection(self.similar_tree)).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Quarentena dos grupos", command=self.quarantine_selected_similar_groups).pack(side=LEFT)
        ttk.Button(actions, text="Excluir grupos", command=self.delete_selected_similar_groups, style="Danger.TButton").pack(side=LEFT, padx=6)
        ttk.Label(actions, text="Ações afetarão todos os arquivos dos grupos; nomes similares não são prova de duplicidade.", style="Sub.TLabel").pack(side=RIGHT)
        self.similar_tree = ttk.Treeview(self.similar_tab, columns=("group", "count", "best", "files"), show="headings", selectmode="extended")
        for key, title, width in [("group", "Grupo", 90), ("count", "Arquivos", 90), ("best", "Maior arquivo", 170), ("files", "Nomes e locais", 850)]:
            self.similar_tree.heading(key, text=title)
            self.similar_tree.column(key, width=width, minwidth=60, anchor="w")
        self.similar_tree.pack(fill=BOTH, expand=True)
        self.similar_tree.bind("<Double-1>", lambda _event: self.compare_similar_group())

    def build_quarantine_tab(self) -> None:
        actions = ttk.Frame(self.quarantine_tab)
        actions.pack(fill=X, pady=(0, 8))
        ttk.Button(actions, text="Atualizar lista", command=self.load_quarantine).pack(side=LEFT)
        ttk.Button(actions, text="Restaurar selecionado", command=self.restore_selected).pack(side=LEFT, padx=6)
        ttk.Button(actions, text="Abrir quarentena", command=self.open_quarantine_folder).pack(side=LEFT)
        ttk.Label(actions, text="A quarentena é reversível e mantém um manifesto de restauração.", style="Sub.TLabel").pack(side=RIGHT)
        self.quarantine_tree = ttk.Treeview(self.quarantine_tab, columns=("time", "name", "original", "quarantine", "status"), show="headings", selectmode="extended")
        for key, title, width in [("time", "Data", 145), ("name", "Arquivo", 220), ("original", "Local original", 460), ("quarantine", "Na quarentena", 460), ("status", "Status", 130)]:
            self.quarantine_tree.heading(key, text=title)
            self.quarantine_tree.column(key, width=width, minwidth=80, anchor="w")
        self.quarantine_tree.pack(fill=BOTH, expand=True)
        self.load_quarantine()

    def choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Escolha a pasta do HD a analisar")
        if chosen:
            self.set_root(chosen)

    def set_root(self, chosen: str) -> None:
        path = str(Path(chosen).resolve())
        self.root_path = path
        self.folder_usage_path = path
        if hasattr(self, "folder_usage_path_var"):
            self.folder_usage_path_var.set(f"Pronto para medir: {path}")
        if hasattr(self, "folder_usage_tree"):
            self.folder_usage_data = {}
            for item in self.folder_usage_tree.get_children():
                self.folder_usage_tree.delete(item)
        self.path_var.set(path)
        self.refresh_files()
        self.refresh_summary()
        self.status_var.set("Pasta selecionada. Clique em Analisar HD para indexar em modo somente leitura.")

    def toggle_video_filter(self) -> None:
        if self.only_videos_var.get():
            self.category_var.set("Vídeos")
        elif self.category_var.get() == "Vídeos":
            self.category_var.set("Todos")
        self.refresh_files()

    def start_scan(self) -> None:
        chosen = self.path_var.get().strip()
        if not chosen or not Path(chosen).is_dir():
            messagebox.showwarning(APP_NAME, "Escolha uma pasta válida antes de iniciar a análise.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.root_path = str(Path(chosen).resolve())
        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.configure(value=0, mode="indeterminate")
        self.progress.start(12)
        self.status_var.set("Analisando… nenhuma alteração será feita nos arquivos.")
        self.started_at = time.time()
        self.include_hidden_scan = bool(self.include_hidden_var.get())
        self.worker = threading.Thread(target=self.scan_worker, args=(self.root_path, self.include_hidden_scan), daemon=True)
        self.worker.start()

    def scan_worker(self, root: str, include_hidden: bool) -> None:
        try:
            self.db.clear_root(root)
            batch = []
            count = 0
            stack = [Path(root)]
            visited: set[str] = set()
            while stack and not self.cancel_event.is_set():
                current = stack.pop()
                try:
                    current_key = str(current.resolve()).lower()
                    if current_key in visited:
                        continue
                    visited.add(current_key)
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if self.cancel_event.is_set():
                                break
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    if entry.name.lower() not in SKIP_DIR_NAMES and (include_hidden or not entry.name.startswith(".")):
                                        stack.append(Path(entry.path))
                                    continue
                                if not entry.is_file(follow_symlinks=False):
                                    continue
                                name = entry.name
                                if not include_hidden and name.startswith("."):
                                    continue
                                path = Path(entry.path)
                                stat = entry.stat(follow_symlinks=False)
                                ext = path.suffix.lower()
                                batch.append((root, str(path), name, ext, category_for(ext), int(stat.st_size), float(stat.st_mtime), None, None, None, now_iso()))
                                count += 1
                                if len(batch) >= 400:
                                    self.db.insert_batch(batch)
                                    batch.clear()
                                    self.events.put(("progress", count, None))
                            except (OSError, PermissionError):
                                continue
                except (OSError, PermissionError):
                    continue
            if batch:
                self.db.insert_batch(batch)
            self.events.put(("scan_done", count, self.cancel_event.is_set()))
        except Exception as exc:
            self.events.put(("error", f"Falha na análise: {exc}"))

    def start_hashing(self, force: bool = False) -> None:
        if not self.root_path or not Path(self.root_path).is_dir():
            messagebox.showwarning(APP_NAME, "Analise uma pasta primeiro.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.stop()
        self.progress.configure(value=0, mode="determinate")
        self.status_var.set("Preparando hashes de todos os candidatos com o mesmo tamanho…" if force else "Preparando hashes dos candidatos ainda não confirmados…")
        self.worker = threading.Thread(target=self.hash_worker, args=(self.root_path, force), daemon=True)
        self.worker.start()

    def hash_worker(self, root: str, force: bool = False) -> None:
        try:
            candidates = self.db.hash_candidates(root, force)
            total = len(candidates)
            done = 0
            for row in candidates:
                if self.cancel_event.is_set():
                    break
                path = Path(row["path"])
                try:
                    sha = self.hash_file(path)
                    self.db.update_hash(str(path), sha)
                except HashCancelled:
                    break
                except (OSError, PermissionError):
                    pass
                done += 1
                self.events.put(("hash_progress", done, total, row["name"]))
            self.events.put(("hash_done", done, total, self.cancel_event.is_set()))
        except Exception as exc:
            self.events.put(("error", f"Falha nos hashes: {exc}"))

    def hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                if self.cancel_event.is_set():
                    raise HashCancelled()
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def analyze_selected_videos(self) -> None:
        rows = [row for row in self.selected_rows() if row["category"] == "Vídeos"]
        if not rows:
            messagebox.showinfo(APP_NAME, "Selecione pelo menos um vídeo na tabela principal.")
            return
        self.start_video_analysis([row["path"] for row in rows], force=False)

    def analyze_all_videos(self) -> None:
        if not self.root_path:
            messagebox.showinfo(APP_NAME, "Analise uma pasta primeiro.")
            return
        self.start_video_analysis(None, force=False)

    def start_video_analysis(self, paths: list[str] | None, force: bool = False) -> None:
        if not self.ffprobe_path:
            messagebox.showwarning(APP_NAME, "ffprobe não foi encontrado. Instale FFmpeg e reinicie a aplicação.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "Já existe uma operação em andamento.")
            return
        candidates = self.db.video_metadata_candidates(self.root_path, paths, force=force)
        if not candidates:
            self.status_var.set("Nenhum vídeo novo ou alterado precisa de análise.")
            self.refresh_files()
            return
        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.stop()
        self.progress.configure(value=0, mode="determinate")
        self.status_var.set(f"Preparando análise de {len(candidates)} vídeo(s)…")
        self.worker = threading.Thread(target=self.video_worker, args=(candidates,), daemon=True)
        self.worker.start()

    def video_worker(self, candidates: list[sqlite3.Row]) -> None:
        total = len(candidates)
        done = 0
        errors = 0
        for row in candidates:
            if self.cancel_event.is_set():
                break
            path = Path(row["path"])
            try:
                stat = path.stat()
                metadata = probe_payload(path, self.ffprobe_path)
                self.db.upsert_video_metadata(str(path), int(stat.st_size), float(stat.st_mtime), metadata, None)
            except Exception as exc:
                errors += 1
                try:
                    stat = path.stat()
                    self.db.upsert_video_metadata(str(path), int(stat.st_size), float(stat.st_mtime), {}, str(exc)[:500])
                except OSError:
                    pass
            done += 1
            self.events.put(("video_progress", done, total, path.name))
        self.events.put(("video_done", done, total, self.cancel_event.is_set(), errors))

    def generate_thumbnail_for_row(self, row, dialog=None) -> None:
        if not self.ffmpeg_path:
            messagebox.showwarning(APP_NAME, "ffmpeg não foi encontrado. Instale FFmpeg e reinicie a aplicação.", parent=dialog or self.root)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "Aguarde a operação atual terminar.", parent=dialog or self.root)
            return
        path = Path(row["path"])
        if not path.exists():
            messagebox.showwarning(APP_NAME, "O vídeo não está mais disponível.", parent=dialog or self.root)
            return
        try:
            stat = path.stat()
            cache_key = hashlib.sha256(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")).hexdigest()
            destination = self.thumbnail_cache_dir / f"{cache_key}.png"
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível ler o vídeo: {exc}", parent=dialog or self.root)
            return
        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Gerando miniatura: {path.name}")
        self.worker = threading.Thread(target=self.thumbnail_worker, args=(path, destination), daemon=True)
        self.worker.start()

    def thumbnail_worker(self, path: Path, destination: Path) -> None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                commands = [
                    [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-ss", "00:00:03", "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2", "-y", str(destination)],
                    [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-ss", "00:00:00", "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2", "-y", str(destination)],
                ]
                last_error = ""
                for command in commands:
                    if self.cancel_event.is_set():
                        raise HashCancelled()
                    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False)
                    if completed.returncode == 0 and destination.exists():
                        break
                    last_error = completed.stderr.strip()
                else:
                    raise RuntimeError(last_error or "ffmpeg não conseguiu gerar a miniatura")
            self.db.set_thumbnail_path(str(path), str(destination))
            self.events.put(("thumbnail_done", str(path), str(destination), None))
        except HashCancelled:
            self.events.put(("thumbnail_done", str(path), "", "Operação cancelada"))
        except Exception as exc:
            self.events.put(("thumbnail_done", str(path), "", str(exc)[:500]))

    def show_thumbnail_preview(self, thumbnail: Path, title: str) -> None:
        if not thumbnail.exists():
            messagebox.showwarning(APP_NAME, "A miniatura não está disponível.")
            return
        preview = Toplevel(self.root)
        preview.title(f"Miniatura — {title}")
        preview.geometry("520x420")
        preview.transient(self.root)
        try:
            image = PhotoImage(file=str(thumbnail))
            preview._thumbnail_image = image
            ttk.Label(preview, image=image).pack(fill=BOTH, expand=True, padx=12, pady=12)
            ttk.Label(preview, text=title, style="Sub.TLabel").pack(pady=(0, 12))
        except Exception as exc:
            preview.destroy()
            messagebox.showerror(APP_NAME, f"Não foi possível exibir a miniatura: {exc}")

    def stop_worker(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Parando com segurança…")

    def process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    self.status_var.set(f"Arquivos encontrados: {event[1]:,}".replace(",", "."))
                elif kind == "scan_done":
                    count, canceled = event[1], event[2]
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=100)
                    self.scan_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status_var.set(("Análise interrompida" if canceled else "Análise concluída") + f" — {count:,} arquivos indexados.".replace(",", "."))
                    self.refresh_summary()
                    self.refresh_files()
                elif kind == "hash_progress":
                    done, total, name = event[1], event[2], event[3]
                    self.progress.configure(value=(done / total * 100) if total else 100)
                    self.status_var.set(f"Hash {done:,}/{total:,}: {name}".replace(",", "."))
                elif kind == "hash_done":
                    done, total, canceled = event[1], event[2], event[3]
                    self.scan_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status_var.set(("Hashes interrompidos" if canceled else "Hashes concluídos") + f" — {done:,}/{total:,} candidatos.".replace(",", "."))
                    self.refresh_duplicates()
                    self.refresh_summary()
                elif kind == "video_progress":
                    done, total, name = event[1], event[2], event[3]
                    self.progress.configure(value=(done / total * 100) if total else 100)
                    self.status_var.set(f"Vídeo {done:,}/{total:,}: {name}".replace(",", "."))
                    if done % 5 == 0:
                        self.refresh_files()
                elif kind == "video_done":
                    done, total, canceled, errors = event[1], event[2], event[3], event[4]
                    self.scan_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    suffix = f" com {errors} erro(s)" if errors else ""
                    self.status_var.set(("Análise de vídeos interrompida" if canceled else "Análise de vídeos concluída") + f" — {done:,}/{total:,}{suffix}.".replace(",", "."))
                    self.refresh_files()
                    self.refresh_summary()
                elif kind == "thumbnail_done":
                    path, thumbnail, error = event[1], event[2], event[3]
                    self.scan_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    if error:
                        self.status_var.set(f"Miniatura não gerada: {error}")
                        messagebox.showwarning(APP_NAME, f"Não foi possível gerar a miniatura:\n{error}")
                    else:
                        self.status_var.set("Miniatura gerada e armazenada no cache.")
                        self.show_thumbnail_preview(Path(thumbnail), Path(path).name)
                    self.refresh_files()
                elif kind == "folder_usage_progress":
                    done, total, name = event[1], event[2], event[3]
                    self.progress.configure(value=(done / total * 100) if total else 100)
                    self.status_var.set(f"Medindo {done:,}/{total:,}: {name}".replace(",", "."))
                elif kind == "folder_usage_done":
                    path, rows, canceled, inaccessible = event[1], event[2], event[3], event[4]
                    self.scan_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.progress.configure(value=100)
                    self.folder_usage_path = path
                    self.folder_usage_path_var.set(f"Uso por pasta: {path}")
                    self.folder_usage_data = {}
                    for item in self.folder_usage_tree.get_children():
                        self.folder_usage_tree.delete(item)
                    measured_total = 0
                    for index, row in enumerate(rows):
                        item_id = f"usage_{index}"
                        self.folder_usage_data[item_id] = row
                        measured_total += int(row["size"])
                        self.folder_usage_tree.insert("", END, iid=item_id, values=(
                            row["name"],
                            row["kind"],
                            format_bytes(row["size"]),
                            f"{row['files']:,}".replace(",", "."),
                            f"{row['dirs']:,}".replace(",", "."),
                            row["path"],
                        ))
                    suffix = f" • {inaccessible} item(ns) sem acesso" if inaccessible else ""
                    state = "Medição interrompida" if canceled else "Medição concluída"
                    self.status_var.set(f"{state} — {format_bytes(measured_total)} visíveis neste nível{suffix}.")
                    self.notebook.select(self.folder_usage_tab)
                elif kind == "error":
                    self.progress.stop()
                    self.scan_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status_var.set(event[1])
                    messagebox.showerror(APP_NAME, event[1])
        except queue.Empty:
            pass
        self.root.after(120, self.process_events)

    def refresh_summary(self) -> None:
        if not self.root_path or not Path(self.root_path).is_dir():
            self.summary_var.set("Nenhum índice carregado")
            return
        data = self.db.summary(self.root_path)
        pending = data.get("pending_hashes", 0)
        pending_text = f" • {pending} candidatos aguardando hash" if pending else ""
        self.summary_var.set(f"{data['count']:,} arquivos • {format_bytes(data['size'])} • {len(data['categories'])} categorias • {data['duplicate_groups']} grupos confirmados por SHA-256{pending_text}".replace(",", "."))

    def refresh_files(self) -> None:
        if not hasattr(self, "files_tree"):
            return
        for item in self.files_tree.get_children():
            self.files_tree.delete(item)
        self.current_rows.clear()
        if not self.root_path:
            return
        category = "Vídeos" if self.only_videos_var.get() else self.category_var.get()
        rows = self.db.query(self.root_path, self.search_var.get(), category, self.sort_column, self.sort_desc)
        for row in rows:
            item = self.files_tree.insert("", END, values=(row["name"], row["category"], row["extension"] or "—", format_bytes(row["size"]), format_resolution(row), format_duration(row_get(row, "video_duration")), format_video_codec(row), format_date(row["mtime"]), row["path"]))
            self.current_rows[item] = row

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_column = column
            self.sort_desc = column in {"size", "mtime"}
        self.refresh_files()

    def selected_rows(self) -> list[sqlite3.Row]:
        return [self.current_rows[item] for item in self.files_tree.selection() if item in self.current_rows]

    def open_selected_folder(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo(APP_NAME, "Selecione pelo menos um arquivo.")
            return
        folder = str(Path(rows[0]["path"]).parent)
        try:
            os.startfile(folder)
        except AttributeError:
            pass

    def compare_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) < 2:
            messagebox.showinfo(APP_NAME, "Selecione pelo menos dois arquivos para comparar.")
            return
        self.show_comparison(rows, "Comparação dos arquivos selecionados")

    def show_comparison(self, rows: list[sqlite3.Row] | list[dict], title: str) -> None:
        dialog = Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("1500x760")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text=title, style="Title.TLabel").pack(anchor="w", padx=18, pady=(16, 4))
        sizes = [int(row["size"]) for row in rows]
        largest = max(sizes) if sizes else 0
        recommendation = ttk.Label(dialog, text=f"O maior arquivo tem {format_bytes(largest)}. Resolução, duração e codec ajudam a comparar versões, mas o SHA-256 continua sendo a confirmação de conteúdo idêntico. Selecione uma linha para abrir, analisar, gerar miniatura, copiar, renomear ou excluir.", style="Sub.TLabel", wraplength=1420)
        recommendation.pack(anchor="w", padx=18, pady=(0, 12))
        tree = ttk.Treeview(dialog, columns=("name", "resolution", "duration", "codec", "fps", "size", "date", "hash", "path"), show="headings", selectmode="extended")
        for key, heading, width in [("name", "Nome", 220), ("resolution", "Resolução", 100), ("duration", "Duração", 85), ("codec", "Codec", 140), ("fps", "FPS", 65), ("size", "Tamanho", 105), ("date", "Modificado", 140), ("hash", "SHA-256", 210), ("path", "Caminho", 420)]:
            tree.heading(key, text=heading)
            tree.column(key, width=width, minwidth=60)
        tree.pack(fill=BOTH, expand=True, padx=18, pady=(0, 10))
        row_by_item: dict[str, sqlite3.Row | dict] = {}
        for row in sorted(rows, key=lambda r: int(r["size"]), reverse=True):
            fps = row_get(row, "video_fps")
            fps_text = f"{float(fps):.2f}" if fps else "—"
            item = tree.insert("", END, values=(row["name"], format_resolution(row), format_duration(row_get(row, "video_duration")), format_video_codec(row), fps_text, format_bytes(row["size"]), format_date(row["mtime"]), row["sha256"] or "não calculado", row["path"]))
            row_by_item[item] = row

        def selected_row():
            selected = tree.selection()
            if not selected or selected[0] not in row_by_item:
                messagebox.showinfo(APP_NAME, "Selecione um arquivo na comparação.", parent=dialog)
                return None
            return row_by_item[selected[0]]

        def selected_rows_in_comparison() -> list[sqlite3.Row | dict]:
            return [row_by_item[item] for item in tree.selection() if item in row_by_item]

        def select_all_rows() -> None:
            tree.selection_set(tree.get_children())

        def clear_rows_selection() -> None:
            tree.selection_remove(tree.selection())

        def open_selected_file() -> None:
            row = selected_row()
            if row:
                self.open_file_for_row(row, dialog)

        def reveal_selected_file() -> None:
            row = selected_row()
            if row:
                self.reveal_file_for_row(row, dialog)

        def copy_selected_name() -> None:
            row = selected_row()
            if row:
                self.copy_text_to_clipboard(str(row["name"]), "Nome copiado.", dialog)

        def copy_selected_path() -> None:
            row = selected_row()
            if row:
                self.copy_text_to_clipboard(str(row["path"]), "Caminho copiado.", dialog)

        def analyze_selected_video() -> None:
            row = selected_row()
            if row and row["category"] == "Vídeos":
                self.start_video_analysis([row["path"]], force=True)
            elif row:
                messagebox.showinfo(APP_NAME, "O arquivo selecionado não é um vídeo.", parent=dialog)

        def thumbnail_selected_video() -> None:
            row = selected_row()
            if not row:
                return
            if row["category"] != "Vídeos":
                messagebox.showinfo(APP_NAME, "O arquivo selecionado não é um vídeo.", parent=dialog)
                return
            cached = row_get(row, "thumbnail_path")
            if cached and Path(cached).exists():
                self.show_thumbnail_preview(Path(cached), row["name"])
            else:
                self.generate_thumbnail_for_row(row, dialog)

        def rename_selected_file() -> None:
            row = selected_row()
            if row and self.rename_comparison_row(row, dialog):
                dialog.destroy()
                self.refresh_after_file_change()

        def quarantine_selected_file() -> None:
            row = selected_row()
            if row and self.quarantine_comparison_row(row, dialog):
                dialog.destroy()
                self.refresh_after_file_change()

        def delete_selected_file() -> None:
            row = selected_row()
            if row and self.delete_comparison_row(row, dialog):
                dialog.destroy()
                self.refresh_after_file_change()

        def quarantine_multiple_files() -> None:
            rows = selected_rows_in_comparison()
            if not rows:
                messagebox.showinfo(APP_NAME, "Selecione um ou mais arquivos.", parent=dialog)
                return
            if self.quarantine_rows_batch(rows, parent=dialog, explanation=f"Enviar {len(rows)} arquivo(s) selecionado(s) para quarentena reversível?"):
                dialog.destroy()

        def delete_multiple_files() -> None:
            rows = selected_rows_in_comparison()
            if not rows:
                messagebox.showinfo(APP_NAME, "Selecione um ou mais arquivos.", parent=dialog)
                return
            if self.delete_rows_batch(rows, parent=dialog, explanation=f"Excluir permanentemente {len(rows)} arquivo(s) selecionado(s)?"):
                dialog.destroy()

        def rename_multiple_files() -> None:
            rows = selected_rows_in_comparison()
            if not rows:
                messagebox.showinfo(APP_NAME, "Selecione um ou mais arquivos.", parent=dialog)
                return
            self.rename_rows_batch(rows, parent=dialog, close_callback=dialog.destroy)

        tree.bind("<Double-1>", lambda _event: open_selected_file())
        context = __import__("tkinter").Menu(dialog, tearoff=0)
        context.add_command(label="Abrir arquivo", command=open_selected_file)
        context.add_command(label="Mostrar no Explorer", command=reveal_selected_file)
        context.add_separator()
        context.add_command(label="Analisar metadados do vídeo", command=analyze_selected_video)
        context.add_command(label="Gerar / abrir miniatura", command=thumbnail_selected_video)
        context.add_separator()
        context.add_command(label="Copiar nome", command=copy_selected_name)
        context.add_command(label="Copiar caminho", command=copy_selected_path)
        context.add_separator()
        context.add_command(label="Renomear arquivo…", command=rename_selected_file)
        context.add_command(label="Enviar para quarentena", command=quarantine_selected_file)
        context.add_command(label="Excluir permanentemente…", command=delete_selected_file)
        context.add_separator()
        context.add_command(label="Selecionar todos", command=select_all_rows)
        context.add_command(label="Limpar seleção", command=clear_rows_selection)
        context.add_command(label="Quarentena dos selecionados", command=quarantine_multiple_files)
        context.add_command(label="Renomear selecionados…", command=rename_multiple_files)
        context.add_command(label="Excluir selecionados…", command=delete_multiple_files)

        def show_context(event) -> None:
            item = tree.identify_row(event.y)
            if item:
                tree.selection_set(item)
                context.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", show_context)
        actions = ttk.Frame(dialog, padding=(18, 0, 18, 10))
        actions.pack(fill=X)
        ttk.Button(actions, text="Selecionar tudo", command=select_all_rows).pack(side=LEFT)
        ttk.Button(actions, text="Limpar seleção", command=clear_rows_selection).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Abrir arquivo", command=open_selected_file, style="Primary.TButton").pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Mostrar no Explorer", command=reveal_selected_file).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Analisar vídeo", command=analyze_selected_video).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Miniatura", command=thumbnail_selected_video).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Copiar nome", command=copy_selected_name).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Copiar caminho", command=copy_selected_path).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Renomear…", command=rename_selected_file).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Quarentena", command=quarantine_selected_file).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Excluir permanentemente", command=delete_selected_file, style="Danger.TButton").pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Renomear selecionados", command=rename_multiple_files).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Quarentena selecionados", command=quarantine_multiple_files).pack(side=LEFT, padx=4)
        ttk.Button(actions, text="Excluir selecionados", command=delete_multiple_files, style="Danger.TButton").pack(side=LEFT, padx=4)
        ttk.Label(actions, text="Use Ctrl/Shift ou Selecionar tudo para ações em massa.", style="Sub.TLabel").pack(side=RIGHT)
        footer = ttk.Frame(dialog, padding=(18, 0, 18, 16))
        footer.pack(fill=X)
        ttk.Button(footer, text="Abrir local do maior", command=lambda: self.open_path_for_row(max(rows, key=lambda r: int(r["size"])), dialog)).pack(side=LEFT)
        ttk.Button(footer, text="Fechar", command=dialog.destroy).pack(side=RIGHT)

    def copy_text_to_clipboard(self, value: str, status: str, dialog=None) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()
        self.status_var.set(status)
        if dialog:
            dialog.focus_set()

    def open_file_for_row(self, row, dialog=None) -> None:
        path = Path(row["path"])
        if not path.exists():
            messagebox.showwarning(APP_NAME, "O arquivo não está mais disponível neste caminho.", parent=dialog or self.root)
            return
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível abrir o arquivo: {exc}", parent=dialog or self.root)
        if dialog:
            dialog.focus_set()

    def reveal_file_for_row(self, row, dialog=None) -> None:
        path = Path(row["path"])
        if not path.exists():
            messagebox.showwarning(APP_NAME, "O arquivo não está mais disponível neste caminho.", parent=dialog or self.root)
            return
        try:
            subprocess.Popen(["explorer.exe", f"/select,{path}"])
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível abrir o Explorer: {exc}", parent=dialog or self.root)
        if dialog:
            dialog.focus_set()

    def open_path_for_row(self, row, dialog=None) -> None:
        self.reveal_file_for_row(row, dialog)

    def rename_comparison_row(self, row, dialog=None) -> bool:
        path = Path(row["path"])
        if not path.exists():
            messagebox.showwarning(APP_NAME, "O arquivo não está mais disponível.", parent=dialog or self.root)
            return False
        new_name = filedialog.asksaveasfilename(parent=dialog or self.root, title="Escolha o novo nome", initialdir=str(path.parent), initialfile=path.name, defaultextension=path.suffix, filetypes=[("Mesmo tipo", f"*{path.suffix}"), ("Todos os arquivos", "*.*")])
        if not new_name:
            return False
        target = Path(new_name)
        if target.suffix.lower() != path.suffix.lower():
            target = target.with_suffix(path.suffix)
        if target == path:
            return False
        if target.exists():
            messagebox.showerror(APP_NAME, "Já existe um arquivo com esse nome.", parent=dialog or self.root)
            return False
        if not messagebox.askyesno("Confirmar renomeação", f"Renomear:\n{path.name}\n\npara:\n{target.name}?", parent=dialog or self.root):
            return False
        try:
            self.apply_renames([(row, target.name, "Pronto")])
            self.db.update_path(str(path), str(target))
            return True
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível renomear: {exc}", parent=dialog or self.root)
            return False

    def quarantine_comparison_row(self, row, dialog=None) -> bool:
        root = Path(self.root_path)
        source = Path(row["path"])
        destination_root = root / "_Organizador_HD_Quarentena"
        if not source.exists():
            messagebox.showwarning(APP_NAME, "O arquivo não está mais disponível.", parent=dialog or self.root)
            return False
        if not messagebox.askyesno("Confirmar quarentena", f"Mover {source.name} para a quarentena reversível?", parent=dialog or self.root):
            return False
        try:
            destination_root.mkdir(exist_ok=True)
            destination = destination_root / safe_relative(source, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = destination.with_name(f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}")
            shutil.move(str(source), str(destination))
            self.db.delete_file(str(source))
            manifest = destination_root / "manifest.jsonl"
            with manifest.open("a", encoding="utf-8") as handle:
                record = {"time": now_iso(), "name": source.name, "original": str(source), "quarantine": str(destination), "size": int(row["size"]), "sha256": row["sha256"]}
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível enviar para quarentena: {exc}", parent=dialog or self.root)
            return False

    def delete_comparison_row(self, row, dialog=None) -> bool:
        path = Path(row["path"])
        if not path.exists():
            messagebox.showwarning(APP_NAME, "O arquivo não está mais disponível.", parent=dialog or self.root)
            return False
        parent = dialog or self.root
        if not messagebox.askyesno("Excluir permanentemente", f"ATENÇÃO: excluir permanentemente?\n\n{path.name}\n\nEsta ação não pode ser desfeita. Para uma opção reversível, use Quarentena.", parent=parent):
            return False
        if not messagebox.askyesno("Confirmação final", "Confirma a exclusão permanente deste arquivo?", parent=parent):
            return False
        try:
            path.unlink()
            self.db.delete_file(str(path))
            return True
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível excluir: {exc}", parent=parent)
            return False

    def refresh_after_file_change(self) -> None:
        self.refresh_files()
        self.refresh_summary()
        self.refresh_duplicates()
        self.load_quarantine()

    def select_all_tree(self, tree) -> None:
        if tree:
            tree.selection_set(tree.get_children())

    def clear_tree_selection(self, tree) -> None:
        if tree:
            tree.selection_remove(tree.selection())

    def selected_groups(self, tree, data: dict[str, list[sqlite3.Row]]) -> list[list[sqlite3.Row]]:
        return [data[item] for item in tree.selection() if item in data]

    def rows_from_groups(self, groups: list[list[sqlite3.Row]], keep_largest: bool = False) -> tuple[list[sqlite3.Row], int]:
        result: list[sqlite3.Row] = []
        seen: set[str] = set()
        kept = 0
        for group in groups:
            ordered = sorted(group, key=lambda row: (int(row["size"]), float(row["mtime"])), reverse=True)
            keeper = ordered[0] if ordered else None
            for row in ordered:
                path = str(row["path"])
                if keep_largest and row is keeper:
                    kept += 1
                    continue
                if path not in seen:
                    result.append(row)
                    seen.add(path)
        return result, kept

    def quarantine_rows_batch(self, rows: list[sqlite3.Row], parent=None, explanation: str = "") -> bool:
        unique_rows = []
        seen: set[str] = set()
        for row in rows:
            path = str(row["path"])
            if path not in seen and Path(path).exists():
                unique_rows.append(row)
                seen.add(path)
        if not unique_rows:
            messagebox.showinfo(APP_NAME, "Nenhum arquivo disponível para a ação.", parent=parent or self.root)
            return False
        text = explanation or f"Mover {len(unique_rows)} arquivo(s) para a quarentena reversível?"
        if not messagebox.askyesno("Confirmar quarentena em massa", text, parent=parent or self.root):
            return False
        root = Path(self.root_path)
        quarantine_root = root / "_Organizador_HD_Quarentena"
        moved = 0
        errors = []
        try:
            quarantine_root.mkdir(exist_ok=True)
            manifest_path = quarantine_root / "manifest.jsonl"
            with manifest_path.open("a", encoding="utf-8") as manifest:
                for row in unique_rows:
                    source = Path(row["path"])
                    try:
                        relative = safe_relative(source, root)
                        destination = quarantine_root / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if destination.exists():
                            destination = destination.with_name(f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}")
                        shutil.move(str(source), str(destination))
                        self.db.delete_file(str(source))
                        record = {"time": now_iso(), "name": source.name, "original": str(source), "quarantine": str(destination), "size": int(row["size"]), "sha256": row["sha256"]}
                        manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
                        moved += 1
                    except OSError as exc:
                        errors.append(f"{source.name}: {exc}")
            self.refresh_after_file_change()
            self.load_quarantine()
            message = f"{moved} arquivo(s) enviado(s) para quarentena."
            if errors:
                message += f" {len(errors)} falha(s)."
            self.status_var.set(message)
            if errors:
                messagebox.showwarning(APP_NAME, message + "\n\n" + "\n".join(errors[:8]), parent=parent or self.root)
            return moved > 0
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"A quarentena em massa foi interrompida: {exc}", parent=parent or self.root)
            return False

    def delete_rows_batch(self, rows: list[sqlite3.Row], parent=None, explanation: str = "") -> bool:
        unique_rows = []
        seen: set[str] = set()
        for row in rows:
            path = str(row["path"])
            if path not in seen and Path(path).exists():
                unique_rows.append(row)
                seen.add(path)
        if not unique_rows:
            messagebox.showinfo(APP_NAME, "Nenhum arquivo disponível para a ação.", parent=parent or self.root)
            return False
        parent = parent or self.root
        if not messagebox.askyesno("Excluir arquivos selecionados", explanation or f"Excluir permanentemente {len(unique_rows)} arquivo(s)?", parent=parent):
            return False
        if not messagebox.askyesno("Confirmação final", "Esta exclusão não pode ser desfeita. Confirma novamente?", parent=parent):
            return False
        deleted = 0
        errors = []
        for row in unique_rows:
            path = Path(row["path"])
            try:
                path.unlink()
                self.db.delete_file(str(path))
                deleted += 1
            except OSError as exc:
                errors.append(f"{path.name}: {exc}")
        self.refresh_after_file_change()
        message = f"{deleted} arquivo(s) excluído(s) permanentemente."
        if errors:
            message += f" {len(errors)} falha(s)."
        self.status_var.set(message)
        if errors:
            messagebox.showwarning(APP_NAME, message + "\n\n" + "\n".join(errors[:8]), parent=parent)
        return deleted > 0

    def rename_rows_batch(self, rows: list[sqlite3.Row | dict], parent=None, close_callback=None) -> bool:
        parent = parent or self.root
        find_text = simpledialog.askstring("Renomeação em massa", "Texto a procurar no nome (deixe vazio para não substituir):", parent=parent)
        if find_text is None:
            return False
        replace_text = simpledialog.askstring("Renomeação em massa", "Substituir por:", parent=parent, initialvalue="")
        if replace_text is None:
            return False
        prefix = simpledialog.askstring("Renomeação em massa", "Prefixo opcional:", parent=parent, initialvalue="")
        if prefix is None:
            return False
        suffix = simpledialog.askstring("Renomeação em massa", "Sufixo opcional:", parent=parent, initialvalue="")
        if suffix is None:
            return False
        add_number = messagebox.askyesno("Renomeação em massa", "Adicionar numeração sequencial aos novos nomes?", parent=parent)
        preview = []
        seen: set[str] = set()
        for index, row in enumerate(rows, 1):
            path = Path(row["path"])
            stem = path.stem
            new_stem = stem.replace(find_text, replace_text) if find_text else stem
            new_stem = f"{prefix}{new_stem}{suffix}"
            if add_number:
                new_stem = f"{index:03d}_{new_stem}"
            target = path.with_name(new_stem + path.suffix)
            status = "Pronto"
            key = str(target).lower()
            if key in seen or (target != path and target.exists()):
                status = "Bloqueado: colisão"
            seen.add(key)
            preview.append((row, target.name, status))
        blocked = [item for item in preview if item[2] != "Pronto"]
        sample = "\n".join(f"{item[0]['name']}  →  {item[1]}" for item in preview[:12])
        if len(preview) > 12:
            sample += f"\n… e mais {len(preview) - 12} arquivo(s)"
        if blocked:
            messagebox.showerror("Renomeação bloqueada", "Existem colisões na prévia. Nenhum arquivo foi alterado.", parent=parent)
            return False
        if not messagebox.askyesno("Confirmar renomeação em massa", f"Prévia de {len(preview)} arquivo(s):\n\n{sample}\n\nConfirmar?", parent=parent):
            return False
        try:
            self.apply_renames(preview)
            for row, new_name, _status in preview:
                self.db.update_path(str(row["path"]), str(Path(row["path"]).with_name(new_name)))
            self.refresh_after_file_change()
            self.status_var.set(f"{len(preview)} arquivo(s) renomeado(s) em massa.")
            if close_callback:
                close_callback()
            return True
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível concluir a renomeação em massa: {exc}", parent=parent)
            return False

    def quarantine_selected_duplicate_groups(self) -> None:
        groups = self.selected_groups(self.duplicates_tree, getattr(self, "duplicate_data", {}))
        if not groups:
            messagebox.showinfo(APP_NAME, "Selecione um ou mais grupos de duplicados.")
            return
        rows, kept = self.rows_from_groups(groups, keep_largest=True)
        self.quarantine_rows_batch(rows, explanation=f"Foram selecionados {len(groups)} grupo(s). A ação enviará {len(rows)} duplicado(s) para quarentena e manterá o maior arquivo de cada grupo ({kept} mantido(s)). Continuar?")

    def delete_selected_duplicate_groups(self) -> None:
        groups = self.selected_groups(self.duplicates_tree, getattr(self, "duplicate_data", {}))
        if not groups:
            messagebox.showinfo(APP_NAME, "Selecione um ou mais grupos de duplicados.")
            return
        rows, kept = self.rows_from_groups(groups, keep_largest=True)
        self.delete_rows_batch(rows, explanation=f"Foram selecionados {len(groups)} grupo(s). A ação excluirá {len(rows)} duplicado(s) e manterá o maior arquivo de cada grupo ({kept} mantido(s)). Continuar?")

    def quarantine_selected_similar_groups(self) -> None:
        groups = self.selected_groups(self.similar_tree, getattr(self, "similar_data", {}))
        if not groups:
            messagebox.showinfo(APP_NAME, "Selecione um ou mais grupos de nomes similares.")
            return
        rows, _ = self.rows_from_groups(groups, keep_largest=False)
        self.quarantine_rows_batch(rows, explanation=f"Nomes similares não confirmam conteúdo igual. A ação enviará todos os {len(rows)} arquivo(s) dos {len(groups)} grupo(s) para quarentena. Continuar?")

    def delete_selected_similar_groups(self) -> None:
        groups = self.selected_groups(self.similar_tree, getattr(self, "similar_data", {}))
        if not groups:
            messagebox.showinfo(APP_NAME, "Selecione um ou mais grupos de nomes similares.")
            return
        rows, _ = self.rows_from_groups(groups, keep_largest=False)
        self.delete_rows_batch(rows, explanation=f"ATENÇÃO: nomes similares não confirmam conteúdo igual. A ação excluirá todos os {len(rows)} arquivo(s) dos {len(groups)} grupo(s). Continuar?")

    def refresh_duplicates(self) -> None:
        for item in self.duplicates_tree.get_children():
            self.duplicates_tree.delete(item)
        self.duplicate_data: dict[str, list[sqlite3.Row]] = {}
        if not self.root_path:
            return
        groups = self.db.duplicate_groups(self.root_path)
        for index, group in enumerate(groups, 1):
            item_id = f"dup_{index}"
            self.duplicate_data[item_id] = group
            names = " | ".join(f"{row['name']} ({format_bytes(row['size'])})" for row in group)
            biggest = max(group, key=lambda row: int(row["size"]))
            self.duplicates_tree.insert("", END, iid=item_id, values=(f"#{index}", len(group), format_bytes(sum(int(r["size"]) for r in group)), f"Manter: {biggest['name']}", names))

    def compare_duplicate_group(self) -> None:
        selected = self.duplicates_tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Selecione um grupo de duplicados.")
            return
        self.show_comparison(self.duplicate_data[selected[0]], "Comparação de duplicados exatos")

    def refresh_similar(self) -> None:
        if not self.root_path:
            messagebox.showinfo(APP_NAME, "Analise uma pasta primeiro.")
            return
        rows = self.db.all_rows(self.root_path)
        groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            signature = normalized_name(row["name"])
            if signature:
                groups[signature].append(row)
        # Comparar apenas dentro de baldes de prefixo e comprimento próximos evita O(n²)
        # no acervo completo quando há milhares de nomes diferentes.
        merged: list[list[sqlite3.Row]] = []
        buckets: dict[tuple[str, int], list[str]] = defaultdict(list)
        for signature in groups:
            if len(signature) >= 8:
                buckets[(signature[:4], len(signature) // 6)].append(signature)
        used: set[str] = set()
        for bucket_signatures in buckets.values():
            for signature in bucket_signatures:
                if signature in used:
                    continue
                group_keys = [signature]
                used.add(signature)
                for other in bucket_signatures:
                    if other in used or abs(len(other) - len(signature)) > max(8, len(signature) // 3):
                        continue
                    if name_similarity(signature, other) >= 0.84:
                        group_keys.append(other)
                        used.add(other)
                collected = [row for key in group_keys for row in groups[key]]
                if len(collected) > 1:
                    merged.append(collected)
        # Nomes normalizados idênticos, inclusive curtos, já são grupos válidos.
        for signature, group in groups.items():
            if len(group) > 1 and signature not in used:
                merged.append(group)
        merged.sort(key=lambda group: (-len(group), -max(int(r["size"]) for r in group)))
        for item in self.similar_tree.get_children():
            self.similar_tree.delete(item)
        self.similar_data: dict[str, list[sqlite3.Row]] = {}
        for index, group in enumerate(merged, 1):
            item_id = f"sim_{index}"
            self.similar_data[item_id] = group
            names = " | ".join(f"{row['name']} — {safe_relative(Path(row['path']), Path(self.root_path))}" for row in group[:8])
            if len(group) > 8:
                names += f" | +{len(group)-8} outros"
            biggest = max(group, key=lambda row: int(row["size"]))
            self.similar_tree.insert("", END, iid=item_id, values=(f"#{index}", len(group), f"{biggest['name']} ({format_bytes(biggest['size'])})", names))
        self.notebook.select(self.similar_tab)
        self.status_var.set(f"Nomes similares encontrados: {len(merged)} grupos.")

    def compare_similar_group(self) -> None:
        selected = self.similar_tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Selecione um grupo de nomes similares.")
            return
        self.show_comparison(self.similar_data[selected[0]], "Comparação de nomes similares")

    def rename_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo(APP_NAME, "Selecione pelo menos um arquivo para renomear.")
            return
        dialog = Toplevel(self.root)
        dialog.title("Renomear com prévia")
        dialog.geometry("1000x680")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Renomeação segura", style="Title.TLabel").pack(anchor="w", padx=18, pady=(16, 4))
        ttk.Label(dialog, text="A prévia é calculada antes da confirmação. Extensões são preservadas; colisões são bloqueadas.", style="Sub.TLabel").pack(anchor="w", padx=18, pady=(0, 12))
        form = ttk.Frame(dialog, padding=(18, 0, 18, 10))
        form.pack(fill=X)
        find_var = StringVar()
        replace_var = StringVar()
        prefix_var = StringVar()
        suffix_var = StringVar()
        number_var = BooleanVar(value=False)
        for row_index, (label, variable) in enumerate([("Procurar no nome", find_var), ("Substituir por", replace_var), ("Prefixo", prefix_var), ("Sufixo", suffix_var)]):
            ttk.Label(form, text=label + ":").grid(row=row_index, column=0, sticky="w", pady=4)
            entry = ttk.Entry(form, textvariable=variable, width=60)
            entry.grid(row=row_index, column=1, sticky="ew", padx=(8, 0), pady=4)
        ttk.Checkbutton(form, text="Adicionar numeração sequencial", variable=number_var).grid(row=4, column=1, sticky="w", pady=5)
        form.columnconfigure(1, weight=1)
        preview_tree = ttk.Treeview(dialog, columns=("old", "new", "status"), show="headings")
        for key, heading, width in [("old", "Nome atual", 330), ("new", "Novo nome", 390), ("status", "Status", 180)]:
            preview_tree.heading(key, text=heading)
            preview_tree.column(key, width=width, minwidth=80)
        preview_tree.pack(fill=BOTH, expand=True, padx=18, pady=(0, 12))

        def make_preview() -> list[tuple[sqlite3.Row, str, str]]:
            result = []
            seen: set[str] = set()
            for index, row in enumerate(rows, 1):
                old_name = row["name"]
                path = Path(row["path"])
                stem = path.stem
                new_stem = stem.replace(find_var.get(), replace_var.get()) if find_var.get() else stem
                new_stem = f"{prefix_var.get()}{new_stem}{suffix_var.get()}"
                if number_var.get():
                    new_stem = f"{index:03d}_{new_stem}"
                new_name = new_stem + path.suffix
                target = path.with_name(new_name)
                lower_target = str(target).lower()
                status = "Pronto"
                if lower_target in seen or (target != path and target.exists()):
                    status = "Bloqueado: colisão"
                seen.add(lower_target)
                result.append((row, new_name, status))
            return result

        def render_preview() -> None:
            for item in preview_tree.get_children():
                preview_tree.delete(item)
            for row, new_name, status in make_preview():
                preview_tree.insert("", END, values=(row["name"], new_name, status))

        for variable in [find_var, replace_var, prefix_var, suffix_var, number_var]:
            variable.trace_add("write", lambda *_args: render_preview())
        render_preview()

        footer = ttk.Frame(dialog, padding=(18, 0, 18, 16))
        footer.pack(fill=X)
        ttk.Button(footer, text="Atualizar prévia", command=render_preview).pack(side=LEFT)
        ttk.Button(footer, text="Cancelar", command=dialog.destroy).pack(side=RIGHT, padx=(6, 0))

        def execute() -> None:
            preview = make_preview()
            blocked = [x for x in preview if x[2] != "Pronto"]
            if blocked:
                messagebox.showerror("Renomeação bloqueada", "Corrija as colisões indicadas na prévia antes de continuar.", parent=dialog)
                return
            if not messagebox.askyesno("Confirmar renomeação", f"Renomear {len(preview)} arquivo(s)? Esta ação altera somente os nomes, não o conteúdo.", parent=dialog):
                return
            try:
                self.apply_renames(preview)
                for row, new_name, _status in preview:
                    self.db.update_path(str(row["path"]), str(Path(row["path"]).with_name(new_name)))
                dialog.destroy()
                self.refresh_files()
                self.status_var.set(f"{len(preview)} arquivo(s) renomeado(s) com sucesso.")
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Não foi possível concluir a renomeação: {exc}", parent=dialog)

        ttk.Button(footer, text="Confirmar renomeação", style="Primary.TButton", command=execute).pack(side=RIGHT)

    def apply_renames(self, preview: list[tuple[sqlite3.Row, str, str]]) -> None:
        temp_paths: list[tuple[Path, Path, Path]] = []
        try:
            for row, new_name, _status in preview:
                old_path = Path(row["path"])
                temp_path = old_path.with_name(f".__organizador_tmp_{uuid.uuid4().hex}{old_path.suffix}")
                os.replace(old_path, temp_path)
                temp_paths.append((old_path, temp_path, old_path.with_name(new_name)))
            for old_path, temp_path, new_path in temp_paths:
                os.replace(temp_path, new_path)
        except Exception:
            for old_path, temp_path, new_path in reversed(temp_paths):
                try:
                    if temp_path.exists():
                        os.replace(temp_path, old_path)
                    elif new_path.exists() and not old_path.exists():
                        os.replace(new_path, old_path)
                except OSError:
                    pass
            raise

    def quarantine_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo(APP_NAME, "Selecione pelo menos um arquivo para a quarentena.")
            return
        root = Path(self.root_path)
        quarantine_root = root / "_Organizador_HD_Quarentena"
        message = f"Mover {len(rows)} arquivo(s) para uma quarentena reversível em:\n{quarantine_root}\n\nNenhum arquivo será apagado permanentemente. Continuar?"
        if not messagebox.askyesno("Confirmar quarentena", message):
            return
        try:
            quarantine_root.mkdir(exist_ok=True)
            manifest_path = quarantine_root / "manifest.jsonl"
            with manifest_path.open("a", encoding="utf-8") as manifest:
                for row in rows:
                    source = Path(row["path"])
                    relative = safe_relative(source, root)
                    destination = quarantine_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        destination = destination.with_name(f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}")
                    shutil.move(str(source), str(destination))
                    record = {"time": now_iso(), "name": source.name, "original": str(source), "quarantine": str(destination), "size": int(row["size"]), "sha256": row["sha256"]}
                    manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.db.conn.commit()
            self.refresh_files()
            self.refresh_summary()
            self.load_quarantine()
            self.status_var.set(f"{len(rows)} arquivo(s) enviado(s) para quarentena reversível.")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"A quarentena foi interrompida: {exc}")

    def load_quarantine(self) -> None:
        for item in self.quarantine_tree.get_children():
            self.quarantine_tree.delete(item)
        self.quarantine_rows = []
        if not self.root_path:
            return
        manifest = Path(self.root_path) / "_Organizador_HD_Quarentena" / "manifest.jsonl"
        if not manifest.exists():
            return
        try:
            with manifest.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        record = json.loads(line)
                        record["status"] = "Disponível" if Path(record["quarantine"]).exists() else ("Restaurado" if Path(record["original"]).exists() else "Ausente")
                        self.quarantine_rows.append(record)
            for index, record in enumerate(reversed(self.quarantine_rows)):
                self.quarantine_tree.insert("", END, iid=f"q_{index}", values=(record.get("time", ""), record.get("name", ""), record.get("original", ""), record.get("quarantine", ""), record.get("status", "")))
        except (OSError, json.JSONDecodeError) as exc:
            self.status_var.set(f"Não foi possível ler o manifesto: {exc}")

    def restore_selected(self) -> None:
        selected = self.quarantine_tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Selecione itens disponíveis para restaurar.")
            return
        records = []
        for item in selected:
            index = int(item.split("_")[-1])
            record = list(reversed(self.quarantine_rows))[index]
            if record.get("status") == "Disponível":
                records.append(record)
        if not records:
            messagebox.showinfo(APP_NAME, "Os itens selecionados não estão disponíveis para restauração.")
            return
        if not messagebox.askyesno("Confirmar restauração", f"Restaurar {len(records)} arquivo(s) para os locais originais?"):
            return
        restored = 0
        for record in records:
            source = Path(record["quarantine"])
            target = Path(record["original"])
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    messagebox.showwarning(APP_NAME, f"O destino já existe e não foi sobrescrito:\n{target}")
                    continue
                shutil.move(str(source), str(target))
                restored += 1
            except OSError:
                continue
        self.load_quarantine()
        self.refresh_files()
        self.refresh_summary()
        self.status_var.set(f"{restored} arquivo(s) restaurado(s).")

    def open_quarantine_folder(self) -> None:
        if not self.root_path:
            messagebox.showinfo(APP_NAME, "Escolha uma pasta primeiro.")
            return
        folder = Path(self.root_path) / "_Organizador_HD_Quarentena"
        folder.mkdir(exist_ok=True)
        try:
            os.startfile(str(folder))
        except AttributeError:
            pass

    def export_csv(self) -> None:
        if not self.root_path:
            messagebox.showinfo(APP_NAME, "Analise uma pasta primeiro.")
            return
        destination = filedialog.asksaveasfilename(title="Exportar índice", defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="relatorio_organizador_hd.csv")
        if not destination:
            return
        rows = self.db.all_rows(self.root_path)
        try:
            with open(destination, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["Nome", "Caminho", "Categoria", "Extensão", "Tamanho bytes", "Tamanho legível", "Resolução", "Duração", "Codec vídeo", "Codec áudio", "FPS", "Bitrate", "Contêiner", "Modificado", "SHA-256", "Erro análise vídeo"])
                for row in rows:
                    writer.writerow([row["name"], row["path"], row["category"], row["extension"], row["size"], format_bytes(row["size"]), format_resolution(row), format_duration(row_get(row, "video_duration")), row_get(row, "video_codec") or "", row_get(row, "audio_codec") or "", row_get(row, "video_fps") or "", row_get(row, "video_bitrate") or "", row_get(row, "video_container") or "", format_date(row["mtime"]), row["sha256"] or "", row_get(row, "video_error") or ""])
            messagebox.showinfo(APP_NAME, f"CSV exportado com {len(rows)} registros.")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível exportar: {exc}")

    def show_report(self) -> None:
        if not self.root_path:
            messagebox.showinfo(APP_NAME, "Analise uma pasta primeiro.")
            return
        data = self.db.summary(self.root_path)
        dialog = Toplevel(self.root)
        dialog.title("Relatório do acervo")
        dialog.geometry("1000x720")
        text = ScrolledText(dialog, wrap="word", font=("Consolas", 10))
        text.pack(fill=BOTH, expand=True, padx=14, pady=14)
        rows_for_report = self.db.all_rows(self.root_path)
        video_count = sum(1 for row in rows_for_report if row["category"] == "Vídeos")
        analyzed_videos = sum(1 for row in rows_for_report if row["category"] == "Vídeos" and row_get(row, "video_analyzed_at") is not None)
        lines = [f"{APP_NAME} — relatório", f"Gerado em: {now_iso()}", f"Pasta: {self.root_path}", "", f"Total: {data['count']:,} arquivos | {format_bytes(data['size'])}".replace(",", "."), f"Grupos duplicados com hash: {data['duplicate_groups']}", f"Vídeos: {video_count} | Metadados analisados: {analyzed_videos}", "", "POR CATEGORIA"]
        for row in data["categories"]:
            lines.append(f"  {row[0]:<16} {row[1]:>8} arquivos   {format_bytes(row[2]):>14}")
        lines.extend(["", "EXTENSÕES MAIS FREQUENTES"])
        for row in data["extensions"]:
            lines.append(f"  {(row[0] or '[sem extensão]'):<16} {row[1]:>8} arquivos   {format_bytes(row[2]):>14}")
        lines.extend(["", "15 MAIORES ARQUIVOS"])
        for index, row in enumerate(data["largest"], 1):
            lines.append(f"  {index:>2}. {format_bytes(row['size']):>14} | {row['name']} | {row['path']}")
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        ttk.Button(dialog, text="Fechar", command=dialog.destroy).pack(anchor="e", padx=14, pady=(0, 14))

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Uma operação está em andamento. Parar e fechar?", parent=self.root):
                return
            self.cancel_event.set()
        self.db.close()
        self.root.destroy()


def main() -> None:
    app_root = Tk()
    OrganizadorApp(app_root)
    app_root.mainloop()


if __name__ == "__main__":
    main()

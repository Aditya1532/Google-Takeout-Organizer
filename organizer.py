"""Safe, copy-first file organization primitives for Windows and other platforms."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

EXCLUDED_NAMES = {
    "windows", "program files", "program files (x86)", "programdata", "appdata",
    "windowsapps", "system volume information", "$recycle.bin", "recovery",
    "boot", "documents and settings", "config.msi", "msocache",
}
EXTENSIONS = {
    "Photos": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".raw"},
    "Videos": {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".wmv", ".webm"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"},
    "PDFs": {".pdf"},
    "Archives": {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2"},
    "Software Installers": {".exe", ".msi", ".msix", ".appx", ".deb", ".dmg", ".pkg"},
    "Code": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".html", ".css", ".json", ".ipynb"},
    "Documents": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
}

@dataclass
class Candidate:
    source: str
    destination: str
    category: str
    reason: str
    size: int
    warning: str = ""
    decision: str = "include"
    reviewed: bool = False
    operation: str = "Copy"
    replace_existing: bool = False
    replacement_target: str = ""

def preflight_destination_space(candidates: list[Candidate], destination: Path,
                                reserve_bytes: int = 64 * 1024 * 1024) -> tuple[bool, str]:
    """Estimate staging and replacement-backup space before any output is written."""
    destination = Path(destination).expanduser()
    try:
        anchor = destination
        while not anchor.exists() and anchor != anchor.parent:
            anchor = anchor.parent
        if not anchor.is_dir():
            return False, f"Cannot check destination storage: {anchor} is not an available folder."
        usage = shutil.disk_usage(anchor)
        needed = 0
        for candidate in candidates:
            source = Path(candidate.source)
            needed += source.stat().st_size
            target = Path(candidate.destination)
            if candidate.replace_existing and target.exists():
                needed += target.stat().st_size  # The old output is backed up before replacement.
        reserve = max(reserve_bytes, int(needed * 0.05))
    except OSError as exc:
        return False, f"Cannot safely check the destination or source file sizes ({exc}). No files were copied."

    required = needed + reserve
    if usage.free < required:
        def size_text(value):
            units = ("B", "KB", "MB", "GB", "TB")
            amount = float(value)
            for unit in units:
                if amount < 1024 or unit == units[-1]:
                    return f"{amount:.1f} {unit}"
                amount /= 1024
        return False, (f"Not enough free space on the destination drive.\n\n"
                       f"Available: {size_text(usage.free)}\n"
                       f"Estimated for this operation: {size_text(needed)}\n"
                       f"Safety reserve: {size_text(reserve)}\n\n"
                       "The operation was stopped before copying. Free space or choose another destination, then preview again.")
    return True, f"Destination space check passed ({usage.free:,} bytes free; about {required:,} bytes reserved)."

def excluded_path(path: Path) -> bool:
    """Reject known system locations and protected directory names at any depth."""
    try:
        parts = [p.casefold() for p in path.parts]
        if any(p in EXCLUDED_NAMES for p in parts):
            return True
        # Windows protected locations even when their directory has been renamed/mounted.
        text = str(path).casefold().replace("/", "\\")
        for marker in ("\\windows\\", "\\program files\\", "\\program files (x86)\\", "\\programdata\\", "\\windowsapps\\", "\\system volume information\\"):
            if marker in text:
                return True
        return False
    except (OSError, ValueError):
        return True

def is_link_or_junction(path: Path) -> bool:
    """Detect symlinks and, on Python versions that expose it, Windows junctions."""
    try:
        if path.is_symlink(): return True
        checker = getattr(path, "is_junction", None)
        if checker and checker(): return True
        checker = getattr(os.path, "isjunction", None)
        return bool(checker and checker(path))
    except (OSError, ValueError):
        return True

def index_existing_files_by_name(root: Path) -> dict[str, list[Path]]:
    """Index output files by case-insensitive basename without following links."""
    index: dict[str, list[Path]] = {}
    root = Path(root).expanduser()
    if not root.is_dir(): return index
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=lambda _error: None):
        here = Path(current)
        dirs[:] = [name for name in dirs if name.casefold() != ".ai-file-organizer"
                   and not is_link_or_junction(here / name)]
        for name in files:
            path = here / name
            if is_link_or_junction(path): continue
            try:
                if path.is_file(): index.setdefault(name.casefold(), []).append(path)
            except OSError:
                continue
    return index

def indices_without_output_name_match(candidates: list[Candidate],
                                      existing_index: dict[str, list[Path]]) -> list[int]:
    """Return candidate indexes whose source basename is not anywhere in output."""
    return [index for index, candidate in enumerate(candidates)
            if not existing_index.get(Path(candidate.source).name.casefold())]

def folder_size_bytes(root: Path, cancel: threading.Event | None = None) -> int | None:
    """Quickly sum file metadata with scandir; never follow links; None means cancelled."""
    root = Path(root)
    if excluded_path(root) or is_link_or_junction(root): return 0
    total = 0
    stack = [root]
    visited = 0
    while stack:
        if cancel and cancel.is_set(): return None
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if cancel and visited % 128 == 0 and cancel.is_set(): return None
                    if entry.name.casefold() in EXCLUDED_NAMES: continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    # Junctions and symbolic links are reparse points on Windows;
                    # POSIX symlinks have a non-regular, non-directory mode.
                    attrs = getattr(info, "st_file_attributes", 0)
                    if attrs & 0x400: continue  # FILE_ATTRIBUTE_REPARSE_POINT
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
        except OSError:
            continue
    return total

def classify(path: Path, ai_classifier: Callable[[Path], str | None] | None = None,
             context_path: Path | None = None) -> tuple[str, str]:
    ext = path.suffix.casefold()
    # A year-labelled folder is the organizing signal, regardless of file type.
    # Keep the year folder hierarchy shared by every Google Takeout part.
    context_parts = context_path.parts if context_path is not None else path.parts
    for part in reversed(context_parts):
        segment = part.casefold()
        year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", segment)
        short_photo_year = re.search(r"\bphotos?\s*[_-]?\s*(\d{2})\b", segment)
        if year_match:
            year = year_match.group(1)
            return f"Data/{year}", f"All file types grouped under Data/{year} from source folder '{part}'"
        if short_photo_year:
            year = f"20{short_photo_year.group(1)}"
            return f"Data/{year}", f"All file types grouped under Data/{year} from source folder '{part}'"
    metadata_year = _takeout_photo_year(path)
    if metadata_year:
        return f"Data/{metadata_year}", f"Grouped under Data/{metadata_year} using Google Photos Takeout sidecar date"
    for category, extensions in EXTENSIONS.items():
        if ext in extensions:
            return category, f"File extension {ext}"
    name = path.name.casefold()
    if "resume" in name or "cv" in name:
        return "Resumes", "Filename suggests a resume"
    if any(word in name for word in ("college", "lecture", "assignment", "course", "semester")):
        return "College", "Filename suggests college or coursework"
    if any(word in name for word in ("project", "portfolio", "prototype")):
        return "Projects", "Filename suggests a project"
    if ai_classifier:
        try:
            result = ai_classifier(path)
            if result:
                return result, "Optional local AI suggestion"
        except Exception:
            pass
    return "Review Needed", "No confident local rule matched"


def _metadata_sidecar_for_photo(photo: Path) -> Path | None:
    """Find common Google Photos Takeout JSON sidecar names beside a photo."""
    candidates = (
        Path(str(photo) + ".json"),
        photo.with_name(photo.name + ".supplemental-metadata.json"),
    )
    for candidate in candidates:
        if candidate.is_file() and not is_link_or_junction(candidate):
            return candidate
    return None


def _photo_for_metadata_sidecar(sidecar: Path) -> Path | None:
    """Resolve the adjacent photo for filename.json or filename.supplemental-metadata.json."""
    name = sidecar.name
    suffix = ".supplemental-metadata.json"
    if name.casefold().endswith(suffix):
        photo_name = name[:-len(suffix)]
    elif name.casefold().endswith(".json"):
        photo_name = name[:-len(".json")]
    else:
        return None
    photo = sidecar.with_name(photo_name)
    if photo.suffix.casefold() not in EXTENSIONS["Photos"]:
        return None
    if photo.is_file() and not is_link_or_junction(photo):
        return photo
    return None


def _year_from_takeout_metadata(sidecar: Path) -> str | None:
    """Read a plausible original photo year from Google's photoTakenTime/creationTime."""
    try:
        # Sidecars are small JSON records. Ignore unexpectedly large files instead of
        # reading unbounded content while scanning an export.
        if sidecar.stat().st_size > 4 * 1024 * 1024 or is_link_or_junction(sidecar):
            return None
        with sidecar.open("r", encoding="utf-8-sig") as stream:
            metadata = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(metadata, dict):
        return None
    for field in ("photoTakenTime", "creationTime"):
        value = metadata.get(field)
        if not isinstance(value, dict):
            continue
        timestamp = value.get("timestamp")
        if timestamp is not None:
            try:
                year = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).year
                if 1900 <= year <= 2100:
                    return str(year)
            except (ValueError, TypeError, OverflowError, OSError):
                pass
        # Some Takeout variants retain only an ISO date string.
        for key in ("dateTime", "formatted"):
            text = value.get(key)
            if not isinstance(text, str):
                continue
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if 1900 <= parsed.year <= 2100:
                    return str(parsed.year)
            except ValueError:
                continue
    return None


def _takeout_photo_year(path: Path) -> str | None:
    """Use a paired Google Photos sidecar for a photo or its JSON file."""
    sidecar: Path | None
    if path.suffix.casefold() == ".json":
        # Generic JSON files are not Takeout photo sidecars unless their photo exists.
        if _photo_for_metadata_sidecar(path) is None:
            return None
        sidecar = path
    elif path.suffix.casefold() in EXTENSIONS["Photos"]:
        sidecar = _metadata_sidecar_for_photo(path)
    else:
        return None
    return _year_from_takeout_metadata(sidecar) if sidecar else None

def default_locations() -> list[Path]:
    home = Path.home()
    return [home / n for n in ("Desktop", "Downloads", "Documents", "Pictures", "Videos") if (home / n).is_dir()]

def scan(roots: Iterable[Path], destination_root: Path | None = None, cancel: threading.Event | None = None,
         on_error: Callable[[str], None] | None = None,
         on_progress: Callable[[int, str], None] | None = None) -> list[Candidate]:
    """Walk selected roots without following links; inaccessible folders are skipped."""
    results: list[Candidate] = []
    dest = destination_root.resolve() if destination_root and destination_root.exists() else destination_root
    for raw_root in roots:
        root = Path(raw_root)
        if cancel and cancel.is_set(): break
        if not root.exists() or excluded_path(root) or is_link_or_junction(root): continue
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=lambda e: on_error(str(e)) if on_error else None):
            here = Path(current)
            if on_progress:
                on_progress(len(results), str(here))
            dirs[:] = [d for d in dirs if not excluded_path(here / d) and not is_link_or_junction(here / d)]
            if dest and (here == dest or dest in here.parents):
                dirs[:] = []
                continue
            for name in files:
                if cancel and cancel.is_set(): return results
                src = here / name
                try:
                    if is_link_or_junction(src) or not src.is_file() or excluded_path(src): continue
                    try:
                        relative = src.relative_to(root)
                        context = Path(root.name) / relative.parent
                    except ValueError:
                        context = src.parent
                    category, reason = classify(src, context_path=context)
                    results.append(Candidate(str(src), str((destination_root or Path(".") ) / category / name), category, reason, src.stat().st_size))
                    if on_progress and (len(results) == 1 or len(results) % 25 == 0):
                        on_progress(len(results), str(here))
                except (OSError, PermissionError) as e:
                    if on_error: on_error(f"{src}: {e}")
    # Pick deterministic, distinct proposed paths; actual execution rechecks disk state.
    used: set[str] = set()
    destination_counts: dict[str, int] = {}
    for candidate in results:
        base = Path(candidate.destination)
        key = str(base.parent / Path(candidate.source).name).casefold()
        destination_counts[key] = destination_counts.get(key, 0) + 1
    for c in results:
        proposed = Path(c.destination)
        group_key = str(proposed.parent / Path(c.source).name).casefold()
        if destination_counts[group_key] > 1:
            c.warning = "Duplicate output filename; unique filename proposed"
        key = str(proposed).casefold()
        if key in used:
            i = 2
            while str(proposed.with_name(f"{proposed.stem} ({i}){proposed.suffix}")).casefold() in used: i += 1
            proposed = proposed.with_name(f"{proposed.stem} ({i}){proposed.suffix}")
            c.destination = str(proposed)
            c.warning = "Duplicate name in scan; unique filename proposed"
        used.add(str(proposed).casefold())
        if proposed.exists():
            c.warning = (c.warning + "; " if c.warning else "") + "Destination exists; unique filename proposed"
            base = proposed
            i = 2
            while True:
                alternate = base.with_name(f"{base.stem} ({i}){base.suffix}")
                if not alternate.exists() and str(alternate).casefold() not in used:
                    proposed = alternate
                    c.destination = str(alternate)
                    used.add(str(alternate).casefold())
                    break
                i += 1
        if c.category == "Review Needed" or c.warning:
            c.decision = "pending"
    return results

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

class OperationLog:
    def __init__(self, path: Path): self.path = path
    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
    def records(self) -> list[dict]:
        if not self.path.exists(): return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try: records.append(json.loads(line))
            except json.JSONDecodeError: continue
        return records

def unique_path(path: Path) -> Path:
    if not path.exists(): return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists(): return candidate
        i += 1

def copy_verified(candidate: Candidate, log: OperationLog, cancel: threading.Event | None = None) -> dict:
    src = Path(candidate.source)
    target = unique_path(Path(candidate.destination))
    if cancel and cancel.is_set(): raise InterruptedError("Cancelled")
    if not src.is_file() or is_link_or_junction(src): raise OSError(f"Source is unavailable or is a link: {src}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".organizer-", suffix=".part", dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with src.open("rb") as r, temp.open("wb") as w:
            while True:
                if cancel and cancel.is_set(): raise InterruptedError("Cancelled")
                block = r.read(1024 * 1024)
                if not block: break
                w.write(block)
            w.flush(); os.fsync(w.fileno())
        source_hash = sha256_file(src)
        if temp.stat().st_size != src.stat().st_size or sha256_file(temp) != source_hash:
            raise IOError("Copy verification failed")
        # Atomic no-overwrite publication; recheck immediately before publishing.
        while target.exists(): target = unique_path(target)
        try: os.link(temp, target)
        except (OSError, NotImplementedError):
            # Exclusive creation is required here: replace() could overwrite a
            # file created by another process between our existence check and publish.
            while True:
                try:
                    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                    break
                except FileExistsError:
                    target = unique_path(target)
            try:
                with os.fdopen(fd, "wb") as writer, temp.open("rb") as reader:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                    writer.flush(); os.fsync(writer.fileno())
                if target.stat().st_size != src.stat().st_size or sha256_file(target) != source_hash:
                    raise IOError("Published copy verification failed")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        temp.unlink(missing_ok=True)
        record = {"action": "copy", "source": str(src), "destination": str(target), "size": src.stat().st_size,
                  "sha256": source_hash, "time": time.time(), "status": "complete"}
        log.append(record)
        return record
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

def copy_batch_verified(candidates: list[Candidate], log: OperationLog,
                        cancel: threading.Event | None = None,
                        on_progress: Callable[[dict], None] | None = None) -> tuple[list[dict], list[str], bool]:
    """Stage the whole batch, verify every staged copy, then publish complete files."""
    total_files = len(candidates)
    total_bytes = max(1, sum(c.size for c in candidates))
    work_total = max(1, total_bytes * 3)  # one copy pass plus source and destination hash passes
    started = time.monotonic()
    verify_started: float | None = None
    copied_bytes = 0
    hashed_bytes = 0
    staged: list[dict] = []
    records: list[dict] = []
    failures: list[str] = []
    cancelled = False

    def emit(stage: str, index: int, filename: str, work_done: int) -> None:
        if not on_progress: return
        elapsed = max(0.01, time.monotonic() - started)
        if stage == "verify" and verify_started is not None:
            verify_done = max(0, work_done - total_bytes)
            verify_elapsed = max(0.01, time.monotonic() - verify_started)
            verify_rate = verify_done / verify_elapsed if verify_done else 0
            eta = max(0, (2 * total_bytes - verify_done) / verify_rate) if verify_rate else None
            eta_phase = "Verification ETA"
            verify_percent = min(100.0, verify_done * 100.0 / (2 * total_bytes))
        else:
            copy_rate = copied_bytes / elapsed if copied_bytes else 0
            eta = max(0, (total_bytes - copied_bytes) / copy_rate) if copy_rate else None
            eta_phase = "Copy ETA"
            verify_percent = 0.0
        on_progress({"stage": stage, "index": index, "total_files": total_files,
                     "filename": filename, "copy_percent": min(99.0, copied_bytes * 99.0 / total_bytes),
                     "verify_percent": verify_percent, "eta_seconds": eta, "eta_phase": eta_phase,
                     "copied_bytes": copied_bytes, "total_bytes": total_bytes,
                     "published_count": len(records)})

    try:
        # Phase 1: copy all sources into temporary files in their destination folders.
        for index, candidate in enumerate(candidates, 1):
            if cancel and cancel.is_set(): cancelled = True; break
            src = Path(candidate.source)
            target = Path(candidate.destination) if candidate.replace_existing else unique_path(Path(candidate.destination))
            if not src.is_file() or is_link_or_junction(src):
                raise OSError(f"Source is unavailable or is a link: {src}")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".organizer-", suffix=".part", dir=target.parent)
            os.close(fd)
            temp = Path(temp_name)
            item = {"candidate": candidate, "source": src, "target": target, "temp": temp, "sha256": ""}
            staged.append(item)
            emit("copy", index, src.name, copied_bytes)
            with src.open("rb") as reader, temp.open("wb") as writer:
                while True:
                    if cancel and cancel.is_set(): cancelled = True; break
                    block = reader.read(1024 * 1024)
                    if not block: break
                    writer.write(block)
                    copied_bytes += len(block)
                    emit("copy", index, src.name, copied_bytes)
                writer.flush(); os.fsync(writer.fileno())
            if cancelled: break
        if cancelled:
            for item in staged: item["temp"].unlink(missing_ok=True)
            emit("cancelled", len(staged), "", copied_bytes)
            return records, failures, True

        # Phase 2: verify source and staged copy hashes while the bar pulses at 99%.
        verify_started = time.monotonic()
        for index, item in enumerate(staged, 1):
            src, temp = item["source"], item["temp"]
            emit("verify", index, src.name, total_bytes + hashed_bytes)
            if temp.stat().st_size != src.stat().st_size:
                raise IOError(f"Size verification failed: {src}")
            def hash_with_progress(path: Path) -> str:
                nonlocal hashed_bytes
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        if cancel and cancel.is_set(): raise InterruptedError("Cancelled during verification")
                        digest.update(block)
                        hashed_bytes += len(block)
                        emit("verify", index, src.name, total_bytes + hashed_bytes)
                return digest.hexdigest()
            source_hash = hash_with_progress(src)
            copy_hash = hash_with_progress(temp)
            if source_hash != copy_hash:
                raise IOError(f"SHA-256 verification failed: {src}")
            item["sha256"] = source_hash

        if cancel and cancel.is_set():
            for item in staged: item["temp"].unlink(missing_ok=True)
            emit("cancelled", total_files, "", total_bytes + hashed_bytes)
            return records, failures, True

        # Phase 3: publish each verified file without replacing an existing file.
        for index, item in enumerate(staged, 1):
            if cancel and cancel.is_set(): cancelled = True; break
            temp, target = item["temp"], item["target"]
            try:
                replaced_backup = None
                replaced_sha256 = None
                if item["candidate"].replace_existing and target.exists():
                    output_root = log.path.parent.parent
                    try: relative_target = target.relative_to(output_root)
                    except ValueError: relative_target = Path(target.name)
                    backup_base = log.path.parent / "replaced" / relative_target
                    backup_base.parent.mkdir(parents=True, exist_ok=True)
                    backup_temp_fd, backup_temp_name = tempfile.mkstemp(prefix=".backup-", suffix=".part", dir=backup_base.parent)
                    os.close(backup_temp_fd)
                    backup_temp = Path(backup_temp_name)
                    item["backup_temp"] = backup_temp
                    with target.open("rb") as old_reader, backup_temp.open("wb") as backup_writer:
                        shutil.copyfileobj(old_reader, backup_writer, 1024 * 1024)
                        backup_writer.flush(); os.fsync(backup_writer.fileno())
                    replaced_sha256 = sha256_file(target)
                    if backup_temp.stat().st_size != target.stat().st_size or sha256_file(backup_temp) != replaced_sha256:
                        backup_temp.unlink(missing_ok=True)
                        raise IOError(f"Could not verify backup of existing destination: {target}")
                    while True:
                        backup_path = unique_path(backup_base)
                        try:
                            os.link(backup_temp, backup_path)
                            break
                        except FileExistsError:
                            continue
                        except OSError:
                            try: backup_fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                            except FileExistsError: continue
                            try:
                                with os.fdopen(backup_fd, "wb") as writer, backup_temp.open("rb") as reader:
                                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                                    writer.flush(); os.fsync(writer.fileno())
                                if sha256_file(backup_path) != replaced_sha256:
                                    backup_path.unlink(missing_ok=True)
                                    raise IOError("Could not verify replacement backup")
                            except BaseException:
                                backup_path.unlink(missing_ok=True)
                                raise
                            break
                    backup_temp.unlink(missing_ok=True)
                    item["backup_temp"] = None
                    replaced_backup = str(backup_path)
                    os.replace(temp, target)
                while True:
                    if replaced_backup:
                        break
                    if target.exists(): target = unique_path(target)
                    try:
                        os.link(temp, target)
                        break
                    except FileExistsError:
                        target = unique_path(target)
                    except OSError:
                        # Exclusive create is the safe fallback when hard links are unavailable.
                        try:
                            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                        except FileExistsError:
                            target = unique_path(target)
                            continue
                        try:
                            with os.fdopen(fd, "wb") as writer, temp.open("rb") as reader:
                                shutil.copyfileobj(reader, writer, 1024 * 1024)
                                writer.flush(); os.fsync(writer.fileno())
                            if target.stat().st_size != item["source"].stat().st_size or sha256_file(target) != item["sha256"]:
                                raise IOError(f"Published copy verification failed: {target}")
                        except BaseException:
                            target.unlink(missing_ok=True)
                            raise
                        break
                record = {"action": "copy", "source": str(item["source"]), "destination": str(target),
                          "size": item["source"].stat().st_size, "sha256": item["sha256"],
                          "time": time.time(), "status": "complete"}
                if replaced_backup:
                    record["replaced_backup"] = replaced_backup
                    record["replaced_sha256"] = replaced_sha256
                try:
                    log.append(record)
                except Exception:
                    if replaced_backup and Path(replaced_backup).exists() and sha256_file(target) == item["sha256"]:
                        os.replace(replaced_backup, target)
                    elif not replaced_backup and target.exists() and sha256_file(target) == item["sha256"]:
                        target.unlink()
                    raise
                records.append(record)
                temp.unlink(missing_ok=True)
                emit("publish", index, item["source"].name, total_bytes * 3)
            except Exception as error:
                if item.get("backup_temp"): Path(item["backup_temp"]).unlink(missing_ok=True)
                failures.append(f"{item['source']}: {error}")
        for item in staged: item["temp"].unlink(missing_ok=True)
        final_stage = "cancelled" if cancelled else "error" if failures else "complete"
        emit(final_stage, len(records), "", total_bytes * 3)
        return records, failures, cancelled
    except InterruptedError:
        cancelled = True
        for item in staged: item["temp"].unlink(missing_ok=True)
        emit("cancelled", len(staged), "", total_bytes + hashed_bytes)
        return records, failures, True
    except Exception as error:
        failures.append(str(error))
        for item in staged:
            item["temp"].unlink(missing_ok=True)
            if item.get("backup_temp"): Path(item["backup_temp"]).unlink(missing_ok=True)
        emit("error", len(staged), "", copied_bytes)
        return records, failures, False

def remove_sources_after_verified(records: list[dict], log: OperationLog,
                                  on_progress: Callable[[int, int, str], None] | None = None) -> tuple[int, list[str]]:
    """Remove originals only when their current content still matches a verified copy."""
    removed, skipped = 0, []
    for index, record in enumerate(records, 1):
        source, destination = Path(record["source"]), Path(record["destination"])
        try:
            if not source.is_file() or is_link_or_junction(source): skipped.append(f"Source unavailable: {source}")
            elif sha256_file(source) != record["sha256"]: skipped.append(f"Source changed since copy; kept it: {source}")
            else:
                # A Delete action already copied to the app's deleted backup folder.
                # Moves also get an independent recovery backup in case the arranged
                # destination is edited before Undo is requested.
                if ".ai-file-organizer" in destination.parts and "deleted" in destination.parts:
                    restore_backup = destination
                    if sha256_file(restore_backup) != record["sha256"]:
                        skipped.append(f"Verified delete backup changed; kept source: {source}")
                        if on_progress: on_progress(index, len(records), source.name)
                        continue
                else:
                    output_root = log.path.parent.parent
                    try: relative = destination.relative_to(output_root)
                    except ValueError: relative = Path(destination.name)
                    backup_base = log.path.parent / "moved" / relative
                    backup_base.parent.mkdir(parents=True, exist_ok=True)
                    restore_backup = unique_path(backup_base)
                    fd, backup_temp_name = tempfile.mkstemp(prefix=".moved-backup-", suffix=".part", dir=backup_base.parent)
                    os.close(fd); backup_temp = Path(backup_temp_name)
                    try:
                        shutil.copyfile(source, backup_temp)
                        if backup_temp.stat().st_size != source.stat().st_size or sha256_file(backup_temp) != record["sha256"]:
                            raise IOError("Move recovery backup verification failed")
                        try: os.link(backup_temp, restore_backup)
                        except OSError:
                            fd = os.open(restore_backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                            with os.fdopen(fd, "wb") as writer, backup_temp.open("rb") as reader:
                                shutil.copyfileobj(reader, writer, 1024 * 1024)
                                writer.flush(); os.fsync(writer.fileno())
                        if sha256_file(restore_backup) != record["sha256"]:
                            restore_backup.unlink(missing_ok=True)
                            raise IOError("Move recovery backup verification failed")
                    finally: backup_temp.unlink(missing_ok=True)
                source.unlink()
                try:
                    log.append({"action": "source_removed", "source": str(source), "destination": str(destination),
                                "restore_backup": str(restore_backup), "sha256": record["sha256"],
                                "time": time.time(), "status": "complete"})
                except Exception:
                    _restore_without_overwrite(restore_backup, source, record["sha256"])
                    if restore_backup != destination: restore_backup.unlink(missing_ok=True)
                    raise
                removed += 1
        except OSError as error: skipped.append(f"Could not remove {source}: {error}")
        if on_progress: on_progress(index, len(records), source.name)
    return removed, skipped

def _restore_without_overwrite(source: Path, destination: Path, expected_hash: str) -> bool:
    if destination.exists() or is_link_or_junction(source) or sha256_file(source) != expected_hash: return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".organizer-undo-", suffix=".part", dir=destination.parent)
    os.close(fd); temp = Path(temp_name)
    try:
        shutil.copyfile(source, temp)
        if temp.stat().st_size != source.stat().st_size or sha256_file(temp) != expected_hash: return False
        try: os.link(temp, destination)
        except FileExistsError: return False
        except OSError:
            try: fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
            except FileExistsError: return False
            try:
                with os.fdopen(fd, "wb") as writer, temp.open("rb") as reader:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                    writer.flush(); os.fsync(writer.fileno())
                if sha256_file(destination) != expected_hash:
                    destination.unlink(missing_ok=True); return False
            except BaseException:
                destination.unlink(missing_ok=True); raise
        return sha256_file(destination) == expected_hash
    finally: temp.unlink(missing_ok=True)

def undo_last(log: OperationLog) -> int:
    """Undo copies and verified moves without overwriting newer files."""
    count = 0
    records = log.records()
    source_removed_destinations = {str(Path(r["destination"])) for r in records if r.get("action") == "source_removed"}
    for record in reversed(records):
        if record.get("status") != "complete": continue
        if record.get("action") == "source_removed":
            source, dest = Path(record["source"]), Path(record["destination"])
            backup = Path(record.get("restore_backup", dest))
            if source.exists() or not backup.exists(): continue
            try:
                if not _restore_without_overwrite(backup, source, record.get("sha256", "")): continue
                if dest != backup and dest.exists() and sha256_file(dest) == record.get("sha256"):
                    dest.unlink()
                if backup.exists() and sha256_file(backup) == record.get("sha256"):
                    backup.unlink()
                log.append({"action": "undo_source_removed", "source": str(source), "destination": str(dest),
                            "time": time.time(), "status": "complete"})
                count += 1
            except OSError: continue
            continue
        if record.get("action") != "copy": continue
        dest = Path(record["destination"])
        if str(dest) in source_removed_destinations: continue
        if not dest.exists() or is_link_or_junction(dest) or sha256_file(dest) != record.get("sha256"): continue
        backup = Path(record["replaced_backup"]) if record.get("replaced_backup") else None
        if backup:
            if not backup.exists() or sha256_file(backup) != record.get("replaced_sha256"): continue
            dest.unlink()
            try: os.link(backup, dest)
            except OSError:
                try:
                    with backup.open("rb") as reader, dest.open("xb") as writer:
                        shutil.copyfileobj(reader, writer, 1024 * 1024)
                    if sha256_file(dest) != record.get("replaced_sha256"):
                        dest.unlink(missing_ok=True); continue
                except (FileExistsError, OSError): continue
            backup.unlink(missing_ok=True)
        else: dest.unlink()
        log.append({"action": "undo", "destination": str(dest), "time": time.time(), "status": "complete"})
        count += 1
    return count

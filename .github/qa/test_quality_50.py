"""Fifty user-focused regression scenarios using temporary files only."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import organizer
from organizer import (Candidate, OperationLog, classify, copy_batch_verified,
                       copy_verified, folder_size_bytes, index_existing_files_by_name,
                       remove_sources_after_verified, scan, undo_last)


class QualityScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.output = self.base / "organized"
        self.log = OperationLog(self.output / ".ai-file-organizer" / "operations.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name="item.txt", data=b"example", parent=None):
        path = (parent or self.source) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def candidate(self, source, destination=None):
        return Candidate(str(source), str(destination or self.output / source.name),
                         "Documents", "test fixture", source.stat().st_size)


def _case(name):
    """Build one isolated scenario from its named behavior."""
    def run(self):
        if name == "classify photo extension":
            assert classify(Path("photo.jpg"))[0] == "Photos"
        elif name == "classify video extension":
            assert classify(Path("movie.mp4"))[0] == "Videos"
        elif name == "classify audio extension":
            assert classify(Path("song.flac"))[0] == "Audio"
        elif name == "copy fallback uses exclusive no-overwrite publish":
            src = self.file(data=b"verified fallback")
            with patch("organizer.os.link", side_effect=OSError("links unavailable")):
                rec = copy_verified(self.candidate(src), self.log)
            assert Path(rec["destination"]).read_bytes() == src.read_bytes()
        elif name == "classify office document":
            assert classify(Path("notes.docx"))[0] == "Documents"
        elif name == "classify archive extension":
            assert classify(Path("backup.zip"))[0] == "Archives"
        elif name == "classify installer extension":
            assert classify(Path("setup.msi"))[0] == "Software Installers"
        elif name == "classify code extension":
            assert classify(Path("script.py"))[0] == "Code"
        elif name == "unknown type requests review":
            assert classify(Path("unknown.xyz"))[0] == "Review Needed"
        elif name == "resume filename rule":
            assert classify(Path("resume.xyz"))[0] == "Resumes"
        elif name == "college filename rule":
            assert classify(Path("lecture-notes.xyz"))[0] == "College"
        elif name == "project filename rule":
            assert classify(Path("portfolio.xyz"))[0] == "Projects"
        elif name == "filename topic rules for resume college and project":
            assert classify(Path("resume.xyz"))[0] == "Resumes"
            assert classify(Path("lecture-notes.xyz"))[0] == "College"
            assert classify(Path("portfolio.xyz"))[0] == "Projects"
        elif name == "AI classifier suggestion used when needed":
            assert classify(Path("unknown.xyz"), lambda _p: "College")[0] == "College"
        elif name == "AI classifier failure falls back to review":
            assert classify(Path("unknown.xyz"), lambda _p: (_ for _ in ()).throw(RuntimeError()))[0] == "Review Needed"
        elif name == "Takeout full year groups all file types":
            p = self.file("note.pdf", parent=self.source / "part" / "Photo 2025")
            row = scan([self.source], self.output)[0]
            assert Path(row.destination).parent.name == "2025"
            assert "Data" in Path(row.destination).parts
        elif name == "Takeout short photo year normalizes":
            assert classify(Path("a.pdf"), context_path=Path("photo 24"))[0] == "Data/2024"
        elif name == "newest year context takes precedence":
            assert classify(Path("a.pdf"), context_path=Path("2024/Photo 2025"))[0] == "Data/2025"
        elif name == "year grouping includes video and PDF":
            year = self.source / "photo 2025"; self.file("a.mp4", parent=year); self.file("b.pdf", parent=year)
            rows = scan([self.source], self.output)
            assert len(rows) == 2 and {Path(x.destination).parent.name for x in rows} == {"2025"}
        elif name == "scan is dry run":
            self.file("a.pdf"); scan([self.source], self.output); assert not self.output.exists()
        elif name == "scan skips Windows folder":
            self.file("safe.txt"); self.file("secret.txt", parent=self.source / "Windows")
            assert [Path(x.source).name for x in scan([self.source], self.output)] == ["safe.txt"]
        elif name == "scan skips nested Program Files":
            self.file("secret.exe", parent=self.source / "nested" / "Program Files")
            assert scan([self.source], self.output) == []
        elif name == "scan rejects linked root":
            with patch("organizer.is_link_or_junction", side_effect=lambda p: Path(p) == self.source):
                assert scan([self.source], self.output) == []
        elif name == "scan does not follow linked child":
            self.file("outside.txt", parent=self.base / "outside")
            with patch("organizer.is_link_or_junction", side_effect=lambda p: Path(p).name == "linked"):
                (self.source / "linked").mkdir()
                assert scan([self.source], self.output) == []
        elif name == "scan skips destination nested in source":
            self.file("source.pdf"); nested_output = self.source / "organized"
            self.file("already.pdf", parent=nested_output)
            rows = scan([self.source], nested_output)
            assert [Path(x.source).name for x in rows] == ["source.pdf"]
        elif name == "missing scan root is harmless":
            assert scan([self.base / "missing"], self.output) == []
        elif name == "permission scan error reports and continues":
            errors = []
            def fake_walk(root, **kwargs):
                kwargs["onerror"](PermissionError("blocked")); return iter(())
            with patch("organizer.os.walk", side_effect=fake_walk):
                assert scan([self.source], self.output, on_error=errors.append) == []
            assert errors
        elif name == "cancelled scan returns safely":
            self.file("a.txt"); event = threading.Event(); event.set()
            assert scan([self.source], self.output, event) == []
        elif name == "duplicate scan names become unique":
            self.file("same.txt", parent=self.source / "a"); self.file("same.txt", parent=self.source / "b")
            rows = scan([self.source], self.output)
            assert len({x.destination.casefold() for x in rows}) == 2
        elif name == "duplicate names require review":
            self.file("same.txt", parent=self.source / "a"); self.file("same.txt", parent=self.source / "b")
            assert any(x.decision == "pending" for x in scan([self.source], self.output))
        elif name == "case insensitive output index":
            self.file("Photo.JPG", parent=self.output)
            assert "photo.jpg" in index_existing_files_by_name(self.output)
        elif name == "output index omits organizer log":
            self.file("x.jpg", parent=self.output / ".ai-file-organizer" / "moved")
            assert index_existing_files_by_name(self.output) == {}
        elif name == "output index finds deep year file":
            path = self.file("same.pdf", parent=self.output / "Data" / "2025")
            assert index_existing_files_by_name(self.output)["same.pdf"] == [path]
        elif name == "size adds nested regular files":
            self.file("a.bin", b"a" * 11); self.file("b.bin", b"b" * 17, self.source / "nested")
            assert folder_size_bytes(self.source) == 28
        elif name == "size ignores protected subtree":
            self.file("safe", b"a"); self.file("protected", b"b" * 20, self.source / "AppData")
            assert folder_size_bytes(self.source) == 1
        elif name == "size handles empty folder":
            assert folder_size_bytes(self.source) == 0
        elif name == "size cancellation returns none":
            event = threading.Event(); event.set(); assert folder_size_bytes(self.source, event) is None
        elif name == "zero byte file remains scannable":
            self.file("empty.txt", b""); row = scan([self.source], self.output)[0]; assert row.size == 0
        elif name == "copy preserves source bytes":
            src = self.file(data=b"original"); rec = copy_verified(self.candidate(src), self.log)
            assert src.read_bytes() == Path(rec["destination"]).read_bytes()
        elif name == "copy never overwrites existing file":
            src = self.file(data=b"new"); target = self.output / src.name; target.parent.mkdir(parents=True); target.write_bytes(b"old")
            rec = copy_verified(self.candidate(src), self.log)
            assert target.read_bytes() == b"old" and Path(rec["destination"]).read_bytes() == b"new"
        elif name == "copy uses numbered conflict name":
            src = self.file("a.txt"); target = self.output / src.name; target.parent.mkdir(parents=True); target.write_bytes(b"1")
            self.file("a.txt", b"2", self.source / "elsewhere")
            rec = copy_verified(self.candidate(src), self.log); assert Path(rec["destination"]).name == "a (2).txt"
        elif name == "copy cancellation creates no output":
            src = self.file(); event = threading.Event(); event.set()
            with self.assertRaises(InterruptedError): copy_verified(self.candidate(src), self.log, event)
            assert not self.output.exists()
        elif name == "failed copy verification cleans temporary":
            src = self.file();
            with patch("organizer.sha256_file", side_effect=OSError("simulated")):
                with self.assertRaises(OSError): copy_verified(self.candidate(src), self.log)
            assert not list(self.output.rglob("*.part"))
        elif name == "batch publishes all verified files":
            a = self.file("a.txt"); b = self.file("b.txt")
            records, errors, cancelled = copy_batch_verified([self.candidate(a), self.candidate(b)], self.log)
            assert len(records) == 2 and not errors and not cancelled
        elif name == "batch failure does not publish missing source":
            missing = self.source / "gone.txt"; c = Candidate(str(missing), str(self.output / "gone.txt"), "x", "x", 3)
            records, errors, cancelled = copy_batch_verified([c], self.log)
            assert not records and errors and not cancelled and not (self.output / "gone.txt").exists()
        elif name == "batch cancellation leaves no partial files":
            src = self.file(); event = threading.Event(); event.set()
            records, errors, cancelled = copy_batch_verified([self.candidate(src)], self.log, event)
            assert cancelled and not records and not errors and not self.output.exists()
        elif name == "batch progress reports verify stage":
            src = self.file(data=b"progress"); events = []
            copy_batch_verified([self.candidate(src)], self.log, on_progress=events.append)
            assert any(e["stage"] == "verify" for e in events)
        elif name == "replace preserves old version for undo":
            src = self.file(data=b"new"); target = self.output / src.name; target.parent.mkdir(parents=True); target.write_bytes(b"old")
            c = self.candidate(src); c.replace_existing = True
            recs, errors, _ = copy_batch_verified([c], self.log)
            assert not errors and target.read_bytes() == b"new" and Path(recs[0]["replaced_backup"]).read_bytes() == b"old"
        elif name == "undo copy removes unchanged destination":
            src = self.file(); rec = copy_verified(self.candidate(src), self.log)
            assert undo_last(self.log) == 1 and not Path(rec["destination"]).exists()
        elif name == "undo keeps modified destination":
            src = self.file(); rec = copy_verified(self.candidate(src), self.log); Path(rec["destination"]).write_bytes(b"newer")
            assert undo_last(self.log) == 0 and Path(rec["destination"]).read_bytes() == b"newer"
        elif name == "move cleanup verifies then restores with undo":
            src = self.file(); recs, errors, _ = copy_batch_verified([self.candidate(src)], self.log)
            removed, skipped = remove_sources_after_verified(recs, self.log)
            assert not errors and removed == 1 and not skipped and not src.exists()
            assert undo_last(self.log) == 1 and src.exists()
        elif name == "move existing output back to source-side holding folder":
            existing = self.file("prior.pdf", b"prior output", self.output / "Data" / "2025")
            holding = self.source / "Existing data in Organized" / "2025" / existing.name
            records, errors, cancelled = copy_batch_verified([self.candidate(existing, holding)], self.log)
            removed, skipped = remove_sources_after_verified(records, self.log)
            assert not errors and not cancelled and removed == 1 and not skipped
            assert not existing.exists() and holding.read_bytes() == b"prior output"
            assert undo_last(self.log) == 1 and existing.read_bytes() == b"prior output" and not holding.exists()
        elif name == "move keeps changed original":
            src = self.file(); recs, _, _ = copy_batch_verified([self.candidate(src)], self.log); src.write_bytes(b"newer")
            removed, skipped = remove_sources_after_verified(recs, self.log)
            assert removed == 0 and skipped and src.read_bytes() == b"newer"
        elif name == "move undo will not overwrite newer original":
            src = self.file(data=b"old"); recs, _, _ = copy_batch_verified([self.candidate(src)], self.log)
            remove_sources_after_verified(recs, self.log); src.write_bytes(b"newer")
            assert undo_last(self.log) == 0 and src.read_bytes() == b"newer"
        elif name == "replacement undo restores prior output":
            src = self.file(data=b"new"); target = self.output / src.name; target.parent.mkdir(parents=True); target.write_bytes(b"old")
            c = self.candidate(src); c.replace_existing = True; copy_batch_verified([c], self.log)
            assert undo_last(self.log) == 1 and target.read_bytes() == b"old"
        elif name == "UI offers only the three requested operations":
            text = (Path(__file__).parents[2] / "app.py").read_text(encoding="utf-8")
            assert text.count('values=("Copy", "Move", "Copy, but delete source")') == 2
        elif name == "UI tab order is output existing review":
            text = (Path(__file__).parents[2] / "app.py").read_text(encoding="utf-8")
            positions = [text.index('self.tabs.add(self.preview_tab'), text.index('self.tabs.add(self.replace_tab'), text.index('self.tabs.add(self.review_tab')]
            assert positions == sorted(positions)
        elif name == "UI includes existing data copy and move actions":
            text = (Path(__file__).parents[2] / "app.py").read_text(encoding="utf-8")
            assert "Copy selected existing files into their source folder" in text
            assert "Move selected existing files to source folder" in text
        elif name == "UI asks separately before existing-output move cleanup":
            text = (Path(__file__).parents[2] / "app.py").read_text(encoding="utf-8")
            assert 'askyesno("Confirm move cleanup"' in text and "copies are verified" in text
        elif name == "launcher hides console and has no paid API dependency":
            root = Path(__file__).parents[2]
            batch = (root / "launch.bat").read_text(encoding="utf-8").casefold()
            hidden = (root / "launch.vbs").read_text(encoding="utf-8").casefold()
            assert "launch.vbs" in batch and "app.py" in hidden
            assert "pyw -3" in hidden and "shell.run command, 0, false" in hidden
            requirements = (root / "requirements.txt").read_text(encoding="utf-8").casefold()
            assert "openai" not in requirements and "api" not in requirements
        elif name == "requirements remain free from paid services":
            text = (Path(__file__).parents[2] / "requirements.txt").read_text(encoding="utf-8").casefold()
            assert "openai" not in text and "api" not in text
        elif name == "existing matches show total count and combined size":
            text = (Path(__file__).parents[2] / "app.py").read_text(encoding="utf-8")
            assert "Existing output matches:" in text and "unique files" in text and "total" in text
        else:
            raise AssertionError(f"No implementation for scenario: {name}")
    run.__name__ = "test_" + name.lower().replace(" ", "_")
    run.__doc__ = name
    return run


SCENARIOS = [
    "classify photo extension", "classify video extension",
    "copy fallback uses exclusive no-overwrite publish", "unknown type requests review",
    "filename topic rules for resume college and project",
    "AI classifier suggestion used when needed", "AI classifier failure falls back to review",
    "Takeout full year groups all file types", "Takeout short photo year normalizes",
    "year grouping includes video and PDF",
    "scan is dry run", "scan skips Windows folder", "scan skips nested Program Files",
    "scan rejects linked root", "scan does not follow linked child", "scan skips destination nested in source",
    "missing scan root is harmless", "permission scan error reports and continues", "cancelled scan returns safely",
    "duplicate scan names become unique", "duplicate names require review", "case insensitive output index",
    "output index finds deep year file", "size adds nested regular files",
    "size ignores protected subtree", "size cancellation returns none",
    "zero byte file remains scannable", "copy preserves source bytes", "copy never overwrites existing file",
    "copy uses numbered conflict name", "copy cancellation creates no output", "failed copy verification cleans temporary",
    "batch publishes all verified files", "batch failure does not publish missing source",
    "batch cancellation leaves no partial files", "batch progress reports verify stage",
    "replace preserves old version for undo", "undo copy removes unchanged destination", "undo keeps modified destination",
    "move cleanup verifies then restores with undo", "move existing output back to source-side holding folder", "move keeps changed original",
    "move undo will not overwrite newer original", "replacement undo restores prior output",
    "UI offers only the three requested operations", "UI tab order is output existing review",
    "UI includes existing data copy and move actions", "UI asks separately before existing-output move cleanup",
    "launcher hides console and has no paid API dependency", "existing matches show total count and combined size",
]

for _scenario in SCENARIOS:
    setattr(QualityScenarios, _case(_scenario).__name__, _case(_scenario))


if __name__ == "__main__":
    unittest.main()

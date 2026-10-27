import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from organizer import Candidate, OperationLog, copy_batch_verified, copy_verified, folder_size_bytes, index_existing_files_by_name, preflight_destination_space, remove_sources_after_verified, scan, undo_last

class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.tmp.name)
        self.src = self.root / "source"; self.src.mkdir()
        self.dest = self.root / "organized"
        self.log = OperationLog(self.dest / ".ai-file-organizer" / "operations.jsonl")

    def tearDown(self): self.tmp.cleanup()

    def candidate(self, src, name="report.pdf"):
        return Candidate(str(src), str(self.dest / "PDFs" / name), "PDFs", "test", src.stat().st_size)

    def test_space_preflight_passes_with_enough_capacity(self):
        from collections import namedtuple
        Usage = namedtuple("Usage", "total used free")
        source = self.src / "ok.pdf"; source.write_bytes(b"x" * 100)
        with patch("organizer.shutil.disk_usage", return_value=Usage(10000, 1000, 9000)):
            ok, message = preflight_destination_space([self.candidate(source)], self.dest, reserve_bytes=100)
        self.assertTrue(ok, message)
        self.assertIn("passed", message)

    def test_space_preflight_stops_when_capacity_is_insufficient(self):
        from collections import namedtuple
        Usage = namedtuple("Usage", "total used free")
        source = self.src / "too-large.pdf"; source.write_bytes(b"x" * 1000)
        with patch("organizer.shutil.disk_usage", return_value=Usage(10000, 9990, 10)):
            ok, message = preflight_destination_space([self.candidate(source)], self.dest, reserve_bytes=100)
        self.assertFalse(ok)
        self.assertIn("stopped before copying", message)
        self.assertFalse(self.dest.exists())

    def test_space_preflight_includes_replace_backup_size(self):
        from collections import namedtuple
        Usage = namedtuple("Usage", "total used free")
        source = self.src / "replace.pdf"; source.write_bytes(b"new payload")
        target = self.dest / "PDFs" / source.name
        target.parent.mkdir(parents=True); target.write_bytes(b"old output" * 20)
        candidate = self.candidate(source, "replace.pdf"); candidate.replace_existing = True
        with patch("organizer.shutil.disk_usage", return_value=Usage(10000, 9850, 150)):
            ok, message = preflight_destination_space([candidate], self.dest, reserve_bytes=0)
        self.assertFalse(ok)
        self.assertIn("Estimated for this operation", message)

    def test_space_preflight_stops_if_destination_drive_cannot_be_checked(self):
        source = self.src / "unknown.pdf"; source.write_bytes(b"data")
        with patch("organizer.shutil.disk_usage", side_effect=OSError("device unavailable")):
            ok, message = preflight_destination_space([self.candidate(source)], self.dest)
        self.assertFalse(ok)
        self.assertIn("Cannot safely check", message)

    def test_existing_output_index_finds_deep_year_path_and_skips_undo_store(self):
        deep = self.dest / "Data" / "Photo" / "2025" / "same.jpg"
        deep.parent.mkdir(parents=True); deep.write_bytes(b"existing")
        hidden = self.dest / ".ai-file-organizer" / "replaced" / "same.jpg"
        hidden.parent.mkdir(parents=True); hidden.write_bytes(b"backup")
        index = index_existing_files_by_name(self.dest)
        self.assertEqual(index["same.jpg"], [deep])

    def test_folder_size_counts_files_and_skips_protected_directories(self):
        (self.src / "a.txt").write_bytes(b"12345")
        nested = self.src / "photos"; nested.mkdir(); (nested / "b.jpg").write_bytes(b"1234567")
        protected = self.src / "Windows"; protected.mkdir(); (protected / "system.bin").write_bytes(b"x" * 50)
        self.assertEqual(folder_size_bytes(self.src), 12)
        cancelled = threading.Event(); cancelled.set()
        self.assertIsNone(folder_size_bytes(self.src, cancelled))

    def test_dry_scan_duplicate_names_and_protected_paths(self):
        a = self.src / "a"; b = self.src / "b"; a.mkdir(); b.mkdir()
        (a / "same.pdf").write_text("a"); (b / "same.pdf").write_text("b")
        (self.src / "Windows").mkdir(); (self.src / "Windows" / "secret.txt").write_text("x")
        rows = scan([self.src], self.dest)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].destination.casefold(), rows[1].destination.casefold())
        self.assertTrue(any("Duplicate" in r.warning for r in rows))
        self.assertTrue(all(r.decision == "pending" for r in rows))
        self.assertFalse(self.dest.exists())

    def test_unknown_types_are_held_for_review(self):
        unknown = self.src / "mystery.customtype"
        unknown.write_bytes(b"sample")
        row = scan([self.src], self.dest)[0]
        self.assertEqual(row.category, "Review Needed")
        self.assertEqual(row.decision, "pending")

    def test_year_labelled_photo_folders_merge_by_year(self):
        sources = [
            self.src / "New folder" / "photo 2025",
            self.src / "New folder 2" / "photo 24",
            self.src / "New folder 2" / "photo 2025",
            self.src / "New folder 3" / "photo 2024",
        ]
        for i, folder in enumerate(sources):
            folder.mkdir(parents=True)
            (folder / f"image{i}.jpg").write_bytes(f"sample image {i}".encode())
        (sources[0] / "takeout-video.mp4").write_bytes(b"sample video")
        (sources[0] / "notes.pdf").write_bytes(b"sample pdf")
        rows = scan([self.src], self.dest)
        self.assertEqual({Path(r.destination).parent.name for r in rows}, {"2024", "2025"})
        self.assertEqual({Path(r.destination).parent.parent.name for r in rows}, {"Data"})
        year_2025 = [r for r in rows if Path(r.destination).parent.name == "2025"]
        self.assertEqual(len(year_2025), 4)
        self.assertEqual({Path(r.destination).suffix for r in year_2025}, {".jpg", ".mp4", ".pdf"})

    def test_verified_copy_and_undo(self):
        src = self.src / "report.pdf"; src.write_bytes(b"preserve me")
        rec = copy_verified(self.candidate(src), self.log)
        self.assertTrue(src.exists()); self.assertEqual(Path(rec["destination"]).read_bytes(), src.read_bytes())
        self.assertEqual(undo_last(self.log), 1)
        self.assertTrue(src.exists()); self.assertFalse(Path(rec["destination"]).exists())

    def test_batch_copy_progress_enters_verification_at_99_and_publishes_verified_files(self):
        first = self.src / "one.pdf"; first.write_bytes(b"first payload")
        second = self.src / "two.pdf"; second.write_bytes(b"second payload")
        events = []
        candidates = [self.candidate(first, "one.pdf"), self.candidate(second, "two.pdf")]
        records, failures, cancelled = copy_batch_verified(candidates, self.log, on_progress=events.append)
        self.assertFalse(failures)
        self.assertFalse(cancelled)
        self.assertEqual(len(records), 2)
        self.assertIn("copy", [event["stage"] for event in events])
        self.assertIn("verify", [event["stage"] for event in events])
        first_verify = next(event for event in events if event["stage"] == "verify")
        self.assertEqual(first_verify["copy_percent"], 99)
        self.assertEqual(events[-1]["stage"], "complete")
        for record in records:
            self.assertEqual(Path(record["source"]).read_bytes(), Path(record["destination"]).read_bytes())

    def test_cancelled_batch_discards_staged_files(self):
        source = self.src / "large.pdf"; source.write_bytes(b"some data")
        event = threading.Event(); event.set()
        records, failures, cancelled = copy_batch_verified([self.candidate(source, "large.pdf")], self.log, event)
        self.assertTrue(cancelled)
        self.assertFalse(failures)
        self.assertFalse(records)
        self.assertFalse((self.dest / "PDFs" / "large.pdf").exists())

    def test_batch_failed_source_does_not_publish_partial_output(self):
        missing = self.src / "missing.pdf"
        candidate = Candidate(str(missing), str(self.dest / "PDFs" / "missing.pdf"), "PDFs", "test", 10)
        records, failures, cancelled = copy_batch_verified([candidate], self.log)
        self.assertTrue(failures)
        self.assertFalse(cancelled)
        self.assertFalse(records)
        self.assertFalse((self.dest / "PDFs" / "missing.pdf").exists())

    def test_move_cleanup_keeps_undo_backup_and_restores_source(self):
        source = self.src / "move.pdf"; source.write_bytes(b"move me safely")
        records, failures, cancelled = copy_batch_verified([self.candidate(source, "move.pdf")], self.log)
        self.assertFalse(failures); self.assertFalse(cancelled)
        removed, skipped = remove_sources_after_verified(records, self.log)
        self.assertEqual((removed, skipped), (1, []))
        self.assertFalse(source.exists())
        self.assertEqual(undo_last(self.log), 1)
        self.assertEqual(source.read_bytes(), b"move me safely")
        self.assertFalse(Path(records[0]["destination"]).exists())

    def test_move_undo_never_overwrites_newer_source_or_removes_its_backup(self):
        source = self.src / "move-newer.pdf"; source.write_bytes(b"original")
        records, failures, cancelled = copy_batch_verified([self.candidate(source, "move-newer.pdf")], self.log)
        self.assertFalse(failures); self.assertFalse(cancelled)
        removed, skipped = remove_sources_after_verified(records, self.log)
        self.assertEqual((removed, skipped), (1, []))
        source.write_bytes(b"newer user file")
        self.assertEqual(undo_last(self.log), 0)
        self.assertEqual(source.read_bytes(), b"newer user file")
        self.assertTrue(Path(records[0]["destination"]).exists())

    def test_delete_source_keeps_recoverable_backup_for_undo(self):
        source = self.src / "delete.pdf"; source.write_bytes(b"recoverable delete")
        dest = self.dest / ".ai-file-organizer" / "deleted" / "PDFs" / source.name
        candidate = Candidate(str(source), str(dest), "PDFs", "test", source.stat().st_size, operation="Delete source")
        records, failures, cancelled = copy_batch_verified([candidate], self.log)
        self.assertFalse(failures); self.assertFalse(cancelled)
        removed, skipped = remove_sources_after_verified(records, self.log)
        self.assertEqual((removed, skipped), (1, []))
        self.assertFalse(source.exists()); self.assertTrue(dest.exists())
        self.assertEqual(undo_last(self.log), 1)
        self.assertEqual(source.read_bytes(), b"recoverable delete")
        self.assertFalse(dest.exists())

    def test_replace_backs_up_existing_output_and_undo_restores_it(self):
        source = self.src / "new.pdf"; source.write_bytes(b"new version")
        target = self.dest / "PDFs" / "new.pdf"
        target.parent.mkdir(parents=True); target.write_bytes(b"old version")
        candidate = self.candidate(source, "new.pdf"); candidate.replace_existing = True
        records, failures, cancelled = copy_batch_verified([candidate], self.log)
        self.assertFalse(failures); self.assertFalse(cancelled)
        self.assertEqual(target.read_bytes(), b"new version")
        backup = Path(records[0]["replaced_backup"])
        self.assertEqual(backup.read_bytes(), b"old version")
        self.assertEqual(undo_last(self.log), 1)
        self.assertEqual(target.read_bytes(), b"old version")
        self.assertFalse(backup.exists())

    def test_existing_name_never_overwritten(self):
        src = self.src / "report.pdf"; src.write_bytes(b"new")
        target = self.dest / "PDFs" / "report.pdf"; target.parent.mkdir(parents=True); target.write_bytes(b"old")
        rec = copy_verified(self.candidate(src), self.log)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(Path(rec["destination"]).read_bytes(), b"new")

    def test_failed_copy_leaves_no_partial_or_record(self):
        src = self.src / "report.pdf"; src.write_bytes(b"payload")
        with patch("organizer.sha256_file", side_effect=OSError("simulated read failure")):
            with self.assertRaises(OSError): copy_verified(self.candidate(src), self.log)
        self.assertEqual(list((self.dest / "PDFs").glob(".organizer-*.part")), [])
        self.assertEqual(self.log.records(), [])

    def test_cancel_discards_temporary_copy(self):
        src = self.src / "report.pdf"; src.write_bytes(b"payload")
        event = threading.Event(); event.set()
        with self.assertRaises(InterruptedError): copy_verified(self.candidate(src), self.log, event)
        self.assertEqual(list((self.dest / "PDFs").glob(".organizer-*.part")), [])
        self.assertEqual(self.log.records(), [])

    def test_undo_keeps_changed_newer_file(self):
        src = self.src / "report.pdf"; src.write_bytes(b"payload")
        rec = copy_verified(self.candidate(src), self.log)
        Path(rec["destination"]).write_bytes(b"newer user version")
        self.assertEqual(undo_last(self.log), 0)
        self.assertTrue(Path(rec["destination"]).exists())

    def test_permission_errors_are_reported_without_crashing(self):
        errors = []
        def fake_walk(root, **kwargs):
            kwargs["onerror"](PermissionError("denied"))
            return iter(())
        with patch("organizer.os.walk", side_effect=fake_walk):
            self.assertEqual(scan([self.src], self.dest, on_error=errors.append), [])
        self.assertTrue(errors)

if __name__ == "__main__": unittest.main()

"""Age-band usability heuristics plus functional workflow checks (temporary data only).

These are scripted persona scenarios, not interviews with real people. They check
clear labels and safe, repeatable workflows across varied assumed experience levels.
"""
import tempfile
import threading
import unittest
from pathlib import Path

from organizer import (Candidate, OperationLog, copy_batch_verified,
                       copy_verified, indices_without_output_name_match,
                       remove_sources_after_verified, undo_last)


PERSONAS = [
    ("13_first_time", 13, "first time using a file organizer"),
    ("16_student", 16, "comfortable with school apps, new to file operations"),
    ("19_college", 19, "managing a multi-part Takeout export"),
    ("24_new_worker", 24, "comfortable with basic folders, cautious about data"),
    ("31_busy_parent", 31, "limited time and needs clear progress"),
    ("42_small_business", 42, "works with mixed documents and backups"),
    ("53_returning_user", 53, "uses Windows but rarely organizes files"),
    ("64_low_vision_careful", 64, "needs explicit action wording and confirmation"),
    ("73_senior_beginner", 73, "prefers simple instructions and reversible actions"),
    ("82_confidence_builder", 82, "wants clear feedback before changing files"),
]

TASKS = [
    "find the scan and output steps",
    "understand dry run and explicit apply",
    "quick select review files with no same-name output file",
    "filter a 5000-file review queue with 4000 existing names",
    "keep existing matches out of the no-match selection",
    "copy without removing source files",
    "cancel a file operation before it starts",
    "move existing output files back and undo safely",
    "preserve a changed file during undo",
    "understand review selection and its action choices",
]


class AgePersonaScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.root = Path(self.tmp.name)
        self.source = self.root / "Takeout source"
        self.source.mkdir()
        self.output = self.root / "Organized output"
        self.log = OperationLog(self.output / ".ai-file-organizer" / "operations.jsonl")
        self.app_text = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name, data=b"sample", parent=None):
        path = (parent or self.source) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def candidate(self, source, target=None):
        return Candidate(str(source), str(target or self.output / source.name),
                         "Documents", "persona fixture", source.stat().st_size)

    def run_persona_task(self, persona, task_index):
        persona_id, age, experience = persona
        task = TASKS[task_index]
        with self.subTest(age=age, persona=persona_id, task=task):
            if task_index == 0:
                self.assertIn("1. Scan locations", self.app_text)
                self.assertIn("2. Output destination", self.app_text)
                self.assertIn("Add folder(s) / drive", self.app_text)
                self.assertIn("Choose destination", self.app_text)
                self.assertTrue((Path(__file__).parents[1] / "assets" / "takeout-organizer-logo.png").is_file())
                self.assertIn("Takeout Organizer", self.app_text)
                self.assertIn('self.root.state("zoomed")', self.app_text)
                self.assertIn("☀ Light mode", self.app_text)
                self.assertIn("🌙 Dark mode", self.app_text)
                self.assertIn("def toggle_theme(self)", self.app_text)
                self.assertIn('self.style.configure("Treeview"', self.app_text)
            elif task_index == 1:
                self.assertIn("DRY RUN", self.app_text)
                self.assertIn("Apply Changes", self.app_text)
                self.assertIn("Nothing will be moved or copied until you choose Apply Changes", self.app_text)
            elif task_index == 2:
                self.assertIn("Select review files with no same-named output file", self.app_text)
                self.assertIn("same-named file in the output destination", self.app_text)
                self.assertIn('messagebox.showinfo("Preview first"', self.app_text)
            elif task_index == 3:
                # Model 5,000 uncertain files, 4,000 already in output, and 1,000 to review.
                candidates = []
                existing = {}
                for number in range(5000):
                    filename = f"{persona_id}_item_{number:04}.unknown"
                    candidates.append(Candidate(str(self.source / filename), "", "Review Needed", "unknown", 0))
                    if number < 4000:
                        existing[filename.casefold()] = [self.output / "Data" / "2025" / filename]
                selected = indices_without_output_name_match(candidates, existing)
                self.assertEqual(len(selected), 1000)
                self.assertEqual(selected[0], 4000)
                self.assertEqual(selected[-1], 4999)
                self.assertTrue(all(candidates[i].source.endswith(f"{i:04}.unknown") for i in selected))
            elif task_index == 4:
                candidates = [
                    Candidate(str(self.source / f"{persona_id}_Photo.JPG"), "", "Review Needed", "unknown", 2),
                    Candidate(str(self.source / f"{persona_id}_unique.xyz"), "", "Review Needed", "unknown", 1),
                ]
                existing = {f"{persona_id.lower()}_photo.jpg": [self.output / "deep" / "photo.jpg"]}
                self.assertEqual(indices_without_output_name_match(candidates, existing), [1])
            elif task_index == 5:
                src = self.file(f"{persona_id}_copy.txt", f"age {age}".encode())
                candidate = self.candidate(src)
                self.assertFalse(self.output.exists(), "dry-run should not create output")
                records, failures, cancelled = copy_batch_verified([candidate], self.log)
                self.assertEqual((len(records), failures, cancelled), (1, [], False))
                self.assertTrue(src.exists(), f"copy should preserve originals for {experience}")
                self.assertEqual(src.read_bytes(), Path(records[0]["destination"]).read_bytes())
            elif task_index == 6:
                src = self.file(f"{persona_id}_cancel.txt")
                cancel = threading.Event(); cancel.set()
                with self.assertRaises(InterruptedError):
                    copy_verified(self.candidate(src), self.log, cancel)
                self.assertFalse(self.output.exists())
            elif task_index == 7:
                old_output = self.file(f"{persona_id}_old.pdf", b"previous output", self.output / "Data" / "2025")
                restored_target = self.source / f"{persona_id}_Existing data" / "2025" / old_output.name
                records, failures, cancelled = copy_batch_verified([self.candidate(old_output, restored_target)], self.log)
                self.assertEqual((len(records), failures, cancelled), (1, [], False))
                removed, skipped = remove_sources_after_verified(records, self.log)
                self.assertEqual((removed, skipped), (1, []))
                self.assertFalse(old_output.exists())
                self.assertEqual(undo_last(self.log), 1)
                self.assertEqual(old_output.read_bytes(), b"previous output")
                self.assertFalse(restored_target.exists())
            elif task_index == 8:
                src = self.file(f"{persona_id}_newer.txt")
                records, errors, _ = copy_batch_verified([self.candidate(src)], self.log)
                self.assertFalse(errors)
                destination = Path(records[0]["destination"])
                destination.write_bytes(b"newer file from user")
                self.assertEqual(undo_last(self.log), 0)
                self.assertEqual(destination.read_bytes(), b"newer file from user")
            elif task_index == 9:
                self.assertIn("Select one or more files", self.app_text)
                self.assertIn("pick an action below", self.app_text)
                self.assertIn("Keep both (unique name)", self.app_text)
                self.assertIn("Copy to Review Needed folder", self.app_text)
                self.assertIn("Exclude from this run", self.app_text)


def _make_method(persona, task_index):
    def test(self):
        self.run_persona_task(persona, task_index)
    persona_id, age, _experience = persona
    test.__name__ = f"test_age_{age}_{persona_id}_{task_index + 1:02d}"
    test.__doc__ = f"Age {age} ({persona_id}): {TASKS[task_index]}"
    return test


for _persona in PERSONAS:
    for _task_index in range(len(TASKS)):
        setattr(AgePersonaScenarios, _make_method(_persona, _task_index).__name__,
                _make_method(_persona, _task_index))


if __name__ == "__main__":
    unittest.main()

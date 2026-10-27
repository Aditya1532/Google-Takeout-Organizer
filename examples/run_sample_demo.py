"""Run a safe demonstration using only the synthetic files in examples/."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from organizer import OperationLog, copy_verified, scan

BASE = Path(__file__).resolve().parent
SAMPLE = BASE / "sample_takeout"
DESTINATION = Path(tempfile.mkdtemp(prefix="demo-output-", dir=BASE))

def main():
    source_parts = sorted(SAMPLE.glob("Takeout Part *"))
    candidates = scan(source_parts, DESTINATION)
    print(f"Preview: {len(candidates)} sample files")
    for item in candidates:
        print(f"{item.source} -> {item.destination} ({item.reason}) {item.warning}")
        # This demo uses only checked-in synthetic files, so explicitly accept
        # the safe unique-name proposals that the GUI would hold for review.
        if item.decision == "pending":
            item.decision = "include"
            item.reviewed = True
            print("  Sample-only choice: accept the proposed conflict-safe destination")
    log = OperationLog(DESTINATION / ".ai-file-organizer" / "operations.jsonl")
    for item in candidates:
        result = copy_verified(item, log)
        print(f"Verified copy: {result['destination']} SHA-256={result['sha256']}")
    print(f"\nSample organized output: {DESTINATION}")
    print(f"The synthetic source files are unchanged. You can remove this demo output when finished: {DESTINATION}")

if __name__ == "__main__": main()

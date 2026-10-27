"""Run the organizer against the checked-in synthetic sample_data only."""
from pathlib import Path
from organizer import OperationLog, copy_verified, scan

BASE = Path(__file__).resolve().parent
SAMPLE = BASE / "sample_data"
DESTINATION = SAMPLE / "organized_demo_output_v2"

def main():
    source_parts = sorted(SAMPLE.glob("New folder*"))
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
    print("The original sample_data/New folder* files are still present.")

if __name__ == "__main__": main()

# Takeout Organizer: 50-case safety and usability test report

**Result:** 50 / 50 focused scenarios passed. The full regression suite passed 72 / 72 tests. Python compilation passed.

All file-operation scenarios used isolated temporary folders created by the tests. No personal folders, drives, or real Takeout data were scanned or changed. UI checks inspect the UI definitions and operation prompts; visual UI automation could not be run because the Windows inspection helper did not initialize in this session.

## Case results

| # | Flag | Scenario |
|---:|:---:|---|
| 1 | PASS | Photo extension classification |
| 2 | PASS | Video extension classification |
| 3 | PASS | Copy fallback uses exclusive, no-overwrite publishing |
| 4 | PASS | Unknown file types are sent to Review Needed |
| 5 | PASS | Resume, college, and project filename rules |
| 6 | PASS | Optional AI suggestion is used for ambiguous files |
| 7 | PASS | AI classifier failure safely falls back to Review Needed |
| 8 | PASS | Takeout year folder groups files under Data/year |
| 9 | PASS | Short photo year is normalized to a four-digit year |
| 10 | PASS | Different file types share the same year folder |
| 11 | PASS | Scan is dry run and does not create output |
| 12 | PASS | Windows directory is skipped |
| 13 | PASS | Nested Program Files directory is skipped |
| 14 | PASS | Linked scan root is rejected |
| 15 | PASS | Linked child directory is not traversed |
| 16 | PASS | Destination inside source is not recursively scanned |
| 17 | PASS | Missing scan location is handled safely |
| 18 | PASS | Permission errors are reported without crashing |
| 19 | PASS | Cancelled scan returns safely |
| 20 | PASS | Duplicate input names receive unique proposals |
| 21 | PASS | Duplicate proposals require review |
| 22 | PASS | Existing-output filename matching is case-insensitive |
| 23 | PASS | Existing-output search finds deep year-folder files |
| 24 | PASS | Folder-size total includes nested regular files |
| 25 | PASS | Folder-size calculation skips protected paths |
| 26 | PASS | Folder-size calculation responds to cancellation |
| 27 | PASS | Zero-byte files remain visible to scan |
| 28 | PASS | Verified copy preserves source bytes |
| 29 | PASS | Copy never overwrites an existing file |
| 30 | PASS | Copy uses a numbered name on conflict |
| 31 | PASS | Pre-cancelled single-file copy creates no output |
| 32 | PASS | Failed verification removes temporary copy files |
| 33 | PASS | Batch copy publishes all verified files |
| 34 | PASS | Missing-source batch fails without publishing output |
| 35 | PASS | Batch cancellation leaves no partial files |
| 36 | PASS | Progress events include the verification stage |
| 37 | PASS | Replacement preserves the old version for Undo |
| 38 | PASS | Undo removes an unchanged organizer copy |
| 39 | PASS | Undo preserves a modified destination |
| 40 | PASS | Move verifies first and Undo restores the source |
| 41 | PASS | Existing-output move returns files to the source-side holding folder and Undo restores them |
| 42 | PASS | Move keeps an original that changed after copying |
| 43 | PASS | Move Undo does not overwrite a newer source file |
| 44 | PASS | Replacement Undo restores the prior output |
| 45 | PASS | UI offers only Copy, Move, and Copy-but-delete-source operations |
| 46 | PASS | UI tab order is Output preview, Existing output, Review needed |
| 47 | PASS | UI includes Existing-output Copy and Move actions |
| 48 | PASS | Existing-output Move requires separate cleanup confirmation |
| 49 | PASS | Requirements do not introduce a paid API dependency |
| 50 | PASS | Existing-output summary includes unique-file count and total size |

## Issues found and fixes applied

| Flag | Issue | Fix |
|:---:|---|---|
| FIXED | Cancelling a single-file copy before it began could leave an empty destination folder. | Check cancellation before creating destination directories. |
| FIXED | A selected scan root that was itself a symbolic link or junction could bypass child-link filtering. | Reject linked roots before walking them. |
| FIXED | A fallback publishing path used replace semantics, which could overwrite a file created concurrently. | Use exclusive file creation and verify the published bytes instead. |
| CLEANED | Two functions had the same `undo_last` name, leaving an older, less capable implementation shadowed by the safer one. | Removed the unused duplicate so only the tested rollback implementation remains. |

## Limits of this pass

- GUI behavior was checked through source-level assertions. The Windows UI inspection runtime failed to initialize, so visual layout was not manually inspected.
- Permission failures were simulated. Operating-system-specific access-control behavior can vary by Windows account and drive.
- Storage-device disconnections and hardware failures cannot be fully reproduced with temporary-folder tests.

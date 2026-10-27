# Takeout Organizer for Windows 11

![Google Takeout Organizer logo](assets/google-takeout-organizer-logo.png)

A beginner-friendly desktop app for organizing Google Takeout files by year while keeping different media and document types together. The app uses Python's built-in Tkinter interface and standard library. It needs no paid API and makes no network requests while organizing files.

## Install on Windows

1. Open the project's **Releases** page on GitHub and choose the latest version.
2. Download `TakeoutOrganizer-Setup-<version>.exe` and run it. The installer works for your Windows account and does not need administrator access. A desktop shortcut is optional.
3. Start **Takeout Organizer** from the Start menu or desktop. The app opens without a terminal window.

> Once this project is published, its Releases page will contain the installer download. Tagged releases (`v1.0.0`, for example) automatically build and attach it.

## Start the app

1. For running from source, install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/) and select **Add Python to PATH** (the Python Launcher is recommended). The Windows installer already bundles the app and does not require Python.
2. Double-click `launch.vbs` to open the app without a terminal window. `launch.bat` is also available as a quick handoff to the hidden launcher. For a terminal-based start, open PowerShell here and run `py -3 app.py`.
3. Use **1. Scan locations** to add or remove the source folders you want to organize. The Explorer picker supports Ctrl-click and Shift-click to add multiple folders at once. Each selected folder shows an estimated total size in GB, calculated in the background from file sizes only. Use **2. Output destination** to choose a separate folder where organized copies will be saved.

The app opens maximized on Windows so the scan, output, review, operation, and progress areas fit into one screen. You can still resize the window.

Use the sun/moon button in the top-right corner to switch between light and dark mode.

## Safe workflow

- **Scan** recursively lists files under selected locations. It does not write to source or destination folders. The scan list starts empty; add only the folders you want to organize.
- Windows, Program Files, Program Files (x86), ProgramData, AppData, WindowsApps, Recovery, System Volume Information, Recycle Bin, and common boot/system folders are skipped. Junctions and symbolic links are not followed. Permission errors are skipped.
- **Analyze files (local rules)** re-applies local filename, path, and extension rules to the scanned files. Obvious file types are categorized by extension; uncertain files go to **Review Needed**. Names suggesting coursework, projects, or resumes are placed into those categories. The app does not include or configure an AI model, so it does not contact a service or require an API key.
- Every file type found inside a clearly year-labelled source folder is grouped by year under one `Data` directory. For example, PDFs, videos, documents, and photos from `photo 2025` all target `Data/2025`, and `photo 24` and `photo 2024` both target `Data/2024`. Duplicate filenames get safe unique names such as `image (2).jpg`.
- To use an optional local classifier, integrate a function that accepts a `pathlib.Path` and returns a category string (or `None`), then pass it as `ai_classifier` to `organizer.classify` or extend the Analyze button to call it. The classifier is intentionally an interface hook rather than a bundled model; no model is downloaded or contacted by default.
- **Preview Changes** shows source path, destination, reason, size, and filename conflicts. The app starts in **DRY RUN** mode.
- The **Review needed** tab lists uncertain file types and destination conflicts. The **Existing output** tab separately shows same-named files anywhere below the chosen output root, including deep year folders and the existing/incoming sizes, plus a total unique-file count and size. Select matches and use **Copy selected existing files into their source folder** to preserve them under `Existing data in <output name> - <parent name>` beside their corresponding source folder, or choose **Move selected existing files to source folder** to copy and verify them there before separately confirming removal from output. Both options are conflict-safe and logged for Undo. If there is more than one match, select the exact existing path to replace. Replace backs up the old file for Undo; you can instead keep both under a unique name or exclude the incoming file. Apply is blocked while any review item is undecided. The **Output preview** tab shows the final destination and decision for every scanned file before copying.
- For a large Review needed list, click **Select review files with no same-named output file** to select only review rows whose filenames do not appear in the current output destination. Click **Preview Changes** after scanning or changing review decisions first so the existing-output list is refreshed. Then use the review actions on the selected rows.
- **Apply Changes** requires that you first view **Preview Changes** after the last scan, analysis, review decision, or destination edit. This keeps the displayed destination plan current before confirmation.
- Immediately before copying, a storage preflight checks the destination drive's free space against the staged copy size, replacement backup sizes, and a safety reserve. If free space is insufficient or the drive cannot be checked, Apply is stopped before copying and a warning explains why. This cannot predict a device disconnect or new writes that consume space after the check.
- During Apply, the progress bar tracks the batch copy phase up to 99%, then pulses at 99% while SHA-256 verification runs. The line beside it shows the current filename and a rough ETA based on measured throughput. Cancellation during copying or verification removes staged temporary files; already published verified files remain logged.
- Scan locations start empty. Select folders to add; the app does not preselect Desktop, Downloads, Documents, Pictures, or Videos.
- The operation menu offers **Copy**, **Move**, and **Copy, but delete source**, for all files or selected preview rows. Copy leaves originals untouched. Move and Copy, but delete source both copy and verify first, then ask separately before removing unchanged originals. The Remove selected button only excludes a row from this run.
- Reusing the same output root reuses its existing `Data/<year>` folders. When a target filename already exists, Review offers keeping both under a unique name or replacing the existing output after saving a backup for Undo.
- **Apply Changes** requires confirmation and copies in 1 MiB chunks. It verifies file size and SHA-256, uses a temporary file before publishing, and never intentionally overwrites an existing destination. Originals remain in place.
- **Cancel** stops between chunks/files and discards the active temporary copy.
- **Undo** requires confirmation and removes only logged destination copies whose current hash still matches the hash at copy time. Modified/newer files are preserved. Original files are never deleted.
- The persistent operation log is stored at `<destination>/.ai-file-organizer/operations.jsonl`.

No real files are scanned or modified during development. Always review the preview and confirm the destination before applying.

## Tests

Run the temporary-directory safety suite with:

```powershell
py -3 -m unittest discover -s tests -v
```

To run the checked-in synthetic example (and create `sample_data/organized_demo_output_v2/Data/2024` and `Data/2025` while keeping the sample originals), run:

```powershell
py -3 run_sample_demo.py
```

The suite covers dry-run behavior, duplicate names, conflicts, hash verification, failed copies, cancellation, permission handling, and rollback safety.

## Build the Windows installer yourself

The app can be bundled into a standalone Windows program with PyInstaller and wrapped in an account-scoped setup wizard with Inno Setup. Both are free tools. In PowerShell from the project folder, run:

```powershell
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name TakeoutOrganizer --add-data "assets/google-takeout-organizer-logo.png;assets" app.py
winget install --id JRSoftware.InnoSetup --exact
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 packaging\TakeoutOrganizer.iss
```

The installer is written to `dist\TakeoutOrganizer-Setup-1.0.0.exe`. GitHub Actions runs this build on pushes and pull requests. To publish a downloadable release, push a version tag such as `v1.0.0`; the workflow attaches the installer to that GitHub Release. The repository owner must first create a GitHub repository and push this project to it.

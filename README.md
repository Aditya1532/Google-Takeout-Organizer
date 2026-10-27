# Google Takeout Organizer

<p align="center"><img src="assets/google-takeout-organizer-logo.png" width="160" alt="Google Takeout Organizer logo"></p>

A Windows desktop app that brings Google Takeout files from several export folders into one year-based library. It keeps photos, videos, PDFs, and other files together by year, with a review step before anything is copied.

> Independent community project. Not affiliated with or endorsed by Google.

## Download and install

**Windows installer:** [Download Google Takeout Organizer](https://github.com/Aditya1532/Google-Takeout-Organizer/releases/latest/download/GoogleTakeoutOrganizer-Setup.exe)

1. Run the installer. It installs for your Windows account and does not need administrator access or a separate Python installation.
2. Optionally select a desktop shortcut.
3. Open **Google Takeout Organizer** from the Start menu.

The installer is not code-signed yet, so Windows may show a “protected your PC” or unknown-publisher warning. Only download it from this project's official GitHub Releases page.

## What it does

- Scans only folders you add. The scan list starts empty; it does not scan your computer automatically.
- Combines files from separate Takeout parts into one Data/year folder when the source names identify a year.
- Uses year-labelled folder names to group every file type under Data/year. For other files, local file-extension and name rules suggest a category. Uncertain files go to **Review Needed**.
- Shows an output preview, existing-name matches, duplicate warnings, and file sizes before applying.
- Copies and verifies files using file size and SHA-256 checks. The default operation is **Copy**, so source files remain in place.
- Supports progress, phase-specific ETA, cancellation, a persistent operation log, and Undo for unchanged output files.
- Works offline and does not send file names or contents to an online AI service. No paid API is required.

## Example

Files spread across several Takeout parts:

~~~text
Takeout export/
├── Part 1/
│   └── photo 2025/
│       ├── trip.jpg
│       └── notes.pdf
├── Part 2/
│   └── photo 2025/
│       └── video.mp4
└── Part 3/
    └── photo 2024/
        └── family.png
~~~

With an output destination you choose, the year-labelled files are grouped together:

~~~text
My Organized Files/
└── Data/
    ├── 2024/
    │   └── family.png
    └── 2025/
        ├── notes.pdf
        ├── trip.jpg
        └── video.mp4
~~~

Duplicate names are kept with conflict-safe names, such as trip (2).jpg. Existing output files are never silently overwritten or discarded.

## Use it

1. **Add scan locations.** Click the input-folder button and choose one or more folders. In the Windows picker, use Ctrl-click or Shift-click to select multiple folders. Their approximate sizes appear next to them.
2. **Choose an output destination.** Pick the root folder where the organized result should live. For example, if the destination is D:\My Organized Files, the app creates Data inside it as needed.
3. Click **Scan**, then **Analyze with AI**. Despite the button label, this version uses local filename, path, and extension rules; it has no bundled AI model and does not call an online AI service. Ambiguous items are sent to Review.
4. Review **Output Preview**, **Review Needed**, and **Existing Output**. Select uncertain items and decide where they should go, keep both versions, replace an existing output with a backup, or exclude an item from this run.
5. Choose **Copy** or another operation for the whole batch or selected files. **Move** and **Copy, but delete source** require a separate confirmation after a verified copy has been made.
6. Click **Apply Changes** only after previewing the plan. Use **Cancel** to stop an active batch, or **Undo** to roll back logged outputs that have not been changed since.

The existing-output search checks the selected destination, including nested folders. It compares file names, not file contents.

## Safety and privacy

- The default operation is **Copy** and the app starts in **DRY RUN**. It does not move or delete files automatically.
- No files are changed until you confirm **Apply Changes**.
- System and protected directories are skipped. Junctions and symbolic links are not followed. Permission errors are reported or skipped.
- Copies are staged, checked, and published without intentionally overwriting a destination. Failed or cancelled temporary copies are removed.
- Optional source cleanup happens only after verification and a separate confirmation. Use Copy if you want to preserve every original.
- Undo preserves any destination file that was edited or replaced after the organizer created it.
- Operation history is kept in the .ai-file-organizer/operations.jsonl folder under your chosen destination.
- Scanning and organizing happen locally. There is no sign-in, telemetry, or online classifier.

## Uninstall

Use **Settings → Apps → Installed apps → Google Takeout Organizer → Uninstall**. Removing the application does not remove organized files or operation logs from your chosen output folder.

## Troubleshooting

- **A file is in Review Needed:** the current local rules could not confidently choose a destination. Select the row and choose a destination or exclude it before applying.
- **The output drive has insufficient space:** choose another destination or free space, then preview and apply again. The app checks available space before starting a batch.
- **An existing file is reported:** review the match and choose keep both, replace with a backup, or exclude the incoming file. Replacing is never automatic.
- **Windows warns about the installer:** releases are not code-signed yet. Download only from the repository's Releases page and review the publisher warning before continuing.

## Run from source

For development or to run without the installer, install Python 3.10 or newer on Windows, then from this folder run:

~~~powershell
py -3 app.py
~~~

Or double-click launch.vbs to start the app without leaving a terminal window. The Windows installer already bundles the runtime, so end users do not need Python.

## Tests

Run the safety suite against temporary test folders:

~~~powershell
py -3 -m unittest discover -s tests -v
~~~

The suite currently has 172 passing tests, including cases for duplicate names, failed copies, cancellation, permission errors, and rollback. The 100 age-persona cases are scripted checks, not a study with human participants. No personal folders are used by the test suite.

A synthetic example is available separately:

~~~powershell
py -3 run_sample_demo.py
~~~

It writes to sample_data/organized_demo_output_v2/ and leaves the sample source files in place.

## Build a Windows installer

The GitHub Actions workflow runs the test suite and builds a standalone app with PyInstaller, then creates a per-user setup program with NSIS. Both build tools are free. The workflow stores a downloadable build artifact for branch builds. A version tag such as v1.0.2 also creates a GitHub Release with a stable GoogleTakeoutOrganizer-Setup.exe asset, so the README download link always points to the latest installer.

To build locally, install PyInstaller and NSIS, then run in PowerShell:

~~~powershell
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name GoogleTakeoutOrganizer --add-data "assets/takeout-organizer-logo.png;assets" app.py
& "C:\Program Files (x86)\NSIS\makensis.exe" /DAPP_VERSION=1.0.0 packaging\TakeoutOrganizer.nsi
~~~

The installer is written to dist\GoogleTakeoutOrganizer-Setup-1.0.0.exe.

## License

This project is licensed under the MIT License. See LICENSE for the full terms.

## Project layout

~~~text
.github/workflows/   Windows test, build, and release workflow
assets/              App logo
packaging/           NSIS installer definition
sample_data/         Synthetic Takeout example files
tests/               Automated safety tests
app.py               Windows desktop interface
organizer.py         Scanning, classification, copy, verify, and undo logic
~~~

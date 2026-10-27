# Google Takeout Organizer

<p align="center"><img src="assets/google-takeout-organizer-logo.png" width="192" alt="Google Takeout Organizer logo"></p>

<p align="center">
  <a href="https://github.com/Aditya1532/Google-Takeout-Organizer/actions/workflows/windows-release.yml"><img src="https://github.com/Aditya1532/Google-Takeout-Organizer/actions/workflows/windows-release.yml/badge.svg?branch=main" alt="Windows build"></a>
  <a href="https://github.com/Aditya1532/Google-Takeout-Organizer/releases/latest"><img src="https://img.shields.io/github/v/release/Aditya1532/Google-Takeout-Organizer" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Aditya1532/Google-Takeout-Organizer" alt="MIT license"></a>
</p>

**A free, open-source Windows app for organizing Google Takeout exports into one year-based library.** Preview every proposed change, keep your originals safe, and verify copied files before deciding what to do next.

> This is an independent community project. It is not affiliated with or endorsed by Google.

## Download

[**Download the latest Windows installer**](https://github.com/Aditya1532/Google-Takeout-Organizer/releases/latest/download/GoogleTakeoutOrganizer-Setup.exe)

Run the installer and start **Google Takeout Organizer** from the Windows Start menu. Installation is per-user and does not require administrator access or a separate Python installation. The installer is not code-signed yet, so Windows may show an unknown-publisher warning; download it only from this repository's Releases page.

## Features

- Select one or more Takeout folders, then choose a separate output folder.
- Merge files from different Takeout parts into a shared `Data/<year>` structure.
- Use paired Google Photos JSON sidecars (`photoTakenTime`, then `creationTime`) to find a photo's year when the folder path does not specify one. The photo and sidecar are kept together.
- Preview proposed destinations, review uncertain files, and inspect existing-name matches before applying.
- Copy files first, verify their sizes and SHA-256 hashes, and keep the originals by default.
- Handle name conflicts with unique filenames or a deliberate replacement choice with backup.
- Track progress and phase-specific estimates, cancel work, and undo unchanged outputs.
- Work offline. Classification uses local path, filename, extension, and sidecar rules; no online AI or paid API is used.

## Quick start

1. Install and open the app.
2. Add the Takeout folders you want to organize. The scan list starts empty.
3. Choose the output destination, such as `D:\My Organized Files`.
4. Click **Scan**, then **Analyze files (local rules)**.
5. Review **Output Preview**, **Review Needed**, and **Existing Output**. Adjust or exclude files as needed.
6. Choose an operation and inspect the preview. Click **Apply Changes** only when the proposed results look right.

The default operation is **Copy**. The app does not move or delete originals automatically. Move and source-cleanup actions require a separate confirmation after verification.

## Example result

Files from separate Takeout parts, including mixed file types, can be combined under the same year:

```text
Takeout Part 1/photo 2025/trip.jpg       ─┐
Takeout Part 2/photo 2025/notes.pdf       ─┼─> My Organized Files/Data/2025/
Takeout Part 3/photo 2024/family.png      ───> My Organized Files/Data/2024/
```

If a Google Photos folder has no year in its name, the organizer checks a matching JSON sidecar when available. It considers `photoTakenTime` first and `creationTime` as a fallback. Sidecars without a matching photo, malformed JSON, and unrelated JSON files use the normal classification rules.

## Safety

- Nothing is copied, moved, replaced, or removed until you approve **Apply Changes**.
- Copies are staged and verified; an existing file is not silently overwritten.
- Replacements keep a backup. Undo does not overwrite files that have changed since the operation.
- Protected system folders are excluded, and directory junctions or symbolic links are not followed.
- The app works locally and does not upload file names or contents.
- Operation history is stored under `.ai-file-organizer` inside the chosen output folder.

## Run from source

Requires Python 3.10 or newer on Windows. From the repository folder:

```powershell
py -3 app.py
```

Or double-click `launch.bat` to start without leaving a terminal window.

## Try the synthetic example

The example uses only the small synthetic files checked into `examples/sample_takeout`. It writes to a new ignored `examples/demo-output-*` folder and leaves the sample inputs unchanged:

```powershell
py -3 examples\run_sample_demo.py
```

## Development and tests

The application uses Python's standard library. The automated safety suite runs against temporary directories and is kept under `.github/qa` so the project root stays focused:

```powershell
py -3 -m unittest discover -s .github/qa -p "test_*.py" -v
```

The suite covers classification, Google Photos sidecars, duplicate names, copy failures, cancellation, permissions, and rollback. GitHub Actions runs the suite before building the Windows installer.

## Build the Windows installer

Install [PyInstaller](https://pyinstaller.org/) and [NSIS](https://nsis.sourceforge.io/), then run these commands in PowerShell:

```powershell
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name GoogleTakeoutOrganizer --icon assets/google-takeout-organizer.ico --add-data "assets/google-takeout-organizer-logo.png;assets" --add-data "assets/google-takeout-organizer.ico;assets" app.py
& "C:\Program Files (x86)\NSIS\makensis.exe" /DAPP_VERSION=1.0.0 packaging\TakeoutOrganizer.nsi
```

The installer is created at `dist\GoogleTakeoutOrganizer-Setup-1.0.0.exe`. GitHub Actions builds and smoke-tests the installer on Windows for pushes, pull requests, and version tags.

## License

Google Takeout Organizer is released under the [MIT License](LICENSE).

## Repository layout

```text
.github/       CI workflow and automated QA suite
assets/        Application logo and Windows icon
examples/      Synthetic Takeout input and safe demo script
packaging/     NSIS installer definition
app.py         Windows desktop interface
organizer.py   Scanning, classification, verified copy, and undo
```

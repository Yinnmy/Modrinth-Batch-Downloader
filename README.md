# Modrinth Batch Downloader

Modrinth Batch Downloader (MBD) is a Windows desktop application for downloading Minecraft mods and their dependencies from Modrinth automatically. Instead of opening and downloading projects one by one, you can paste multiple Modrinth links, choose the target Minecraft version and mod loader, and let the app handle the rest. AI generated-text and assisted in the creation of this program.

MBD helps you:
- batch download mods and dependencies
- analyze installed mods and detect missing dependencies
- find compatible versions for another Minecraft version
- check for updates to installed mods
- review logs, reports, and download history

Code version: 1.0.0  
Platform: Windows desktop application  
Languages: English and Portuguese

## About the project

The Modrinth Batch Downloader is a desktop tool designed to simplify Minecraft mod management from Modrinth. It brings together batch downloading, dependency analysis, compatibility checks, and update detection in a single workflow.

In addition to downloading multiple projects at once, MBD can:
- scan existing .jar files on your computer
`please not that this only scans the minecraft .mods folder, nothing else.`
- detect missing dependencies and conflicts and download them automatically.
- look for updates to installed mods
- find compatible versions for another Minecraft version and loader
`if it doesn't find any, it won't install that mod or dependency.`

This makes it easier to keep mod folders organized, updated, and compatible with a specific Minecraft setup.

## Quick start

### Run from source
1. Install Python 3.10 or newer on Windows.
2. Make sure Tkinter is available.
3. Download or clone the repository.
4. Open the project folder and run `run.bat`.

The script installs dependencies from `requirements.txt` and launches the application.

### Use the Windows executable
Just... execute it.

> Windows and antivirus software may show warnings for executables downloaded from the internet. These warnings alone do not prove that a file is malicious or safe. Only download software from trusted sources.

## Features

### Batch downloads

- Paste multiple Modrinth links, one per line.
- Preview recognized projects before starting, including:
  - project names
  - icons
  - project types
  - compatibility information when available
- Select the Minecraft version and mod loader for the projects you want to download.
- Supported loaders include Fabric, Forge, NeoForge, and Quilt.
- Automatically resolve and download required dependencies when enabled.
- Download multiple files in parallel by setting 3, 4, or 5 simultaneous downloads.
- Track each download’s progress, downloaded size, speed in MB/s, and overall task progress.
- Stop a running task at any time. Files already in progress may finish before the task fully stops.

MBD recognizes different types of Modrinth projects and organizes them into the appropriate destination folders:

| Project type | Destination folder |
| --- | --- |
| Mods | `Main destination folder` |
| Shaders | `shaderpacks/` |
| Resource packs | `resourcepacks/` |
| Datapacks | `datapacks/` |
| Plugins | `plugins/` |
| Modpacks | `modpacks/` |

### More reliable downloads

- Integrity checks: compares downloaded file SHA-1 and SHA-512 hashes with values published by Modrinth, when available.
- Protection against mismatched files: if a hash does not match, the file is discarded and reported as an integrity issue.
- Automatic retries: transient network errors, timeouts, HTTP 5xx responses, and HTTP 429 rate limits may trigger retries with increasing wait times and respect for the `Retry-After` header when provided.
- Existing-file detection: compares SHA-1 hashes to avoid downloading the same file again, even if the file has been renamed.
- Replacement of different files: when a different version of the corresponding file is found, the new version is downloaded. When applicable, the previous version is preserved with the `.old` extension.
- Stable-version preference: can prioritize stable releases. If none are available, it may fall back to beta and then alpha versions while recording a notice.

If Modrinth does not provide a hash for a file, the program records that the integrity check could not be performed. This does not mean the file was confirmed by hash validation.

### Switching to another Minecraft version

The Convert section allows you to select .jar files or an existing mods folder and search for versions of the same projects that are compatible with another Minecraft version and selected target loader.

- Select individual .jar files or choose a mods folder to analyze.
- Set the source version, target version, and desired loader.
- MBD attempts to identify each mod from its metadata and find a matching project on Modrinth.
- The original files are not modified; compatible copies are downloaded to the configured destination folder.
- Recognized required dependencies may also be resolved during the process.

Important: this does not convert a mod’s code from one loader to another. The program searches for a published version of the project that is compatible with the selected Minecraft and loader combination.

### Mod and dependency analysis

In the Active Mods section, you can scan the configured mods folder or select another folder to analyze its .jar files.

- Reads metadata from recognized mods, including IDs, versions, loaders, and dependencies.
- Shows which dependencies each mod requires and which libraries are installed.
- Identifies required dependencies that appear to be missing and indicates which mods need them.
- Accounts for modules embedded in other JAR files (such as Fabric API jar-in-jar modules) and some ID aliases published in metadata.
- Identifies potential conflicts, including:
  - two files with the same mod ID
  - mods from different loaders mixed in the same folder

Analysis depends on the metadata the program can read from the JAR files. As a result, it may not recognize mods with missing, unusual, or unsupported metadata formats.

### Checking for and installing updates

- Use “Check for Updates” to compare analyzed mods with versions available on Modrinth.
- The program calculates SHA-1 hashes for local files and checks for versions matching the selected Minecraft version and loader.
- Results identify mods for which a newer compatible version was found.
- “Update All” downloads available versions and rescans the folder when finished.

Detection depends on whether the local project can be identified and whether a compatible version has been published on Modrinth.

### Reports, logs, and history

When a task finishes, MBD displays a report with totals for:
- files downloaded
- skipped files
- incompatible files
- failed files

The report may also list:
- files discarded because of invalid hashes
- detected conflicts
- compatibility issues

Additional features include:
- Copy the list of incompatible projects in Title — link format, so it can be pasted back into the links section.
- Export the log to a text file to help diagnose errors.
- Open the destination folder directly from the application.
- Review run history and reopen previous reports.
- Enable or disable Windows notifications when a task completes.

### Interface and settings

- Interface available in English and Portuguese.
- Built-in themes with customizable background and accent colors.
- Interface scaling options: 90%, 100%, 115%, 130%, and 150%.
- Configure the number of simultaneous downloads and automatic retries after failures.
- Option to include Minecraft snapshots in the version list.
- Configure the download folder and the mod analysis folder separately.
- Choose a custom image for the window icon. To embed that icon into the executable, the application must be rebuilt.
- Minecraft version list is retrieved through the API, with an option to refresh it manually.
- Optional checks for new MBD version.

## Downloading and running

### Using the Windows executable

Download the published executable, such as `ModrinthBatchDownloader.exe`, and open it on Windows.

> Windows and antivirus software may display warnings for executables downloaded from the internet. These warnings alone do not prove a file is malicious or safe. Only download from sources you trust. You can use Virus Total Scan if you're that scared.

### Virus Total Scans
Screenshots: 
<img width="1919" height="941" alt="image" src="https://github.com/user-attachments/assets/9256cf4d-bc7d-43a5-98f8-5341131a4540" />

<img width="1919" height="937" alt="image" src="https://github.com/user-attachments/assets/7b5a63d9-7f0f-4a72-baf6-6a2f2726b4d0" />

## About the VirusTotal scans shown in the release screenshots

You may see VirusTotal results like "8/63" for the EXE and "5/57" for the ZIP in the screenshots included with this release. That means 8 out of 63 antivirus engines flagged the EXE and 5 out of 57 flagged the ZIP. These counts are an aggregate of different vendors' engines and labels — they are not a definitive proof of malware.

Why this can happen even when the source code is clean
- Packaging and heuristics: The Windows executable is produced with PyInstaller / a one-file build, and the PyInstaller bundle (and similar packers) often looks unusual to heuristic engines. In our build spec we enable UPX/compression (upx=True), which also commonly triggers heuristic alerts.
- Unsigned binaries: Releases that are not code-signed are more likely to be treated cautiously by some engines.
- Generic detection names: Many detections you see in the scan (names like "TR/W64.Malware", "W32.Malware", "Trojan", or "suspicious PE") are generic heuristic labels rather than precise forensic classifications.
- Archive scanning differences: A ZIP may show fewer flags because some engines only scan inside an archive in a second stage or treat packed archives differently.
- False positives are common for new, packaged, or uncommon binaries — especially ones produced by bundlers and one-file runners.

How we check and what we do when a detection appears
- We validate the release file hash (SHA256) and publish it so anyone can verify the downloaded file.
- We compare the published binary to a local build from the repository to make sure they match.
- We test the executable in an isolated environment (VM) and run a behaviour check.
- For likely false positives, we report the file to the antivirus vendors and document the outcome on the release page.

If you are concerned, you can verify the file yourself (short steps follow).


### Running from source

- Install Python 3.10 or newer on Windows, with Tkinter available.
- Download or clone the repository and extract it to a regular folder.
- Run `run.bat`.

The script installs the dependencies listed in the project and launches the application.

Third-party dependencies are listed in `requirements.txt`. Pillow is used for visual features and image-to-icon conversion; without it, some of those features may be limited.

### Building the executable

Builds must be performed on Windows:

- Install Python 3.10 or newer.
- Open the project folder.
- Run `build_exe.bat`.
- After a successful build, the executable will be created at `dist/ModrinthBatchDownloader.exe`.

The script installs the required dependencies and uses PyInstaller with the `--onefile` option, including resources from `assets/`. If you customized the icon in the application, the script may use a custom icon file from `assets/` during the build.

## Technologies and project structure

- Python + Tkinter: desktop application and interface
- Modrinth API: retrieves project, version, file, dependency, and metadata information
- PyInstaller: builds the Windows executable
- Pillow: image features and icon customization

Project structure:

```text
MBD/
├── app.py              # Application interface and main workflow
├── core.py             # API, downloads, hashes, dependencies, and updates
├── i18n.py             # English and Portuguese text
├── ui_kit.py           # Reusable visual components
├── assets/             # Icons and mascot
├── tests/              # Automated core tests
├── tools/              # Helper tools
├── requirements.txt    # Python dependencies
├── run.bat             # Run from source
├── build_exe.bat       # Build the executable
└── README.md           # Project documentation

```
## License  

This project is currently distributed as open source for personal and community use.

# Contributing
Contributions, bug reports, issues, and feature suggestions are welcome. If you find a bug or want to request a feature, please open an issue in the repository.

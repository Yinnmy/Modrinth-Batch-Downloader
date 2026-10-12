# Modrinth-Batch-Downloader
Modrinth Batch Downloaded is a thirdy-app program that download mods and their dependencies automatically all at once for any version, built for modrinth entirely for free.


Modrinth Batch Downloader (MBD)

Download, organize, analyze, and update Minecraft projects from Modrinth in one place.

    Code version: 5.0.0 · Windows desktop application · English and Portuguese interface

About the project

The Modrinth Batch Downloader (MBD) is a desktop application that makes it easier to manage Minecraft projects from Modrinth. Instead of opening and downloading projects one by one, you can paste multiple links at once, choose a Minecraft version and mod loader, and let the program find compatible versions, download files, and identify dependencies.

In addition to batch downloads, MBD can analyze .jar files already on your computer, check for missing dependencies and conflicts, look for updates to installed mods, and find project versions compatible with a different Minecraft version.
Features
Batch downloads

    Paste multiple Modrinth links, one per line.
    Preview recognized projects before starting, including their names, icons, project types, and compatibility information when available.
    Choose the Minecraft version and mod loader for the projects you want to download. The available loaders in the interface are Fabric, Forge, NeoForge, and Quilt.
    Automatically resolve and download required dependencies when this option is enabled.
    Download multiple files in parallel by setting 3, 4, or 5 simultaneous downloads.
    Track each file's progress, downloaded size, speed in MB/s, and overall progress.
    Stop a running task. Files already being processed may finish before the task fully stops.

MBD recognizes different types of Modrinth projects and organizes them into appropriate folders inside the selected destination:
Type	Destination folder
Mods	Main destination folder
Shaders	shaderpacks/
Resource packs	resourcepacks/
Datapacks	datapacks/
Plugins	plugins/
Modpacks	modpacks/
More reliable downloads

    Integrity checks: compares the downloaded file's SHA-1 and SHA-512 hashes with the values published by Modrinth, when available.
    Protection against mismatched files: if a hash does not match, the file is discarded and reported as an integrity issue.
    Automatic retries: transient network errors, timeouts, HTTP 5xx responses, and HTTP 429 rate limits may trigger retries, with increasing wait times and   respect for the Retry-After header when provided.
    Existing-file detection: compares SHA-1 hashes to avoid downloading an identical file again, even if the file has been renamed.
    Replacing different files: when a different version of the corresponding file is found, the new version is downloaded. When applicable, the previous version is preserved with the .old extension to reduce the risk of leaving two active copies of the same mod.
    Stable-version preference: can prioritize releases. If no release is available, it may fall back to beta and then alpha versions, recording a notice.

    If Modrinth does not provide a hash for a file, the program records that the check could not be performed. This does not mean the file's integrity was confirmed by a hash.

Switching to another Minecraft version

The Convert section lets you select .jar files or an existing mods folder and search for versions of the same projects that are compatible with another Minecraft version and the selected target loader.

    Select individual .jar files or choose a mods folder to analyze.
    Set the source version, target version, and desired loader.
    MBD attempts to identify each mod from its metadata and find a matching project on Modrinth.
    The selected original files are not modified: compatible copies are downloaded to the configured destination folder.
    Recognized required dependencies may also be resolved during the process.

Important: this does not convert a mod's code from one loader to another. The program searches for a published version of the project that is compatible with the selected Minecraft and loader combination. Mods with unreadable metadata or no identifiable match may not be converted.
Mod and dependency analysis

In the Active Mods section, you can scan the configured mods folder or select another folder to analyze its .jar files.

    Reads metadata from recognized mods, including IDs, versions, loaders, and dependencies.
    Shows which dependencies each mod requires and which libraries are installed.
    Identifies required dependencies that appear to be missing and indicates which mods need them.
    Accounts for modules embedded in other JARs (such as Fabric API jar-in-jar modules) and certain ID aliases published in metadata.
    Identifies potential conflicts, including two files with the same mod ID and mods from different loaders mixed in the same folder.

Analysis depends on the metadata the program can read from the JARs. As a result, it may not recognize mods with missing, unusual, or unsupported metadata formats.
Checking for and installing updates

    Use Check for Updates to compare the analyzed mods with versions available on Modrinth.
    The program calculates SHA-1 hashes for local files and checks for versions matching the selected Minecraft version and loader.
    Results identify mods for which a newer compatible version was found.
    Update All downloads the available versions and rescans the folder when finished.

Detection depends on whether the local project can be identified and whether a compatible version has been published on Modrinth.
Reports, logs, and history

When a task finishes, MBD displays a report with totals for files downloaded, skipped, incompatible, and failed. The report may also list files discarded because of invalid hashes and any detected conflicts.

    Copy the list of incompatible projects in Title — link format, which can be pasted back into the links section.
    Export the log to a text file to help diagnose errors.
    Open the destination folder directly from the application.
    Review run history and reopen previous reports.
    Enable or disable Windows notifications when a task completes.

Interface and settings

    Interface available in English and Portuguese.
    Built-in themes and options to customize the background and accent colors.
    Interface scaling options: 90%, 100%, 115%, 130%, and 150%.
    Configure the number of simultaneous downloads and automatic retries after failures.
    Option to include Minecraft snapshots in the version list.
    Configure the download folder and the folder used for mod analysis separately.
    Choose a custom image for the window icon. To embed that icon into the executable, the application must be rebuilt.
    Minecraft version list retrieved through the API, with an option to refresh it manually.
    Optional checks for new MBD versions, configured through a GitHub releases URL or a URL that provides JSON containing the version and download link. This check remains inactive until a valid URL is configured.

Downloading and running
Using the Windows executable

If the project is distributed through this repository's Releases section, download the published executable, for example ModrinthBatchDownloader.exe, and open it on Windows. The project's packaged build uses PyInstaller's single-file mode and does not require users to install Python separately.

Windows or antivirus software may show warnings for executables downloaded from the internet. Such warnings alone do not prove that a file is malicious or safe; only download it from a source you trust.
Running from source

    Install Python 3.10 or newer on Windows, with Tkinter available.
    Download or clone the repository and extract it to a regular folder.
    Run run.bat. The script installs the dependencies listed in the project and launches the application.

Third-party dependencies are listed in requirements.txt. Pillow is used for visual features and image-to-icon conversion; without it, some of those features may be limited.
Building the executable

Builds must be performed on Windows:

    Install Python 3.10 or newer.
    Open the project folder.
    Run build_exe.bat.
    After a successful build, the executable will be created at dist/ModrinthBatchDownloader.exe.

The script installs the required dependencies and uses PyInstaller with the --onefile option, including resources from assets/. If you customized the icon in the application, the script may use assets/custom_icon.ico during the next build.
Technologies and project structure

    Python + Tkinter: desktop application and interface.
    Modrinth API: retrieves project, version, file, dependency, and metadata information.
    PyInstaller: builds the Windows executable.
    Pillow: image features and icon customization.

Main project structure:
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
└── build_exe.bat       # Build the executable
Tests

The project includes automated core tests that use a mocked Modrinth service. With the dependencies installed, run the following command from the project folder:
python -m unittest discover -s tests -v
Known limitations

    Conversion searches for compatible builds of the same project; it does not transform a mod's code from one loader to another.
    Dependency analysis and resolution rely on metadata in the JAR files and information published by Modrinth.
    Projects with no compatible version, available file, or identifiable match may be skipped or marked as incompatible.
    Hash-based integrity checks are only possible when Modrinth publishes an expected hash.
    The appearance of the native title bar depends on Windows support.
    Notifications use the Windows toast mechanism through PowerShell and may appear associated with Windows PowerShell.
    Changing the window icon does not automatically change the icon embedded in the .exe; the executable must be rebuilt.
    Checks for new versions of MBD require a valid URL to be configured in the settings.

Contributions and issues

When reporting a problem, include the MBD version, Minecraft version, selected loader, and steps to reproduce the issue. When possible, attach a log exported from the application and remove any personal information before posting it.

Suggestions, fixes, and improvements are welcome through issues and pull requests in this repository.

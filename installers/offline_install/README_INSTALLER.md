# Ragcmdr — Build the Windows Installer

This guide explains how to build `ragcmdr-setup.exe` from the source files.

---

## What the installer does

1. Extracts an embedded Python 3.12 runtime (no Python required on the target machine)
2. Creates a virtual environment in `{install_dir}\.venv\`
3. Installs all dependencies from `requirements.txt` silently
4. Adds `ragcmdr` to the Windows PATH so the user can type it from any terminal
5. Creates an uninstaller via Windows Add/Remove Programs

**RAM footprint is preserved** — the virtual environment loads only what is needed,
exactly like the development setup. No dependencies are bundled into a single blob.

---

## Prerequisites (on your build machine)

### 1. Inno Setup 6
Download and install from:
> https://jrsoftware.org/isinfo.php

### 2. Python 3.12 embeddable package
Download the **64-bit embeddable zip** from:
> https://www.python.org/downloads/windows/

Look for: `python-3.12.x-embed-amd64.zip`

Extract the contents into a folder named **`python\`** placed next to `install.iss`:

```
ragstudio\
├── install.iss
├── python\               ← extracted here
│   ├── python.exe
│   ├── python312.dll
│   ├── python312._pth
│   └── ...
```

### 3. get-pip.py
Download from:
> https://bootstrap.pypa.io/get-pip.py

Place it next to `install.iss`:

### 4. Pre-download packages (offline mode only)

Run the provided script on your build machine (requires internet + Python 3.12):
```cmd
download_packages.bat
```
This populates a `packages\` folder (~2 GB). Skip for an online installer.

```
ragstudio\
├── install.iss
├── get-pip.py            ← here
```

---

## Folder structure before compiling

```
ragstudio\
├── install.iss
├── post_install.bat
├── ragcmdr.bat
├── ragstudio.py
├── requirements.txt
├── config.json
├── get-pip.py
├── python\
│   ├── python.exe
│   └── ...
├── commands\
│   ├── __init__.py
│   ├── collection.py
│   └── document.py
├── core\
│   ├── __init__.py
│   ├── config_manager.py
│   ├── embedder.py
│   ├── llm_client.py
│   ├── parser.py
│   ├── state_manager.py
│   └── vectorstore.py
└── chat\
    ├── __init__.py
    └── session.py
```

---

## Build steps

### Option A — Offline installer (recommended)

All packages are embedded. No internet needed on the target machine.
**Final size: ~2-3 GB** (PyTorch is unavoidable).

1. Run `download_packages.bat` on your build machine (needs internet + Python 3.12)
   - This creates a `packages\` folder with all .whl files
2. Open **Inno Setup Compiler**
3. File → Open → select `install.iss`
4. Build → **Compile** (or press `F9`)
5. Output: `ragstudio\Output\ragcmdr-setup.exe` (~2-3 GB)

### Option B — Online installer (lightweight)

Packages are downloaded during setup (~2-5 min, internet required on target machine).
**Final size: ~50 MB**.

1. Do **not** run `download_packages.bat` (no `packages\` folder needed)
2. Open **Inno Setup Compiler**
3. File → Open → select `install.iss`
4. Build → **Compile** (or press `F9`)
5. Output: `ragstudio\Output\ragcmdr-setup.exe` (~50 MB)

> `install.iss` detects automatically whether `packages\` exists
> and switches between offline and online mode accordingly.

---

## What the user does

1. Double-click `ragcmdr-setup.exe`
2. Follow the wizard (choose install folder, click Next)
3. Wait for the dependency installation step (~2-5 minutes depending on internet speed)
4. Open a **new** terminal (cmd or PowerShell) — PATH is updated automatically
5. Start using Ragcmdr:

```cmd
ragcmdr create collection my-docs
ragcmdr open collection my-docs
ragcmdr add "D:\my documents\"
ragcmdr list docs
ragcmdr chat
```

---

## Troubleshooting

**Dependencies failed to install**
Check the log file created during installation:
```
C:\Program Files\Ragcmdr\install.log
```

**`ragcmdr` not recognized after install**
The PATH update requires opening a new terminal. If it still fails, add the
install directory manually to your user PATH:
- Windows Settings → Search "environment variables" → User variables → Path → Edit → New
- Add: `C:\Program Files\Ragcmdr`

**HuggingFace models not downloading**
Ragcmdr sets `HF_HUB_DISABLE_SYMLINKS_WARNING=1` automatically.
If model downloads fail, enable Developer Mode in Windows Settings → System → For developers.
Models are cached after the first download and never re-downloaded.

---

## Uninstall

Windows Settings → Apps → Ragcmdr → Uninstall

The uninstaller removes:
- The virtual environment (`.venv\`)
- The embedded Python runtime
- All source files
- The PATH entry

**Collections and output files are preserved** — they must be deleted manually
if desired (location shown in `ragcmdr status`).

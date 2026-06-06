# Voice Commands — Source Files

This repo contains all the source code for the Voice Commands app.

---

## Repos

| Repo | Purpose |
|------|---------|
| [Voice-commands](https://github.com/xXBunchXx/Voice-commands) | Public release repo — contains the built `.exe` and `.zip` for distribution |
| [voice-commands-source-files](https://github.com/xXBunchXx/voice-commands-source-files) | This repo — all source `.py` files, full commit history, used for development |

---

## Saving your work

Double-click **`save.bat`** in the project folder.

It will ask for a commit message — press **Enter** to auto-use a timestamp — then push to both repos automatically.

---

## Rolling back to a previous version

Use this when a bug is introduced and you want to go back to a working state.

### Step 1 — Find the commit you want

Go to the commit history:
**https://github.com/xXBunchXx/voice-commands-source-files/commits/main**

Browse until you find a commit before the bug appeared. Click on it and copy the **commit hash** — it's the 7-character code shown on the right (e.g. `3007dfa`).

---

### Option A — Restore a single file (safest)

Use this if only one file is broken and you want to roll back just that file.

Open a terminal in the project folder and run:

```
git checkout <hash> -- filename.py
```

**Example** — restore `settings_window.py` to how it was at commit `3007dfa`:
```
git checkout 3007dfa -- settings_window.py
```

Then rebuild with `build.bat` as normal.

---

### Option B — Roll back the entire project

Use this if multiple files are broken and you want to go back to a known-good state completely.

> ⚠️ This will discard ALL changes made after that commit. Make sure you've noted what you want to keep first.

```
git reset --hard <hash>
git push origin main --force
git push backup main --force
```

**Example:**
```
git reset --hard 3007dfa
git push origin main --force
git push backup main --force
```

---

### Option C — Copy code from a specific commit without changing anything

If you just want to *look at* or copy the old version of a file without actually rolling back:

1. Go to **https://github.com/xXBunchXx/voice-commands-source-files/commits/main**
2. Click the commit you want
3. Click the file you want to view
4. Copy the code from the browser

---

## Rebuilding the exe

After making or restoring any source file changes, run **`build.bat`** to compile a new `VoiceCommands.exe`.

The build script will ask:
- **1** = Small update (patch — e.g. bug fix)
- **2** = Medium update (minor — e.g. new feature)
- **3** = Large update (major — e.g. big overhaul)

The version number in `version.txt` is bumped automatically and the new exe is zipped ready for distribution.

---

## File overview

| File | What it does |
|------|-------------|
| `main.py` | Main window, system tray, update checker, engine thread |
| `voice_controls.py` | Voice recognition engine, all command logic |
| `user_config.py` | Reads/writes per-user config from `%APPDATA%\VoiceCommands\config.json` |
| `manage_apps.py` | Manage Apps window — add, edit, rename, delete, scan installed apps |
| `settings_window.py` | Settings window — engine, volume, commands, context commands |
| `build.bat` | Builds the exe with PyInstaller and zips it for release |
| `save.bat` | Commits and pushes source changes to both GitHub repos |
| `version.txt` | Current version number (auto-incremented by build.bat) |

---

## User config location

Each user's personal settings (apps, trigger words, volume steps etc.) are stored at:

```
%APPDATA%\VoiceCommands\config.json
```

This file is **never overwritten by updates** — each person keeps their own entries.

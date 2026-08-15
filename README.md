# Google Maps List Converter

Import a Google My Maps **KMZ** export into Google Maps **Saved Lists**. Each My Maps layer becomes a separate list, placemark descriptions become place notes, and coordinate-only pins receive the original KMZ name as a private Google Maps label.

> Google has no official bulk-import API for Saved Lists. This tool automates the current Google Maps web interface, so selectors may need maintenance when Google changes Maps.

## What is imported

- One Google Maps Saved List per My Maps layer (including nested folder paths)
- Point names and coordinates
- Placemark descriptions as Google Maps place notes
- The KMZ document/general description as every generated list's description
- Original point names as private labels when Google resolves only a coordinate pin
- A CSV audit log with separate place, label, and note results

Duplicate coordinates are merged only within the same layer. The same point in two layers remains in both generated lists. Lines and polygons are skipped.

Google Maps notes are normally collapsed behind **Note / הערה**. The text is saved even when it is not expanded in the list view.

## Show all generated lists on one map

In Google Maps, open **Saved**, open each generated list, and enable **Show on your map**. Multiple Saved Lists can be visible together. They remain separate lists, because Saved Lists do not support My Maps-style sections.

## Privacy

KMZ descriptions may contain addresses, access codes, links, or other personal information. Review them before importing or sharing a list.

The repository ignores KMZ/KML files, generated CSV/log files, Chrome automation profiles, `.env` files, caches, and virtual environments. Never force-add these files. The audit log records statuses but never note bodies.

## Requirements

- Python 3.10+
- Google Chrome
- A Google account signed in to Google Maps
- Google Maps web interface set to **English or Hebrew only**

```powershell
python -m pip install -r requirements.txt
```

## Supported Google Maps languages

The browser automation currently supports only these Google Maps interface languages:

- English
- Hebrew (עברית)

The language of the KMZ content and point names may be different; this limitation applies only to Google Maps buttons, dialogs, and accessibility labels used by the automation.

Before importing, open Google Maps in the dedicated Chrome profile and set the interface language to English or Hebrew. In Maps, open the main menu, choose **Language / שפה**, select **English** or **עברית**, and wait for Maps to reload. Do not change the language while an import is running.

Other interface languages are unsupported and may cause list creation, saving, labels, or notes to fail. To support another language, add its localized patterns/selectors to the configuration section at the top of `google_maps_list_converter.py` and verify the complete import flow before use.
## Import instructions

### 1. Export My Maps

Open the map menu in Google My Maps, choose **Export to KML/KMZ**, export the whole map, and keep the `.kmz` file.

### 2. Preview safely

The preview prints generated list names and counts, but not private descriptions:

```powershell
python google_maps_list_converter.py "C:\path\to\my-map.kmz" --dry-run
```

The KMZ document name is the default list prefix. Override it if desired:

```powershell
python google_maps_list_converter.py "C:\path\to\my-map.kmz" `
  --list-prefix "Cyprus 2026" --dry-run
```

Google Maps list names are limited to 40 characters, so long prefix/layer combinations are shortened automatically.

### 3. Start Chrome for automation

Close Chrome completely, then start a dedicated profile.

Windows PowerShell:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$PWD\chrome-automation-profile"
```

macOS/Linux equivalents:

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir="$PWD/chrome-automation-profile"

# Linux
google-chrome --remote-debugging-port=9222 \
  --user-data-dir="$PWD/chrome-automation-profile"
```

Sign in to Google Maps in that Chrome window and leave Maps open. The importer creates the layer lists automatically.

### 4. Import

```powershell
python google_maps_list_converter.py "C:\path\to\my-map.kmz" `
  --list-prefix "Cyprus 2026"
```

Do not interact with the automated Maps tab until it finishes.

Options:

```text
--list-prefix TEXT  Prefix for every generated layer list
--dry-run           Parse and summarize without opening Chrome
--no-notes          Save places without placemark notes
--delay 3           Wait three seconds between points
--log FILE.csv      Select the audit-log path
--cdp-url URL       Select a different Chrome debugging endpoint
--log-level LEVEL   DEBUG, INFO (default), WARNING, or ERROR
--debug-log FILE    Detailed UTF-8 diagnostic log (default: converter.log)
--screenshots DIR   Save private local verification PNGs
```

## Screenshots and content verification

Screenshots are opt-in because they can expose private point names, notes, addresses, and account information. To capture local evidence for every processed point:

```powershell
python google_maps_list_converter.py "C:\path\to\my-map.kmz" `
  --list-prefix "Cyprus 2026" `
  --screenshots "verification-screenshots"
```

The importer verifies retained list-description, private-label, and note values through the rendered Maps controls. The CSV adds `VerificationStatus`, `VerificationMessage`, `ScreenshotStatus`, and `ScreenshotPath`. A screenshot is taken after each point's label/note handling so failures have visual evidence too.

`verification-screenshots/` and `screenshots/` are ignored by Git. If you select a different directory, keep it outside Git or add it to `.gitignore`. Review every image before sharing it.
## Logging and UI maintenance

Python's standard `logging` module is used; no extra logging package is required. The default `INFO` level records normal progress to the console and `converter.log`. Use `--log-level DEBUG` when diagnosing Google Maps UI changes:

```powershell
python google_maps_list_converter.py "C:\path\to\my-map.kmz" `
  --list-prefix "Cyprus 2026" `
  --log-level DEBUG `
  --debug-log "converter-debug.log"
```

Use `WARNING` or `ERROR` for quieter output. Diagnostic `.log` files are ignored by Git. The CSV audit remains the per-point result report and contains separate `Status`, `LabelStatus`, and `NoteStatus` columns.

All change-prone Google Maps selectors, localized English/Hebrew text patterns, timeouts, URLs, and limits are defined together at the top of `google_maps_list_converter.py`. Update that configuration section first when Google changes its interface.
## Notes, labels, and reruns

The importer locates the specific saved-list row by point name before adding its note. This avoids the earlier bug where comments after the first few points could be attached to the wrong row.

When name search fails, the importer saves the coordinate pin and adds the original KMZ point name using Google Maps' **private label** feature. This editor requires real keyboard events (typing plus Enter); programmatic form filling is ignored by Maps. The importer verifies the resulting label before reporting `LabelStatus=OK`.

Before creating a layer list, the importer expands the Saved-list collection and searches every loaded list for an exact name. It reuses any existing match and logs a warning if duplicates already exist; it never creates another list when at least one exact match is found. Existing duplicate lists are not deleted automatically because they may contain user data.

For safety, a rerun does not add a note to an item already present in the target list: Google Maps does not expose a stable entry identifier, and guessing could overwrite another point's note. Use fresh generated lists for a clean full import, or inspect `NoteStatus` in the audit log for manual retries.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use synthetic KML only and never open Chrome or contain personal map data.

## Troubleshooting

- **Cannot connect to port 9222:** close all Chrome processes and relaunch with both remote-debugging options.
- **Not signed in:** sign in inside the dedicated Chrome profile, not your normal Chrome window.
- **Coordinate shown as title:** inspect `LabelStatus`; the private label UI may have changed or the point may already have a different label.
- **Comment missing:** expand **Note / הערה**, then check `NoteStatus` and `NoteMessage` in the audit CSV.
- **List creation failed:** check the generated name in dry-run and confirm Maps is open in the signed-in automation profile.

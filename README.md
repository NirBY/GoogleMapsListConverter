# Google Maps List Converter

Import a Google My Maps **KMZ** export into one Google Maps **Saved List**.
The converter preserves My Maps folder names as searchable section labels and
copies placemark descriptions into the corresponding place notes.

> Google does not provide an official bulk-import API for Saved Lists. This
> project automates the current Google Maps web interface and may need selector
> updates when Google changes that interface.

## What is preserved

- Point name and coordinates
- My Maps folder hierarchy
- Placemark description, converted from HTML to readable text
- One Google Maps Saved List selected by name
- A CSV audit log with separate place and note statuses

Google Maps Saved Lists do **not** currently provide nested folders/sections on
the desktop web interface. To keep everything in one list, each note starts
with `[Section: folder / nested folder]`. This makes the original sections
visible and searchable without creating multiple lists. Saved Lists may also
reorder places independently of the KMZ order.

Only KML `Point` placemarks are imported. Lines and polygons are skipped.

## Privacy

KMZ descriptions can contain addresses, access codes, Wi-Fi credentials, and
other personal information. Review the source before importing or sharing the
Google Maps list.

This repository ignores:

- `*.kmz` and `*.kml`
- extracted/generated place CSV files and import logs
- Chrome automation profiles (cookies, sessions, browsing data)
- `.env` files, caches, and virtual environments

Never force-add those files to Git. The audit log records note status but not
the note body.

## Requirements

- Windows, macOS, or Linux
- Python 3.10+
- Google Chrome
- A Google account signed in to Google Maps

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

The importer connects to Chrome itself, so a separately downloaded Playwright
browser is not required.

## Import instructions

### 1. Export from My Maps

In Google My Maps, open the map menu, choose **Export to KML/KMZ**, export the
entire map, and keep the result as a `.kmz` file.

### 2. Preview the KMZ safely

This verifies the file and displays only folder and point counts. Descriptions
are deliberately not printed because they may contain private information.

```powershell
python google_maps_list_converter.py "C:\path\to\my-map.kmz" `
  --list-name "My trip" `
  --dry-run
```

### 3. Start a dedicated Chrome profile

Close Chrome completely first. Current Chrome versions require a non-default
profile for remote debugging.

Windows PowerShell:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$PWD\chrome-automation-profile"
```

macOS:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$PWD/chrome-automation-profile"
```

Linux:

```bash
google-chrome --remote-debugging-port=9222 \
  --user-data-dir="$PWD/chrome-automation-profile"
```

In that Chrome window:

1. Sign in to Google Maps.
2. Create the destination Saved List manually.
3. Keep Google Maps open.

### 4. Run the import

```powershell
$env:PYTHONIOENCODING="utf-8"
python google_maps_list_converter.py "C:\path\to\my-map.kmz" `
  --list-name "My trip"
```

Useful options:

```text
--dry-run       Parse and summarize only; do not connect to Chrome
--no-notes      Save places without folder/description notes
--delay 3       Wait three seconds between places
--log FILE.csv  Choose the audit-log path
--cdp-url URL   Use a different Chrome debugging endpoint
```

Do not interact with the automated Maps tab while the import runs. Chrome is
left open when the process finishes.

## Notes and sections

For a placemark in `Restaurants / Vegan` with the description `Book ahead`,
the importer attempts to add this Google Maps note:

```text
[Section: Restaurants / Vegan]

Book ahead
```

Google localizes and changes the note editor more often than the Save picker.
The CSV audit log therefore reports `Status` and `NoteStatus` separately. A
place can be saved successfully even if its note needs manual attention.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

Tests use synthetic KML data only and never open Chrome or contain personal map
content.

## Troubleshooting

- **Cannot connect to port 9222:** close all Chrome processes and relaunch with
  both `--remote-debugging-port` and `--user-data-dir`.
- **Target list not found:** create it in the same dedicated Chrome profile and
  match spelling/capitalization exactly.
- **No savable place:** Google could not resolve the name or coordinate to a
  place/pin supported by Saved Lists; check the audit log.
- **Note failed:** the place remains saved. Add the note manually or update the
  localized note selectors in `MapsImporter.add_note`.

#!/usr/bin/env python3
"""Import Google My Maps KMZ point layers into Google Maps Saved Lists."""

from __future__ import annotations
import argparse
import csv
import html
import logging
import re
import sys
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from xml.etree import ElementTree as ET

# Stable configuration and change-prone Google Maps UI selectors live here.
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
MAPS_URL = "https://www.google.com/maps"
NOTE_LIMIT = 4000
LIST_NAME_LIMIT = 40
UI_TIMEOUT_MS = 5000
SAVE_PICKER_RETRIES = 3
LIST_SYNC_SECONDS = 5
SAVE_SELECTOR = (
    'button[aria-label^="Save"],button[aria-label="Saved"],'
    'button[aria-label^="שמירה"],button[aria-label="נשמר"]'
)
SAVE_ROW_SELECTOR = "xpath=ancestor-or-self::*[@role='menuitemradio' or @role='menuitemcheckbox' or @role='checkbox'][1]"
SAVED_NAV_SELECTOR = 'button[jsaction="navigationrail.saved"]'
VIEW_MORE_LISTS_SELECTOR = 'button[jsaction*="navigationrail.viewMore"]:visible'
FIRST_RESULT_SELECTOR = 'a[href*="/maps/place/"]'
NEW_LIST_PATTERN = re.compile(r"^(New list|רשימה חדשה)$")
NEW_LIST_SELECTOR = 'button[aria-label="New list"],button[aria-label="רשימה חדשה"]'
NOTE_ROW_XPATH = "xpath=ancestor::*[.//button[@aria-label='Add a note' or @aria-label='הוספה של הערה']][1]"
LIST_TITLE_SELECTOR = 'input[maxlength="40"]:visible'
LIST_SUBMIT_SELECTOR = 'button[jsaction$=".done"]:visible'
LIST_CREATE_PATTERN = re.compile(r"^(Create|Done|יצירה|סיום)$")
LIST_DESCRIPTION_SELECTOR = (
    'textarea[aria-label="List description"]:visible,'
    'textarea[aria-label="תיאור הרשימה"]:visible'
)
LABEL_TRIGGER_PATTERN = re.compile(r"^(Add a label|New label|הוספת תווית|תווית חדשה)$")
LABEL_INPUT_SELECTOR = (
    'input[jsaction="aliasEditor.select"]:visible,input.ZBTq6e:visible'
)
NOTE_BUTTON_SELECTOR = (
    'button[aria-label="Add a note"],button[aria-label="הוספה של הערה"]'
)
NOTE_EDITOR_SELECTOR = (
    'textarea[aria-label="Note"]:visible,textarea[aria-label="הערה"]:visible'
)
LOGGER = logging.getLogger("google_maps_list_converter")


@dataclass(frozen=True)
class Place:
    name: str
    latitude: float
    longitude: float
    section: str = ""
    description: str = ""

    @property
    def note(self) -> str:
        return build_note(self.description)


def normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def description_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in text.splitlines()]
    return "\n".join(x for x in lines if x)


def build_note(description: str, limit: int = NOTE_LIMIT) -> str:
    note = description_to_text(description)
    return note if len(note) <= limit else note[: limit - 1].rstrip() + "…"


def _coordinates(mark: ET.Element) -> tuple[float, float] | None:
    raw = mark.findtext(".//kml:Point/kml:coordinates", namespaces=KML_NS)
    if not raw:
        return None
    parts = raw.strip().split()[0].split(",")
    if len(parts) < 2:
        return None
    try:
        lon, lat = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _walk(node: ET.Element, folders: tuple[str, ...] = ()) -> Iterable[Place]:
    for child in node:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "Folder":
            name = normalize(child.findtext("kml:name", namespaces=KML_NS))
            yield from _walk(child, folders + ((name,) if name else ()))
        elif tag == "Placemark":
            coords = _coordinates(child)
            if not coords:
                continue
            name = normalize(child.findtext("kml:name", namespaces=KML_NS))
            desc = child.findtext("kml:description", default="", namespaces=KML_NS)
            yield Place(
                name or f"Dropped pin {coords[0]:.6f},{coords[1]:.6f}",
                coords[0],
                coords[1],
                " / ".join(folders),
                description_to_text(desc),
            )
        elif tag in {"Document", "kml"}:
            yield from _walk(child, folders)


def parse_kml(data: bytes | str) -> list[Place]:
    return list(_walk(ET.fromstring(data)))


def parse_kmz(path: Path) -> list[Place]:
    with zipfile.ZipFile(path) as z:
        names = [x for x in z.namelist() if x.lower().endswith(".kml")]
        if not names:
            raise ValueError("KMZ does not contain a KML document")
        name = next((x for x in names if Path(x).name.lower() == "doc.kml"), names[0])
        return parse_kml(z.read(name))


def group_places_by_layer(places: list[Place]) -> OrderedDict[str, list[Place]]:
    """Keep layers separate and de-duplicate coordinates only inside a layer."""
    grouped = OrderedDict()
    for place in places:
        layer = place.section or "Unsectioned"
        points = grouped.setdefault(layer, OrderedDict())
        key = (round(place.latitude, 7), round(place.longitude, 7))
        if key not in points:
            points[key] = place
        elif place.description and place.description not in points[key].description:
            prior = points[key]
            points[key] = Place(
                prior.name,
                prior.latitude,
                prior.longitude,
                prior.section,
                "\n\n".join(filter(None, (prior.description, place.description))),
            )
    return OrderedDict(
        (layer, list(points.values())) for layer, points in grouped.items()
    )


def make_list_name(prefix: str, layer: str, limit: int = LIST_NAME_LIMIT) -> str:
    prefix, layer = normalize(prefix), normalize(layer)
    candidate = f"{prefix} — {layer}" if prefix else layer
    if len(candidate) <= limit:
        return candidate
    suffix = f" — {layer}"
    if len(suffix) < limit:
        return prefix[: limit - len(suffix)].rstrip() + suffix
    return layer[:limit].rstrip()


def parse_kmz_description(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = [x for x in z.namelist() if x.lower().endswith(".kml")]
        if not names:
            return ""
        member = next((x for x in names if Path(x).name.lower() == "doc.kml"), names[0])
        root = ET.fromstring(z.read(member))
        document = root.find("kml:Document", KML_NS)
        return (
            description_to_text(
                document.findtext("kml:description", default="", namespaces=KML_NS)
            )
            if document is not None
            else ""
        )


def parse_kmz_name(path: Path) -> str:
    """Return the KML document name, falling back to the KMZ filename."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
        if not names:
            return path.stem
        member = next(
            (name for name in names if Path(name).name.lower() == "doc.kml"), names[0]
        )
        root = ET.fromstring(archive.read(member))
        document = root.find("kml:Document", KML_NS)
        if document is None:
            return path.stem
        return (
            normalize(document.findtext("kml:name", default="", namespaces=KML_NS))
            or path.stem
        )


class MapsImporter:
    """Drive the current Google Maps web UI through a signed-in Chrome tab."""

    SAVE = SAVE_SELECTOR
    ROW = SAVE_ROW_SELECTOR

    def __init__(self, page, list_name: str, delay: float = 2.0, notes: bool = True):
        self.page = page
        self.list_name = list_name
        self.delay = delay
        self.notes = notes
        self.coordinate_fallback = False

    def _button(self):
        return self.page.locator(self.SAVE).last

    def _has_button(self) -> bool:
        try:
            return self._button().is_visible(timeout=1000)
        except Exception:
            return False

    def _first_result(self) -> None:
        result = self.page.locator(FIRST_RESULT_SELECTOR).first
        try:
            if result.is_visible(timeout=1500):
                result.click()
                time.sleep(1.5)
        except Exception:
            pass

    def open_saved(self) -> None:
        self.page.locator(SAVED_NAV_SELECTOR).click()
        time.sleep(1)

    def _saved_list_matches(self):
        """Match list cards by contained text; Maps wraps names with icons/counts."""
        return self.page.locator("button").filter(has_text=self.list_name)

    def ensure_list(self, description: str = "") -> tuple[bool, str]:
        """Reuse an exact-name list; create only after exhaustive discovery."""
        try:
            self.open_saved()
            view_more = self.page.locator(VIEW_MORE_LISTS_SELECTOR)
            if view_more.count() and view_more.last.is_visible(timeout=1200):
                view_more.last.click()
                time.sleep(1.5)

            matches = self._saved_list_matches()
            match_count = matches.count()
            LOGGER.debug(
                "List discovery name=%r matches=%d", self.list_name, match_count
            )
            if match_count > 1:
                LOGGER.warning(
                    "Duplicate lists already exist for %r; reusing the last match",
                    self.list_name,
                )
            if match_count == 0:
                LOGGER.info("Creating missing list %r", self.list_name)
                self.page.locator(NEW_LIST_SELECTOR).last.click()
                title = self.page.locator(LIST_TITLE_SELECTOR).last
                title.wait_for(state="visible", timeout=UI_TIMEOUT_MS)
                title.fill(self.list_name)
                submit = self.page.locator(LIST_SUBMIT_SELECTOR).last
                if not submit.count():
                    submit = self.page.get_by_text(LIST_CREATE_PATTERN).last
                submit.click()
                time.sleep(2)
            else:
                LOGGER.info("Reusing existing list %r", self.list_name)
            return self.set_list_description(description)
        except Exception as error:
            return (
                False,
                "List creation/open failed: " + str(error).replace(chr(10), " ")[:180],
            )

    def search(self, place: Place) -> None:
        """Prefer a named result; fall back to an exact coordinate pin."""
        self.coordinate_fallback = False
        query = f"{place.name} {place.latitude},{place.longitude}"
        self.page.goto(
            "https://www.google.com/maps/search/" + quote(query),
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(2)
        self._first_result()
        if not self._has_button():
            self.coordinate_fallback = True
            coordinates = f"{place.latitude},{place.longitude}"
            self.page.goto(
                "https://www.google.com/maps/search/?api=1&query=" + quote(coordinates),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(2)
            self._first_result()

    def save(self) -> tuple[bool, str, bool]:
        """Save to the list, retrying while a newly created list propagates."""
        for attempt in range(1, SAVE_PICKER_RETRIES + 1):
            try:
                self._button().wait_for(state="visible", timeout=UI_TIMEOUT_MS)
                self._button().click()
            except Exception:
                return False, "No savable Google place or coordinate pin found", False
            time.sleep(1)
            label = self.page.get_by_text(self.list_name, exact=True).last
            try:
                label.wait_for(state="visible", timeout=UI_TIMEOUT_MS)
                break
            except Exception:
                self.page.keyboard.press("Escape")
                LOGGER.warning(
                    "Save picker missing list=%r attempt=%d/%d",
                    self.list_name,
                    attempt,
                    SAVE_PICKER_RETRIES,
                )
                if attempt == SAVE_PICKER_RETRIES:
                    return False, f'Target list "{self.list_name}" not found', False
                time.sleep(2)
        row = label.locator(self.ROW)
        target = row if row.count() else label
        already = target.get_attribute("aria-checked") == "true"
        if not already:
            target.click(timeout=10000)
            time.sleep(0.5)
        self.page.keyboard.press("Escape")
        return True, "Already saved" if already else "Saved", not already

    def set_private_label(self, place: Place) -> tuple[bool, str]:
        """Give coordinate-only pins their original KMZ name and verify it."""
        if not self.coordinate_fallback:
            return True, "Not needed"
        name = place.name
        if self.page.get_by_text(name, exact=True).count():
            LOGGER.debug("Private label already present: %r", name)
            return True, "Already labeled"
        try:
            trigger = self.page.get_by_text(LABEL_TRIGGER_PATTERN).last
            trigger.wait_for(state="visible", timeout=UI_TIMEOUT_MS)
            trigger.click()
            editor = self.page.locator(LABEL_INPUT_SELECTOR).last
            editor.wait_for(state="visible", timeout=UI_TIMEOUT_MS)
            # Maps ignores fill() here; real keyboard events are required.
            editor.click()
            editor.type(name, delay=20)
            editor.press("Enter")
            time.sleep(1.5)

            # Maps renders labels asynchronously; reopen before verification.
            coordinates = f"{place.latitude},{place.longitude}"
            self.page.goto(
                MAPS_URL + "/search/?api=1&query=" + quote(coordinates),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(2)
            persisted = name in self.page.locator("body").inner_text()
            LOGGER.debug(
                "Private label reopen verification name=%r persisted=%s",
                name,
                persisted,
            )
            return persisted, (
                "Added" if persisted else "Google Maps did not retain the private label"
            )
        except Exception as error:
            return (
                False,
                "Private label failed: " + str(error).replace(chr(10), " ")[:180],
            )

    def _note_trigger(self, place_name: str):
        """Find the note button in the row for this place, not merely row one."""
        buttons = 'button[aria-label="Add a note"],button[aria-label="הוספה של הערה"]'
        named = self.page.get_by_text(place_name, exact=True).first
        if named.count():
            row = named.locator(
                "xpath=ancestor::*[.//button[@aria-label='Add a note' or @aria-label='הוספה של הערה']][1]"
            )
            if row.count():
                return row.locator(buttons).first
        return self.page.locator(buttons).first

    def add_note(
        self, note: str, place_name: str, newly_saved: bool
    ) -> tuple[bool, str]:
        if not self.notes or not note:
            return True, "Skipped"
        if not newly_saved:
            return (
                False,
                "Skipped for already-saved item to avoid editing the wrong entry",
            )
        try:
            self.open_saved()
            self._saved_list_matches().last.click()
            time.sleep(2)
            trigger = self._note_trigger(place_name)
            trigger.wait_for(state="visible", timeout=5000)
            trigger.click()
            editor = self.page.locator(
                'textarea[aria-label="Note"]:visible,textarea[aria-label="הערה"]:visible'
            ).last
            editor.fill(note)
            editor.press("Tab")
            time.sleep(1.5)
            retained = editor.input_value() == note
            self.page.keyboard.press("Escape")
            return retained, (
                "Added" if retained else "Google Maps did not retain the note value"
            )
        except Exception as error:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return (
                False,
                "List note editor failed: " + str(error).replace(chr(10), " ")[:180],
            )

    def set_list_description(self, description: str) -> tuple[bool, str]:
        if not description:
            return True, "Skipped"
        try:
            self.open_saved()
            self._saved_list_matches().last.click()
            time.sleep(1)
            editor = self.page.locator(
                'textarea[aria-label="List description"]:visible,textarea[aria-label="תיאור הרשימה"]:visible'
            ).first
            editor.fill(description)
            editor.press("Tab")
            time.sleep(1.5)
            retained = editor.input_value() == description
            return retained, (
                "Added"
                if retained
                else "Google Maps did not retain the list description"
            )
        except Exception as error:
            return (
                False,
                "List description failed: " + str(error).replace(chr(10), " ")[:180],
            )

    def import_place(self, place: Place) -> dict[str, str]:
        self.search(place)
        ok, message, newly_saved = self.save()
        label_ok, label_message = (
            self.set_private_label(place) if ok else (False, "Not attempted")
        )
        note_ok, note_message = (
            self.add_note(place.note, place.name, newly_saved)
            if ok
            else (False, "Not attempted")
        )
        time.sleep(self.delay)
        return {
            "Status": "OK" if ok else "FAILED",
            "Message": message,
            "LabelStatus": "OK" if label_ok else "FAILED",
            "LabelMessage": label_message,
            "NoteStatus": "OK" if note_ok else "FAILED",
            "NoteMessage": note_message,
        }


def preview(groups: OrderedDict[str, list[Place]], prefix: str) -> None:
    """Show list names and counts without exposing private descriptions."""
    print(f"Parsed {sum(map(len,groups.values()))} placemarks into {len(groups)} lists")
    for layer, places in groups.items():
        print(f"  {make_list_name(prefix,layer)}: {len(places)}")
    print("Descriptions are not printed because they may contain private data.")


def maps_page(context):
    return next(
        (page for page in context.pages if "google.com/maps" in page.url),
        context.pages[0] if context.pages else context.new_page(),
    )


def ensure_login(page) -> None:
    page.goto(
        "https://www.google.com/maps", wait_until="domcontentloaded", timeout=30000
    )
    time.sleep(2)
    for label in ("Sign in", "כניסה"):
        try:
            if page.get_by_text(label, exact=True).is_visible(timeout=800):
                raise RuntimeError("Chrome is not signed in to Google Maps")
        except RuntimeError:
            raise
        except Exception:
            pass


FIELDS = [
    "Name",
    "Layer",
    "ListName",
    "Latitude",
    "Longitude",
    "Status",
    "Message",
    "LabelStatus",
    "LabelMessage",
    "NoteStatus",
    "NoteMessage",
]


def run(args) -> int:
    prefix = args.list_prefix or parse_kmz_name(args.kmz)
    groups = group_places_by_layer(parse_kmz(args.kmz))
    preview(groups, prefix)
    if args.dry_run:
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("Run: pip install -r requirements.txt") from error
    ok = failed = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:
            raise RuntimeError("Chrome has no browser context")
        page = maps_page(browser.contexts[0])
        ensure_login(page)
        description = parse_kmz_description(args.kmz)
        with args.log.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            total = sum(map(len, groups.values()))
            index = 0
            for layer, places in groups.items():
                list_name = make_list_name(prefix, layer)
                importer = MapsImporter(page, list_name, args.delay, not args.no_notes)
                list_ok, list_message = importer.ensure_list(description)
                print(
                    f"List {list_name}: {'OK' if list_ok else 'FAILED'} - {list_message}"
                )
                for place in places:
                    index += 1
                    print(f"[{index}/{total}] {place.name} -> {list_name}")
                    base = {
                        "Name": place.name,
                        "Layer": layer,
                        "ListName": list_name,
                        "Latitude": place.latitude,
                        "Longitude": place.longitude,
                    }
                    try:
                        result = (
                            importer.import_place(place)
                            if list_ok
                            else {
                                "Status": "FAILED",
                                "Message": list_message,
                                "LabelStatus": "FAILED",
                                "LabelMessage": "Not attempted",
                                "NoteStatus": "FAILED",
                                "NoteMessage": "Not attempted",
                            }
                        )
                    except Exception as error:
                        result = {
                            "Status": "ERROR",
                            "Message": str(error).replace("\n", " ")[:500],
                            "LabelStatus": "FAILED",
                            "LabelMessage": "Import error",
                            "NoteStatus": "FAILED",
                            "NoteMessage": "Import error",
                        }
                    writer.writerow({**base, **result})
                    stream.flush()
                    if result["Status"] == "OK":
                        ok += 1
                    else:
                        failed += 1
                    print(
                        f"  -> {result['Status']}; label: {result['LabelStatus']}; note: {result['NoteStatus']}"
                    )
    print(f"Finished: {ok} saved, {failed} failed\nAudit log: {args.log.resolve()}")
    return 1 if failed else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import each My Maps layer into a separate Google Maps Saved List"
    )
    p.add_argument("kmz", type=Path)
    p.add_argument("--list-prefix", help="Defaults to the KMZ document name")
    p.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--log", type=Path, default=Path("google_maps_import_log.csv"))
    p.add_argument("--no-notes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    p.add_argument("--debug-log", type=Path, default=Path("converter.log"))
    return p


def configure_logging(level: str, log_file: Path) -> None:
    """Configure console and UTF-8 file diagnostics with adjustable levels."""
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        handlers=[file_handler, console_handler],
        force=True,
    )
    LOGGER.debug("Logging initialized: level=%s file=%s", level, log_file.resolve())


def main(argv=None) -> int:
    # Hebrew layer names require UTF-8 on legacy Windows consoles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        args = parser().parse_args(argv)
        configure_logging(args.log_level, args.debug_log)
        return run(args)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Import Google My Maps KMZ placemarks into one Google Maps Saved List."""

from __future__ import annotations
import argparse, csv, html, re, sys, time, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from xml.etree import ElementTree as ET

KML_NS={"kml":"http://www.opengis.net/kml/2.2"}
DEFAULT_CDP_URL="http://127.0.0.1:9222"
NOTE_LIMIT=4000

@dataclass(frozen=True)
class Place:
    name:str
    latitude:float
    longitude:float
    section:str=""
    description:str=""
    @property
    def note(self)->str:
        return build_note(self.section,self.description)

def normalize(value:str|None)->str:
    return re.sub(r"\s+"," ",(value or "").strip())

def description_to_text(value:str|None)->str:
    if not value:return ""
    text=html.unescape(value)
    text=re.sub(r"(?i)<br\s*/?>","\n",text)
    text=re.sub(r"(?i)</(?:p|div|li|tr|h[1-6])>","\n",text)
    text=re.sub(r"<[^>]+>","",text)
    lines=[re.sub(r"[ \t]+"," ",x).strip() for x in text.splitlines()]
    return "\n".join(x for x in lines if x)

def build_note(section:str,description:str,limit:int=NOTE_LIMIT)->str:
    parts=([f"[Section: {section}]"] if section else [])
    cleaned=description_to_text(description)
    if cleaned:parts.append(cleaned)
    note="\n\n".join(parts)
    return note if len(note)<=limit else note[:limit-1].rstrip()+"…"

def _coordinates(mark:ET.Element)->tuple[float,float]|None:
    raw=mark.findtext(".//kml:Point/kml:coordinates",namespaces=KML_NS)
    if not raw:return None
    parts=raw.strip().split()[0].split(",")
    if len(parts)<2:return None
    try:lon,lat=float(parts[0]),float(parts[1])
    except ValueError:return None
    return (lat,lon) if -90<=lat<=90 and -180<=lon<=180 else None

def _walk(node:ET.Element,folders:tuple[str,...]=())->Iterable[Place]:
    for child in node:
        tag=child.tag.rsplit("}",1)[-1]
        if tag=="Folder":
            name=normalize(child.findtext("kml:name",namespaces=KML_NS))
            yield from _walk(child,folders+((name,) if name else ()))
        elif tag=="Placemark":
            coords=_coordinates(child)
            if not coords:continue
            name=normalize(child.findtext("kml:name",namespaces=KML_NS))
            desc=child.findtext("kml:description",default="",namespaces=KML_NS)
            yield Place(name or f"Dropped pin {coords[0]:.6f},{coords[1]:.6f}",coords[0],coords[1]," / ".join(folders),description_to_text(desc))
        elif tag in {"Document","kml"}:
            yield from _walk(child,folders)

def parse_kml(data:bytes|str)->list[Place]:
    return list(_walk(ET.fromstring(data)))

def parse_kmz(path:Path)->list[Place]:
    with zipfile.ZipFile(path) as z:
        names=[x for x in z.namelist() if x.lower().endswith(".kml")]
        if not names:raise ValueError("KMZ does not contain a KML document")
        name=next((x for x in names if Path(x).name.lower()=="doc.kml"),names[0])
        return parse_kml(z.read(name))

class MapsImporter:
    SAVE='button[aria-label^="Save"],button[aria-label^="Saved in"],button[aria-label^="שמירה"],button[aria-label^="שמורים ב"]'
    ROW="xpath=ancestor-or-self::*[@role='menuitemradio' or @role='menuitemcheckbox' or @role='checkbox'][1]"
    def __init__(self,page,list_name:str,delay:float=2.0,notes:bool=True):
        self.page,self.list_name,self.delay,self.notes=page,list_name,delay,notes
    def _button(self):return self.page.locator(self.SAVE).first
    def _has_button(self):
        try:return self._button().is_visible(timeout=1000)
        except Exception:return False
    def _first_result(self):
        result=self.page.locator('a[href*="/maps/place/"]').first
        try:
            if result.is_visible(timeout=1500):result.click();time.sleep(1.5)
        except Exception:pass
    def search(self,place:Place):
        query=f"{place.name} {place.latitude},{place.longitude}"
        self.page.goto("https://www.google.com/maps/search/"+quote(query),wait_until="domcontentloaded",timeout=30000)
        time.sleep(2);self._first_result()
        if not self._has_button():
            coords=f"{place.latitude},{place.longitude}"
            self.page.goto("https://www.google.com/maps/search/?api=1&query="+quote(coords),wait_until="domcontentloaded",timeout=30000)
            time.sleep(2);self._first_result()
    def save(self)->tuple[bool,str]:
        try:self._button().wait_for(state="visible",timeout=5000);self._button().click()
        except Exception:return False,"No savable Google place or coordinate pin found"
        time.sleep(1)
        label=self.page.get_by_text(self.list_name,exact=True).last
        try:label.wait_for(state="visible",timeout=5000)
        except Exception:
            self.page.keyboard.press("Escape")
            return False,f'Target list "{self.list_name}" not found'
        row=label.locator(self.ROW);target=row if row.count() else label
        already=target.get_attribute("aria-checked")=="true"
        if not already:target.click(timeout=10000);time.sleep(.5)
        self.page.keyboard.press("Escape")
        return True,"Already saved" if already else "Saved"
    def add_note(self,note:str)->tuple[bool,str]:
        if not self.notes or not note:return True,"Skipped"
        trigger=self.page.get_by_text(re.compile(r"^(Add (a )?note|הוספת הערה|הוספת פתק)$",re.I)).last
        try:trigger.wait_for(state="visible",timeout=3500);trigger.click()
        except Exception:return False,"Add-note control unavailable in current Maps UI"
        editor=self.page.locator("textarea:visible").last
        if not editor.count():editor=self.page.locator('input[type="text"]:visible').last
        try:editor.fill(note)
        except Exception:
            self.page.keyboard.press("Escape");return False,"Note editor not found"
        for name in ("Done","Save","סיום","שמירה"):
            button=self.page.get_by_role("button",name=name,exact=True).last
            try:
                if button.is_visible(timeout=800):button.click();return True,"Added"
            except Exception:pass
        editor.press("Control+Enter");return True,"Added"
    def import_place(self,place:Place)->dict[str,str]:
        self.search(place);ok,msg=self.save()
        note_ok,note_msg=self.add_note(place.note) if ok else (False,"Not attempted")
        time.sleep(self.delay)
        return {"Status":"OK" if ok else "FAILED","Message":msg,"NoteStatus":"OK" if note_ok else "FAILED","NoteMessage":note_msg}

def preview(places:list[Place])->None:
    sections={}
    for p in places:sections[p.section or "(unsectioned)"]=sections.get(p.section or "(unsectioned)",0)+1
    print(f"Parsed {len(places)} placemarks in {len(sections)} sections")
    for name,count in sections.items():print(f"  {name}: {count}")
    print("Descriptions are not printed because they may contain private data.")

def maps_page(context):
    return next((p for p in context.pages if "google.com/maps" in p.url),context.pages[0] if context.pages else context.new_page())

def ensure_login(page):
    page.goto("https://www.google.com/maps",wait_until="domcontentloaded",timeout=30000);time.sleep(2)
    for label in ("Sign in","כניסה"):
        try:
            if page.get_by_text(label,exact=True).is_visible(timeout=800):raise RuntimeError("Chrome is not signed in to Google Maps")
        except RuntimeError:raise
        except Exception:pass

FIELDS=["Name","Section","Latitude","Longitude","Status","Message","NoteStatus","NoteMessage"]

def run(args)->int:
    places=parse_kmz(args.kmz);preview(places)
    if args.dry_run:return 0
    try:from playwright.sync_api import sync_playwright
    except ImportError as e:raise RuntimeError("Run: pip install -r requirements.txt") from e
    ok=failed=0
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:raise RuntimeError("Chrome has no browser context")
        page=maps_page(browser.contexts[0]);ensure_login(page)
        importer=MapsImporter(page,args.list_name,args.delay,not args.no_notes)
        with args.log.open("w",newline="",encoding="utf-8-sig") as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
            for i,place in enumerate(places,1):
                print(f"[{i}/{len(places)}] {place.name} ({place.section or 'unsectioned'})")
                base={"Name":place.name,"Section":place.section,"Latitude":place.latitude,"Longitude":place.longitude}
                try:result=importer.import_place(place)
                except Exception as e:result={"Status":"ERROR","Message":str(e).replace("\n"," ")[:500],"NoteStatus":"FAILED","NoteMessage":"Import error"}
                writer.writerow({**base,**result});f.flush()
                if result["Status"]=="OK":ok+=1
                else:failed+=1
                print(f"  -> {result['Status']}: {result['Message']}; note: {result['NoteStatus']}")
    print(f"Finished: {ok} saved, {failed} failed\nAudit log: {args.log.resolve()}")
    return 1 if failed else 0

def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Import a My Maps KMZ into one Google Maps Saved List")
    p.add_argument("kmz",type=Path);p.add_argument("--list-name",required=True)
    p.add_argument("--cdp-url",default=DEFAULT_CDP_URL);p.add_argument("--delay",type=float,default=2.0)
    p.add_argument("--log",type=Path,default=Path("google_maps_import_log.csv"))
    p.add_argument("--no-notes",action="store_true");p.add_argument("--dry-run",action="store_true")
    return p

def main(argv=None)->int:
    try:return run(parser().parse_args(argv))
    except (OSError,ValueError,zipfile.BadZipFile,RuntimeError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2

if __name__=="__main__":raise SystemExit(main())

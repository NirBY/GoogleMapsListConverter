import zipfile

import pytest

from google_maps_list_converter import (
    build_note,
    description_to_text,
    parse_kml,
    parse_kmz,
)


KML = b'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Folder><name>Food</name>
    <Folder><name>Cafes</name>
      <Placemark><name>Example Cafe</name>
        <description>Try &lt;b&gt;cake&lt;/b&gt;&lt;br&gt;Open early</description>
        <Point><coordinates>33.1234,34.9876,0</coordinates></Point>
      </Placemark>
    </Folder>
  </Folder>
  <Placemark><name>Line, not a point</name><LineString><coordinates>1,2</coordinates></LineString></Placemark>
</Document></kml>'''


def test_parse_nested_folders_and_description():
    places = parse_kml(KML)
    assert len(places) == 1
    place = places[0]
    assert place.name == "Example Cafe"
    assert place.section == "Food / Cafes"
    assert place.latitude == pytest.approx(34.9876)
    assert place.longitude == pytest.approx(33.1234)
    assert place.description == "Try cake\nOpen early"
    assert place.note == "[Section: Food / Cafes]\n\nTry cake\nOpen early"


def test_parse_kmz_prefers_doc_kml(tmp_path):
    path = tmp_path / "map.kmz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other.kml", "<kml xmlns='http://www.opengis.net/kml/2.2'/>")
        archive.writestr("doc.kml", KML)
    assert parse_kmz(path)[0].name == "Example Cafe"


def test_kmz_without_kml_is_rejected(tmp_path):
    path = tmp_path / "bad.kmz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("icon.png", b"not an image")
    with pytest.raises(ValueError, match="does not contain"):
        parse_kmz(path)


def test_html_cleanup_and_note_limit():
    assert description_to_text("A&amp;B<div>Next</div>") == "A&BNext"
    note = build_note("Section", "x" * 100, limit=30)
    assert len(note) == 30
    assert note.endswith("…")

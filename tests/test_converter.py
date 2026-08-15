from pathlib import Path
import zipfile
import pytest
from google_maps_list_converter import (
    Place,
    build_note,
    description_to_text,
    group_places_by_layer,
    make_list_name,
    parse_kml,
    parse_kmz,
    parse_kmz_description,
    parser,
)

KML = b"""<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Trip</name><description>General</description><Folder><name>Food</name><Folder><name>Cafes</name><Placemark><name>Example Cafe</name><description>Try &lt;b&gt;cake&lt;/b&gt;&lt;br&gt;Open early</description><Point><coordinates>33.1234,34.9876,0</coordinates></Point></Placemark></Folder></Folder><Placemark><name>Line</name><LineString><coordinates>1,2</coordinates></LineString></Placemark></Document></kml>"""


def test_parse_nested_folders_and_description():
    place = parse_kml(KML)[0]
    assert place.name == "Example Cafe" and place.section == "Food / Cafes"
    assert place.latitude == pytest.approx(34.9876)
    assert place.note == "Try cake\nOpen early"


def test_layers_are_separate_and_deduplicated_only_within_layer():
    places = [
        Place("A", 1, 2, "One", "first"),
        Place("A2", 1, 2, "One", "second"),
        Place("B", 1, 2, "Two", "third"),
    ]
    groups = group_places_by_layer(places)
    assert list(groups) == ["One", "Two"]
    assert len(groups["One"]) == 1 and len(groups["Two"]) == 1
    assert groups["One"][0].description == "first\n\nsecond"


def test_list_names_are_limited():
    assert make_list_name("Trip", "Food") == "Trip — Food"
    assert len(make_list_name("x" * 50, "Restaurants")) <= 40


def test_parse_kmz_and_general_description(tmp_path):
    path = tmp_path / "map.kmz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other.kml", "<kml xmlns='http://www.opengis.net/kml/2.2'/>")
        archive.writestr("doc.kml", KML)
    assert parse_kmz(path)[0].name == "Example Cafe"
    assert parse_kmz_description(path) == "General"


def test_kmz_without_kml_is_rejected(tmp_path):
    path = tmp_path / "bad.kmz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("icon.png", b"x")
    with pytest.raises(ValueError, match="does not contain"):
        parse_kmz(path)


def test_html_cleanup_and_note_limit():
    assert description_to_text("A&amp;B<div>Next</div>") == "A&BNext"
    note = build_note("x" * 100, limit=30)
    assert len(note) == 30 and note.endswith("…")


def test_screenshot_cli_option():
    args = parser().parse_args(["map.kmz", "--screenshots", "verification-screenshots"])
    assert args.screenshots == Path("verification-screenshots")

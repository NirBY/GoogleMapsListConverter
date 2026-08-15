from pathlib import Path
import zipfile
import pytest
from google_maps_list_converter import (
    MapsImporter,
    Place,
    build_note,
    create_verification_clip,
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
    assert args.video_dir == Path("verification-clips")
    assert args.video_fps == 2.0
    assert not args.no_media


def test_timestamp_watermarked_verification_clip(tmp_path):
    import imageio.v2 as imageio
    import numpy as np

    frames = tmp_path / "frames"
    frames.mkdir()
    imageio.imwrite(frames / "001.png", np.zeros((128, 512, 3), dtype=np.uint8))
    imageio.imwrite(frames / "002.png", np.full((128, 512, 3), 255, dtype=np.uint8))
    output = tmp_path / "clip.mp4"
    ok, message = create_verification_clip(frames, output, fps=2)
    assert ok, message
    assert output.stat().st_size > 0
    reader = imageio.get_reader(output)
    first_frame = reader.get_data(0)
    reader.close()
    assert first_frame[-32:, :300].max() > 0


def test_page_source_evidence_is_timestamped_and_grouped(tmp_path):
    class Page:
        @staticmethod
        def content():
            return "<html><body>real rendered content</body></html>"

    importer = MapsImporter(Page(), "Layer / One", 0, True, tmp_path)
    ok, message = importer.capture_page_source()
    output = Path(message)
    assert ok and output.parent.name == "Layer _ One"
    source = output.read_text(encoding="utf-8")
    assert source.startswith("<!-- Captured ")
    assert "real rendered content" in source

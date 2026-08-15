from pathlib import Path
import zipfile
import pytest
import google_maps_list_converter as converter
from google_maps_list_converter import (
    FIELDS,
    LIST_SYNC_SECONDS,
    MapsImporter,
    Place,
    build_note,
    create_verification_clip,
    description_to_text,
    failure_result,
    group_places_by_layer,
    list_text_pattern,
    make_list_name,
    normalize,
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
    assert description_to_text("A&amp;B<div>Next</div>") == "A&B Next"
    assert description_to_text("<b>Header</b><p>Content</p>") == "Header Content"
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


def test_normalize_removes_bidi_and_zero_width_markers():
    assert (
        normalize("  Ocean\u200f\u200f  Aquarium\u200e\u200b\ufeff ")
        == "Ocean Aquarium"
    )


def test_list_text_pattern_accepts_count_but_not_partial_name():
    pattern = list_text_pattern("Cyprus 2026 — Food")
    assert pattern.fullmatch(" Cyprus 2026 — Food (12) ")
    assert not pattern.fullmatch("Cyprus 2026 — Food Extra")


def test_note_trigger_has_no_unsafe_first_row_fallback():
    class Missing:
        first = None

        def __init__(self):
            self.first = self

        @staticmethod
        def count():
            return 0

    class Page:
        @staticmethod
        def get_by_text(*_args, **_kwargs):
            return Missing()

        @staticmethod
        def locator(*_args, **_kwargs):
            raise AssertionError("must not fall back to the first note button")

    assert MapsImporter(Page(), "List", 0, True, None)._note_trigger("Missing") is None


def test_new_list_waits_for_save_picker_propagation(monkeypatch):
    sleeps = []

    class Locator:
        def __init__(self, count=1):
            self._count = count
            self.last = self

        def count(self):
            return self._count

        @staticmethod
        def is_visible(**_kwargs):
            return False

        @staticmethod
        def click():
            return None

        @staticmethod
        def wait_for(**_kwargs):
            return None

        @staticmethod
        def fill(_value):
            return None

    class Page:
        @staticmethod
        def locator(selector):
            return Locator(0 if "viewMore" in selector else 1)

    importer = MapsImporter(Page(), "New list", 0, True, None)
    monkeypatch.setattr(importer, "open_saved", lambda: None)
    monkeypatch.setattr(importer, "_saved_list_matches", lambda: Locator(0))
    monkeypatch.setattr(
        importer, "set_list_description", lambda _value: (True, "Skipped")
    )
    monkeypatch.setattr(converter.time, "sleep", sleeps.append)
    assert importer.ensure_list()[0]
    assert LIST_SYNC_SECONDS in sleeps


def test_failure_result_populates_every_audit_result_field():
    result = failure_result("ERROR", "boom", "Import error")
    assert set(result) == set(FIELDS[5:])
    assert all(result[field] for field in FIELDS[5:])


def test_main_configures_stdout_and_stderr_as_utf8(monkeypatch, tmp_path):
    class Stream:
        def __init__(self):
            self.encoding_set = None

        def reconfigure(self, *, encoding):
            self.encoding_set = encoding

        @staticmethod
        def write(_value):
            return None

        @staticmethod
        def flush():
            return None

    stdout, stderr = Stream(), Stream()
    monkeypatch.setattr(converter.sys, "stdout", stdout)
    monkeypatch.setattr(converter.sys, "stderr", stderr)
    monkeypatch.setattr(converter, "configure_logging", lambda *_args: None)
    assert converter.main([str(tmp_path / "missing.kmz"), "--dry-run"]) == 2
    assert stdout.encoding_set == stderr.encoding_set == "utf-8"


def test_version_option_is_available(capsys):
    with pytest.raises(SystemExit) as exit_info:
        parser().parse_args(["--version"])
    assert exit_info.value.code == 0
    assert "1.0.0" in capsys.readouterr().out

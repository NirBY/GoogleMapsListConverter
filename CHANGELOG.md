# Changelog

## v1.0.0 - 2026-08-15

First stable release.

### Fixed

- Wait for newly created lists to propagate before importing the first point.
- Remove invisible bidi and zero-width Unicode markers from KMZ names.
- Refuse to edit a note when its exact saved-place row cannot be found.
- Match Save-picker list names with optional whitespace and count suffixes.
- Configure both Windows output streams for UTF-8.
- Populate every audit CSV status/evidence field on failures.
- Preserve word boundaries while converting HTML descriptions to notes.

### Included

- Separate Google Maps list per My Maps layer.
- KMZ descriptions, private coordinate labels, duplicate-list protection, EN/HE selectors, configurable logging, screenshots, timestamped HTML source, and timestamp-watermarked MP4 evidence.

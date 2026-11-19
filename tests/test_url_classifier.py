"""Unit tests for URL classifier, sanitizer, and filename heuristics."""
import pytest
from app.core.models import DownloadType
from app.core.url_classifier import (
    classify_url,
    extract_filename_from_url,
    is_media_url,
    parse_content_disposition,
    sanitize_filename,
    sanitize_url,
)


def test_sanitize_url_removes_tracking_and_whitespace():
    raw = "   https://example.com/file.zip?utm_source=twitter&utm_medium=cpc&id=123&fbclid=abcdef   "
    clean = sanitize_url(raw)
    assert "utm_source" not in clean
    assert "fbclid" not in clean
    assert "id=123" in clean
    assert clean.startswith("https://example.com/file.zip")


def test_sanitize_url_prepends_https():
    raw = "releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso"
    clean = sanitize_url(raw)
    assert clean.startswith("https://releases.ubuntu.com")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
        ("https://youtu.be/dQw4w9WgXcQ", True),
        ("https://www.facebook.com/watch/?v=10153231379946729", True),
        ("https://fb.watch/xyz123/", True),
        ("https://twitter.com/user/status/123456789", True),
        ("https://x.com/user/status/123456789", True),
        ("https://www.tiktok.com/@creator/video/1234567890", True),
        ("https://vimeo.com/76979871", True),
        ("https://www.reddit.com/r/videos/comments/xyz/funny_cat_video/", True),
        ("https://speed.hetzner.de/100MB.bin", False),
        ("https://cdn.example.com/software/setup.exe", False),
        ("https://releases.ubuntu.com/ubuntu-24.04.iso", False),
    ],
)
def test_is_media_url(url, expected):
    assert is_media_url(url) == expected


def test_classify_url():
    assert classify_url("https://www.youtube.com/watch?v=abc") == DownloadType.MEDIA_STREAM
    assert classify_url("https://speed.hetzner.de/100MB.bin") == DownloadType.DIRECT_HTTP


def test_extract_filename_from_url():
    url = "https://example.org/downloads/v1.2.3/Application%20Installer%20v1.2.3.exe?token=abc"
    fn = extract_filename_from_url(url)
    assert fn == "Application Installer v1.2.3.exe"

    url2 = "https://example.org/archive.tar.gz"
    assert extract_filename_from_url(url2) == "archive.tar.gz"


def test_sanitize_filename_windows_disallowed_characters():
    dirty = 'bad:name*with?illegal<chars>and|pipes".zip'
    clean = sanitize_filename(dirty)
    for char in '<>:"/\\|?*':
        assert char not in clean
    assert clean.endswith(".zip")


def test_parse_content_disposition():
    cd1 = 'attachment; filename="release-v2.0.zip"'
    assert parse_content_disposition(cd1) == "release-v2.0.zip"

    cd2 = "attachment; filename=document.pdf"
    assert parse_content_disposition(cd2) == "document.pdf"

    # RFC 5987 UTF-8 encoded
    cd3 = "attachment; filename*=UTF-8''my%20presentation%20%28final%29.pptx"
    assert parse_content_disposition(cd3) == "my presentation (final).pptx"

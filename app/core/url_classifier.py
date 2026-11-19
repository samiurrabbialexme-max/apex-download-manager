"""URL classification, sanitization, and filename extraction heuristics."""
import os
import re
from typing import Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from app.core.models import DownloadType

MEDIA_DOMAINS = [
    r"(?:www\.)?youtube\.com",
    r"youtu\.be",
    r"(?:www\.)?facebook\.com",
    r"(?:www\.)?fb\.watch",
    r"(?:www\.)?instagram\.com",
    r"(?:www\.)?twitter\.com",
    r"(?:www\.)?x\.com",
    r"(?:www\.)?tiktok\.com",
    r"(?:www\.)?reddit\.com",
    r"(?:v\.)?redd\.it",
    r"(?:www\.)?vimeo\.com",
    r"(?:www\.)?dailymotion\.com",
    r"(?:www\.)?twitch\.tv",
    r"(?:www\.)?soundcloud\.com",
    r"(?:www\.)?bilibili\.com",
]

MEDIA_DOMAIN_PATTERN = re.compile(
    r"^(?:https?:\/\/)?(?:[a-zA-Z0-9_\-]+\.)*(" + "|".join(MEDIA_DOMAINS) + r")(?:\/.*)?$",
    re.IGNORECASE,
)

COMMON_FILE_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk",
    ".iso", ".img", ".bin",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a",
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".txt", ".csv", ".json", ".xml",
}


def sanitize_url(raw_url: str) -> str:
    """Strips whitespace, surrounding quotes, and common tracking query params."""
    url = raw_url.strip().strip("'\"<>`")
    if not url:
        return ""

    if not url.startswith(("http://", "https://", "ftp://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        # Strip tracking params
        tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
        filtered_query = {k: v for k, v in query.items() if k.lower() not in tracking_keys}
        new_query = urlencode(filtered_query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


def is_media_url(url: str) -> bool:
    """Checks if the URL is hosted on a recognized streaming or media platform."""
    clean = sanitize_url(url)
    parsed = urlparse(clean)
    host = parsed.netloc.lower()
    if not host:
        return False
    return bool(MEDIA_DOMAIN_PATTERN.match(clean) or MEDIA_DOMAIN_PATTERN.match(f"https://{host}"))


def classify_url(url: str) -> DownloadType:
    """Classifies a URL as either MEDIA_STREAM or DIRECT_HTTP."""
    if is_media_url(url):
        return DownloadType.MEDIA_STREAM
    return DownloadType.DIRECT_HTTP


def extract_filename_from_url(url: str, default: str = "download") -> str:
    """Extracts a clean filename from a direct download URL."""
    clean = sanitize_url(url)
    try:
        parsed = urlparse(clean)
        path = unquote(parsed.path)
        base = os.path.basename(path.rstrip("/"))
        if base and "." in base:
            # Clean invalid filename characters for Windows
            return sanitize_filename(base)
    except Exception:
        pass
    return sanitize_filename(default)


def parse_content_disposition(cd_header: str) -> str:
    """Parses RFC 6266 / RFC 5987 Content-Disposition header."""
    if not cd_header:
        return ""
    
    # 1. Look for filename*=UTF-8''encoded_name
    utf8_match = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", cd_header, re.IGNORECASE)
    if utf8_match:
        return sanitize_filename(unquote(utf8_match.group(1).strip()))

    # 2. Look for filename="name" or filename=name
    match = re.search(r'filename\s*=\s*(?:"([^"]+)"|([^;\s]+))', cd_header, re.IGNORECASE)
    if match:
        name = match.group(1) or match.group(2)
        return sanitize_filename(name.strip())

    return ""


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """Sanitizes filename for Windows and POSIX filesystems."""
    # Disallowed chars on Windows: < > : " / \ | ? *
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    if not clean:
        clean = "download"
    if len(clean) > max_length:
        stem, ext = os.path.splitext(clean)
        clean = stem[: max_length - len(ext)] + ext
    return clean

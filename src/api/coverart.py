"""Cover Art Archive API interface for album and release artwork."""
import requests

CAA_BASE = "https://coverartarchive.org"
TIMEOUT = 15


def get_release_images(release_id: str) -> list[dict]:
    """
    Return metadata for all cover art images associated with a release.

    Each dict contains: id, types, front, back, comment, image, thumbnails.
    Returns an empty list if no images are found or on network error.
    """
    url = f"{CAA_BASE}/release/{release_id}"
    try:
        resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "id": img.get("id", ""),
                "types": img.get("types", []),
                "front": img.get("front", False),
                "back": img.get("back", False),
                "comment": img.get("comment", ""),
                "image": img.get("image", ""),
                "thumbnails": img.get("thumbnails", {}),
            }
            for img in data.get("images", [])
        ]
    except (requests.RequestException, ValueError):
        return []


def download_image(url: str) -> bytes | None:
    """Download an image from a URL and return its raw bytes, or None on failure."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        return None


def get_front_cover(release_id: str, size: str = "500") -> bytes | None:
    """
    Fetch the front cover image for a release.

    Tries the sized URL first, then falls back to the unsized redirect.
    Returns raw image bytes, or None if unavailable.
    """
    for url in (
        f"{CAA_BASE}/release/{release_id}/front-{size}",
        f"{CAA_BASE}/release/{release_id}/front",
    ):
        data = download_image(url)
        if data is not None:
            return data
    return None

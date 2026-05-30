"""MusicBrainz API interface for artist and release metadata."""
import logging
import time
import musicbrainzngs

logger = logging.getLogger(__name__)

musicbrainzngs.set_useragent(
    "SongLyricsToEbook",
    "1.0",
    "https://github.com/dfbr/song-lyrics-to-ebook",
)


def search_artists(query: str, limit: int = 25) -> list[dict]:
    """Search for artists by name. Returns a list of artist dicts."""
    result = musicbrainzngs.search_artists(query=query, limit=limit)
    artists = []
    for artist in result.get("artist-list", []):
        artists.append(
            {
                "id": artist.get("id", ""),
                "name": artist.get("name", ""),
                "disambiguation": artist.get("disambiguation", ""),
                "country": artist.get("country", ""),
                "score": int(artist.get("ext:score", 0)),
            }
        )
    return artists


def search_release_groups(query: str, limit: int = 25) -> list[dict]:
    """Search release groups by title and return simplified album entries."""
    result = musicbrainzngs.search_release_groups(query=query, limit=limit)
    groups = []
    for rg in result.get("release-group-list", []):
        artist_name = ""
        artist_credit = rg.get("artist-credit", [])
        if artist_credit:
            first = artist_credit[0]
            if isinstance(first, dict):
                artist_name = first.get("artist", {}).get("name", "")

        groups.append(
            {
                "id": rg.get("id", ""),
                "title": rg.get("title", ""),
                "type": rg.get("primary-type", rg.get("type", "Other")),
                "primary_type": rg.get("primary-type", ""),
                "secondary_types": rg.get("secondary-type-list", []),
                "first_release_date": rg.get("first-release-date", ""),
                "artist": artist_name,
                "score": int(rg.get("ext:score", 0)),
            }
        )
    return groups


def get_artist_release_groups(artist_id: str) -> list[dict]:
    """
    Get all release groups (albums, singles, EPs, etc.) for an artist.
    Uses pagination to retrieve the full catalogue.
    """
    all_groups: list[dict] = []
    limit = 100
    offset = 0

    while True:
        result = musicbrainzngs.browse_release_groups(
            artist=artist_id,
            limit=limit,
            offset=offset,
        )
        groups = result.get("release-group-list", [])
        total = int(result.get("release-group-count", 0))

        for rg in groups:
            all_groups.append(
                {
                    "id": rg.get("id", ""),
                    "title": rg.get("title", ""),
                    "type": rg.get("primary-type", rg.get("type", "Other")),
                    "primary_type": rg.get("primary-type", ""),
                    "secondary_types": rg.get("secondary-type-list", []),
                    "first_release_date": rg.get("first-release-date", ""),
                }
            )

        offset += len(groups)
        if offset >= total or not groups:
            break

        time.sleep(1)  # MusicBrainz rate limit: 1 request/second

    all_groups.sort(key=lambda x: x.get("first_release_date") or "0000")
    return all_groups


def get_release_group_releases(release_group_id: str) -> list[dict]:
    """Return all releases that belong to a release group."""
    result = musicbrainzngs.get_release_group_by_id(
        release_group_id,
        includes=["releases"],
    )
    rg = result.get("release-group", {})
    releases = []
    for rel in rg.get("release-list", []):
        releases.append(
            {
                "id": rel.get("id", ""),
                "title": rel.get("title", ""),
                "status": rel.get("status", ""),
                "date": rel.get("date", ""),
                "country": rel.get("country", ""),
            }
        )
    return releases


def get_release_tracks(release_id: str) -> tuple[dict, list[dict]]:
    """
    Fetch full release information and its track listing.

    Returns:
        (release_info dict, list of track dicts)
    """
    result = musicbrainzngs.get_release_by_id(
        release_id,
        includes=["recordings", "artist-credits", "release-groups", "labels", "media"],
    )
    release = result.get("release", {})

    info: dict = {
        "id": release.get("id", ""),
        "title": release.get("title", ""),
        "artist": "",
        "date": release.get("date", ""),
        "status": release.get("status", ""),
        "country": release.get("country", ""),
        "barcode": release.get("barcode", ""),
        "label": "",
        "catalog_number": "",
        "release_group_id": "",
        "type": "",
        "first_release_date": "",
    }

    release_artist_credit = release.get("artist-credit", [])
    if release_artist_credit:
        first = release_artist_credit[0]
        if isinstance(first, dict):
            info["artist"] = first.get("artist", {}).get("name", "")

    for label_info in release.get("label-info-list", []):
        label = label_info.get("label", {})
        info["label"] = label.get("name", "")
        info["catalog_number"] = label_info.get("catalog-number", "")
        break

    rg = release.get("release-group", {})
    info["release_group_id"] = rg.get("id", "")
    info["type"] = rg.get("primary-type", rg.get("type", ""))
    info["first_release_date"] = rg.get("first-release-date", "")

    tracks: list[dict] = []
    for medium in release.get("medium-list", []):
        disc_number = int(medium.get("position", 1))
        for track in medium.get("track-list", []):
            recording = track.get("recording", {})
            artist_credit = recording.get("artist-credit", [])
            artist_name = ""
            if artist_credit:
                first = artist_credit[0]
                if isinstance(first, dict):
                    artist_name = first.get("artist", {}).get("name", "")

            tracks.append(
                {
                    "position": int(track.get("position", 0)),
                    "disc": disc_number,
                    "number": track.get("number", ""),
                    "title": track.get("title") or recording.get("title", ""),
                    "length": int(recording.get("length", 0) or 0),
                    "recording_id": recording.get("id", ""),
                    "artist": artist_name,
                }
            )

    logger.info("Loaded %s tracks for release %s", len(tracks), release_id)
    return info, tracks

"""Support for Photoview media source."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import BrowseMedia
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .api import PhotoviewApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HARDCODED_FOLDERS = [
    {"id": "albums", "title": "Albums", "media_class": "directory"},
    {"id": "people", "title": "People", "media_class": "directory"},
    {"id": "starred", "title": "Starred", "media_class": "directory"},
]


async def async_get_media_source(hass: HomeAssistant) -> PhotoviewMediaSource:
    """Set up Photoview media source."""
    return PhotoviewMediaSource(hass)


class PhotoviewMediaSource(MediaSource):
    """Provide Photoview media source."""

    name: str = "Photoview"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Photoview media source."""
        super().__init__(DOMAIN)
        self.hass = hass
        self.api_client = None

    async def _get_api_client(self) -> PhotoviewApiClient:
        """Get the Photoview API client."""
        if self.api_client is None:
            # Get the API client from the integration
            config_entries = self.hass.config_entries.async_entries(DOMAIN)
            if not config_entries:
                raise Unresolvable("No Photoview integration configured")

            entry = config_entries[0]
            self.api_client = self.hass.data[DOMAIN][entry.entry_id]
        return self.api_client

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable URL."""
        _LOGGER.debug("Resolving media item: %s", item.identifier)

        api_client = await self._get_api_client()

        # Parse the identifier to get the media ID
        media_id = item.identifier

        # Get the media URL from Photoview
        media_url = await api_client.async_get_media_url(media_id)

        # Convert the media URL to use our proxy for authentication
        proxied_url = api_client.get_authenticated_url(media_url)

        _LOGGER.debug("Resolved media %s to proxied URL: %s",
                      media_id, proxied_url)

        return PlayMedia(proxied_url, "image/jpeg")

    async def async_browse_media(
        self, item: MediaSourceItem
    ) -> BrowseMediaSource:
        """Return media objects for browsing."""
        identifier = item.identifier if item.identifier is not None else ""
        _LOGGER.debug("Browsing media for identifier: '%s'", identifier)

        api_client = await self._get_api_client()

        if item.identifier == "" or item.identifier is None:
            # Root level - show hardcoded folders
            return await self._browse_root()
        elif item.identifier == "albums":
            # Albums folder - show root albums
            return await self._browse_albums_root(api_client)
        elif item.identifier.startswith("album:"):
            # Specific album - show contents
            album_id = item.identifier[6:]  # Remove "album:" prefix
            return await self._browse_album(api_client, album_id)
        elif item.identifier == "people":
            # People folder - not implemented yet
            return await self._browse_not_implemented("People")
        elif item.identifier == "starred":
            # Starred folder - not implemented yet
            return await self._browse_not_implemented("Starred")
        else:
            _LOGGER.warning("Unknown identifier: %s", item.identifier)
            raise Unresolvable(f"Unknown identifier: {item.identifier}")

    async def _browse_root(self) -> BrowseMediaSource:
        """Browse the root level with hardcoded folders."""
        _LOGGER.debug("Browsing root level")

        children = []
        for folder in HARDCODED_FOLDERS:
            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=folder["id"],
                    media_class=folder["media_class"],
                    media_content_type="",
                    title=folder["title"],
                    can_play=False,
                    can_expand=True,
                )
            )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier="",
            media_class="directory",
            media_content_type="",
            title="Photoview",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_albums_root(self, api_client: PhotoviewApiClient) -> BrowseMediaSource:
        """Browse root albums in the Albums folder."""
        _LOGGER.debug("Browsing root albums")

        albums = await api_client.async_get_albums(only_root=True)
        children = []

        for album in albums:
            # Get thumbnail URL if available
            thumbnail = None
            _LOGGER.debug("Album %s (%s) raw thumbnail data: %s", album.get(
                "title"), album.get("id"), album.get("thumbnail"))

            # Handle both nested and flat thumbnail structures
            if album.get("thumbnail"):
                relative_url = None
                if album["thumbnail"].get("thumbnail") and album["thumbnail"]["thumbnail"].get("url"):
                    # Nested structure: thumbnail.thumbnail.url
                    relative_url = album["thumbnail"]["thumbnail"]["url"]
                elif album["thumbnail"].get("url"):
                    # Flat structure: thumbnail.url
                    relative_url = album["thumbnail"]["url"]

                if relative_url:
                    thumbnail = api_client.get_authenticated_url(relative_url)
                    _LOGGER.debug("Album %s thumbnail URL: %s",
                                  album.get("title"), thumbnail)

            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"album:{album['id']}",
                    media_class="directory",
                    media_content_type="",
                    title=album["title"],
                    can_play=False,
                    can_expand=True,
                    thumbnail=thumbnail,
                )
            )

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier="albums",
            media_class="directory",
            media_content_type="",
            title="Albums",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_album(self, api_client: PhotoviewApiClient, album_id: str) -> BrowseMediaSource:
        """Browse a specific album's contents."""
        _LOGGER.debug("Browsing album: %s", album_id)

        # Get album details, child albums, and photos
        album_details = await api_client.async_get_album_details(album_id)
        child_albums = await api_client.async_get_album_children(album_id)
        photos = await api_client.async_get_photos(album_id)

        children = []

        # Add child albums first
        for child_album in child_albums:
            # Get thumbnail URL if available
            thumbnail = None
            if child_album.get("thumbnail"):
                relative_url = None
                if child_album["thumbnail"].get("thumbnail") and child_album["thumbnail"]["thumbnail"].get("url"):
                    # Nested structure: thumbnail.thumbnail.url
                    relative_url = child_album["thumbnail"]["thumbnail"]["url"]
                elif child_album["thumbnail"].get("url"):
                    # Flat structure: thumbnail.url
                    relative_url = child_album["thumbnail"]["url"]

                if relative_url:
                    thumbnail = api_client.get_authenticated_url(relative_url)

            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"album:{child_album['id']}",
                    media_class="directory",
                    media_content_type="",
                    title=child_album["title"],
                    can_play=False,
                    can_expand=True,
                    thumbnail=thumbnail,
                )
            )

        # Add photos
        for photo in photos:
            # Get thumbnail URL if available
            thumbnail = None
            if photo.get("thumbnail"):
                relative_url = photo["thumbnail"]["url"]
                thumbnail = api_client.get_authenticated_url(relative_url)

            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=photo["id"],
                    media_class="image",
                    media_content_type="image/jpeg",
                    title=photo.get("title", f"Photo {photo['id']}"),
                    can_play=True,
                    can_expand=False,
                    thumbnail=thumbnail,
                )
            )

        album_title = album_details.get("title", f"Album {album_id}")

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"album:{album_id}",
            media_class="directory",
            media_content_type="",
            title=album_title,
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def _browse_not_implemented(self, folder_name: str) -> BrowseMediaSource:
        """Browse a folder that's not implemented yet."""
        _LOGGER.debug("Browsing not implemented folder: %s", folder_name)

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=folder_name.lower(),
            media_class="directory",
            media_content_type="",
            title=f"{folder_name} (Not Implemented)",
            can_play=False,
            can_expand=False,
            children=[],
        )

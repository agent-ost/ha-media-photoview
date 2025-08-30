"""Custom integration to integrate photoview with Home Assistant.

For more details about this integration, please refer to
https://github.com/agent-ost/ha-media-photoview
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.components import http
from homeassistant.components.http import HomeAssistantView
from aiohttp import web
import aiohttp
import logging

from .api import PhotoviewApiClient
from .const import CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""
    hass.data.setdefault(DOMAIN, {})

    # Store the API client for media source usage
    client = PhotoviewApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        base_url=entry.data[CONF_BASE_URL],
        session=async_get_clientsession(hass),
    )
    hass.data[DOMAIN][entry.entry_id] = client

    # Register the thumbnail proxy endpoint
    _register_thumbnail_proxy(hass)

    # Media source is automatically discovered via async_get_media_source
    # No need to forward setup to platforms for media source

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    # Remove the stored client data
    hass.data[DOMAIN].pop(entry.entry_id)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


def _register_thumbnail_proxy(hass: HomeAssistant) -> None:
    """Register the photo proxy endpoint for thumbnails and high-res images."""

    class PhotoviewPhotoView(HomeAssistantView):
        """View to proxy photo requests to Photoview with authentication."""

        url = "/api/photoview/photo/{photo_path:.*}"
        name = "api:photoview:photo"
        requires_auth = False  # We'll handle auth internally

        async def get(self, request, photo_path):
            """Handle GET request for photos (thumbnails and high-res)."""
            if not photo_path:
                return web.Response(status=400, text="Missing photo path")

            # Get the first available API client (we assume single config for now)
            clients = list(hass.data[DOMAIN].values())
            if not clients:
                _LOGGER.error("No Photoview API client available")
                return web.Response(status=503, text="Photoview not configured")

            api_client = clients[0]

            try:
                # Ensure we have an auth token
                if not api_client._auth_token:
                    await api_client.async_authenticate()

                # Build the full Photoview photo URL
                photoview_url = f"{api_client._base_url}/api/photo/{photo_path}"
                _LOGGER.debug(
                    "Proxying photo request to: %s", photoview_url)

                # Make authenticated request to Photoview using the auth-token cookie
                headers = {}
                if api_client._auth_token:
                    headers["Cookie"] = f"auth-token={api_client._auth_token}"
                    _LOGGER.debug(
                        "Using auth-token cookie for photo request")
                else:
                    _LOGGER.warning(
                        "No auth token available for photo request")

                async with api_client._session.get(photoview_url, headers=headers) as response:
                    _LOGGER.debug(
                        "Photoview response status: %s for URL: %s", response.status, photoview_url)
                    if response.status == 200:
                        # Stream the image back to client
                        content_type = response.headers.get(
                            "content-type", "image/jpeg")
                        data = await response.read()

                        return web.Response(
                            body=data,
                            content_type=content_type,
                            headers={
                                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                            }
                        )
                    else:
                        _LOGGER.warning(
                            "Failed to fetch photo from Photoview: %s", response.status)
                        return web.Response(status=response.status, text="Failed to fetch photo")

            except Exception as err:
                _LOGGER.error("Error proxying photo request: %s", err)
                return web.Response(status=500, text="Internal server error")

    # Register the view
    hass.http.register_view(PhotoviewPhotoView())

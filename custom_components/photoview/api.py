"""Photoview API Client."""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)


class PhotoviewApiClientError(Exception):
    """Exception to indicate a general API error."""


class PhotoviewApiClientCommunicationError(PhotoviewApiClientError):
    """Exception to indicate a communication error."""


class PhotoviewApiClientAuthenticationError(PhotoviewApiClientError):
    """Exception to indicate an authentication error."""


class PhotoviewApiClient:
    """Photoview API Client."""

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize Photoview API Client."""
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._auth_token: str | None = None

    async def async_authenticate(self) -> None:
        """Authenticate with Photoview and get auth token."""
        _LOGGER.debug("Authenticating with Photoview at %s", self._base_url)

        auth_mutation = """
        mutation AuthorizeUser($username: String!, $password: String!) {
            authorizeUser(username: $username, password: $password) {
                success
                token
            }
        }
        """

        variables = {
            "username": self._username,
            "password": self._password,
        }

        _LOGGER.debug(
            "Sending authentication mutation for user: %s", self._username)
        response = await self._graphql_request(auth_mutation, variables)

        if not response.get("data", {}).get("authorizeUser", {}).get("success"):
            _LOGGER.error("Authentication failed for user %s", self._username)
            raise PhotoviewApiClientAuthenticationError(
                "Authentication failed")

        self._auth_token = response["data"]["authorizeUser"]["token"]
        _LOGGER.debug(
            "Authentication successful, token received (length: %d)", len(self._auth_token))

    async def async_get_albums(self, only_root: bool = False) -> list[dict[str, Any]]:
        """Get user albums from Photoview."""
        if only_root:
            _LOGGER.debug("Fetching root albums from Photoview")
        else:
            _LOGGER.debug("Fetching all albums from Photoview")

        if not self._auth_token:
            _LOGGER.debug("No auth token available, authenticating first")
            await self.async_authenticate()

        if only_root:
            query = """
            query getMyRootAlbums {
                myAlbums(order: {order_by: "title"}, onlyRoot: true, showEmpty: true) {
                    id
                    title
                    thumbnail {
                        id
                        thumbnail {
                            url
                        }
                    }
                }
            }
            """
        else:
            query = """
            query GetAlbums {
                myAlbums {
                    id
                    title
                }
            }
            """

        response = await self._graphql_request(query)
        albums = response.get("data", {}).get("myAlbums", [])
        _LOGGER.debug("Retrieved %d albums from Photoview", len(albums))
        return albums

    async def async_get_album_path(self, album_id: str) -> list[dict[str, Any]]:
        """Get the path/hierarchy for an album."""
        _LOGGER.debug("Fetching album path for: %s", album_id)

        if not self._auth_token:
            _LOGGER.debug("No auth token available, authenticating first")
            await self.async_authenticate()

        query = """
        query albumPathQuery($id: ID!) {
            album(id: $id) {
                id
                path {
                    id
                    title
                }
            }
        }
        """

        variables = {"id": album_id}
        response = await self._graphql_request(query, variables)
        album_data = response.get("data", {}).get("album", {})
        path = album_data.get("path", [])
        _LOGGER.debug("Retrieved path with %d levels for album %s",
                      len(path), album_id)
        return path

    async def async_get_album_children(self, album_id: str) -> list[dict[str, Any]]:
        """Get child albums for a given album."""
        _LOGGER.debug("Fetching child albums for: %s", album_id)

        if not self._auth_token:
            _LOGGER.debug("No auth token available, authenticating first")
            await self.async_authenticate()

        query = """
        query getAlbumChildren($id: ID!) {
            album(id: $id) {
                subAlbums {
                    id
                    title
                    thumbnail {
                        id
                        thumbnail {
                            url
                        }
                    }
                }
            }
        }
        """

        variables = {"id": album_id}
        response = await self._graphql_request(query, variables)
        album_data = response.get("data", {}).get("album", {})
        children = album_data.get("subAlbums", [])
        _LOGGER.debug("Retrieved %d child albums for album %s",
                      len(children), album_id)
        return children

    async def async_get_album_details(self, album_id: str) -> dict[str, Any]:
        """Get details for a specific album."""
        _LOGGER.debug("Fetching album details for: %s", album_id)

        if not self._auth_token:
            _LOGGER.debug("No auth token available, authenticating first")
            await self.async_authenticate()

        query = """
        query getAlbumDetails($id: ID!) {
            album(id: $id) {
                id
                title
            }
        }
        """

        variables = {"id": album_id}
        response = await self._graphql_request(query, variables)
        album_data = response.get("data", {}).get("album", {})
        _LOGGER.debug("Retrieved details for album %s: %s",
                      album_id, album_data.get("title", "Unknown"))
        return album_data

    def get_authenticated_url(self, relative_url: str) -> str:
        """Convert a relative URL to a Home Assistant proxy URL."""
        if not relative_url:
            return ""
        if relative_url.startswith("http"):
            return relative_url

        # Extract path from the relative URL (remove /api/photo/ prefix)
        photo_path = relative_url
        if photo_path.startswith("/api/photo/"):
            photo_path = photo_path[len("/api/photo/"):]
        elif photo_path.startswith("api/photo/"):
            photo_path = photo_path[len("api/photo/"):]

        # Return Home Assistant proxy URL using the generic photo endpoint
        return f"/api/photoview/photo/{photo_path}"

    async def async_get_media_url(self, media_id: str) -> str:
        """Get the full-resolution URL for a media item."""
        _LOGGER.debug("Getting media URL for: %s", media_id)

        if not self._auth_token:
            _LOGGER.debug("No auth token available, authenticating first")
            await self.async_authenticate()

        query = """
        query getMediaUrl($id: ID!) {
            media(id: $id) {
                id
                highRes {
                    url
                }
            }
        }
        """

        variables = {"id": media_id}
        response = await self._graphql_request(query, variables)
        media_data = response.get("data", {}).get("media", {})

        if media_data and media_data.get("highRes"):
            url = media_data["highRes"]["url"]
            _LOGGER.debug("Retrieved media URL for %s: %s", media_id, url)
            return url
        else:
            _LOGGER.error("No high-res URL found for media %s", media_id)
            raise Exception(f"No URL found for media {media_id}")

    async def async_get_photos(self, album_id: str | None = None) -> list[dict[str, Any]]:
        """Get photos from Photoview."""
        if album_id:
            _LOGGER.debug("Fetching photos for album: %s", album_id)
        else:
            _LOGGER.debug("Fetching all photos from Photoview")

        if not self._auth_token:
            _LOGGER.debug("No auth token available, authenticating first")
            await self.async_authenticate()

        if album_id:
            query = """
            query GetAlbumPhotos($albumId: ID!) {
                album(id: $albumId) {
                    media {
                        id
                        title
                        type
                        thumbnail {
                            url
                        }
                    }
                }
            }
            """
            variables = {"albumId": album_id}
            response = await self._graphql_request(query, variables)
            photos = response.get("data", {}).get("album", {}).get("media", [])
            _LOGGER.debug("Retrieved %d photos from album %s",
                          len(photos), album_id)
            return photos
        else:
            query = """
            query GetAllPhotos {
                myMedia {
                    id
                    title
                    type
                    thumbnail {
                        url
                    }
                }
            }
            """
            response = await self._graphql_request(query)
            photos = response.get("data", {}).get("myMedia", [])
            _LOGGER.debug("Retrieved %d photos from all media", len(photos))
            return photos

    async def async_validate_connection(self) -> bool:
        """Validate the connection to Photoview."""
        _LOGGER.debug("Validating connection to Photoview at %s",
                      self._base_url)
        try:
            await self.async_authenticate()
            _LOGGER.debug("Connection validation successful")
            return True
        except Exception as e:
            _LOGGER.error("Connection validation failed: %s", e)
            return False

    async def _graphql_request(
        self,
        query: str,
        variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a GraphQL request to Photoview."""
        url = f"{self._base_url}/api/graphql"

        _LOGGER.debug("Making GraphQL request to %s", url)
        if variables:
            _LOGGER.debug("GraphQL variables: %s", variables)

        headers = {
            "Content-Type": "application/json",
        }

        # Add auth token as cookie if available
        if self._auth_token:
            headers["Cookie"] = f"auth-token={self._auth_token}"
            _LOGGER.debug(
                "Using auth token for request (length: %d)", len(self._auth_token))
        else:
            _LOGGER.debug("No auth token available for request")

        payload = {
            "query": query,
        }

        if variables:
            payload["variables"] = variables

        try:
            async with async_timeout.timeout(10):
                _LOGGER.debug("Sending HTTP POST request to GraphQL endpoint")
                response = await self._session.request(
                    method="POST",
                    url=url,
                    headers=headers,
                    json=payload,
                )

                _LOGGER.debug(
                    "Received HTTP response with status: %d", response.status)

                if response.status in (401, 403):
                    _LOGGER.error(
                        "Authentication failed - HTTP %d", response.status)
                    raise PhotoviewApiClientAuthenticationError(
                        "Invalid credentials",
                    )

                response.raise_for_status()

                data = await response.json()
                _LOGGER.debug("GraphQL response received successfully")

                # Check for GraphQL errors
                if "errors" in data:
                    error_messages = [
                        error.get("message", "Unknown error") for error in data["errors"]]
                    _LOGGER.error(
                        "GraphQL errors in response: %s", error_messages)
                    if any("unauthorized" in msg.lower() for msg in error_messages):
                        raise PhotoviewApiClientAuthenticationError(
                            f"Authentication error: {', '.join(error_messages)}"
                        )
                    raise PhotoviewApiClientError(
                        f"GraphQL errors: {', '.join(error_messages)}"
                    )

                return data

        except asyncio.TimeoutError as exception:
            _LOGGER.error(
                "Timeout error during GraphQL request: %s", exception)
            raise PhotoviewApiClientCommunicationError(
                "Timeout error fetching information",
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            _LOGGER.error(
                "Network error during GraphQL request: %s", exception)
            raise PhotoviewApiClientCommunicationError(
                "Error fetching information",
            ) from exception
        except Exception as exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Unexpected error during GraphQL request: %s", exception)
            raise PhotoviewApiClientError(
                "Something really wrong happened!"
            ) from exception


# Legacy API Client for backward compatibility
class IntegrationBlueprintApiClient(PhotoviewApiClient):
    """Legacy API Client for backward compatibility."""

    async def async_get_data(self) -> Any:
        """Get data from the API (legacy method)."""
        return await self.async_validate_connection()

    async def async_set_title(self, value: str) -> Any:
        """Get data from the API (legacy method)."""
        # Not implemented for Photoview
        return {"status": "ok"}

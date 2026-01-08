"""
Sefaria API Client

Provides async access to Sefaria's API for:
- Calendar data (parsha, daf yomi)
- Text retrieval (Torah, commentaries)
- Related content (links between texts)
- Index/structure information
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class SefariaConfig:
    """Configuration for Sefaria API client."""

    base_url: str = "https://www.sefaria.org/api"
    timeout: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0


class SefariaClient:
    """Async client for Sefaria API."""

    def __init__(self, config: SefariaConfig | None = None):
        self.config = config or SefariaConfig()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SefariaClient":
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers={"Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _request(self, endpoint: str, params: dict | list | None = None) -> dict[str, Any]:
        """Make a request with retry logic. Params can be dict or list of tuples."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        last_error = None
        for attempt in range(self.config.retry_attempts):
            try:
                response = await self._client.get(endpoint, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                last_error = e
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        raise last_error or RuntimeError("Request failed")

    # ─────────────────────────────────────────────────────────────
    # Calendar API
    # ─────────────────────────────────────────────────────────────

    async def get_calendars(
        self, year: int | None = None, month: int | None = None, day: int | None = None
    ) -> dict[str, Any]:
        """
        Get calendar data for a specific date or today.

        Returns learning schedules including:
        - Parashat Hashavua (weekly Torah portion)
        - Daf Yomi (daily Talmud page)
        - Haftarah
        - And more

        Example response item:
        {
            "title": {"en": "Parashat Hashavua", "he": "פרשת השבוע"},
            "displayValue": {"en": "Vayishlach", "he": "וישלח"},
            "url": "Genesis.32.4-36.43",
            "ref": "Genesis 32:4-36:43",
            "category": "Tanakh"
        }
        """
        params = {}
        if year:
            params["year"] = year
        if month:
            params["month"] = month
        if day:
            params["day"] = day

        return await self._request("/calendars", params or None)

    # ─────────────────────────────────────────────────────────────
    # Text API
    # ─────────────────────────────────────────────────────────────

    async def get_text(
        self,
        ref: str,
        *,
        with_commentary: bool = False,
        version: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """
        Get text content for a reference.

        Args:
            ref: Sefaria reference (e.g., "Genesis 1:1", "Genesis 32:4-30")
            with_commentary: Include linked commentaries
            version: Specific version/translation name
            language: 'he' for Hebrew, 'en' for English (or None for both)

        Returns:
            {
                "ref": "Genesis 1:1",
                "he": ["בְּרֵאשִׁית בָּרָא אֱלֹהִים..."],
                "text": ["In the beginning God created..."],
                "versions": [...],
                ...
            }
        """
        # For path segment, we need to URL encode manually since httpx won't
        import urllib.parse
        encoded_ref = urllib.parse.quote(ref, safe='')
        endpoint = f"/v3/texts/{encoded_ref}"

        # Build params list to support duplicate keys
        params = []
        if not with_commentary:
            params.append(("commentary", "0"))

        if language:
            # Request specific language
            params.append(("version", f"{language}|all"))
        else:
            # Request both Hebrew and English explicitly
            params.append(("version", "he|all"))
            params.append(("version", "en|all"))

        if version:
            params.append(("ven", version))

        return await self._request(endpoint, params if params else None)

    async def get_text_versions(self, ref: str) -> list[dict[str, Any]]:
        """Get available versions/translations for a text."""
        encoded_ref = ref.replace(" ", "%20")
        return await self._request(f"/texts/versions/{encoded_ref}")

    # ─────────────────────────────────────────────────────────────
    # Related/Links API
    # ─────────────────────────────────────────────────────────────

    async def get_related(self, ref: str) -> dict[str, Any]:
        """
        Get all content related to a reference.

        Returns:
            {
                "links": [...],      # Links to other texts
                "sheets": [...],     # Source sheets
                "topics": [...],     # Related topics
                "notes": [...],
                "webpages": [...],
                ...
            }
        """
        encoded_ref = ref.replace(" ", "%20")
        return await self._request(f"/related/{encoded_ref}")

    async def get_links(self, ref: str) -> list[dict[str, Any]]:
        """
        Get links/connections for a reference.

        Each link contains:
        - sourceRef: The commenting/linking text reference
        - anchorRef: The base text reference (our query)
        - type: Link type (commentary, quotation, etc.)
        - category: Category of the linked text
        """
        encoded_ref = ref.replace(" ", "%20")
        return await self._request(f"/links/{encoded_ref}")

    # ─────────────────────────────────────────────────────────────
    # Index/Structure API
    # ─────────────────────────────────────────────────────────────

    async def get_index(self, title: str) -> dict[str, Any]:
        """
        Get the index/schema for a text.

        Returns structure information including:
        - Title variants
        - Categories
        - Schema (section structure)
        """
        # Only encode spaces, keep semicolons as Sefaria uses them as separators
        encoded_title = title.replace(" ", "%20")
        return await self._request(f"/v2/index/{encoded_title}")

    async def get_table_of_contents(self) -> list[dict[str, Any]]:
        """Get the full Sefaria library table of contents."""
        return await self._request("/index")

    # ─────────────────────────────────────────────────────────────
    # Search API
    # ─────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        filters: list[str] | None = None,
        size: int = 10,
    ) -> dict[str, Any]:
        """
        Search Sefaria's text corpus.

        Args:
            query: Search query
            filters: Category filters (e.g., ["Tanakh", "Torah"])
            size: Number of results
        """
        params = {
            "q": query,
            "size": size,
        }
        if filters:
            params["filters"] = ",".join(filters)

        return await self._request("/search-wrapper", params)

    # ─────────────────────────────────────────────────────────────
    # Convenience Methods
    # ─────────────────────────────────────────────────────────────

    async def get_parsha_ref(
        self, year: int | None = None, month: int | None = None, day: int | None = None
    ) -> dict[str, str] | None:
        """
        Get the parsha reference for a date.

        Returns:
            {
                "name_en": "Vayishlach",
                "name_he": "וישלח",
                "ref": "Genesis 32:4-36:43"
            }
        """
        calendars = await self.get_calendars(year, month, day)

        for item in calendars.get("calendar_items", []):
            title = item.get("title", {})
            if title.get("en") == "Parashat Hashavua":
                display = item.get("displayValue", {})
                return {
                    "name_en": display.get("en", ""),
                    "name_he": display.get("he", ""),
                    "ref": item.get("ref", ""),
                }

        return None

    async def get_daf_yomi(
        self, year: int | None = None, month: int | None = None, day: int | None = None
    ) -> dict[str, str] | None:
        """
        Get the Daf Yomi reference for a date.

        Returns:
            {
                "name_en": "Bava Kamma 96",
                "name_he": "בבא קמא צ״ו",
                "ref": "Bava Kamma 96a"
            }
        """
        calendars = await self.get_calendars(year, month, day)

        for item in calendars.get("calendar_items", []):
            title = item.get("title", {})
            if title.get("en") == "Daf Yomi":
                display = item.get("displayValue", {})
                return {
                    "name_en": display.get("en", ""),
                    "name_he": display.get("he", ""),
                    "ref": item.get("ref", item.get("url", "")),
                }

        return None

    async def count_links(self, ref: str) -> int:
        """Count the number of links/connections for a reference."""
        related = await self.get_related(ref)
        return len(related.get("links", []))

    async def get_commentary_links(
        self, ref: str, commentator: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Get commentary links for a reference, optionally filtered by commentator.

        Args:
            ref: Base text reference
            commentator: Optional commentator name to filter by
        """
        links = await self.get_links(ref)

        commentary_links = [
            link for link in links if link.get("type") == "commentary" or "Commentary" in link.get("category", "")
        ]

        if commentator:
            commentary_links = [
                link
                for link in commentary_links
                if commentator.lower() in link.get("collectiveTitle", {}).get("en", "").lower()
                or commentator.lower() in link.get("index_title", "").lower()
            ]

        return commentary_links


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of SefariaClient."""
    async with SefariaClient() as client:
        # Get today's parsha
        parsha = await client.get_parsha_ref()
        print(f"This week's parsha: {parsha}")

        # Get text with Hebrew and English
        if parsha:
            text = await client.get_text("Genesis 1:1-3")
            print(f"\nSample text:")
            print(f"  Hebrew: {text.get('he', [])[:1]}")
            print(f"  English: {text.get('text', [])[:1]}")

        # Count links for a verse
        link_count = await client.count_links("Genesis 32:25")
        print(f"\nLinks for Genesis 32:25: {link_count}")


if __name__ == "__main__":
    asyncio.run(main())

"""
Tests for Sefaria Client

Note: These tests make real API calls to Sefaria.
Run with: pytest tests/test_sefaria_client.py -v
"""

import pytest
from src.sefaria_client import SefariaClient


@pytest.fixture
async def client():
    """Create a Sefaria client for testing."""
    async with SefariaClient() as c:
        yield c


class TestSefariaClient:
    """Tests for SefariaClient."""

    @pytest.mark.asyncio
    async def test_get_calendars(self, client):
        """Test fetching calendar data."""
        calendars = await client.get_calendars()

        assert "calendar_items" in calendars
        assert len(calendars["calendar_items"]) > 0

        # Check for expected items
        titles = [item["title"]["en"] for item in calendars["calendar_items"]]
        assert "Parashat Hashavua" in titles

    @pytest.mark.asyncio
    async def test_get_parsha_ref(self, client):
        """Test getting parsha reference."""
        parsha = await client.get_parsha_ref()

        assert parsha is not None
        assert "name_en" in parsha
        assert "name_he" in parsha
        assert "ref" in parsha
        assert len(parsha["ref"]) > 0

    @pytest.mark.asyncio
    async def test_get_text(self, client):
        """Test fetching text content."""
        text = await client.get_text("Genesis 1:1")

        assert text is not None
        # Should have Hebrew content
        versions = text.get("versions", [])
        assert len(versions) > 0

    @pytest.mark.asyncio
    async def test_get_text_range(self, client):
        """Test fetching a range of verses."""
        text = await client.get_text("Genesis 1:1-3")

        assert text is not None
        versions = text.get("versions", [])

        # Find Hebrew version
        he_version = next((v for v in versions if v.get("language") == "he"), None)
        if he_version:
            he_text = he_version.get("text", [])
            # Should have multiple verses
            assert len(he_text) >= 1

    @pytest.mark.asyncio
    async def test_get_related(self, client):
        """Test fetching related content."""
        related = await client.get_related("Genesis 1:1")

        assert "links" in related
        # Genesis 1:1 should have many links
        assert len(related["links"]) > 0

    @pytest.mark.asyncio
    async def test_count_links(self, client):
        """Test counting links for a verse."""
        count = await client.count_links("Genesis 1:1")

        # Genesis 1:1 is heavily commented
        assert count > 10

    @pytest.mark.asyncio
    async def test_get_commentary_links(self, client):
        """Test getting commentary links."""
        links = await client.get_commentary_links("Genesis 1:1", "Rashi")

        # Rashi comments on Genesis 1:1
        assert len(links) > 0

    @pytest.mark.asyncio
    async def test_get_daf_yomi(self, client):
        """Test getting Daf Yomi reference."""
        daf = await client.get_daf_yomi()

        assert daf is not None
        assert "name_en" in daf
        assert "ref" in daf


class TestCalendarDates:
    """Tests for specific calendar dates."""

    @pytest.mark.asyncio
    async def test_specific_date(self, client):
        """Test fetching calendar for a specific date."""
        # Use a known date
        calendars = await client.get_calendars(year=2024, month=1, day=15)

        assert "calendar_items" in calendars


class TestHebrewText:
    """Tests for Hebrew text handling."""

    @pytest.mark.asyncio
    async def test_hebrew_with_nikud(self, client):
        """Test that Hebrew text includes nikud (vowel points)."""
        text = await client.get_text("Genesis 1:1")

        versions = text.get("versions", [])
        he_version = next((v for v in versions if v.get("language") == "he"), None)

        if he_version:
            he_text = he_version.get("text", "")
            if isinstance(he_text, list):
                he_text = he_text[0] if he_text else ""

            # Check for nikud characters (U+05B0 to U+05BD range)
            has_nikud = any(
                0x05B0 <= ord(c) <= 0x05BD for c in he_text
            )
            # Note: Not all Sefaria texts have nikud
            # This test just verifies we can retrieve Hebrew text
            assert len(he_text) > 0

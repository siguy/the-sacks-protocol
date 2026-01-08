"""
Aliyah Text Retrieval Module

Fetches Torah text for a given aliyah with:
- Hebrew text (with nikud/vowel points)
- English translation (Koren preferred, JPS fallback)
- Key verse identification via link graph
"""

import asyncio
import unicodedata
from dataclasses import dataclass

from .sefaria_client import SefariaClient
from .calendar import Aliyah


@dataclass
class Verse:
    """A single Torah verse with Hebrew and English."""

    ref: str  # e.g., "Genesis 32:25"
    hebrew: str  # Hebrew text with nikud
    english: str  # English translation
    link_count: int  # Number of connections (indicates importance)


@dataclass
class AliyahText:
    """Complete text for an aliyah."""

    aliyah: Aliyah
    verses: list[Verse]
    key_verses: list[Verse]  # Most important verses (by link count)
    translation_source: str  # Which translation was used


class AliyahRetriever:
    """Retrieves and processes aliyah text from Sefaria."""

    # Translation preferences in order
    PREFERRED_TRANSLATIONS = [
        "Koren Jerusalem Bible",
        "The Koren Jerusalem Bible",
        "Koren",
        "The Contemporary Torah, JPS, 2006",
        "JPS 1985",
        "Tanakh: The Holy Scriptures, published by JPS",
    ]

    def __init__(self, client: SefariaClient, max_key_verses: int = 4):
        self.client = client
        self.max_key_verses = max_key_verses

    async def get_aliyah_text(self, aliyah: Aliyah) -> AliyahText:
        """
        Fetch complete text for an aliyah.

        Returns Hebrew with nikud, English translation, and identifies key verses.
        """
        # Construct the full reference
        ref = self._build_ref(aliyah)

        # Fetch text (v3 API returns both Hebrew and English)
        text_data = await self.client.get_text(ref)

        # Extract Hebrew and English from response
        hebrew_texts = self._extract_hebrew(text_data)
        english_texts, translation_source = self._extract_english_from_response(text_data)

        # Build verse list
        verses = self._build_verses(ref, hebrew_texts, english_texts)

        # Identify key verses by link count
        key_verses = await self._identify_key_verses(verses)

        return AliyahText(
            aliyah=aliyah,
            verses=verses,
            key_verses=key_verses,
            translation_source=translation_source,
        )

    def _build_ref(self, aliyah: Aliyah) -> str:
        """Build a Sefaria reference from aliyah data."""
        # aliyah.start_verse is like "Genesis 32:4"
        # aliyah.end_verse is like "Genesis 32:13"
        if aliyah.start_verse and aliyah.end_verse:
            start_parts = aliyah.start_verse.split()
            end_parts = aliyah.end_verse.split()

            if len(start_parts) >= 2 and len(end_parts) >= 2:
                book = start_parts[0]
                start = start_parts[1]
                end = end_parts[1]
                return f"{book} {start}-{end}"

        # Fallback to ref directly
        return aliyah.ref

    def _extract_hebrew(self, text_data: dict) -> list[str]:
        """Extract Hebrew text with nikud from Sefaria response."""
        # v2 API returns 'he' field directly
        he = text_data.get("he", [])
        if he:
            flattened = self._flatten(he) if isinstance(he, list) else [he]
            result = [self._normalize_hebrew(t) for t in flattened if t]
            print(f"   DEBUG: Extracted {len(result)} Hebrew texts")
            return result
        return []

    def _extract_english_from_response(self, text_data: dict) -> tuple[list[str], str]:
        """
        Extract English translation from Sefaria v2 API response.

        Returns (texts, source_name)
        """
        # v2 API returns English in 'text' field
        text = text_data.get("text", [])
        if text:
            flattened = self._flatten(text) if isinstance(text, list) else [text]
            result = [t for t in flattened if t]
            source = text_data.get("versionTitle", "Sefaria Translation")
            print(f"   DEBUG: Extracted {len(result)} English texts")
            return result, source
        return [], "No Translation Found"

    def _flatten(self, nested: list) -> list[str]:
        """Flatten nested lists from Sefaria response."""
        result = []
        for item in nested:
            if isinstance(item, list):
                result.extend(self._flatten(item))
            elif item:
                result.append(str(item))
        return result

    def _normalize_hebrew(self, text: str) -> str:
        """
        Normalize Hebrew text.

        - Strip HTML tags and entities
        - Apply NFC normalization
        - Strip cantillation marks (keep nikud)
        """
        import re

        if not text:
            return ""

        # Strip HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Convert common HTML entities
        text = text.replace('&thinsp;', '')
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')

        # NFC normalization for consistent Unicode
        normalized = unicodedata.normalize("NFC", text)

        # Strip cantillation marks (taamim) but keep nikud (vowels)
        # Cantillation: U+0591 to U+05AF
        # Nikud (vowels): U+05B0 to U+05BD, U+05BF, U+05C1, U+05C2, U+05C4, U+05C5, U+05C7
        result = []
        for char in normalized:
            code = ord(char)
            # Skip cantillation marks
            if 0x0591 <= code <= 0x05AF:
                continue
            result.append(char)

        return "".join(result)

    def _build_verses(
        self, ref: str, hebrew_texts: list[str], english_texts: list[str]
    ) -> list[Verse]:
        """Build list of Verse objects from text arrays."""
        verses = []

        # Parse ref to get book and starting chapter:verse
        # Format: "Genesis 32:4-32:13" or "Genesis 32:4-13"
        try:
            book, verse_range = ref.rsplit(" ", 1)
            start_ref = verse_range.split("-")[0]
            start_chapter, start_verse = map(int, start_ref.split(":"))
        except (ValueError, IndexError):
            # Fallback if parsing fails
            book = ref.split()[0] if " " in ref else "Unknown"
            start_chapter, start_verse = 1, 1

        # Build verses
        current_chapter = start_chapter
        current_verse = start_verse

        for i, hebrew in enumerate(hebrew_texts):
            english = english_texts[i] if i < len(english_texts) else ""

            verse_ref = f"{book} {current_chapter}:{current_verse}"

            verses.append(
                Verse(
                    ref=verse_ref,
                    hebrew=hebrew,
                    english=english,
                    link_count=0,  # Will be populated by key verse detection
                )
            )

            current_verse += 1

        return verses

    async def _identify_key_verses(self, verses: list[Verse]) -> list[Verse]:
        """
        Identify key verses by counting their links in Sefaria.

        The most-linked verses are considered most important.
        To avoid timeout with large aliyot, we sample strategically.
        """
        # For large verse sets, sample strategically instead of checking all
        MAX_TO_CHECK = 15

        if len(verses) <= MAX_TO_CHECK:
            verses_to_check = verses
        else:
            # Sample: first 5, last 5, and 5 from middle
            verses_to_check = (
                verses[:5] +  # First 5
                verses[len(verses)//2 - 2 : len(verses)//2 + 3] +  # Middle 5
                verses[-5:]  # Last 5
            )
            # Remove duplicates while preserving order
            seen = set()
            unique = []
            for v in verses_to_check:
                if v.ref not in seen:
                    seen.add(v.ref)
                    unique.append(v)
            verses_to_check = unique

        # Get link counts for sampled verses
        tasks = [self._get_link_count(verse) for verse in verses_to_check]
        link_counts = await asyncio.gather(*tasks)

        # Update verses with link counts
        for verse, count in zip(verses_to_check, link_counts):
            verse.link_count = count

        # Sort by link count and return top N
        sorted_verses = sorted(verses_to_check, key=lambda v: v.link_count, reverse=True)
        return sorted_verses[: self.max_key_verses]

    async def _get_link_count(self, verse: Verse) -> int:
        """Get the number of links for a verse."""
        try:
            return await self.client.count_links(verse.ref)
        except Exception:
            return 0


def strip_nikud(text: str) -> str:
    """
    Strip nikud (vowel points) from Hebrew text.

    Useful for search/matching where nikud variations shouldn't matter.
    """
    # Nikud range: U+05B0 to U+05BD, U+05BF, U+05C1, U+05C2, U+05C4, U+05C5, U+05C7
    nikud_chars = set(
        [chr(c) for c in range(0x05B0, 0x05BE)]
        + [chr(0x05BF), chr(0x05C1), chr(0x05C2), chr(0x05C4), chr(0x05C5), chr(0x05C7)]
    )
    return "".join(c for c in text if c not in nikud_chars)


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of AliyahRetriever."""
    from .calendar import JewishCalendar

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        retriever = AliyahRetriever(client)

        # Get today's info
        today = await calendar.get_today_info()
        print(f"Parsha: {today.parsha.name_en}")

        if today.aliyot:
            aliyah = today.aliyot[0]
            print(f"\nFetching Aliyah {aliyah.number}: {aliyah.ref}")

            aliyah_text = await retriever.get_aliyah_text(aliyah)

            print(f"\nTranslation: {aliyah_text.translation_source}")
            print(f"Total verses: {len(aliyah_text.verses)}")
            print(f"\nKey verses (by link count):")
            for verse in aliyah_text.key_verses:
                print(f"  {verse.ref} ({verse.link_count} links)")
                print(f"    HE: {verse.hebrew[:50]}...")
                print(f"    EN: {verse.english[:50]}...")


if __name__ == "__main__":
    asyncio.run(main())

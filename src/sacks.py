"""
Sacks Essay Retrieval Module

Fetches Rabbi Sacks' Covenant & Conversation essays from Sefaria.
"""

import asyncio
from dataclasses import dataclass, field

from .sefaria_client import SefariaClient


@dataclass
class SacksEssay:
    """A Rabbi Sacks essay from Covenant & Conversation."""

    title: str
    sefaria_ref: str
    parsha: str
    book: str
    series: str  # e.g., "Covenant and Conversation", "Essays on Ethics"
    text: str
    hebrew_title: str = ""
    year: str = ""

    def word_count(self) -> int:
        """Return approximate word count."""
        return len(self.text.split())


@dataclass
class SacksCorpus:
    """Collection of Sacks essays for a parsha."""

    parsha: str
    essays: list[SacksEssay] = field(default_factory=list)

    def get_essay_titles(self) -> list[str]:
        """Return list of essay titles."""
        return [e.title for e in self.essays]


class SacksRetriever:
    """Retrieves Rabbi Sacks' essays from Sefaria."""

    # Sefaria paths for Sacks' works
    SACKS_COLLECTIONS = [
        "Covenant_and_Conversation",
        # Future: add more as Sefaria releases them
        # "Essays_on_Ethics",
        # "Judaism's_Life_Changing_Ideas",
    ]

    # Parsha name mappings (English to Sefaria URL format)
    PARSHA_NAMES = {
        # Genesis
        "Bereishit": "Bereshit",
        "Bereshit": "Bereshit",
        "Noach": "Noach",
        "Noah": "Noach",
        "Lech Lecha": "Lech_Lecha",
        "Lech-Lecha": "Lech_Lecha",
        "Vayera": "Vayera",
        "Chayei Sarah": "Chayei_Sara",
        "Chayei Sara": "Chayei_Sara",
        "Toldot": "Toldot",
        "Vayetze": "Vayetzei",
        "Vayetzei": "Vayetzei",
        "Vayishlach": "Vayishlach",
        "Vayeshev": "Vayeshev",
        "Miketz": "Miketz",
        "Vayigash": "Vayigash",
        "Vayechi": "Vayechi",
        # Exodus
        "Shemot": "Shemot",
        "Vaera": "Vaera",
        "Bo": "Bo",
        "Beshalach": "Beshalach",
        "Yitro": "Yitro",
        "Mishpatim": "Mishpatim",
        "Terumah": "Terumah",
        "Tetzaveh": "Tetzaveh",
        "Ki Tisa": "Ki_Tisa",
        "Ki Tissa": "Ki_Tisa",
        "Vayakhel": "Vayakhel",
        "Pekudei": "Pekudei",
        # Leviticus
        "Vayikra": "Vayikra",
        "Tzav": "Tzav",
        "Shemini": "Shemini",
        "Tazria": "Tazria",
        "Metzora": "Metzora",
        "Acharei Mot": "Achrei_Mot",
        "Achrei Mot": "Achrei_Mot",
        "Kedoshim": "Kedoshim",
        "Emor": "Emor",
        "Behar": "Behar",
        "Bechukotai": "Bechukotai",
        # Numbers
        "Bamidbar": "Bamidbar",
        "Naso": "Naso",
        "Beha'alotcha": "Behaalotcha",
        "Behaalotcha": "Behaalotcha",
        "Shelach": "Shelach",
        "Sh'lach": "Shelach",
        "Korach": "Korach",
        "Chukat": "Chukat",
        "Balak": "Balak",
        "Pinchas": "Pinchas",
        "Matot": "Matot",
        "Masei": "Masei",
        # Deuteronomy
        "Devarim": "Devarim",
        "Vaetchanan": "Vaetchanan",
        "Eikev": "Eikev",
        "Re'eh": "Reeh",
        "Reeh": "Reeh",
        "Shoftim": "Shoftim",
        "Ki Teitzei": "Ki_Teitzei",
        "Ki Tetze": "Ki_Teitzei",
        "Ki Tavo": "Ki_Tavo",
        "Nitzavim": "Nitzavim",
        "Vayelech": "Vayelech",
        "Ha'azinu": "Haazinu",
        "Haazinu": "Haazinu",
        "V'Zot HaBerachah": "Vezot_Haberakhah",
        "Vezot Haberachah": "Vezot_Haberakhah",
    }

    # Book name mappings
    BOOK_NAMES = {
        "Genesis": "Genesis",
        "Exodus": "Exodus",
        "Leviticus": "Leviticus",
        "Numbers": "Numbers",
        "Deuteronomy": "Deuteronomy",
    }

    BOOK_SUBTITLES = {
        "Genesis": "The_Book_of_the_Beginnings",
        "Exodus": "The_Book_of_Redemption",
        "Leviticus": "The_Book_of_Holiness",
        "Numbers": "The_Wilderness_Years",
        "Deuteronomy": "The_Book_of_the_Covenant",
    }

    def __init__(self, client: SefariaClient):
        self.client = client
        self._index_cache: dict[str, dict] = {}

    async def get_essays_for_parsha(self, parsha_name: str, book: str) -> SacksCorpus:
        """
        Get all available Sacks essays for a parsha.

        Args:
            parsha_name: English name of the parsha
            book: Torah book name (Genesis, Exodus, etc.)

        Returns:
            SacksCorpus with all available essays
        """
        essays = []

        # Normalize parsha name
        normalized_parsha = self.PARSHA_NAMES.get(parsha_name, parsha_name.replace(" ", "_"))
        book_subtitle = self.BOOK_SUBTITLES.get(book, "")

        # Try to get index for Covenant and Conversation
        try:
            index = await self._get_sacks_index(book)

            # Find essays for this parsha
            essay_refs = self._find_parsha_essays(index, normalized_parsha, book, book_subtitle)

            # Fetch each essay
            for ref, title in essay_refs:
                essay = await self._fetch_essay(ref, title, parsha_name, book)
                if essay:
                    essays.append(essay)

        except Exception as e:
            print(f"Warning: Could not fetch Sacks essays: {e}")

        return SacksCorpus(parsha=parsha_name, essays=essays)

    async def _get_sacks_index(self, book: str) -> dict:
        """Get the Sefaria index for Covenant and Conversation."""
        cache_key = f"Covenant_and_Conversation_{book}"

        if cache_key in self._index_cache:
            return self._index_cache[cache_key]

        # Build the index reference
        book_subtitle = self.BOOK_SUBTITLES.get(book, "")
        index_ref = f"Covenant_and_Conversation;_{book};_{book_subtitle}"

        try:
            index = await self.client.get_index(index_ref)
            self._index_cache[cache_key] = index
            return index
        except Exception:
            return {}

    def _find_parsha_essays(
        self, index: dict, parsha: str, book: str, book_subtitle: str
    ) -> list[tuple[str, str]]:
        """
        Find all essay references for a parsha in the index.

        Returns list of (sefaria_ref, title) tuples.
        """
        essays = []

        # Navigate the index schema to find parsha essays
        schema = index.get("schema", {})
        nodes = schema.get("nodes", [])

        for node in nodes:
            node_titles = node.get("titles", [])
            node_key = node.get("key", "")

            # Check if this node matches our parsha
            if self._matches_parsha(node_titles, node_key, parsha):
                # Found the parsha node - get its essays
                essay_nodes = node.get("nodes", [])

                for essay_node in essay_nodes:
                    essay_titles = essay_node.get("titles", [])
                    essay_key = essay_node.get("key", "")

                    # Get English title
                    title = self._get_english_title(essay_titles) or essay_key

                    # Normalize the essay key for URL:
                    # - Replace spaces with underscores
                    # - Keep other chars as-is, urllib.parse.quote will handle them
                    normalized_key = essay_key.replace(" ", "_")

                    # Build reference - Sefaria uses underscores not spaces
                    ref = f"Covenant_and_Conversation;_{book};_{book_subtitle},_{parsha},_{normalized_key}"
                    essays.append((ref, title))

        return essays

    def _matches_parsha(self, titles: list, key: str, parsha: str) -> bool:
        """Check if a node matches the target parsha."""
        parsha_lower = parsha.lower().replace("_", " ")

        # Check key
        if key.lower().replace("_", " ") == parsha_lower:
            return True

        # Check titles
        for title_obj in titles:
            title_text = title_obj.get("text", "").lower().replace("_", " ")
            if title_text == parsha_lower:
                return True

        return False

    def _get_english_title(self, titles: list) -> str | None:
        """Extract English title from titles array."""
        for title_obj in titles:
            if title_obj.get("lang") == "en":
                return title_obj.get("text", "")
        return None

    async def _fetch_essay(
        self, ref: str, title: str, parsha: str, book: str
    ) -> SacksEssay | None:
        """Fetch a single essay from Sefaria."""
        try:
            text_data = await self.client.get_text(ref)

            # Extract text content
            text = self._extract_essay_text(text_data)

            if not text:
                return None

            return SacksEssay(
                title=title,
                sefaria_ref=ref,
                parsha=parsha,
                book=book,
                series="Covenant and Conversation",
                text=text,
            )

        except Exception as e:
            print(f"Warning: Could not fetch essay '{title}': {e}")
            return None

    def _extract_essay_text(self, text_data: dict) -> str:
        """Extract essay text from Sefaria v2 API response."""
        # v2 API returns English in 'text' field
        text = text_data.get("text", "")
        if isinstance(text, list):
            raw = self._flatten_text(text)
        else:
            raw = str(text) if text else ""

        result = self._convert_html_to_whatsapp(raw)
        print(f"   DEBUG: Essay text length: {len(result)}")
        return result

    def _convert_html_to_whatsapp(self, text: str) -> str:
        """Convert HTML formatting to WhatsApp markdown."""
        import re

        if not text:
            return ""

        # Convert <b>...</b> to *...* (WhatsApp bold)
        text = re.sub(r'<b>([^<]+)</b>', r'*\1*', text)

        # Convert <i>...</i> to _..._ (WhatsApp italic)
        text = re.sub(r'<i>([^<]+)</i>', r'_\1_', text)

        # Convert <strong>...</strong> to *...*
        text = re.sub(r'<strong>([^<]+)</strong>', r'*\1*', text)

        # Convert <em>...</em> to _..._
        text = re.sub(r'<em>([^<]+)</em>', r'_\1_', text)

        # Remove any remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        return text.strip()

    def _flatten_text(self, nested: list, separator: str = "\n\n") -> str:
        """Flatten nested text arrays into a single string."""
        parts = []

        for item in nested:
            if isinstance(item, list):
                parts.append(self._flatten_text(item, separator="\n"))
            elif item:
                parts.append(str(item))

        return separator.join(parts)

    async def search_essays(self, query: str, parsha: str | None = None) -> list[SacksEssay]:
        """
        Search Sacks essays by keyword.

        Args:
            query: Search query
            parsha: Optional parsha to filter by
        """
        # Use Sefaria search with Sacks filter
        filters = ["Modern Commentary on Tanakh"]

        try:
            results = await self.client.search(query, filters=filters, size=20)

            essays = []
            for hit in results.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})

                # Filter to Sacks content
                if "Sacks" not in source.get("path", ""):
                    continue

                # Filter by parsha if specified
                if parsha and parsha.lower() not in source.get("path", "").lower():
                    continue

                essays.append(
                    SacksEssay(
                        title=source.get("titleVariants", ["Unknown"])[0],
                        sefaria_ref=source.get("ref", ""),
                        parsha=parsha or "Unknown",
                        book="Unknown",
                        series="Covenant and Conversation",
                        text=source.get("content", ""),
                    )
                )

            return essays

        except Exception:
            return []


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of SacksRetriever."""
    from .calendar import JewishCalendar

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        retriever = SacksRetriever(client)

        # Get today's parsha
        today = await calendar.get_today_info()
        print(f"Parsha: {today.parsha.name_en} ({today.parsha.book})")

        # Get Sacks essays
        corpus = await retriever.get_essays_for_parsha(
            today.parsha.name_en, today.parsha.book
        )

        print(f"\nFound {len(corpus.essays)} essays:")
        for essay in corpus.essays:
            print(f"\n  Title: {essay.title}")
            print(f"  Words: {essay.word_count()}")
            print(f"  Preview: {essay.text[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())

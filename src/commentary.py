"""
Commentary Selection Module

Selects traditional commentary using:
1. Link graph to identify important verses
2. Day-of-week rotation to vary commentator voice
3. Fallback logic when preferred commentator unavailable
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .sefaria_client import SefariaClient
from .calendar import DayOfWeek
from .aliyah import Verse


@dataclass
class CommentatorInfo:
    """Information about a commentator."""

    name: str
    hebrew: str
    full_name: str
    era: str


@dataclass
class Commentary:
    """A selected commentary on a verse."""

    verse: Verse  # The verse being commented on
    commentator: CommentatorInfo
    source_ref: str  # Sefaria reference for the commentary
    hebrew_text: str  # Commentary in Hebrew
    english_text: str  # Commentary in English
    selection_reason: str  # Why this commentary was chosen


class CommentarySelector:
    """Selects appropriate commentary based on day rotation and verse importance."""

    # Mapping of commentator names to their Sefaria index titles
    COMMENTATOR_SEFARIA_NAMES = {
        "Rashi": ["Rashi", "Rashi on Genesis", "Rashi on Exodus", "Rashi on Leviticus",
                  "Rashi on Numbers", "Rashi on Deuteronomy"],
        "Ramban": ["Ramban", "Ramban on Genesis", "Ramban on Exodus", "Ramban on Leviticus",
                   "Ramban on Numbers", "Ramban on Deuteronomy"],
        "Ibn Ezra": ["Ibn Ezra", "Ibn Ezra on Genesis", "Ibn Ezra on Exodus",
                    "Ibn Ezra on Leviticus", "Ibn Ezra on Numbers", "Ibn Ezra on Deuteronomy"],
        "Sforno": ["Sforno", "Sforno on Genesis", "Sforno on Exodus", "Sforno on Leviticus",
                   "Sforno on Numbers", "Sforno on Deuteronomy"],
        "Or HaChaim": ["Or HaChaim", "Or HaChaim on Genesis", "Or HaChaim on Exodus",
                       "Or HaChaim on Leviticus", "Or HaChaim on Numbers", "Or HaChaim on Deuteronomy"],
        "Sefat Emet": ["Sefat Emet", "Sefat Emet on Genesis", "Sefat Emet on Exodus"],
        "Kli Yakar": ["Kli Yakar", "Kli Yakar on Genesis", "Kli Yakar on Exodus"],
        "Kedushat Levi": ["Kedushat Levi"],
        "Bereishit Rabbah": ["Bereishit Rabbah"],
        "Shemot Rabbah": ["Shemot Rabbah"],
        "Vayikra Rabbah": ["Vayikra Rabbah"],
        "Bamidbar Rabbah": ["Bamidbar Rabbah"],
        "Devarim Rabbah": ["Devarim Rabbah"],
        "Midrash Tanchuma": ["Midrash Tanchuma"],
        "Rashbam": ["Rashbam", "Rashbam on Genesis", "Rashbam on Exodus"],
    }

    def __init__(self, client: SefariaClient, config_path: Path | None = None):
        self.client = client
        self.config = self._load_config(config_path)
        self.commentators = self._load_commentators()

    def _load_config(self, config_path: Path | None) -> dict[str, Any]:
        """Load rotation configuration from YAML file."""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "rotation.yaml"

        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f)

        # Default rotation if config not found
        return {
            "rotation": {
                0: {"primary": "Rashi", "fallback": ["Rashbam", "Ibn Ezra"], "tradition": "pshat"},
                1: {"primary": "Ramban", "fallback": ["Sforno", "Rashi"], "tradition": "philosophical"},
                2: {"primary": "Bereishit Rabbah", "fallback": ["Midrash Tanchuma", "Rashi"], "tradition": "midrash"},
                3: {"primary": "Sefat Emet", "fallback": ["Kedushat Levi", "Or HaChaim", "Rashi"], "tradition": "chassidic"},
                4: {"primary": "Ibn Ezra", "fallback": ["Sforno", "Kli Yakar", "Rashi"], "tradition": "rationalist"},
                5: {"primary": "Or HaChaim", "fallback": ["Sefat Emet", "Ramban", "Rashi"], "tradition": "mystical"},
                6: {"primary": "Rashi", "fallback": [], "tradition": "pshat"},
            }
        }

    def _load_commentators(self) -> dict[str, CommentatorInfo]:
        """Load commentator metadata."""
        config_commentators = self.config.get("commentators", {})

        commentators = {}
        for name, info in config_commentators.items():
            commentators[name] = CommentatorInfo(
                name=name,
                hebrew=info.get("hebrew", ""),
                full_name=info.get("full_name", name),
                era=info.get("era", ""),
            )

        # Add defaults for any missing
        defaults = {
            "Rashi": ("רש״י", "Rabbi Shlomo Yitzchaki", "Rishonim (1040-1105)"),
            "Ramban": ("רמב״ן", "Rabbi Moshe ben Nachman", "Rishonim (1194-1270)"),
            "Ibn Ezra": ("אבן עזרא", "Rabbi Abraham ibn Ezra", "Rishonim (1089-1167)"),
            "Sforno": ("ספורנו", "Rabbi Ovadiah Sforno", "Rishonim (1475-1550)"),
            "Or HaChaim": ("אור החיים", "Rabbi Chaim ibn Attar", "Acharonim (1696-1743)"),
            "Sefat Emet": ("שפת אמת", "Rabbi Yehudah Aryeh Leib Alter", "Chassidic (1847-1905)"),
            "Bereishit Rabbah": ("בראשית רבה", "Bereishit Rabbah", "Midrash"),
        }

        for name, (hebrew, full_name, era) in defaults.items():
            if name not in commentators:
                commentators[name] = CommentatorInfo(
                    name=name, hebrew=hebrew, full_name=full_name, era=era
                )

        return commentators

    async def select_commentary(
        self,
        key_verses: list[Verse],
        day_of_week: DayOfWeek,
        book: str,
    ) -> Commentary | None:
        """
        Select the best commentary for today's reading.

        Process:
        1. Get the rotation's preferred commentator for this day
        2. Check if they have commentary on the key verses
        3. If not, try fallbacks
        4. Return the best match
        """
        if not key_verses:
            return None

        # Get day's rotation config
        rotation = self.config.get("rotation", {}).get(day_of_week.value, {})
        primary = rotation.get("primary", "Rashi")
        fallbacks = rotation.get("fallback", ["Rashi"])
        tradition = rotation.get("tradition", "pshat")

        # Adjust midrash name based on book
        if primary.endswith("Rabbah") or primary == "Bereishit Rabbah":
            primary = self._get_midrash_for_book(book)

        # Try to find commentary
        commentator_order = [primary] + fallbacks

        for commentator_name in commentator_order:
            for verse in key_verses:
                commentary = await self._try_get_commentary(
                    verse, commentator_name, tradition
                )
                if commentary:
                    return commentary

        return None

    def _get_midrash_for_book(self, book: str) -> str:
        """Get the appropriate Midrash Rabbah for a Torah book."""
        mapping = self.config.get("midrash_by_book", {})
        return mapping.get(book, "Bereishit Rabbah")

    async def _try_get_commentary(
        self,
        verse: Verse,
        commentator_name: str,
        tradition: str,
    ) -> Commentary | None:
        """Try to get commentary from a specific commentator on a verse."""
        try:
            # Get links for this verse filtered by commentator
            links = await self.client.get_commentary_links(verse.ref, commentator_name)

            if not links:
                return None

            # Get the first matching commentary
            for link in links:
                source_ref = link.get("sourceRef", "")
                if not source_ref:
                    continue

                # Fetch the commentary text
                try:
                    text_data = await self.client.get_text(source_ref)

                    hebrew_text = self._extract_text(text_data, "he")
                    english_text = self._extract_text(text_data, "en")

                    if not hebrew_text and not english_text:
                        continue

                    # Get commentator info
                    commentator_info = self.commentators.get(
                        commentator_name,
                        CommentatorInfo(
                            name=commentator_name,
                            hebrew="",
                            full_name=commentator_name,
                            era="",
                        ),
                    )

                    return Commentary(
                        verse=verse,
                        commentator=commentator_info,
                        source_ref=source_ref,
                        hebrew_text=hebrew_text,
                        english_text=english_text,
                        selection_reason=f"Day rotation ({tradition} tradition) on key verse ({verse.link_count} links)",
                    )

                except Exception:
                    continue

        except Exception:
            pass

        return None

    def _extract_text(self, text_data: dict, language: str) -> str:
        """Extract text in specified language from Sefaria response."""
        # Try v3 versions array first
        versions = text_data.get("versions", [])
        for version in versions:
            if version.get("language") == language:
                text = version.get("text", "")
                if isinstance(text, list):
                    raw = " ".join(str(t) for t in self._flatten(text) if t)
                else:
                    raw = str(text) if text else ""
                if raw:
                    return self._convert_html_to_whatsapp(raw)

        # Fallback to legacy fields
        if language == "he":
            text = text_data.get("he", "")
        elif language == "en":
            # For English, try 'text' field first (common in v3 API)
            text = text_data.get("text", "")
            if not text:
                text = text_data.get("en", "")
        else:
            text = text_data.get("text", "")

        if isinstance(text, list):
            raw = " ".join(str(t) for t in self._flatten(text) if t)
        else:
            raw = str(text) if text else ""
        return self._convert_html_to_whatsapp(raw)

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

    def _flatten(self, nested: list) -> list:
        """Flatten nested lists."""
        result = []
        for item in nested:
            if isinstance(item, list):
                result.extend(self._flatten(item))
            else:
                result.append(item)
        return result

    def get_tradition_description(self, day_of_week: DayOfWeek) -> str:
        """Get a description of today's commentary tradition."""
        rotation = self.config.get("rotation", {}).get(day_of_week.value, {})
        tradition = rotation.get("tradition", "pshat")

        descriptions = {
            "pshat": "plain meaning - foundational interpretation",
            "philosophical": "philosophical depth - big-picture meaning",
            "midrash": "aggadic expansion - stories and homiletics",
            "chassidic": "spiritual insight - inner dimensions",
            "rationalist": "rationalist lens - grammatical and ethical",
            "mystical": "mystical dimension - hidden meanings",
        }

        return descriptions.get(tradition, tradition)


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of CommentarySelector."""
    from .calendar import JewishCalendar
    from .aliyah import AliyahRetriever

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        retriever = AliyahRetriever(client)
        selector = CommentarySelector(client)

        # Get today's info
        today = await calendar.get_today_info()
        print(f"Day: {calendar.get_day_name(today.day_of_week)}")
        print(f"Tradition: {selector.get_tradition_description(today.day_of_week)}")

        if today.aliyot:
            aliyah = today.aliyot[0]
            print(f"\nAliyah {aliyah.number}: {aliyah.ref}")

            # Get aliyah text and key verses
            aliyah_text = await retriever.get_aliyah_text(aliyah)
            print(f"Key verses: {[v.ref for v in aliyah_text.key_verses]}")

            # Select commentary
            commentary = await selector.select_commentary(
                aliyah_text.key_verses,
                today.day_of_week,
                today.parsha.book,
            )

            if commentary:
                print(f"\nSelected Commentary:")
                print(f"  Commentator: {commentary.commentator.name} ({commentary.commentator.hebrew})")
                print(f"  On verse: {commentary.verse.ref}")
                print(f"  Source: {commentary.source_ref}")
                print(f"  Reason: {commentary.selection_reason}")
                print(f"\n  Hebrew: {commentary.hebrew_text[:200]}...")
                print(f"\n  English: {commentary.english_text[:200]}...")
            else:
                print("\nNo commentary found")


if __name__ == "__main__":
    asyncio.run(main())

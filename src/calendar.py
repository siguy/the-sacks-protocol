"""
Jewish Calendar Module

Handles:
- Getting today's parsha and Hebrew date
- Mapping day of week to aliyah number
- Determining aliyah verse ranges
"""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml

from .sefaria_client import SefariaClient


def _load_aliyot_data() -> dict:
    """Load aliyah boundaries from data file."""
    data_path = Path(__file__).parent.parent / "data" / "aliyot.yaml"
    if data_path.exists():
        with open(data_path) as f:
            return yaml.safe_load(f)
    return {}


ALIYOT_DATA = _load_aliyot_data()


class DayOfWeek(IntEnum):
    """Days of the week (Python's weekday() convention)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


# Aliyah mapping by day of week
# Sunday=1, Monday=2, ..., Friday=6+7 (double for Shabbat prep)
ALIYAH_SCHEDULE = {
    DayOfWeek.SUNDAY: [1],
    DayOfWeek.MONDAY: [2],
    DayOfWeek.TUESDAY: [3],
    DayOfWeek.WEDNESDAY: [4],
    DayOfWeek.THURSDAY: [5],
    DayOfWeek.FRIDAY: [6, 7],  # Double portion - no phone on Shabbat
    DayOfWeek.SATURDAY: [7],  # Shabbat - typically not generated
}


@dataclass
class HebrewDate:
    """Hebrew date representation."""

    day: int
    month: str
    month_he: str
    year: int

    def __str__(self) -> str:
        return f"{self.day} {self.month} {self.year}"

    def hebrew(self) -> str:
        return f"{self._hebrew_day()} {self.month_he}"

    def _hebrew_day(self) -> str:
        """Convert day number to Hebrew numerals."""
        # Simplified - just return the number for now
        # Full implementation would use Hebrew numerals (גימטריא)
        return str(self.day)


@dataclass
class Parsha:
    """Torah portion (parsha) information."""

    name_en: str
    name_he: str
    ref: str  # Full parsha reference, e.g., "Genesis 32:4-36:43"
    book: str  # Torah book name


@dataclass
class Aliyah:
    """Single aliyah (Torah reading section)."""

    number: int
    ref: str  # Verse reference, e.g., "Genesis 32:4-32:13"
    start_verse: str
    end_verse: str


@dataclass
class TodayInfo:
    """Complete information for today's reading."""

    gregorian_date: date
    hebrew_date: HebrewDate | None
    day_of_week: DayOfWeek
    parsha: Parsha
    aliyot: list[Aliyah]  # The aliyah(s) for today
    is_shabbat: bool
    is_special: bool  # Holiday, Rosh Chodesh, etc.
    special_note: str | None


class JewishCalendar:
    """Jewish calendar utilities using Sefaria API."""

    def __init__(self, client: SefariaClient):
        self.client = client

    async def get_today_info(self, for_date: date | None = None) -> TodayInfo:
        """
        Get complete information for today's (or specified date's) reading.
        """
        target_date = for_date or date.today()
        day_of_week = DayOfWeek(target_date.weekday())

        # Get calendar data from Sefaria
        calendar_data = await self.client.get_calendars(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
        )

        # Extract parsha
        parsha = self._extract_parsha(calendar_data)
        if not parsha:
            raise ValueError(f"No parsha found for {target_date}")

        # Get aliyah boundaries for this parsha
        aliyah_map = await self._get_aliyah_boundaries(parsha.ref, parsha.name_en)

        # Determine which aliyot for today
        today_aliyah_nums = ALIYAH_SCHEDULE[day_of_week]
        today_aliyot = [aliyah_map[num] for num in today_aliyah_nums if num in aliyah_map]

        # Extract Hebrew date (if available in response)
        hebrew_date = self._extract_hebrew_date(calendar_data)

        return TodayInfo(
            gregorian_date=target_date,
            hebrew_date=hebrew_date,
            day_of_week=day_of_week,
            parsha=parsha,
            aliyot=today_aliyot,
            is_shabbat=day_of_week == DayOfWeek.SATURDAY,
            is_special=self._is_special_day(calendar_data),
            special_note=self._get_special_note(calendar_data),
        )

    def _extract_parsha(self, calendar_data: dict[str, Any]) -> Parsha | None:
        """Extract parsha information from calendar API response."""
        for item in calendar_data.get("calendar_items", []):
            title = item.get("title", {})
            if title.get("en") == "Parashat Hashavua":
                display = item.get("displayValue", {})
                ref = item.get("ref", "")

                # Determine book from reference
                book = self._book_from_ref(ref)

                return Parsha(
                    name_en=display.get("en", ""),
                    name_he=display.get("he", ""),
                    ref=ref,
                    book=book,
                )
        return None

    def _book_from_ref(self, ref: str) -> str:
        """Extract Torah book name from a reference."""
        book_names = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]
        for book in book_names:
            if ref.startswith(book):
                return book
        return "Unknown"

    async def _get_aliyah_boundaries(self, parsha_ref: str, parsha_name: str = "") -> dict[int, Aliyah]:
        """
        Get the verse boundaries for each aliyah in a parsha.

        Uses local data file first, then falls back to Sefaria API.
        """
        # First, try our local aliyot data file
        if ALIYOT_DATA and "aliyot" in ALIYOT_DATA:
            # Try exact match first
            parsha_data = ALIYOT_DATA["aliyot"].get(parsha_name)

            # Try common variations if exact match fails
            if not parsha_data:
                name_variations = [
                    parsha_name,
                    parsha_name.replace(" ", "_"),
                    parsha_name.replace("-", " "),
                    parsha_name.title(),
                ]
                for name in name_variations:
                    parsha_data = ALIYOT_DATA["aliyot"].get(name)
                    if parsha_data:
                        break

            if parsha_data and "aliyot" in parsha_data:
                book = parsha_data.get("book", self._book_from_ref(parsha_ref))
                return self._parse_aliyot_from_data(parsha_data["aliyot"], book)

        # Fallback: Try Sefaria's index
        try:
            index_data = await self.client.get_index(f"Parashat {parsha_name}")
            if "aliyot" in index_data:
                return self._parse_aliyot_from_index(index_data["aliyot"])
        except Exception:
            pass

        # Final fallback: estimate
        return await self._estimate_aliyot(parsha_ref)

    def _parse_aliyot_from_data(self, aliyot_dict: dict, book: str) -> dict[int, Aliyah]:
        """Parse aliyot from our local data file."""
        result = {}
        for aliyah_num, ref_str in aliyot_dict.items():
            num = int(aliyah_num)
            # ref_str is like "Exodus 3:1-3:15"
            parts = ref_str.split(" ", 1)
            if len(parts) == 2:
                ref_book = parts[0]  # "Exodus"
                verse_range = parts[1]  # "3:1-3:15"
                if "-" in verse_range:
                    start, end = verse_range.split("-")
                    # Handle formats like "3:1-3:15" or "3:1-15"
                    if ":" not in end:
                        # Same chapter, just verse number
                        start_chapter = start.split(":")[0]
                        end = f"{start_chapter}:{end}"
                else:
                    start = end = verse_range

                result[num] = Aliyah(
                    number=num,
                    ref=f"{ref_book} {start}-{end}",  # Include book name: "Exodus 3:1-3:15"
                    start_verse=f"{ref_book} {start}",
                    end_verse=f"{ref_book} {end}",
                )
        return result

    def _ref_to_parsha_name(self, ref: str) -> str:
        """
        Convert a reference like 'Genesis 32:4-36:43' to parsha name.
        This is a simplified lookup - in production we'd use a proper mapping.
        """
        # This would need a proper parsha-to-ref mapping
        # For now, return empty and rely on estimation
        return ""

    async def _estimate_aliyot(self, parsha_ref: str) -> dict[int, Aliyah]:
        """
        Estimate aliyah boundaries by dividing the parsha into 7 sections.

        This is a fallback when exact boundaries aren't available.
        """
        # Parse the reference to get chapter:verse ranges
        # Format: "Genesis 32:4-36:43"
        try:
            book, verses = parsha_ref.split(" ", 1)
            start_ref, end_ref = verses.split("-")

            start_chapter, start_verse = map(int, start_ref.split(":"))
            end_chapter, end_verse = map(int, end_ref.split(":"))

            # Get total verse count (approximate)
            total_chapters = end_chapter - start_chapter + 1

            # Simple division: allocate chapters to aliyot
            # This is a rough estimate - real aliyot follow specific rules
            aliyot = {}

            if total_chapters >= 7:
                # Distribute chapters across aliyot
                chapters_per_aliyah = total_chapters // 7
                current_chapter = start_chapter

                for i in range(1, 8):
                    aliyah_start_chapter = current_chapter
                    if i == 7:
                        aliyah_end_chapter = end_chapter
                    else:
                        aliyah_end_chapter = min(
                            current_chapter + chapters_per_aliyah - 1, end_chapter
                        )

                    # Create aliyah reference
                    if i == 1:
                        aliyah_start = f"{book} {aliyah_start_chapter}:{start_verse}"
                    else:
                        aliyah_start = f"{book} {aliyah_start_chapter}:1"

                    if i == 7:
                        aliyah_end = f"{book} {aliyah_end_chapter}:{end_verse}"
                    else:
                        # End at last verse of chapter (estimate 30)
                        aliyah_end = f"{book} {aliyah_end_chapter}:30"

                    aliyot[i] = Aliyah(
                        number=i,
                        ref=f"{aliyah_start.split()[1]}-{aliyah_end.split()[1]}",
                        start_verse=aliyah_start,
                        end_verse=aliyah_end,
                    )

                    current_chapter = aliyah_end_chapter + 1

            else:
                # Few chapters - divide verses within chapters
                # Simplified: just use the whole parsha for each aliyah estimate
                for i in range(1, 8):
                    aliyot[i] = Aliyah(
                        number=i,
                        ref=verses,
                        start_verse=f"{book} {start_ref}",
                        end_verse=f"{book} {end_ref}",
                    )

            return aliyot

        except Exception as e:
            # Return empty dict if parsing fails
            print(f"Warning: Could not parse parsha ref '{parsha_ref}': {e}")
            return {}

    def _parse_aliyot_from_index(self, aliyot_data: list) -> dict[int, Aliyah]:
        """Parse aliyot from Sefaria index data."""
        result = {}
        for i, aliyah_ref in enumerate(aliyot_data, 1):
            if isinstance(aliyah_ref, str):
                result[i] = Aliyah(
                    number=i,
                    ref=aliyah_ref,
                    start_verse=aliyah_ref.split("-")[0] if "-" in aliyah_ref else aliyah_ref,
                    end_verse=aliyah_ref.split("-")[1] if "-" in aliyah_ref else aliyah_ref,
                )
        return result

    def _extract_hebrew_date(self, calendar_data: dict[str, Any]) -> HebrewDate | None:
        """Extract Hebrew date from calendar response if available."""
        # Sefaria includes date info in the response
        if "date" in calendar_data:
            # Parse if available
            pass
        return None

    def _is_special_day(self, calendar_data: dict[str, Any]) -> bool:
        """Check if today is a special day (holiday, Rosh Chodesh, etc.)."""
        for item in calendar_data.get("calendar_items", []):
            title = item.get("title", {}).get("en", "")
            if title in ["Rosh Chodesh", "Holiday", "Fast Day"]:
                return True
        return False

    def _get_special_note(self, calendar_data: dict[str, Any]) -> str | None:
        """Get any special reading notes for today."""
        specials = []
        for item in calendar_data.get("calendar_items", []):
            title = item.get("title", {}).get("en", "")
            if title in ["Rosh Chodesh", "Holiday", "Fast Day"]:
                display = item.get("displayValue", {}).get("en", "")
                specials.append(f"{title}: {display}")
        return "; ".join(specials) if specials else None

    def get_day_name(self, day: DayOfWeek) -> str:
        """Get the English name for a day of the week."""
        names = {
            DayOfWeek.SUNDAY: "Sunday",
            DayOfWeek.MONDAY: "Monday",
            DayOfWeek.TUESDAY: "Tuesday",
            DayOfWeek.WEDNESDAY: "Wednesday",
            DayOfWeek.THURSDAY: "Thursday",
            DayOfWeek.FRIDAY: "Friday",
            DayOfWeek.SATURDAY: "Shabbat",
        }
        return names.get(day, "Unknown")

    def get_day_name_hebrew(self, day: DayOfWeek) -> str:
        """Get the Hebrew name for a day of the week."""
        names = {
            DayOfWeek.SUNDAY: "יום ראשון",
            DayOfWeek.MONDAY: "יום שני",
            DayOfWeek.TUESDAY: "יום שלישי",
            DayOfWeek.WEDNESDAY: "יום רביעי",
            DayOfWeek.THURSDAY: "יום חמישי",
            DayOfWeek.FRIDAY: "יום שישי",
            DayOfWeek.SATURDAY: "שבת",
        }
        return names.get(day, "")


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of JewishCalendar."""
    async with SefariaClient() as client:
        calendar = JewishCalendar(client)

        today = await calendar.get_today_info()

        print(f"Date: {today.gregorian_date}")
        print(f"Day: {calendar.get_day_name(today.day_of_week)}")
        print(f"Parsha: {today.parsha.name_en} ({today.parsha.name_he})")
        print(f"Full ref: {today.parsha.ref}")
        print(f"\nToday's aliyot:")
        for aliyah in today.aliyot:
            print(f"  Aliyah {aliyah.number}: {aliyah.ref}")

        if today.is_special:
            print(f"\nSpecial: {today.special_note}")


if __name__ == "__main__":
    asyncio.run(main())

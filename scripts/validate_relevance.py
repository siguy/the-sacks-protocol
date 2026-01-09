#!/usr/bin/env python3
"""
Validate Sacks Essay Relevance Selection

This script shows:
1. All essays found for this week's parasha
2. Verse references extracted from each essay
3. Relevance analysis for each day's aliyah using:
   - Verse matching (do essay verses fall in aliyah range?)
   - Thematic matching (summary comparison)
"""

import asyncio
import re
from datetime import date

# Add parent to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sefaria_client import SefariaClient
from src.calendar import JewishCalendar
from src.aliyah import AliyahRetriever
from src.sacks import SacksRetriever
from src.relevance import RelevanceScorer
from src.generator import DailyGenerator


def extract_verse_refs(text: str, book: str) -> list[tuple[int, int]]:
    """
    Extract verse references from essay text.
    Returns list of (chapter, verse) tuples.

    Patterns matched:
    - "Exodus 3:14" or "Genesis 1:1"
    - "3:14" (chapter:verse)
    - "verse 14" or "verses 1-5"
    """
    refs = []

    # Pattern 1: Full book reference "Exodus 3:14"
    book_pattern = rf'{book}\s+(\d+):(\d+)'
    for match in re.finditer(book_pattern, text, re.IGNORECASE):
        chapter, verse = int(match.group(1)), int(match.group(2))
        refs.append((chapter, verse))

    # Pattern 2: Chapter:verse without book (e.g., "3:14")
    # Only match if preceded by space/punctuation and not part of time
    cv_pattern = r'(?<![:\d])(\d{1,2}):(\d{1,2})(?!\d)'
    for match in re.finditer(cv_pattern, text):
        chapter, verse = int(match.group(1)), int(match.group(2))
        # Filter out likely times (hour > 12 or verse > 100)
        if chapter <= 50 and verse <= 100:
            refs.append((chapter, verse))

    return list(set(refs))  # Remove duplicates


def parse_aliyah_range(ref: str) -> tuple[int, int, int, int]:
    """
    Parse aliyah reference to get start/end chapter:verse.
    Returns (start_chapter, start_verse, end_chapter, end_verse)

    Examples:
    - "Exodus 3:1-3:15" -> (3, 1, 3, 15)
    - "Exodus 3:1-15" -> (3, 1, 3, 15)
    """
    # Extract verse range part after book name
    match = re.search(r'(\d+):(\d+)-(?:(\d+):)?(\d+)', ref)
    if match:
        start_ch = int(match.group(1))
        start_v = int(match.group(2))
        end_ch = int(match.group(3)) if match.group(3) else start_ch
        end_v = int(match.group(4))
        return (start_ch, start_v, end_ch, end_v)
    return (0, 0, 0, 0)


def verse_in_range(chapter: int, verse: int,
                   start_ch: int, start_v: int,
                   end_ch: int, end_v: int) -> bool:
    """Check if a verse falls within an aliyah range."""
    if chapter < start_ch or chapter > end_ch:
        return False
    if chapter == start_ch and verse < start_v:
        return False
    if chapter == end_ch and verse > end_v:
        return False
    return True


def generate_aliyah_summary(aliyah_text) -> str:
    """Generate a thematic summary of the aliyah content."""
    # Combine all English text
    all_text = " ".join(v.english for v in aliyah_text.verses if v.english)

    # Extract key themes/concepts
    themes = []

    # Character detection
    characters = ["Moses", "Moshe", "Aaron", "Pharaoh", "God", "Lord",
                  "Israel", "Israelites", "Egyptians", "midwives"]
    for char in characters:
        if char.lower() in all_text.lower():
            themes.append(char)

    # Event/concept detection
    events = [
        ("burning bush", "burning bush"),
        ("I AM", "divine name"),
        ("afraid", "fear"),
        ("holy ground", "holiness"),
        ("oppression", "slavery/oppression"),
        ("cry", "suffering"),
        ("deliver", "redemption"),
        ("signs", "miracles"),
        ("staff", "signs/wonders"),
        ("serpent", "signs/wonders"),
        ("leprosy", "signs/wonders"),
        ("blood", "plagues"),
        ("firstborn", "plague of firstborn"),
        ("passover", "Passover"),
        ("unleavened", "matzah"),
        ("sea", "splitting of sea"),
        ("song", "Song at the Sea"),
    ]
    for pattern, theme in events:
        if pattern.lower() in all_text.lower() and theme not in themes:
            themes.append(theme)

    return ", ".join(themes[:8])


def generate_essay_summary(essay) -> str:
    """Generate a thematic summary of the essay."""
    text = essay.text[:2000]  # Use first 2000 chars

    themes = []

    # Key Sacks themes
    sacks_themes = [
        ("leadership", "leadership"),
        ("freedom", "freedom"),
        ("identity", "identity"),
        ("covenant", "covenant"),
        ("faith", "faith"),
        ("fear", "fear/courage"),
        ("courage", "fear/courage"),
        ("name", "naming/identity"),
        ("call", "calling/mission"),
        ("mission", "calling/mission"),
        ("responsibility", "responsibility"),
        ("evil", "confronting evil"),
        ("justice", "justice"),
        ("compassion", "compassion"),
        ("hope", "hope"),
        ("redemption", "redemption"),
        ("transformation", "transformation"),
        ("choice", "free choice"),
    ]

    for pattern, theme in sacks_themes:
        if pattern.lower() in text.lower() and theme not in themes:
            themes.append(theme)

    return ", ".join(themes[:6])


def score_essay_for_aliyah(essay, aliyah_text, aliyah_ref: str, book: str) -> dict:
    """
    Score an essay's relevance to an aliyah using multiple methods.

    Returns dict with:
    - verse_score: Points for verse matches
    - verse_matches: List of matching verses
    - theme_score: Points for thematic overlap
    - theme_matches: Overlapping themes
    - total_score: Combined score
    """
    result = {
        "verse_score": 0,
        "verse_matches": [],
        "theme_score": 0,
        "theme_matches": [],
        "total_score": 0,
    }

    # 1. VERSE MATCHING
    essay_verses = extract_verse_refs(essay.text, book)
    start_ch, start_v, end_ch, end_v = parse_aliyah_range(aliyah_ref)

    for ch, v in essay_verses:
        if verse_in_range(ch, v, start_ch, start_v, end_ch, end_v):
            result["verse_matches"].append(f"{ch}:{v}")
            result["verse_score"] += 10  # High weight for direct verse match

    # 2. THEMATIC MATCHING
    aliyah_summary = generate_aliyah_summary(aliyah_text)
    essay_summary = generate_essay_summary(essay)

    aliyah_themes = set(t.strip().lower() for t in aliyah_summary.split(","))
    essay_themes = set(t.strip().lower() for t in essay_summary.split(","))

    overlap = aliyah_themes & essay_themes
    result["theme_matches"] = list(overlap)
    result["theme_score"] = len(overlap) * 3  # 3 points per theme match

    # 3. TITLE RELEVANCE (bonus)
    title_lower = essay.title.lower()
    for theme in aliyah_themes:
        if theme and theme in title_lower:
            result["theme_score"] += 5  # Bonus for title match
            result["theme_matches"].append(f"TITLE:{theme}")

    result["total_score"] = result["verse_score"] + result["theme_score"]
    result["aliyah_themes"] = aliyah_summary
    result["essay_themes"] = essay_summary

    return result


async def main():
    print("=" * 70)
    print("SACKS ESSAY RELEVANCE VALIDATION")
    print("(Improved: Verse Matching + Thematic Analysis)")
    print("=" * 70)

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        sacks_retriever = SacksRetriever(client)
        aliyah_retriever = AliyahRetriever(client)

        # Get this week's info (use Sunday Jan 4, 2026)
        sunday = date(2026, 1, 4)
        today_info = await calendar.get_today_info(sunday)
        parsha_obj = today_info.parsha
        parsha = parsha_obj.name_en
        book = parsha_obj.book

        print(f"\n📖 PARSHA: {parsha}")
        print(f"   Book: {book}")
        print(f"   Week of: {sunday.strftime('%B %d, %Y')}")
        print("-" * 70)

        # ═══════════════════════════════════════════════════════════════════
        # PART 1: Show all essays with verse references
        # ═══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("PART 1: ALL SACKS ESSAYS FOR THIS PARSHA")
        print("=" * 70)

        sacks_corpus = await sacks_retriever.get_essays_for_parsha(parsha, book)

        print(f"\nFound {len(sacks_corpus.essays)} essays:\n")
        for i, essay in enumerate(sacks_corpus.essays, 1):
            word_count = essay.word_count()
            verse_refs = extract_verse_refs(essay.text, book)
            themes = generate_essay_summary(essay)

            print(f"{i}. \"{essay.title}\"")
            print(f"   Words: {word_count}")
            print(f"   Verses cited: {verse_refs[:10] if verse_refs else 'None found'}")
            print(f"   Themes: {themes}")
            print()

        # ═══════════════════════════════════════════════════════════════════
        # PART 2: Run relevance analysis for each day
        # ═══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("PART 2: RELEVANCE ANALYSIS BY DAY/ALIYAH")
        print("=" * 70)

        days = [
            (date(2026, 1, 4), "Sunday", 1),
            (date(2026, 1, 5), "Monday", 2),
            (date(2026, 1, 6), "Tuesday", 3),
            (date(2026, 1, 7), "Wednesday", 4),
            (date(2026, 1, 8), "Thursday", 5),
            (date(2026, 1, 9), "Friday", "6+7"),
        ]

        for for_date, day_name, aliyah_num in days:
            print(f"\n{'─' * 70}")
            print(f"📅 {day_name} {for_date.strftime('%m/%d')} - ALIYAH {aliyah_num}")
            print("─" * 70)

            # Get this day's info
            day_info = await calendar.get_today_info(for_date)

            # Get aliyah text
            aliyah = day_info.aliyot[0]
            print(f"   Ref: {aliyah.ref}")

            aliyah_text = await aliyah_retriever.get_aliyah_text(aliyah)
            print(f"   Verses: {len(aliyah_text.verses)}")

            # Generate aliyah summary
            aliyah_summary = generate_aliyah_summary(aliyah_text)
            print(f"   Aliyah Themes: {aliyah_summary}")

            # Score each essay
            print(f"\n   ESSAY RANKING (by verse + theme matching):")
            scored = []

            for essay in sacks_corpus.essays:
                score_data = score_essay_for_aliyah(
                    essay, aliyah_text, aliyah.ref, book
                )
                scored.append((score_data["total_score"], essay, score_data))

            # Sort by total score
            scored.sort(key=lambda x: x[0], reverse=True)

            # Show all essays with detailed scoring
            for rank, (total_score, essay, data) in enumerate(scored, 1):
                indicator = "→ SELECTED" if rank == 1 else ""
                print(f"\n   {rank}. \"{essay.title}\" (total: {total_score}) {indicator}")

                if data["verse_matches"]:
                    print(f"      📍 VERSE MATCHES ({data['verse_score']} pts): {', '.join(data['verse_matches'])}")
                else:
                    print(f"      📍 Verse matches: None")

                if data["theme_matches"]:
                    print(f"      🎯 THEME MATCHES ({data['theme_score']} pts): {', '.join(data['theme_matches'])}")
                else:
                    print(f"      🎯 Theme matches: None")

                print(f"      Essay themes: {data['essay_themes']}")

        print("\n" + "=" * 70)
        print("VALIDATION COMPLETE")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

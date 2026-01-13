#!/usr/bin/env python3
"""
Weekly Pre-computation Script

Run this at the beginning of each week (or when parsha changes) to:
1. Fetch all essays for the parsha from Sefaria
2. Fetch all 7 aliyah texts with full verses
3. Pre-select commentary for each day based on rotation
4. Run greedy matching to assign essays to aliyot
5. Generate Gemini summaries for each assigned essay
6. Cache everything for fully offline daily generation

Usage:
    python3 scripts/prepare_week.py [parsha_name]

If no parsha_name is provided, uses the current week's parsha.
"""

import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.sefaria_client import SefariaClient
from src.calendar import JewishCalendar, Aliyah, DayOfWeek, ALIYOT_DATA
from src.aliyah import AliyahRetriever, AliyahText, Verse
from src.commentary import CommentarySelector, Commentary
from src.sacks import SacksRetriever
from src.relevance import RelevanceScorer
from src.formatter import OutputFormatter


CACHE_DIR = Path(__file__).parent.parent / "data" / "weekly_cache"


def serialize_verse(verse: Verse) -> dict:
    """Convert Verse object to JSON-serializable dict."""
    return {
        "ref": verse.ref,
        "hebrew": verse.hebrew,
        "english": verse.english,
        "link_count": verse.link_count,
    }


def serialize_aliyah_text(aliyah_text: AliyahText) -> dict:
    """Convert AliyahText object to JSON-serializable dict."""
    return {
        "aliyah": {
            "number": aliyah_text.aliyah.number,
            "ref": aliyah_text.aliyah.ref,
            "start_verse": aliyah_text.aliyah.start_verse,
            "end_verse": aliyah_text.aliyah.end_verse,
        },
        "verses": [serialize_verse(v) for v in aliyah_text.verses],
        "key_verses": [serialize_verse(v) for v in aliyah_text.key_verses],
        "translation_source": aliyah_text.translation_source,
    }


def serialize_commentary(commentary: Commentary) -> dict:
    """Convert Commentary object to JSON-serializable dict."""
    return {
        "verse": serialize_verse(commentary.verse),
        "commentator": {
            "name": commentary.commentator.name,
            "hebrew": commentary.commentator.hebrew,
            "full_name": commentary.commentator.full_name,
            "era": commentary.commentator.era,
        },
        "source_ref": commentary.source_ref,
        "hebrew_text": commentary.hebrew_text,
        "english_text": commentary.english_text,
        "selection_reason": commentary.selection_reason,
    }


async def fetch_all_aliyah_texts(
    parsha_name: str,
    book: str,
    aliyah_retriever: AliyahRetriever,
) -> tuple[dict[int, dict], dict[int, AliyahText]]:
    """Fetch all 7 aliyah texts and return both serializable data and objects."""
    print(f"\n📖 Fetching all 7 aliyah texts for {parsha_name}...")

    # Get aliyah refs from ALIYOT_DATA
    parsha_data = None
    if ALIYOT_DATA and "aliyot" in ALIYOT_DATA:
        parsha_data = ALIYOT_DATA["aliyot"].get(parsha_name)
        if not parsha_data:
            for name in [parsha_name.replace(" ", "_"), parsha_name.title()]:
                parsha_data = ALIYOT_DATA["aliyot"].get(name)
                if parsha_data:
                    break

    if not parsha_data or "aliyot" not in parsha_data:
        print(f"   ❌ No aliyah data found for {parsha_name}")
        return {}, {}

    aliyah_refs = parsha_data["aliyot"]
    serialized_texts = {}
    aliyah_text_objects = {}

    for aliyah_num in range(1, 8):
        ref = aliyah_refs.get(aliyah_num, "")
        if not ref:
            continue

        aliyah = Aliyah(
            number=aliyah_num,
            ref=ref,
            start_verse=ref.split("-")[0] if "-" in ref else ref,
            end_verse=ref.split("-")[1] if "-" in ref else ref,
        )

        try:
            text = await aliyah_retriever.get_aliyah_text(aliyah)
            aliyah_text_objects[aliyah_num] = text
            serialized_texts[aliyah_num] = serialize_aliyah_text(text)
            print(f"   ✅ Aliyah {aliyah_num}: {len(text.verses)} verses, {len(text.key_verses)} key verses")
        except Exception as e:
            print(f"   ❌ Aliyah {aliyah_num}: {e}")

    return serialized_texts, aliyah_text_objects


async def fetch_all_commentary(
    aliyah_text_objects: dict[int, AliyahText],
    book: str,
    commentary_selector: CommentarySelector,
) -> dict[int, dict | None]:
    """Pre-select commentary for each aliyah based on day-of-week rotation."""
    print(f"\n📜 Pre-selecting commentary for each day...")

    # Day-of-week to aliyah mapping:
    # Sunday (0) -> Aliyah 1, Monday (1) -> Aliyah 2, etc.
    # Friday (5) -> Aliyot 6+7
    day_to_aliyah = {
        0: [1],      # Sunday
        1: [2],      # Monday
        2: [3],      # Tuesday
        3: [4],      # Wednesday
        4: [5],      # Thursday
        5: [6, 7],   # Friday
        6: [1],      # Shabbat (fallback to 1)
    }

    commentary_cache = {}

    for day_num in range(6):  # Sunday through Friday
        day_of_week = DayOfWeek(day_num)
        aliyah_nums = day_to_aliyah[day_num]

        # Get key verses from the relevant aliyah(s)
        key_verses = []
        for aliyah_num in aliyah_nums:
            if aliyah_num in aliyah_text_objects:
                key_verses.extend(aliyah_text_objects[aliyah_num].key_verses)

        if not key_verses:
            print(f"   Day {day_num}: No key verses available")
            commentary_cache[day_num] = None
            continue

        # Sort by link count and take top ones
        key_verses.sort(key=lambda v: v.link_count, reverse=True)
        key_verses = key_verses[:4]

        try:
            commentary = await commentary_selector.select_commentary(
                key_verses, day_of_week, book
            )
            if commentary:
                commentary_cache[day_num] = serialize_commentary(commentary)
                print(f"   ✅ Day {day_num} ({day_of_week.name}): {commentary.commentator.name} on {commentary.verse.ref}")
            else:
                commentary_cache[day_num] = None
                print(f"   ⚠️  Day {day_num} ({day_of_week.name}): No commentary found")
        except Exception as e:
            print(f"   ❌ Day {day_num}: Error - {e}")
            commentary_cache[day_num] = None

    return commentary_cache


async def generate_essay_summaries(
    essay_title: str,
    essay_text: str,
    formatter: OutputFormatter,
) -> dict[str, str]:
    """Generate the 4-part summary for an essay using Gemini."""
    from src.sacks import SacksEssay

    # Create a minimal SacksEssay object for the formatter
    essay = SacksEssay(
        title=essay_title,
        text=essay_text,
        parsha="",
        series="",
        sefaria_ref="",
    )

    sections = await formatter._extract_essay_sections_with_llm(essay)
    return sections


async def prepare_week(parsha_name: str | None = None):
    """Main weekly pre-computation function."""
    print("=" * 60)
    print("THE SACKS PROTOCOL - Weekly Pre-computation")
    print("=" * 60)

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        aliyah_retriever = AliyahRetriever(client)
        commentary_selector = CommentarySelector(client)
        sacks_retriever = SacksRetriever(client)
        relevance_scorer = RelevanceScorer()
        formatter = OutputFormatter()

        # 1. Get parsha info
        if parsha_name:
            print(f"\n📅 Using specified parsha: {parsha_name}")
            # Look up book from aliyot data
            parsha_data = ALIYOT_DATA["aliyot"].get(parsha_name)
            if not parsha_data:
                print(f"❌ Unknown parsha: {parsha_name}")
                return
            book = parsha_data.get("book", "Genesis")
        else:
            print("\n📅 Getting current parsha...")
            today_info = await calendar.get_today_info()
            parsha_name = today_info.parsha.name_en
            book = today_info.parsha.book

        print(f"   Parsha: {parsha_name}")
        print(f"   Book: {book}")

        # 2. Fetch all aliyah texts (full verses)
        serialized_texts, aliyah_text_objects = await fetch_all_aliyah_texts(
            parsha_name, book, aliyah_retriever
        )

        if not aliyah_text_objects:
            print("❌ Could not fetch aliyah texts")
            return

        # 3. Pre-select commentary for each day
        commentary_cache = await fetch_all_commentary(
            aliyah_text_objects, book, commentary_selector
        )

        # 4. Fetch essays
        print(f"\n✡️ Fetching Sacks essays...")
        sacks_corpus = await sacks_retriever.get_essays_for_parsha(parsha_name, book)
        print(f"   Found {len(sacks_corpus.essays)} essays:")
        for essay in sacks_corpus.essays:
            print(f"      - \"{essay.title}\"")

        assignments_data = {}

        if not sacks_corpus.essays:
            print("   No essays found for this parsha")
        else:
            # 5. Run greedy matching
            print(f"\n🎯 Computing essay-aliyah assignments...")
            weekly_assignments = relevance_scorer.compute_weekly_assignments(
                essays=sacks_corpus.essays,
                aliyah_texts=aliyah_text_objects,
                book=book,
                threshold=6,
            )

            # 6. Generate summaries for assigned essays
            print(f"\n✨ Generating essay summaries with Gemini...")

            for aliyah_num in range(1, 8):
                assignment = weekly_assignments.get(aliyah_num)

                if assignment:
                    essay, score_data = assignment
                    print(f"\n   Aliyah {aliyah_num}: \"{essay.title}\"")
                    print(f"      Generating 4-part summary...")

                    try:
                        sections = await generate_essay_summaries(
                            essay.title, essay.text, formatter
                        )

                        assignments_data[aliyah_num] = {
                            "essay_title": essay.title,
                            "essay_sefaria_ref": essay.sefaria_ref,
                            "score_data": score_data,
                            "sections": sections,
                        }

                        print(f"      ✅ Generated summaries:")
                        for key in ["question", "turn", "insight", "call"]:
                            if key in sections:
                                preview = sections[key][:60] + "..." if len(sections[key]) > 60 else sections[key]
                                print(f"         {key.upper()}: {preview}")

                    except Exception as e:
                        print(f"      ❌ Error generating summaries: {e}")
                        assignments_data[aliyah_num] = {
                            "essay_title": essay.title,
                            "essay_sefaria_ref": essay.sefaria_ref,
                            "score_data": score_data,
                            "sections": None,
                            "error": str(e),
                        }
                else:
                    print(f"\n   Aliyah {aliyah_num}: NO ESSAY")
                    assignments_data[aliyah_num] = None

        # 7. Save cache
        cache_data = {
            "parsha": parsha_name,
            "book": book,
            "computed_at": datetime.now().isoformat(),
            "week_of": date.today().isoformat(),
            "essays_found": len(sacks_corpus.essays) if sacks_corpus.essays else 0,
            "essay_titles": [e.title for e in sacks_corpus.essays] if sacks_corpus.essays else [],
            "aliyot": serialized_texts,
            "commentary": commentary_cache,
            "assignments": assignments_data,
        }

        _save_cache(parsha_name, cache_data)

        # Summary
        print("\n" + "=" * 60)
        print("WEEKLY PREP COMPLETE")
        print("=" * 60)
        assigned_count = sum(1 for a in assignments_data.values() if a is not None)
        commentary_count = sum(1 for c in commentary_cache.values() if c is not None)
        print(f"\n   Parsha: {parsha_name}")
        print(f"   Aliyot cached: {len(serialized_texts)}/7")
        print(f"   Commentary cached: {commentary_count}/6 days")
        print(f"   Essays found: {len(sacks_corpus.essays) if sacks_corpus.essays else 0}")
        print(f"   Essays assigned: {assigned_count}/7 aliyot")
        print(f"\n   Cache saved to: data/weekly_cache/{_cache_filename(parsha_name)}")
        print("\n   Daily generation will now run FULLY OFFLINE!")


def _cache_filename(parsha_name: str) -> str:
    """Generate cache filename for a parsha."""
    slug = parsha_name.lower().replace(" ", "_").replace("-", "_")
    return f"{slug}.json"


def _save_cache(parsha_name: str, cache_data: dict):
    """Save cache data to file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filepath = CACHE_DIR / _cache_filename(parsha_name)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Cache saved: {filepath}")


def load_weekly_cache(parsha_name: str) -> dict | None:
    """Load cached weekly data for a parsha."""
    filepath = CACHE_DIR / _cache_filename(parsha_name)

    if not filepath.exists():
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    parsha = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(prepare_week(parsha))

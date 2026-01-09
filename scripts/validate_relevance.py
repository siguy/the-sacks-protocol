#!/usr/bin/env python3
"""
Validate Sacks Essay Relevance Selection - Weekly Matching

This script:
1. Scores ALL essays against ALL aliyot (matrix)
2. Greedily assigns essays to aliyot (highest score wins, each essay used once)
3. Shows which days get essays and which don't
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


def extract_verse_refs(text: str, book: str) -> list[tuple[int, int]]:
    """
    Extract verse references from essay text.
    Returns list of (chapter, verse) tuples.
    """
    refs = []

    # Pattern 1: Full book reference "Exodus 3:14"
    book_pattern = rf'{book}\s+(\d+):(\d+)'
    for match in re.finditer(book_pattern, text, re.IGNORECASE):
        chapter, verse = int(match.group(1)), int(match.group(2))
        refs.append((chapter, verse))

    # Pattern 2: Chapter:verse without book (e.g., "3:14")
    cv_pattern = r'(?<![:\d])(\d{1,2}):(\d{1,2})(?!\d)'
    for match in re.finditer(cv_pattern, text):
        chapter, verse = int(match.group(1)), int(match.group(2))
        if chapter <= 50 and verse <= 100:
            refs.append((chapter, verse))

    return list(set(refs))


def parse_aliyah_range(ref: str) -> tuple[int, int, int, int]:
    """Parse aliyah reference to get start/end chapter:verse."""
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


def generate_aliyah_themes(aliyah_text) -> set[str]:
    """Generate theme set from aliyah content."""
    all_text = " ".join(v.english for v in aliyah_text.verses if v.english).lower()

    themes = set()

    # Characters
    for char in ["moses", "aaron", "pharaoh", "god", "lord", "israel", "midwives"]:
        if char in all_text:
            themes.add(char)

    # Events/concepts
    concept_map = {
        "burning bush": "burning bush",
        "i am": "divine name",
        "afraid": "fear",
        "holy ground": "holiness",
        "oppression": "oppression",
        "cry": "suffering",
        "deliver": "redemption",
        "signs": "signs",
        "staff": "signs",
        "serpent": "signs",
        "blood": "plagues",
        "firstborn": "firstborn",
        "passover": "passover",
        "sea": "sea",
        "song": "song",
        "slave": "slavery",
        "birth": "birth",
        "hide": "hiding",
        "basket": "rescue",
        "daughter": "compassion",
        "kill": "violence",
        "flee": "exile",
        "shepherd": "shepherd",
    }
    for pattern, theme in concept_map.items():
        if pattern in all_text:
            themes.add(theme)

    return themes


def generate_essay_themes(essay) -> set[str]:
    """Generate theme set from essay text."""
    text = essay.text[:3000].lower()

    themes = set()

    # Key Sacks themes
    theme_map = {
        "leadership": "leadership",
        "freedom": "freedom",
        "identity": "identity",
        "covenant": "covenant",
        "faith": "faith",
        "fear": "fear",
        "courage": "courage",
        "name": "name",
        "call": "calling",
        "mission": "mission",
        "responsibility": "responsibility",
        "evil": "evil",
        "justice": "justice",
        "compassion": "compassion",
        "hope": "hope",
        "redemption": "redemption",
        "transformation": "transformation",
        "choice": "choice",
        "moses": "moses",
        "pharaoh": "pharaoh",
        "burning bush": "burning bush",
        "slave": "slavery",
        "oppression": "oppression",
        "midwives": "midwives",
    }

    for pattern, theme in theme_map.items():
        if pattern in text:
            themes.add(theme)

    return themes


def score_essay_for_aliyah(essay, aliyah_text, aliyah_ref: str, book: str) -> dict:
    """Score an essay's relevance to an aliyah."""
    result = {
        "verse_score": 0,
        "verse_matches": [],
        "theme_score": 0,
        "theme_matches": [],
        "total_score": 0,
    }

    # 1. VERSE MATCHING (10 pts each)
    essay_verses = extract_verse_refs(essay.text, book)
    start_ch, start_v, end_ch, end_v = parse_aliyah_range(aliyah_ref)

    for ch, v in essay_verses:
        if verse_in_range(ch, v, start_ch, start_v, end_ch, end_v):
            result["verse_matches"].append(f"{ch}:{v}")
            result["verse_score"] += 10

    # 2. THEMATIC MATCHING (3 pts each)
    aliyah_themes = generate_aliyah_themes(aliyah_text)
    essay_themes = generate_essay_themes(essay)

    overlap = aliyah_themes & essay_themes
    result["theme_matches"] = list(overlap)
    result["theme_score"] = len(overlap) * 3

    # 3. TITLE BONUS (5 pts per theme in title)
    title_lower = essay.title.lower()
    for theme in aliyah_themes:
        if theme in title_lower:
            result["theme_score"] += 5
            result["theme_matches"].append(f"TITLE:{theme}")

    result["total_score"] = result["verse_score"] + result["theme_score"]
    return result


def greedy_match(score_matrix: dict) -> dict:
    """
    Greedy matching algorithm.

    Args:
        score_matrix: {aliyah_num: {essay_title: score_data}}

    Returns:
        {aliyah_num: (essay_title, score_data) or None}
    """
    # Flatten to list of (score, aliyah_num, essay_title, score_data)
    all_scores = []
    for aliyah_num, essays in score_matrix.items():
        for essay_title, score_data in essays.items():
            all_scores.append((
                score_data["total_score"],
                aliyah_num,
                essay_title,
                score_data
            ))

    # Sort by score descending
    all_scores.sort(key=lambda x: x[0], reverse=True)

    # Greedy assignment
    assigned_aliyot = {}
    used_essays = set()

    for score, aliyah_num, essay_title, score_data in all_scores:
        # Skip if aliyah already has an essay or essay already used
        if aliyah_num in assigned_aliyot:
            continue
        if essay_title in used_essays:
            continue
        # Skip if score is 0 (no match)
        if score == 0:
            continue

        assigned_aliyot[aliyah_num] = (essay_title, score_data)
        used_essays.add(essay_title)

    return assigned_aliyot


async def main():
    print("=" * 70)
    print("SACKS ESSAY RELEVANCE - WEEKLY MATCHING")
    print("(Greedy Assignment: Each essay used at most once)")
    print("=" * 70)

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        sacks_retriever = SacksRetriever(client)
        aliyah_retriever = AliyahRetriever(client)

        # Get this week's info
        sunday = date(2026, 1, 4)
        today_info = await calendar.get_today_info(sunday)
        parsha_obj = today_info.parsha
        parsha = parsha_obj.name_en
        book = parsha_obj.book

        print(f"\n📖 PARSHA: {parsha}")
        print(f"   Book: {book}")
        print("-" * 70)

        # ═══════════════════════════════════════════════════════════════════
        # STEP 1: Fetch all essays
        # ═══════════════════════════════════════════════════════════════════
        print("\n📚 FETCHING ESSAYS...")
        sacks_corpus = await sacks_retriever.get_essays_for_parsha(parsha, book)
        essays = {e.title: e for e in sacks_corpus.essays}
        print(f"   Found {len(essays)} essays:")
        for title in essays:
            print(f"   • {title}")

        # ═══════════════════════════════════════════════════════════════════
        # STEP 2: Fetch all aliyot and build score matrix
        # ═══════════════════════════════════════════════════════════════════
        print("\n📊 BUILDING SCORE MATRIX (Essays × Aliyot)...")

        days = [
            (date(2026, 1, 4), "Sunday", 1),
            (date(2026, 1, 5), "Monday", 2),
            (date(2026, 1, 6), "Tuesday", 3),
            (date(2026, 1, 7), "Wednesday", 4),
            (date(2026, 1, 8), "Thursday", 5),
            (date(2026, 1, 9), "Friday", 6),  # Using aliyah 6 for Friday
        ]

        aliyah_data = {}  # aliyah_num -> (day_name, aliyah, aliyah_text)
        score_matrix = {}  # aliyah_num -> {essay_title: score_data}

        for for_date, day_name, aliyah_num in days:
            day_info = await calendar.get_today_info(for_date)
            aliyah = day_info.aliyot[0]
            aliyah_text = await aliyah_retriever.get_aliyah_text(aliyah)

            aliyah_data[aliyah_num] = (day_name, aliyah, aliyah_text)
            score_matrix[aliyah_num] = {}

            for essay_title, essay in essays.items():
                score_data = score_essay_for_aliyah(
                    essay, aliyah_text, aliyah.ref, book
                )
                score_matrix[aliyah_num][essay_title] = score_data

        # ═══════════════════════════════════════════════════════════════════
        # STEP 3: Display score matrix
        # ═══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("SCORE MATRIX")
        print("=" * 70)

        # Header
        essay_titles = list(essays.keys())
        short_titles = [t[:25] + "..." if len(t) > 25 else t for t in essay_titles]

        print(f"\n{'Aliyah':<12}", end="")
        for st in short_titles:
            print(f"{st:<30}", end="")
        print()
        print("-" * (12 + 30 * len(essays)))

        for aliyah_num in sorted(score_matrix.keys()):
            day_name = aliyah_data[aliyah_num][0]
            print(f"{aliyah_num} ({day_name[:3]})", end="   ")
            for essay_title in essay_titles:
                score = score_matrix[aliyah_num][essay_title]["total_score"]
                verse_ct = len(score_matrix[aliyah_num][essay_title]["verse_matches"])
                theme_ct = len(score_matrix[aliyah_num][essay_title]["theme_matches"])
                print(f"{score:3d} (v:{verse_ct} t:{theme_ct})           ", end="")
            print()

        # ═══════════════════════════════════════════════════════════════════
        # STEP 4: Run greedy matching
        # ═══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("GREEDY MATCHING RESULTS")
        print("=" * 70)

        assignments = greedy_match(score_matrix)

        print(f"\n📋 ASSIGNMENTS:\n")
        for aliyah_num in sorted(aliyah_data.keys()):
            day_name, aliyah, aliyah_text = aliyah_data[aliyah_num]

            if aliyah_num in assignments:
                essay_title, score_data = assignments[aliyah_num]
                print(f"✅ Aliyah {aliyah_num} ({day_name}): \"{essay_title}\"")
                print(f"   Score: {score_data['total_score']}")
                if score_data["verse_matches"]:
                    print(f"   📍 Verses: {', '.join(score_data['verse_matches'])}")
                if score_data["theme_matches"]:
                    print(f"   🎯 Themes: {', '.join(score_data['theme_matches'][:5])}")
            else:
                print(f"❌ Aliyah {aliyah_num} ({day_name}): NO ESSAY")
                print(f"   DEBUG: No essay matched this aliyah")
            print()

        # ═══════════════════════════════════════════════════════════════════
        # STEP 5: Summary
        # ═══════════════════════════════════════════════════════════════════
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        matched = len(assignments)
        total = len(aliyah_data)
        unmatched = [a for a in aliyah_data if a not in assignments]

        print(f"\n📊 {matched}/{total} days have essay matches")
        if unmatched:
            unmatched_days = [aliyah_data[a][0] for a in unmatched]
            print(f"⚠️  Days without essays: {', '.join(unmatched_days)}")
            print(f"   (These days will need fallback content)")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

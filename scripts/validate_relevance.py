#!/usr/bin/env python3
"""
Validate Sacks Essay Relevance Selection

This script shows:
1. All essays found for this week's parasha
2. Relevance analysis for each day's aliyah (Sunday-Friday)
"""

import asyncio
from datetime import date, timedelta

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


async def main():
    print("=" * 70)
    print("SACKS ESSAY RELEVANCE VALIDATION")
    print("=" * 70)

    async with SefariaClient() as client:
        calendar = JewishCalendar(client)
        sacks_retriever = SacksRetriever(client)
        aliyah_retriever = AliyahRetriever(client)
        relevance_scorer = RelevanceScorer()
        generator = DailyGenerator()

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
        # PART 1: Show all essays for this parsha
        # ═══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("PART 1: ALL SACKS ESSAYS FOR THIS PARSHA")
        print("=" * 70)

        sacks_corpus = await sacks_retriever.get_essays_for_parsha(parsha, book)

        print(f"\nFound {len(sacks_corpus.essays)} essays:\n")
        for i, essay in enumerate(sacks_corpus.essays, 1):
            word_count = essay.word_count()
            # Show first 150 chars of essay
            preview = essay.text[:150].replace('\n', ' ')
            print(f"{i}. \"{essay.title}\"")
            print(f"   Series: {essay.series}")
            print(f"   Words: {word_count}")
            print(f"   Preview: {preview}...")
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

            # Show key verses (first 3)
            print(f"\n   Key Verse Samples:")
            for v in aliyah_text.verses[:3]:
                eng_preview = v.english[:80] + "..." if len(v.english) > 80 else v.english
                print(f"   • {v.ref}: {eng_preview}")

            # Extract keywords from aliyah
            keywords = generator._extract_keywords(aliyah_text)
            print(f"\n   Extracted Keywords: {keywords}")

            # Run relevance scoring
            print(f"\n   ESSAY RANKING:")

            # Score each essay
            scored = []
            keywords_lower = [kw.lower() for kw in keywords]

            for essay in sacks_corpus.essays:
                score = 0
                title_lower = essay.title.lower()
                text_start = essay.text[:500].lower()
                matches = []

                for kw in keywords_lower:
                    if kw in title_lower:
                        score += 3
                        matches.append(f"title:{kw}")
                    if kw in text_start:
                        score += 1
                        matches.append(f"text:{kw}")

                scored.append((score, essay, matches))

            # Sort by score
            scored.sort(key=lambda x: x[0], reverse=True)

            # Show all essays with scores
            for rank, (score, essay, matches) in enumerate(scored, 1):
                indicator = "→ SELECTED" if rank == 1 else ""
                print(f"   {rank}. \"{essay.title}\" (score: {score}) {indicator}")
                if matches:
                    print(f"      Matches: {', '.join(matches[:6])}")

        print("\n" + "=" * 70)
        print("VALIDATION COMPLETE")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

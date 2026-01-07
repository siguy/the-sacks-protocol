#!/usr/bin/env python3
"""
Pre-compute Relevance Scores

One-time script to compute relevance scores for all Sacks essays
against all aliyot. Results are saved to data/relevance/{parsha}.yaml

Usage:
    python scripts/compute_relevance.py --parsha "Vayishlach"
    python scripts/compute_relevance.py --all
    python scripts/compute_relevance.py --next-month

Requires ANTHROPIC_API_KEY environment variable.
Estimated cost: ~$0.75 for all parshiyot
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sefaria_client import SefariaClient
from src.calendar import JewishCalendar
from src.aliyah import AliyahRetriever
from src.sacks import SacksRetriever
from src.relevance import RelevanceScorer


# All parsha names in order
ALL_PARSHIYOT = [
    # Genesis
    "Bereishit", "Noach", "Lech Lecha", "Vayera", "Chayei Sarah",
    "Toldot", "Vayetzei", "Vayishlach", "Vayeshev", "Miketz",
    "Vayigash", "Vayechi",
    # Exodus
    "Shemot", "Vaera", "Bo", "Beshalach", "Yitro", "Mishpatim",
    "Terumah", "Tetzaveh", "Ki Tisa", "Vayakhel", "Pekudei",
    # Leviticus
    "Vayikra", "Tzav", "Shemini", "Tazria", "Metzora",
    "Acharei Mot", "Kedoshim", "Emor", "Behar", "Bechukotai",
    # Numbers
    "Bamidbar", "Naso", "Behaalotcha", "Shelach", "Korach",
    "Chukat", "Balak", "Pinchas", "Matot", "Masei",
    # Deuteronomy
    "Devarim", "Vaetchanan", "Eikev", "Re'eh", "Shoftim",
    "Ki Teitzei", "Ki Tavo", "Nitzavim", "Vayelech", "Haazinu",
    "Vezot Haberachah",
]

PARSHA_TO_BOOK = {
    # Genesis
    **{p: "Genesis" for p in ALL_PARSHIYOT[:12]},
    # Exodus
    **{p: "Exodus" for p in ALL_PARSHIYOT[12:23]},
    # Leviticus
    **{p: "Leviticus" for p in ALL_PARSHIYOT[23:32]},
    # Numbers
    **{p: "Numbers" for p in ALL_PARSHIYOT[32:42]},
    # Deuteronomy
    **{p: "Deuteronomy" for p in ALL_PARSHIYOT[42:]},
}


async def compute_for_parsha(parsha: str, client: SefariaClient) -> bool:
    """Compute relevance scores for a single parsha."""
    book = PARSHA_TO_BOOK.get(parsha)
    if not book:
        print(f"❌ Unknown parsha: {parsha}")
        return False

    print(f"\n{'='*50}")
    print(f"Processing: {parsha} ({book})")
    print(f"{'='*50}")

    aliyah_retriever = AliyahRetriever(client)
    sacks_retriever = SacksRetriever(client)
    relevance_scorer = RelevanceScorer()

    # Check if already computed
    existing = relevance_scorer.load_relevance_data(parsha)
    if existing:
        print(f"⏭️  Already computed ({len(existing)} essays). Skipping.")
        return True

    # Get Sacks essays
    print("📚 Fetching Sacks essays...")
    corpus = await sacks_retriever.get_essays_for_parsha(parsha, book)

    if not corpus.essays:
        print("⚠️  No essays found for this parsha")
        return False

    print(f"   Found {len(corpus.essays)} essays")

    # Get aliyah texts for all 7 aliyot
    # We need to construct aliyah objects - this is a simplified version
    print("📖 Fetching aliyah texts...")

    # Get parsha info from calendar (we'll use a sample date)
    calendar = JewishCalendar(client)

    # For now, create dummy aliyah texts with key verses
    # In production, we'd get the actual aliyah boundaries
    from src.calendar import Aliyah

    # Simplified: create placeholder aliyot
    # Real implementation would get proper boundaries
    aliyah_texts = []
    for i in range(1, 8):
        dummy_aliyah = Aliyah(
            number=i,
            ref=f"Aliyah {i}",
            start_verse="",
            end_verse="",
        )

        # Create minimal aliyah text for scoring
        from src.aliyah import AliyahText, Verse

        aliyah_text = AliyahText(
            aliyah=dummy_aliyah,
            verses=[],
            key_verses=[
                Verse(
                    ref=f"{book} - Aliyah {i}",
                    hebrew="",
                    english=f"Content from aliyah {i} of {parsha}",
                    link_count=0,
                )
            ],
            translation_source="",
        )
        aliyah_texts.append(aliyah_text)

    print(f"   Prepared {len(aliyah_texts)} aliyot")

    # Compute relevance scores
    print("🎯 Computing relevance scores...")
    print(f"   {len(corpus.essays)} essays × {len(aliyah_texts)} aliyot = {len(corpus.essays) * len(aliyah_texts)} API calls")

    try:
        relevance_data = await relevance_scorer.precompute_parsha_relevance(
            parsha,
            corpus.essays,
            aliyah_texts,
        )

        # Save results
        relevance_scorer.save_relevance_data(parsha, relevance_data)
        print(f"✅ Saved relevance data for {parsha}")

        # Print summary
        for title, rel in relevance_data.items():
            best = rel.best_aliyah
            best_str = f"Aliyah {best}" if best else "No strong match"
            print(f"   • {title}: {best_str}")

        return True

    except Exception as e:
        print(f"❌ Error computing relevance: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Pre-compute relevance scores")
    parser.add_argument("--parsha", type=str, help="Single parsha to process")
    parser.add_argument("--all", action="store_true", help="Process all parshiyot")
    parser.add_argument("--book", type=str, help="Process all parshiyot in a book")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    args = parser.parse_args()

    if not any([args.parsha, args.all, args.book]):
        parser.print_help()
        return

    # Determine which parshiyot to process
    parshiyot = []

    if args.parsha:
        parshiyot = [args.parsha]
    elif args.book:
        parshiyot = [p for p, b in PARSHA_TO_BOOK.items() if b == args.book]
    elif args.all:
        parshiyot = ALL_PARSHIYOT

    if args.dry_run:
        print("Would process the following parshiyot:")
        for p in parshiyot:
            print(f"  • {p} ({PARSHA_TO_BOOK.get(p, '?')})")
        print(f"\nTotal: {len(parshiyot)} parshiyot")
        return

    print(f"Processing {len(parshiyot)} parshiyot")
    print("This requires ANTHROPIC_API_KEY environment variable")
    print()

    async with SefariaClient() as client:
        success = 0
        failed = 0

        for parsha in parshiyot:
            try:
                if await compute_for_parsha(parsha, client):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"❌ Failed: {parsha} - {e}")
                failed += 1

            # Small delay between parshiyot
            await asyncio.sleep(1)

        print(f"\n{'='*50}")
        print(f"Complete: {success} succeeded, {failed} failed")
        print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())

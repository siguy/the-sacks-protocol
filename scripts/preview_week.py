#!/usr/bin/env python3
"""
Preview Week - Generate outputs for a range of dates for review.

Usage:
    python3 scripts/preview_week.py

Generates outputs for Jan 11-16, 2026 (Sunday through Friday)
and saves each to output/preview/ folder.
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from src.generator import DailyGenerator


async def main():
    """Generate outputs for Jan 11-16, 2026."""

    # Preview dates: Jan 11 (Sunday) through Jan 16 (Friday)
    dates = [
        (date(2026, 1, 11), "Sunday"),
        (date(2026, 1, 12), "Monday"),
        (date(2026, 1, 13), "Tuesday"),
        (date(2026, 1, 14), "Wednesday"),
        (date(2026, 1, 15), "Thursday"),
        (date(2026, 1, 16), "Friday"),
    ]

    # Create preview output directory
    preview_dir = Path(__file__).parent.parent / "output" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("THE SACKS PROTOCOL - Weekly Preview")
    print("=" * 60)
    print(f"\nGenerating outputs for {dates[0][0]} to {dates[-1][0]}")
    print(f"Output directory: {preview_dir}\n")

    # Generate each day
    for for_date, day_name in dates:
        print("=" * 60)
        print(f"📅 {day_name}, {for_date.strftime('%B %d, %Y')}")
        print("=" * 60)

        try:
            generator = DailyGenerator(output_dir=preview_dir)
            output = await generator.generate(for_date=for_date)

            # Also save with day name for easy identification
            filename = f"{for_date.strftime('%Y-%m-%d')}_{day_name.lower()}.md"
            filepath = preview_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(output.text)

            print(f"\n✅ Saved: {filepath}")
            print(f"   Word count: {output.word_count}")

        except Exception as e:
            print(f"\n❌ Error for {day_name}: {e}")
            import traceback
            traceback.print_exc()

        print()

    print("=" * 60)
    print("PREVIEW COMPLETE")
    print("=" * 60)
    print(f"\nReview outputs in: {preview_dir}")
    print("\nFiles generated:")
    for f in sorted(preview_dir.glob("2026-01-1*.md")):
        print(f"  - {f.name}")


if __name__ == "__main__":
    asyncio.run(main())

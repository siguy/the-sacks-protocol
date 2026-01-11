"""
Main Generator/Orchestrator

Ties together all components to generate daily output:
1. Get today's calendar info (parsha, aliyah)
2. Fetch aliyah text with Hebrew + English
3. Select traditional commentary via link graph + rotation
4. Look up cached Sacks essay (from weekly pre-computation)
5. Format output for WhatsApp

Weekly pre-computation (scripts/prepare_week.py) handles:
- Fetching all essays for the parsha
- Greedy matching essays to aliyot
- Generating Gemini summaries for each essay

This separation reduces API calls and enables review before delivery.
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

from .sefaria_client import SefariaClient
from .calendar import JewishCalendar, TodayInfo
from .aliyah import AliyahRetriever, AliyahText
from .commentary import CommentarySelector, Commentary
from .sacks import SacksRetriever, SacksEssay
from .relevance import RelevanceScorer, RelevanceScore
from .formatter import OutputFormatter, FormattedOutput


CACHE_DIR = Path(__file__).parent.parent / "data" / "weekly_cache"


class DailyGenerator:
    """Generates daily Torah wisdom output."""

    def __init__(
        self,
        output_dir: Path | None = None,
        use_cache: bool = True,
    ):
        self.output_dir = output_dir or Path(__file__).parent.parent / "output"
        self.use_cache = use_cache

    def _load_weekly_cache(self, parsha_name: str) -> dict | None:
        """Load cached weekly data for a parsha."""
        slug = parsha_name.lower().replace(" ", "_").replace("-", "_")
        filepath = CACHE_DIR / f"{slug}.json"

        if not filepath.exists():
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    async def generate(self, for_date: date | None = None) -> FormattedOutput:
        """
        Generate the daily output.

        Args:
            for_date: Date to generate for (default: today)

        Returns:
            Formatted output ready for delivery
        """
        async with SefariaClient() as client:
            # Initialize components
            calendar = JewishCalendar(client)
            aliyah_retriever = AliyahRetriever(client)
            commentary_selector = CommentarySelector(client)
            formatter = OutputFormatter()

            # 1. Get today's info
            print("📅 Getting calendar info...")
            today_info = await calendar.get_today_info(for_date)
            print(f"   Parsha: {today_info.parsha.name_en}")
            print(f"   Aliyot: {[a.number for a in today_info.aliyot]}")

            # 2. Fetch today's aliyah text (only the ones we need for display)
            print("\n📖 Fetching aliyah text...")
            aliyah_texts = []
            for aliyah in today_info.aliyot:
                text = await aliyah_retriever.get_aliyah_text(aliyah)
                aliyah_texts.append(text)
                print(f"   Aliyah {aliyah.number}: {len(text.verses)} verses")

            # Combine aliyah texts for Friday (double portion)
            primary_aliyah_text = self._combine_aliyah_texts(aliyah_texts)

            # 3. Select traditional commentary
            print("\n📜 Selecting commentary...")
            commentary = await commentary_selector.select_commentary(
                primary_aliyah_text.key_verses,
                today_info.day_of_week,
                today_info.parsha.book,
            )
            if commentary:
                print(f"   Commentator: {commentary.commentator.name}")
                print(f"   On verse: {commentary.verse.ref}")
            else:
                print("   No commentary found")

            # 4. Get Sacks essay from cache (or compute if no cache)
            sacks_essay: SacksEssay | None = None
            cached_sections: dict | None = None
            is_aliyah_relevant = False
            primary_aliyah_num = today_info.aliyot[0].number

            # Try to load from weekly cache
            cache = self._load_weekly_cache(today_info.parsha.name_en) if self.use_cache else None

            if cache:
                print("\n✡️ Loading from weekly cache...")
                print(f"   Cache computed: {cache.get('computed_at', 'unknown')}")

                # Get assignment for today's aliyah
                assignment = cache.get("assignments", {}).get(str(primary_aliyah_num))

                if assignment:
                    # Create SacksEssay object from cache
                    sacks_essay = SacksEssay(
                        title=assignment["essay_title"],
                        text="",  # We don't need full text - we have cached sections
                        parsha=today_info.parsha.name_en,
                        series="Covenant and Conversation",
                        sefaria_ref=assignment.get("essay_sefaria_ref", ""),
                    )
                    cached_sections = assignment.get("sections")
                    is_aliyah_relevant = assignment.get("score_data", {}).get("verse_score", 0) > 0

                    print(f"   ✅ Essay: \"{sacks_essay.title}\"")
                    if cached_sections:
                        print(f"   ✅ Using pre-generated summaries")
                else:
                    print(f"   ❌ No essay assigned for aliyah {primary_aliyah_num}")

            else:
                # No cache - fall back to computing (with warning)
                print("\n⚠️  No weekly cache found!")
                print("   Run: python3 scripts/prepare_week.py")
                print("   Falling back to live computation (slower)...")

                # Fall back to current behavior
                sacks_retriever = SacksRetriever(client)
                relevance_scorer = RelevanceScorer()

                sacks_corpus = await sacks_retriever.get_essays_for_parsha(
                    today_info.parsha.name_en,
                    today_info.parsha.book,
                )
                print(f"   Found {len(sacks_corpus.essays)} essays")

                if sacks_corpus.essays:
                    print("\n🎯 Computing weekly essay assignments...")
                    all_aliyah_texts = await self._fetch_all_aliyah_texts(
                        today_info.parsha, aliyah_retriever
                    )

                    weekly_assignments = relevance_scorer.compute_weekly_assignments(
                        essays=sacks_corpus.essays,
                        aliyah_texts=all_aliyah_texts,
                        book=today_info.parsha.book,
                        threshold=6,
                    )

                    assignment = weekly_assignments.get(primary_aliyah_num)
                    if assignment:
                        sacks_essay, score_data = assignment
                        is_aliyah_relevant = score_data.get("verse_score", 0) > 0
                        print(f"\n   ✅ Today's essay: \"{sacks_essay.title}\"")

            # 5. Format output
            print("\n✨ Formatting output...")
            output = await formatter.format_daily_output(
                today_info=today_info,
                aliyah_text=primary_aliyah_text,
                commentary=commentary,
                sacks_essay=sacks_essay,
                relevance_score=None,
                is_aliyah_relevant=is_aliyah_relevant,
                cached_essay_sections=cached_sections,  # Pass cached sections
            )

            print(f"   Word count: {output.word_count}")

            # 6. Save output
            self._save_output(output, today_info)

            return output

    async def _fetch_all_aliyah_texts(
        self,
        parsha: "Parsha",
        aliyah_retriever: AliyahRetriever,
    ) -> dict[int, AliyahText]:
        """
        Fetch all 7 aliyah texts for a parsha (needed for greedy matching).

        Returns:
            Dict mapping aliyah number (1-7) to AliyahText
        """
        from .calendar import Aliyah, ALIYOT_DATA

        all_texts = {}

        # Get aliyah refs from ALIYOT_DATA
        parsha_name = parsha.name_en
        parsha_data = None

        if ALIYOT_DATA and "aliyot" in ALIYOT_DATA:
            parsha_data = ALIYOT_DATA["aliyot"].get(parsha_name)
            # Try variations
            if not parsha_data:
                for name in [parsha_name.replace(" ", "_"), parsha_name.title()]:
                    parsha_data = ALIYOT_DATA["aliyot"].get(name)
                    if parsha_data:
                        break

        if not parsha_data or "aliyot" not in parsha_data:
            print(f"   Warning: No aliyah data found for {parsha_name}")
            return all_texts

        aliyah_refs = parsha_data["aliyot"]

        for aliyah_num in range(1, 8):
            ref = aliyah_refs.get(aliyah_num, "")
            if not ref:
                continue

            # Create Aliyah object
            aliyah = Aliyah(
                number=aliyah_num,
                ref=ref,
                start_verse=ref.split("-")[0] if "-" in ref else ref,
                end_verse=ref.split("-")[1] if "-" in ref else ref,
            )

            try:
                text = await aliyah_retriever.get_aliyah_text(aliyah)
                all_texts[aliyah_num] = text
            except Exception as e:
                print(f"   Warning: Could not fetch aliyah {aliyah_num}: {e}")

        return all_texts

    def _extract_keywords(self, aliyah_text: AliyahText) -> list[str]:
        """
        Extract keywords from aliyah text for heuristic essay matching.

        Looks for names, places, and significant nouns in the English text.
        """
        # Common biblical keywords to look for
        name_patterns = [
            "Moses", "Aaron", "Pharaoh", "God", "Lord", "Israel", "Egypt",
            "Abraham", "Isaac", "Jacob", "Joseph", "burning bush", "bush",
            "Sinai", "Horeb", "plague", "Exodus", "freedom", "liberation",
            "slave", "slavery", "covenant", "promise", "fear", "afraid",
            "name", "names", "I AM", "YHWH", "Midian", "Jethro", "Zipporah",
        ]

        keywords = []

        # Check English text of key verses for keywords
        for verse in aliyah_text.key_verses:
            text_lower = verse.english.lower() if verse.english else ""
            for pattern in name_patterns:
                if pattern.lower() in text_lower and pattern not in keywords:
                    keywords.append(pattern)

        # Also check all verses if we don't have enough keywords
        if len(keywords) < 3:
            for verse in aliyah_text.verses[:10]:  # Check first 10 verses
                text_lower = verse.english.lower() if verse.english else ""
                for pattern in name_patterns:
                    if pattern.lower() in text_lower and pattern not in keywords:
                        keywords.append(pattern)

        return keywords[:10]  # Return top 10 keywords

    def _combine_aliyah_texts(self, aliyah_texts: list[AliyahText]) -> AliyahText:
        """Combine multiple aliyah texts (for Friday double portion)."""
        if len(aliyah_texts) == 1:
            return aliyah_texts[0]

        # Combine verses and key verses
        all_verses = []
        all_key_verses = []

        for text in aliyah_texts:
            all_verses.extend(text.verses)
            all_key_verses.extend(text.key_verses)

        # Sort key verses by link count and take top ones
        all_key_verses.sort(key=lambda v: v.link_count, reverse=True)

        # Create combined aliyah info
        combined_aliyah = aliyah_texts[0].aliyah
        combined_aliyah.ref = f"{aliyah_texts[0].aliyah.ref} - {aliyah_texts[-1].aliyah.ref}"

        return AliyahText(
            aliyah=combined_aliyah,
            verses=all_verses,
            key_verses=all_key_verses[:4],
            translation_source=aliyah_texts[0].translation_source,
        )

    def _save_output(self, output: FormattedOutput, today_info: TodayInfo) -> None:
        """Save the generated output to a file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Filename: YYYY-MM-DD_parsha.md
        date_str = output.date.strftime("%Y-%m-%d")
        parsha_slug = output.parsha.lower().replace(" ", "_")
        filename = f"{date_str}_{parsha_slug}.md"

        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(output.text)

        print(f"\n📄 Saved to: {filepath}")


async def main():
    """Generate today's output."""
    # Load environment variables from .env file (override existing env vars)
    load_dotenv(override=True)

    generator = DailyGenerator()

    print("=" * 50)
    print("THE SACKS PROTOCOL - Daily Generator")
    print("=" * 50)
    print()

    try:
        output = await generator.generate()

        print("\n" + "=" * 50)
        print("GENERATED OUTPUT")
        print("=" * 50)
        print()
        print(output.text)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

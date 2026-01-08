"""
Main Generator/Orchestrator

Ties together all components to generate daily output:
1. Get today's calendar info (parsha, aliyah)
2. Fetch aliyah text with Hebrew + English
3. Select traditional commentary via link graph + rotation
4. Fetch Sacks essays and select best match
5. Format output for WhatsApp
"""

import asyncio
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


class DailyGenerator:
    """Generates daily Torah wisdom output."""

    def __init__(
        self,
        output_dir: Path | None = None,
        use_precomputed_relevance: bool = True,
    ):
        self.output_dir = output_dir or Path(__file__).parent.parent / "output"
        self.use_precomputed_relevance = use_precomputed_relevance

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
            sacks_retriever = SacksRetriever(client)
            relevance_scorer = RelevanceScorer()
            formatter = OutputFormatter()

            # 1. Get today's info
            print("📅 Getting calendar info...")
            today_info = await calendar.get_today_info(for_date)
            print(f"   Parsha: {today_info.parsha.name_en}")
            print(f"   Aliyot: {[a.number for a in today_info.aliyot]}")

            # 2. Fetch aliyah text
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

            # 4. Fetch Sacks essays
            print("\n✡️ Fetching Sacks essays...")
            sacks_corpus = await sacks_retriever.get_essays_for_parsha(
                today_info.parsha.name_en,
                today_info.parsha.book,
            )
            print(f"   Found {len(sacks_corpus.essays)} essays")

            # 5. Select best Sacks essay using relevance scoring
            sacks_essay: SacksEssay | None = None
            relevance_score: RelevanceScore | None = None
            is_aliyah_relevant = False

            if sacks_corpus.essays:
                print("\n🎯 Checking relevance...")

                # Try to load pre-computed relevance
                relevance_data = None
                if self.use_precomputed_relevance:
                    relevance_data = relevance_scorer.load_relevance_data(
                        today_info.parsha.name_en
                    )
                    if relevance_data:
                        print("   Using pre-computed relevance scores")

                # Extract keywords from aliyah for heuristic matching
                aliyah_keywords = self._extract_keywords(primary_aliyah_text)

                # Select best essay
                primary_aliyah_num = today_info.aliyot[0].number
                sacks_essay, relevance_score, is_aliyah_relevant = (
                    relevance_scorer.select_best_essay(
                        sacks_corpus.essays,
                        relevance_data,
                        primary_aliyah_num,
                        aliyah_keywords=aliyah_keywords,
                    )
                )

                if sacks_essay:
                    print(f"   Selected: \"{sacks_essay.title}\"")
                    if is_aliyah_relevant:
                        print(f"   📍 Directly relevant to aliyah {primary_aliyah_num}!")

            # 6. Format output
            print("\n✨ Formatting output...")
            output = await formatter.format_daily_output(
                today_info=today_info,
                aliyah_text=primary_aliyah_text,
                commentary=commentary,
                sacks_essay=sacks_essay,
                relevance_score=relevance_score,
                is_aliyah_relevant=is_aliyah_relevant,
            )

            print(f"   Word count: {output.word_count}")

            # 7. Save output
            self._save_output(output, today_info)

            return output

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

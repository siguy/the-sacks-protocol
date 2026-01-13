"""
Main Generator/Orchestrator

Ties together all components to generate daily output:
1. Load weekly cache (from scripts/prepare_week.py)
2. Get today's aliyah and commentary from cache
3. Format output for WhatsApp

If no cache exists, falls back to live API calls (slower).

Weekly pre-computation (scripts/prepare_week.py) handles:
- Fetching all aliyah texts with full verses
- Pre-selecting commentary for each day
- Greedy matching essays to aliyot
- Generating Gemini summaries for each essay

This separation reduces API calls and enables fully offline daily generation.
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

from .sefaria_client import SefariaClient
from .calendar import JewishCalendar, TodayInfo, Aliyah, DayOfWeek, ALIYOT_DATA, Parsha
from .aliyah import AliyahRetriever, AliyahText, Verse
from .commentary import CommentarySelector, Commentary, CommentatorInfo
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

    def _reconstruct_verse(self, data: dict) -> Verse:
        """Reconstruct a Verse object from cached data."""
        return Verse(
            ref=data["ref"],
            hebrew=data["hebrew"],
            english=data["english"],
            link_count=data.get("link_count", 0),
        )

    def _reconstruct_aliyah_text(self, data: dict) -> AliyahText:
        """Reconstruct an AliyahText object from cached data."""
        aliyah_data = data["aliyah"]
        return AliyahText(
            aliyah=Aliyah(
                number=aliyah_data["number"],
                ref=aliyah_data["ref"],
                start_verse=aliyah_data["start_verse"],
                end_verse=aliyah_data["end_verse"],
            ),
            verses=[self._reconstruct_verse(v) for v in data["verses"]],
            key_verses=[self._reconstruct_verse(v) for v in data["key_verses"]],
            translation_source=data["translation_source"],
        )

    def _reconstruct_commentary(self, data: dict) -> Commentary:
        """Reconstruct a Commentary object from cached data."""
        return Commentary(
            verse=self._reconstruct_verse(data["verse"]),
            commentator=CommentatorInfo(
                name=data["commentator"]["name"],
                hebrew=data["commentator"]["hebrew"],
                full_name=data["commentator"]["full_name"],
                era=data["commentator"]["era"],
            ),
            source_ref=data["source_ref"],
            hebrew_text=data["hebrew_text"],
            english_text=data["english_text"],
            selection_reason=data["selection_reason"],
        )

    def _get_parsha_info_from_cache(self, cache: dict, for_date: date) -> TodayInfo:
        """Build TodayInfo from cache data for a specific date."""
        from .calendar import HebrewDate

        # Determine day of week
        # Python: Monday=0, Sunday=6
        # Jewish week: Day 1=Sunday, Day 6=Friday, Day 7=Shabbat
        python_weekday = for_date.weekday()
        jewish_day_num = ((python_weekday + 1) % 7) + 1  # Sunday=1, Saturday=7

        # DayOfWeek enum uses Sunday=0
        day_of_week_enum_val = (python_weekday + 1) % 7

        # Map day to aliyah number(s)
        day_to_aliyah = {
            1: [1],      # Day 1 (Sunday) -> Aliyah 1
            2: [2],      # Day 2 (Monday) -> Aliyah 2
            3: [3],      # Day 3 (Tuesday) -> Aliyah 3
            4: [4],      # Day 4 (Wednesday) -> Aliyah 4
            5: [5],      # Day 5 (Thursday) -> Aliyah 5
            6: [6, 7],   # Day 6 (Friday) -> Aliyot 6+7
            7: [1],      # Day 7 (Shabbat) -> fallback to 1
        }
        aliyah_nums = day_to_aliyah[jewish_day_num]

        # Build aliyah objects from cache
        aliyot = []
        for num in aliyah_nums:
            aliyah_data = cache["aliyot"].get(str(num), {}).get("aliyah", {})
            if aliyah_data:
                aliyot.append(Aliyah(
                    number=aliyah_data["number"],
                    ref=aliyah_data["ref"],
                    start_verse=aliyah_data["start_verse"],
                    end_verse=aliyah_data["end_verse"],
                ))

        # Build parsha info
        parsha = Parsha(
            name_en=cache["parsha"],
            name_he="",  # Not stored in cache, but not critical
            book=cache["book"],
            order=0,
        )

        return TodayInfo(
            gregorian_date=for_date,
            hebrew_date=None,  # Not critical for formatting
            day_of_week=DayOfWeek(day_of_week_enum_val),
            parsha=parsha,
            aliyot=aliyot,
            is_special=False,
            special_note=None,
        )

    async def generate(self, for_date: date | None = None) -> FormattedOutput:
        """
        Generate the daily output.

        Args:
            for_date: Date to generate for (default: today)

        Returns:
            Formatted output ready for delivery
        """
        target_date = for_date or date.today()

        # Determine day of week
        # Python: Monday=0, Sunday=6
        # Jewish week: Day 1=Sunday, Day 6=Friday, Day 7=Shabbat
        python_weekday = target_date.weekday()
        # Convert to Jewish day number (1-7, where 1=Sunday)
        jewish_day_num = ((python_weekday + 1) % 7) + 1  # Sunday=1, Monday=2, ..., Saturday=7
        if jewish_day_num == 7:
            jewish_day_num = 7  # Shabbat

        # Map day to aliyah number(s)
        day_to_aliyah = {
            1: [1],      # Day 1 (Sunday) -> Aliyah 1
            2: [2],      # Day 2 (Monday) -> Aliyah 2
            3: [3],      # Day 3 (Tuesday) -> Aliyah 3
            4: [4],      # Day 4 (Wednesday) -> Aliyah 4
            5: [5],      # Day 5 (Thursday) -> Aliyah 5
            6: [6, 7],   # Day 6 (Friday) -> Aliyot 6+7
            7: [1],      # Day 7 (Shabbat) -> fallback to 1
        }
        aliyah_nums = day_to_aliyah[jewish_day_num]
        primary_aliyah_num = aliyah_nums[0]

        # Try to find cache for current parsha
        # We need to determine the parsha - check all caches or use API
        cache = None
        today_info = None

        if self.use_cache:
            # Try to find a matching cache file
            if CACHE_DIR.exists():
                for cache_file in CACHE_DIR.glob("*.json"):
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            potential_cache = json.load(f)
                        # Check if this cache is for current week
                        week_of = potential_cache.get("week_of", "")
                        if week_of:
                            cache_week = date.fromisoformat(week_of)
                            # Same week if within 7 days
                            if abs((target_date - cache_week).days) <= 6:
                                cache = potential_cache
                                print(f"📦 Using cached data from: {cache_file.name}")
                                break
                    except (json.JSONDecodeError, KeyError):
                        continue

        if cache:
            # FULLY OFFLINE MODE - use cached data
            print("=" * 50)
            print("THE SACKS PROTOCOL - Daily Generator (OFFLINE)")
            print("=" * 50)
            print()

            # Build today_info from cache
            today_info = self._get_parsha_info_from_cache(cache, target_date)
            print(f"📅 Parsha: {today_info.parsha.name_en}")
            print(f"   Aliyot: {[a.number for a in today_info.aliyot]}")
            print(f"   Day: {today_info.day_of_week.name}")

            # Get aliyah text and cached sections from cache
            print("\n📖 Loading aliyah text from cache...")
            aliyah_texts = []
            cached_aliyah_sections = None
            for aliyah_num in aliyah_nums:
                aliyah_data = cache["aliyot"].get(str(aliyah_num))
                if aliyah_data:
                    text = self._reconstruct_aliyah_text(aliyah_data)
                    aliyah_texts.append(text)
                    # Get cached sections for the primary aliyah
                    if aliyah_num == primary_aliyah_num:
                        cached_aliyah_sections = aliyah_data.get("sections")
                    print(f"   ✅ Aliyah {aliyah_num}: {len(text.verses)} verses")

            primary_aliyah_text = self._combine_aliyah_texts(aliyah_texts)

            if cached_aliyah_sections:
                print(f"   ✅ Cached aliyah summaries loaded")
            else:
                print(f"   ⚠️  No cached aliyah summaries")

            # Get commentary from cache (keyed by day number 1-6)
            print("\n📜 Loading commentary from cache...")
            commentary = None
            commentary_data = cache.get("commentary", {}).get(str(jewish_day_num))
            if commentary_data:
                commentary = self._reconstruct_commentary(commentary_data)
                print(f"   ✅ {commentary.commentator.name} on {commentary.verse.ref}")
            else:
                print("   ⚠️  No cached commentary for today")

            # Get essay from cache
            print("\n✡️ Loading Sacks essay from cache...")
            sacks_essay = None
            cached_sections = None
            is_aliyah_relevant = False

            assignment = cache.get("assignments", {}).get(str(primary_aliyah_num))
            if assignment:
                sacks_essay = SacksEssay(
                    title=assignment["essay_title"],
                    text="",  # We have cached sections
                    parsha=today_info.parsha.name_en,
                    series="Covenant and Conversation",
                    sefaria_ref=assignment.get("essay_sefaria_ref", ""),
                )
                cached_sections = assignment.get("sections")
                is_aliyah_relevant = assignment.get("score_data", {}).get("verse_score", 0) > 0
                print(f"   ✅ Essay: \"{sacks_essay.title}\"")
            else:
                print(f"   ⚠️  No essay assigned for aliyah {primary_aliyah_num}")

            # Format output
            print("\n✨ Formatting output...")
            formatter = OutputFormatter()
            output = await formatter.format_daily_output(
                today_info=today_info,
                aliyah_text=primary_aliyah_text,
                commentary=commentary,
                sacks_essay=sacks_essay,
                relevance_score=None,
                is_aliyah_relevant=is_aliyah_relevant,
                cached_essay_sections=cached_sections,
                cached_aliyah_sections=cached_aliyah_sections,
            )

            print(f"   Word count: {output.word_count}")

            # Save output
            self._save_output(output, today_info)

            return output

        else:
            # ONLINE MODE - fall back to live API calls
            print("=" * 50)
            print("THE SACKS PROTOCOL - Daily Generator (LIVE)")
            print("=" * 50)
            print()
            print("⚠️  No weekly cache found!")
            print("   Run: python3 scripts/prepare_week.py")
            print("   Falling back to live API calls...\n")

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

                primary_aliyah_text = self._combine_aliyah_texts(aliyah_texts)

                # 3. Select commentary
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

                # 4. Get Sacks essay
                sacks_essay = None
                cached_sections = None
                is_aliyah_relevant = False
                primary_aliyah_num = today_info.aliyot[0].number

                sacks_corpus = await sacks_retriever.get_essays_for_parsha(
                    today_info.parsha.name_en,
                    today_info.parsha.book,
                )
                print(f"\n✡️ Found {len(sacks_corpus.essays)} essays")

                if sacks_corpus.essays:
                    print("🎯 Computing essay assignments...")
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
                        print(f"   ✅ Today's essay: \"{sacks_essay.title}\"")

                # 5. Format output
                print("\n✨ Formatting output...")
                output = await formatter.format_daily_output(
                    today_info=today_info,
                    aliyah_text=primary_aliyah_text,
                    commentary=commentary,
                    sacks_essay=sacks_essay,
                    relevance_score=None,
                    is_aliyah_relevant=is_aliyah_relevant,
                    cached_essay_sections=cached_sections,
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

    def _combine_aliyah_texts(self, aliyah_texts: list[AliyahText]) -> AliyahText:
        """Combine multiple aliyah texts (for Friday double portion)."""
        if len(aliyah_texts) == 1:
            return aliyah_texts[0]

        if not aliyah_texts:
            # Return empty aliyah text
            return AliyahText(
                aliyah=Aliyah(number=0, ref="", start_verse="", end_verse=""),
                verses=[],
                key_verses=[],
                translation_source="",
            )

        # Combine verses and key verses
        all_verses = []
        all_key_verses = []

        for text in aliyah_texts:
            all_verses.extend(text.verses)
            all_key_verses.extend(text.key_verses)

        # Sort key verses by link count and take top ones
        all_key_verses.sort(key=lambda v: v.link_count, reverse=True)

        # Create combined aliyah info
        combined_aliyah = Aliyah(
            number=aliyah_texts[0].aliyah.number,
            ref=f"{aliyah_texts[0].aliyah.ref} - {aliyah_texts[-1].aliyah.ref}",
            start_verse=aliyah_texts[0].aliyah.start_verse,
            end_verse=aliyah_texts[-1].aliyah.end_verse,
        )

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

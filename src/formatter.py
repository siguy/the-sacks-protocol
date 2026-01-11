"""
Output Formatter Module

Formats the generated content for WhatsApp delivery.
Uses WhatsApp-compatible markdown (bold, italic, monospace).
"""

from dataclasses import dataclass
from datetime import date
import os
import re

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from .calendar import TodayInfo, DayOfWeek, JewishCalendar
from .aliyah import AliyahText, Verse
from .commentary import Commentary
from .sacks import SacksEssay
from .relevance import RelevanceScore


@dataclass
class FormattedOutput:
    """Complete formatted output ready for delivery."""

    text: str
    parsha: str
    aliyah_nums: list[int]
    date: date
    word_count: int


class OutputFormatter:
    """Formats daily output for WhatsApp."""

    # WhatsApp formatting
    BOLD_START = "*"
    BOLD_END = "*"
    ITALIC_START = "_"
    ITALIC_END = "_"
    MONO_START = "```"
    MONO_END = "```"

    # Section dividers
    THIN_DIVIDER = "─" * 35
    THICK_DIVIDER = "━" * 35

    def __init__(
        self,
        max_verses: int = 4,
        max_commentary_chars: int = 500,
        max_sacks_chars: int = 800,
        google_api_key: str | None = None,
    ):
        self.max_verses = max_verses
        self.max_commentary_chars = max_commentary_chars
        self.max_sacks_chars = max_sacks_chars

        # Initialize Gemini client for summarization
        api_key = google_api_key or os.getenv("GOOGLE_API_KEY")
        self.gemini_client = genai.Client(api_key=api_key) if (api_key and genai) else None

    async def format_daily_output(
        self,
        today_info: TodayInfo,
        aliyah_text: AliyahText,
        commentary: Commentary | None,
        sacks_essay: SacksEssay | None,
        relevance_score: RelevanceScore | None,
        is_aliyah_relevant: bool,
    ) -> FormattedOutput:
        """
        Format the complete daily output.

        Structure:
        1. Header (parsha, aliyah, date)
        2. The Text (aliyah verses with Hebrew + English)
        3. The Commentator (traditional commentary)
        4. The Sacksian Lens (parsha-level, with relevance note if applicable)
        """
        sections = []

        # 1. Header
        sections.append(self._format_header(today_info, aliyah_text))

        # 2. The Text (with AI-generated summaries)
        text_section = await self._format_text_section(aliyah_text)
        sections.append(text_section)

        # 3. The Commentator (with verse context and full text)
        if commentary:
            commentary_section = self._format_commentary_section(commentary, aliyah_text)
            sections.append(commentary_section)

        # 4. The Sacksian Lens
        if sacks_essay:
            sacks_section = await self._format_sacks_section(
                sacks_essay, today_info.parsha.name_en, relevance_score, is_aliyah_relevant
            )
            sections.append(sacks_section)

        # Combine sections
        full_text = "\n\n".join(sections)

        return FormattedOutput(
            text=full_text,
            parsha=today_info.parsha.name_en,
            aliyah_nums=[a.number for a in today_info.aliyot],
            date=today_info.gregorian_date,
            word_count=len(full_text.split()),
        )

    def _format_header(self, today_info: TodayInfo, aliyah_text: AliyahText) -> str:
        """Format the header section."""
        parsha_en = today_info.parsha.name_en
        parsha_he = today_info.parsha.name_he

        aliyah_nums = [a.number for a in today_info.aliyot]
        if len(aliyah_nums) == 1:
            aliyah_str = f"Aliyah {aliyah_nums[0]}"
        else:
            aliyah_str = f"Aliyot {aliyah_nums[0]}-{aliyah_nums[-1]}"

        # Day name
        day_name = self._get_day_name(today_info.day_of_week)

        # Date formatting
        date_str = today_info.gregorian_date.strftime("%B %d, %Y")

        # Hebrew date if available
        hebrew_date_str = ""
        if today_info.hebrew_date:
            hebrew_date_str = f" · {today_info.hebrew_date.hebrew()}"

        header = f"""{self.BOLD_START}{parsha_en}{self.BOLD_END} · {parsha_he}
{aliyah_str} · {day_name}{hebrew_date_str}
{date_str}"""

        if today_info.is_special and today_info.special_note:
            header += f"\n{self.ITALIC_START}{today_info.special_note}{self.ITALIC_END}"

        return header

    async def _format_text_section(self, aliyah_text: AliyahText) -> str:
        """Format the Torah text section with summaries for each logical section."""
        lines = [
            self.THIN_DIVIDER,
            "",
            f"{self.BOLD_START}THE ALIYAH SUMMARY{self.BOLD_END} · {aliyah_text.aliyah.ref}",
            "",
        ]

        # Break aliyah into logical sections and summarize each
        sections = await self._break_into_sections_and_summarize(aliyah_text)

        for i, section in enumerate(sections, 1):
            # Section header with verse range
            lines.append(f"{self.BOLD_START}Section {i}: {section['title']}{self.BOLD_END} | {section['verses']}")
            lines.append("")
            # Summary only (no verses)
            lines.append(section['summary'])
            lines.append("")

        return "\n".join(lines)

    async def _break_into_sections_and_summarize(self, aliyah_text: AliyahText) -> list[dict]:
        """
        Use Gemini to break aliyah into logical narrative sections and summarize each.

        Returns:
            List of dicts with keys: 'title', 'verses', 'summary'
        """
        if not self.gemini_client:
            # Fallback: return simple single section
            print("   DEBUG: No Gemini API key - using fallback single section")
            return [{
                'title': 'Complete Aliyah',
                'verses': aliyah_text.aliyah.ref,
                'summary': 'Summary generation requires Gemini API key.'
            }]

        # Prepare text for Gemini
        verses_text = "\n\n".join([
            f"{v.ref}:\nHebrew: {v.hebrew}\nEnglish: {v.english}"
            for v in aliyah_text.verses
        ])

        prompt = f"""Analyze this Torah portion and break it into 3-5 logical narrative sections based on natural thematic or narrative breaks.

For each section provide:
1. A brief descriptive title (3-6 words)
2. The verse range it covers (e.g., "Exodus 3:1-3:6")
3. A 2-4 line summary that captures the key events or ideas

Torah portion ({aliyah_text.aliyah.ref}):

{verses_text}

Return ONLY a valid JSON array with no other text:
[{{"title": "...", "verses": "...", "summary": "..."}}]"""

        try:
            print(f"   DEBUG: Calling Gemini to break aliyah into sections...")
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.gemini_client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=4096,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0  # Disable thinking for JSON response
                        ),
                    )
                )
            )

            # Parse JSON response
            import json
            response_text = response.text.strip()
            print(f"   DEBUG: Gemini response length: {len(response_text)} chars")

            # Extract JSON if wrapped in markdown code blocks
            if response_text.startswith("```"):
                # Remove markdown code block markers
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:].strip()

            sections = json.loads(response_text)
            print(f"   DEBUG: Generated {len(sections)} sections")
            for i, sec in enumerate(sections, 1):
                print(f"      {i}. {sec['title']} ({sec['verses']})")

            return sections

        except Exception as e:
            print(f"   DEBUG: Error generating sections with Gemini: {e}")
            # Fallback to simple single section
            return [{
                'title': 'Complete Aliyah',
                'verses': aliyah_text.aliyah.ref,
                'summary': f'Error generating summary: {str(e)}'
            }]

    def _format_commentary_section(self, commentary: Commentary, aliyah_text: AliyahText) -> str:
        """Format the traditional commentary section with verse context."""
        lines = [
            self.THIN_DIVIDER,
            "",
            f"{self.BOLD_START}COMMENTATOR DEEP DIVE{self.BOLD_END} · {commentary.commentator.name}",
            f"{commentary.commentator.hebrew} · {commentary.commentator.era}",
            f"On {commentary.verse.ref}",
            "",
        ]

        # Show ONLY the verse being commented on
        lines.append(f"{self.BOLD_START}Context:{self.BOLD_END}")
        lines.append("")
        # Hebrew in bold
        lines.append(f"{self.BOLD_START}{commentary.verse.hebrew}{self.BOLD_END}")
        lines.append("")
        lines.append(f"{self.ITALIC_START}{commentary.verse.english}{self.ITALIC_END}")
        lines.append(f"— {commentary.verse.ref}")
        lines.append("")

        # Show Hebrew commentary with dibur hamatchil bolded
        lines.append(f"{self.BOLD_START}Commentary:{self.BOLD_END}")
        lines.append("")
        if commentary.hebrew_text:
            hebrew_with_dibur = self._format_hebrew_with_dibur(commentary.hebrew_text)
            lines.append(hebrew_with_dibur)
            lines.append("")

        # Show English translation if available (NO truncation)
        if commentary.english_text:
            lines.append(f"{self.ITALIC_START}{commentary.english_text}{self.ITALIC_END}")

        return "\n".join(lines)

    def _get_section_sample_verses(self, verse_range: str, aliyah_text: AliyahText) -> list[Verse]:
        """
        Get 1-2 sample verses from a section to display with the summary.

        Args:
            verse_range: Range like "Exodus 3:1-3:6"
            aliyah_text: The full aliyah text with all verses

        Returns:
            List of 1-2 sample verses from the section
        """
        # Parse the verse range to get start and end refs
        # Format: "Exodus 3:1-3:6" or "Exodus 3:1-4:2"
        try:
            if '-' in verse_range:
                start_ref, end_ref = verse_range.split('-')
                start_ref = start_ref.strip()
                # Handle "Exodus 3:1-3:6" vs "Exodus 3:1-4:2"
                if ':' not in end_ref:
                    # Format like "Exodus 3:1-6" - same chapter
                    book_chapter = start_ref.rsplit(':', 1)[0]
                    end_ref = f"{book_chapter}:{end_ref.strip()}"
                else:
                    # Format like "3:1-4:2" - need to add book name
                    if ' ' not in end_ref:
                        book = start_ref.split()[0]
                        end_ref = f"{book} {end_ref.strip()}"
                    else:
                        end_ref = end_ref.strip()
            else:
                # Single verse
                start_ref = verse_range.strip()
                end_ref = start_ref

            # Find verses in this range
            section_verses = []
            in_range = False
            for verse in aliyah_text.verses:
                if verse.ref == start_ref:
                    in_range = True
                if in_range:
                    section_verses.append(verse)
                if verse.ref == end_ref:
                    break

            # Return first 1-2 verses from the section as samples
            if len(section_verses) <= 2:
                return section_verses
            else:
                # Return first verse only for longer sections
                return section_verses[:1]

        except Exception as e:
            print(f"   DEBUG: Error parsing verse range '{verse_range}': {e}")
            return []

    def _get_context_verses(self, commentary_ref: str, aliyah_text: AliyahText) -> list[Verse]:
        """
        Get 1-2 verses before and after the commentary verse for context.

        Args:
            commentary_ref: Reference like "Exodus 4:14"
            aliyah_text: The full aliyah text with all verses

        Returns:
            List of verses (including the commentary verse itself)
        """
        # Find the commentary verse in the aliyah
        commentary_idx = None
        for i, verse in enumerate(aliyah_text.verses):
            if verse.ref == commentary_ref:
                commentary_idx = i
                break

        if commentary_idx is None:
            # Commentary verse not in aliyah - just return the verse itself if available
            print(f"   DEBUG: Commentary verse {commentary_ref} not found in aliyah")
            return []

        # Get context: up to 2 verses before, the verse itself, and up to 2 verses after
        start_idx = max(0, commentary_idx - 2)
        end_idx = min(len(aliyah_text.verses), commentary_idx + 3)

        context = aliyah_text.verses[start_idx:end_idx]
        print(f"   DEBUG: Context verses for {commentary_ref}: {[v.ref for v in context]}")
        return context

    def _format_hebrew_with_dibur(self, hebrew_text: str) -> str:
        """
        Extract dibur hamatchil (opening phrase) from Hebrew commentary and make it bold.

        The dibur hamatchil is the first ~4 words of the Hebrew commentary that
        typically quotes from the verse being commented on.

        Args:
            hebrew_text: Full Hebrew commentary text

        Returns:
            Hebrew text with dibur hamatchil (first ~4 words) wrapped in bold markers
        """
        # Split into words
        words = hebrew_text.split()

        if len(words) < 4:
            # If less than 4 words, bold all of it
            return f"{self.BOLD_START}{hebrew_text}{self.BOLD_END}"

        # Bold the first 4 words
        dibur = " ".join(words[:4])
        rest = " ".join(words[4:])
        formatted = f"{self.BOLD_START}{dibur}{self.BOLD_END} {rest}"

        print(f"   DEBUG: Dibur hamatchil (first 4 words): '{dibur}'")
        return formatted

    async def _format_sacks_section(
        self,
        essay: SacksEssay,
        parsha_name: str,
        relevance_score: RelevanceScore | None,
        is_aliyah_relevant: bool,
    ) -> str:
        """Format the Rabbi Sacks section."""
        lines = [
            self.THICK_DIVIDER,
            "",
            f"{self.BOLD_START}ON THIS WEEK'S PARSHA{self.BOLD_END} · {parsha_name}",
            "",
        ]

        # Relevance note if directly relevant to today's aliyah
        if is_aliyah_relevant and relevance_score:
            overlap = ", ".join(relevance_score.key_overlap[:3])
            lines.append(
                f"📍 {self.ITALIC_START}Directly addresses today's aliyah: {overlap}{self.ITALIC_END}"
            )
            lines.append("")

        lines.append(f"{self.BOLD_START}THE SACKSIAN LENS{self.BOLD_END}")
        lines.append("")

        # Extract key sections from essay using Gemini summarization
        essay_sections = await self._extract_essay_sections_with_llm(essay)

        # THE QUESTION - textual difficulty or moral tension
        if essay_sections.get("question"):
            lines.append(f"{self.BOLD_START}THE QUESTION{self.BOLD_END}")
            lines.append(essay_sections["question"])
            lines.append("")

        # THE TURN - unexpected lens (philosophy, history, linguistics)
        if essay_sections.get("turn"):
            lines.append(f"{self.BOLD_START}THE TURN{self.BOLD_END}")
            lines.append(essay_sections["turn"])
            lines.append("")

        # THE INSIGHT - synthesizes Torah + universal wisdom
        if essay_sections.get("insight"):
            lines.append(f"{self.BOLD_START}THE INSIGHT{self.BOLD_END}")
            lines.append(essay_sections["insight"])
            lines.append("")

        # THE CALL - practical/ethical implication
        if essay_sections.get("call"):
            lines.append(f"{self.BOLD_START}THE CALL{self.BOLD_END}")
            lines.append(essay_sections["call"])
            lines.append("")

        # Attribution
        lines.append(self.THIN_DIVIDER)
        lines.append(
            f"— From {self.ITALIC_START}\"{essay.title}\"{self.ITALIC_END} by Rabbi Lord Jonathan Sacks"
        )
        lines.append(f"  {essay.series} · {essay.parsha}")

        return "\n".join(lines)

    async def _extract_essay_sections_with_llm(self, essay: SacksEssay) -> dict[str, str]:
        """
        Use Gemini to extract and summarize the 4 key sections from a Sacks essay.

        Returns:
            Dict with keys: 'question', 'turn', 'insight', 'call'
        """
        if not self.gemini_client:
            print("   DEBUG: No Gemini client - falling back to heuristic extraction")
            return self._extract_essay_sections(essay.text)

        prompt = f"""Analyze this Rabbi Jonathan Sacks essay and extract 4 key sections that follow his characteristic structure. For each section, write a clear, complete 2-3 sentence summary.

ESSAY TITLE: "{essay.title}"

ESSAY TEXT:
{essay.text[:6000]}

---

Extract these 4 sections:

1. THE QUESTION: What textual difficulty, paradox, or moral tension does Rabbi Sacks identify at the start? Summarize the core question he's asking.

2. THE TURN: What unexpected lens does he introduce - philosophical, historical, linguistic, or from another tradition? Summarize this pivotal insight.

3. THE INSIGHT: What is his central synthesis of Torah wisdom with universal truth? Summarize his main teaching.

4. THE CALL: What practical or ethical implication does he draw for our lives today? Summarize his call to action.

Return ONLY valid JSON with no other text:
{{"question": "...", "turn": "...", "insight": "...", "call": "..."}}

Each summary should be 2-3 complete sentences. Do not truncate mid-sentence."""

        try:
            print(f"   DEBUG: Calling Gemini to extract Sacks essay sections...")
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.gemini_client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=2048,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0
                        ),
                    )
                )
            )

            # Parse JSON response
            import json
            response_text = response.text.strip()
            print(f"   DEBUG: Gemini response length: {len(response_text)} chars")

            # Extract JSON from markdown if needed
            if response_text.startswith("```"):
                parts = response_text.split("```")
                if len(parts) >= 2:
                    response_text = parts[1]
                    if response_text.lower().startswith("json"):
                        response_text = response_text[4:].lstrip()
            response_text = response_text.strip()

            sections = json.loads(response_text)
            print(f"   DEBUG: Successfully extracted {len(sections)} sections")
            for key in ["question", "turn", "insight", "call"]:
                if key in sections:
                    preview = sections[key][:80] + "..." if len(sections[key]) > 80 else sections[key]
                    print(f"      {key.upper()}: {preview}")

            return sections

        except Exception as e:
            print(f"   DEBUG: Error extracting sections with Gemini: {e}")
            print(f"   DEBUG: Falling back to heuristic extraction")
            return self._extract_essay_sections(essay.text)

    def _extract_essay_sections(self, essay_text: str) -> dict[str, str]:
        """
        Extract key sections from a Sacks essay following his characteristic structure:

        1. THE QUESTION - Opens with textual difficulty or moral tension
        2. THE TURN - Introduces unexpected lens (philosophy, history, linguistics)
        3. THE INSIGHT - Synthesizes Torah + universal wisdom
        4. THE CALL - Ends with practical/ethical implication
        """
        # Split into paragraphs - handle both \n\n and single \n with blank lines
        raw_paragraphs = essay_text.split("\n")
        paragraphs = []
        current_para = []

        for line in raw_paragraphs:
            line = line.strip()
            if line:
                current_para.append(line)
            elif current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []

        if current_para:
            paragraphs.append(" ".join(current_para))

        # Filter to substantial paragraphs only
        paragraphs = [p for p in paragraphs if len(p) > 50]

        print(f"   DEBUG: Essay has {len(paragraphs)} substantial paragraphs")

        if not paragraphs:
            return {}

        sections = {}
        used_indices = set()

        # ═══════════════════════════════════════════════════════════════
        # 1. THE QUESTION - textual difficulty or moral tension (early paragraphs)
        # ═══════════════════════════════════════════════════════════════
        question_keywords = [
            "why", "how", "what", "?",
            "problem", "difficulty", "puzzle", "paradox", "contradiction",
            "strange", "surprising", "troubling", "perplexing",
        ]

        for i, p in enumerate(paragraphs[:5]):
            p_lower = p.lower()
            # Look for paragraphs with questions or tension words
            if '?' in p or any(kw in p_lower for kw in question_keywords[:3]):
                sections["question"] = self._truncate(p, 400)
                used_indices.add(i)
                print(f"   DEBUG: Found QUESTION at paragraph {i+1}")
                break

        if "question" not in sections and paragraphs:
            sections["question"] = self._truncate(paragraphs[0], 400)
            used_indices.add(0)
            print(f"   DEBUG: Using first paragraph as QUESTION")

        # ═══════════════════════════════════════════════════════════════
        # 2. THE TURN - unexpected lens (philosophy, history, linguistics)
        # ═══════════════════════════════════════════════════════════════
        turn_keywords = [
            "philosopher", "aristotle", "plato", "kant", "hegel", "nietzsche",
            "historian", "history", "century", "ancient", "medieval",
            "hebrew", "linguistic", "word", "root", "etymology",
            "psycholog", "sociolog", "anthropolog",
            "science", "research", "study", "experiment",
            "however", "but consider", "yet there is", "interestingly",
            "rabbi", "talmud", "midrash", "rashi", "ramban", "maimonides",
        ]

        # Look in early-middle paragraphs for the turn
        turn_start = 1
        turn_end = min(len(paragraphs) - 2, len(paragraphs) // 2 + 2)

        for i in range(turn_start, turn_end):
            if i in used_indices:
                continue
            p_lower = paragraphs[i].lower()
            if any(kw in p_lower for kw in turn_keywords):
                sections["turn"] = self._truncate(paragraphs[i], 400)
                used_indices.add(i)
                print(f"   DEBUG: Found TURN at paragraph {i+1}")
                break

        # ═══════════════════════════════════════════════════════════════
        # 3. THE INSIGHT - synthesis of Torah + universal wisdom
        # ═══════════════════════════════════════════════════════════════
        insight_keywords = [
            "therefore", "thus", "this teaches", "the answer", "in other words",
            "what we learn", "the truth is", "this is why", "the key", "the point",
            "here we see", "the lesson", "this means", "we learn", "the message",
            "this is the", "herein lies", "the secret", "the essence",
        ]

        # Look through middle-to-late paragraphs for insight
        middle_start = max(2, len(paragraphs) // 3)
        middle_end = len(paragraphs) - 2

        for i in range(middle_start, middle_end):
            if i in used_indices:
                continue
            p_lower = paragraphs[i].lower()
            if any(kw in p_lower for kw in insight_keywords):
                sections["insight"] = self._truncate(paragraphs[i], 400)
                used_indices.add(i)
                print(f"   DEBUG: Found INSIGHT at paragraph {i+1}")
                break

        # Fallback: use a middle paragraph
        if "insight" not in sections and len(paragraphs) > 4:
            mid_idx = len(paragraphs) // 2
            if mid_idx not in used_indices:
                sections["insight"] = self._truncate(paragraphs[mid_idx], 400)
                used_indices.add(mid_idx)
                print(f"   DEBUG: Using middle paragraph as INSIGHT")

        # ═══════════════════════════════════════════════════════════════
        # 4. THE CALL - practical/ethical implication (final paragraphs)
        # ═══════════════════════════════════════════════════════════════
        call_keywords = [
            "we must", "we should", "let us", "our task", "the challenge",
            "in our time", "today", "for us", "we are called", "that is why",
            "this is what", "this is how", "may we", "it is for us",
            "the choice", "we can", "we have", "our responsibility",
        ]

        # Look in final paragraphs
        for i in range(len(paragraphs) - 1, max(len(paragraphs) - 5, 0), -1):
            if i in used_indices:
                continue
            p_lower = paragraphs[i].lower()
            if any(kw in p_lower for kw in call_keywords):
                sections["call"] = self._truncate(paragraphs[i], 350)
                used_indices.add(i)
                print(f"   DEBUG: Found CALL at paragraph {i+1}")
                break

        # Fallback: use last paragraph
        if "call" not in sections and len(paragraphs) >= 2:
            last_idx = len(paragraphs) - 1
            if last_idx not in used_indices:
                sections["call"] = self._truncate(paragraphs[last_idx], 350)
                print(f"   DEBUG: Using last paragraph as CALL")

        return sections

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text at sentence boundary to avoid incomplete thoughts."""
        if len(text) <= max_chars:
            return text

        # Try to find the last complete sentence within max_chars
        truncated = text[:max_chars]

        # Find last sentence-ending punctuation (. ! ?)
        last_period = max(truncated.rfind('. '), truncated.rfind('! '), truncated.rfind('? '))

        if last_period > max_chars * 0.5:  # Only use if we found one reasonably close
            return truncated[:last_period + 1].strip()

        # Otherwise truncate at word boundary
        truncated = truncated.rsplit(" ", 1)[0]
        return truncated + "..."

    def _get_day_name(self, day: DayOfWeek) -> str:
        """Get day name for display."""
        names = {
            DayOfWeek.SUNDAY: "Sunday",
            DayOfWeek.MONDAY: "Monday",
            DayOfWeek.TUESDAY: "Tuesday",
            DayOfWeek.WEDNESDAY: "Wednesday",
            DayOfWeek.THURSDAY: "Thursday",
            DayOfWeek.FRIDAY: "Friday",
            DayOfWeek.SATURDAY: "Shabbat",
        }
        return names.get(day, "")

    def _verse_sort_key(self, ref: str) -> tuple[int, int]:
        """
        Extract chapter and verse numbers for sorting.

        Handles refs like "Exodus 3:15" -> (3, 15)
        """
        try:
            # Split "Exodus 3:15" -> ["Exodus", "3:15"]
            parts = ref.rsplit(" ", 1)
            if len(parts) == 2:
                chapter_verse = parts[1]
                chapter, verse = chapter_verse.split(":")
                return (int(chapter), int(verse))
        except (ValueError, IndexError):
            pass
        return (0, 0)


def format_for_markdown(output: FormattedOutput) -> str:
    """Convert WhatsApp format to standard Markdown."""
    text = output.text
    # WhatsApp uses *bold* and _italic_, which is already valid Markdown
    # Just need to handle monospace if used
    return text


def format_for_plain_text(output: FormattedOutput) -> str:
    """Convert to plain text (remove formatting)."""
    text = output.text
    # Remove formatting markers
    text = text.replace("*", "")
    text = text.replace("_", "")
    text = text.replace("```", "")
    return text

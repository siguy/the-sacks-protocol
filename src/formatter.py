"""
Output Formatter Module

Formats the generated content for WhatsApp delivery.
Uses WhatsApp-compatible markdown (bold, italic, monospace).
"""

from dataclasses import dataclass
from datetime import date

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
    ):
        self.max_verses = max_verses
        self.max_commentary_chars = max_commentary_chars
        self.max_sacks_chars = max_sacks_chars

    def format_daily_output(
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

        # 2. The Text
        sections.append(self._format_text_section(aliyah_text))

        # 3. The Commentator
        if commentary:
            sections.append(self._format_commentary_section(commentary))

        # 4. The Sacksian Lens
        if sacks_essay:
            sections.append(
                self._format_sacks_section(
                    sacks_essay, today_info.parsha.name_en, relevance_score, is_aliyah_relevant
                )
            )

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

    def _format_text_section(self, aliyah_text: AliyahText) -> str:
        """Format the Torah text section with Hebrew and English."""
        lines = [
            self.THIN_DIVIDER,
            "",
            f"{self.BOLD_START}THE TEXT{self.BOLD_END} · {aliyah_text.aliyah.ref}",
            "",
        ]

        # Show all verses in sequential order
        verses_to_show = sorted(
            aliyah_text.verses,
            key=lambda v: self._verse_sort_key(v.ref)
        )

        for verse in verses_to_show:
            # Hebrew with nikud
            lines.append(verse.hebrew)
            lines.append("")
            # English translation
            lines.append(f"{self.ITALIC_START}{verse.english}{self.ITALIC_END}")
            lines.append(f"— {verse.ref}")
            lines.append("")

        # Attribution
        lines.append(f"Translation: {aliyah_text.translation_source}")

        return "\n".join(lines)

    def _format_commentary_section(self, commentary: Commentary) -> str:
        """Format the traditional commentary section."""
        lines = [
            self.THIN_DIVIDER,
            "",
            f"{self.BOLD_START}THE COMMENTATOR{self.BOLD_END} · {commentary.commentator.name}",
            f"{commentary.commentator.hebrew} · {commentary.commentator.era}",
            f"On {commentary.verse.ref}",
            "",
        ]

        # Show Hebrew text (primary source with dibor haMatchil)
        if commentary.hebrew_text:
            hebrew = commentary.hebrew_text
            if len(hebrew) > self.max_commentary_chars:
                hebrew = hebrew[: self.max_commentary_chars].rsplit(" ", 1)[0] + "..."
            lines.append(hebrew)
            lines.append("")

        # Show English translation if available
        if commentary.english_text:
            english = commentary.english_text
            if len(english) > self.max_commentary_chars:
                english = english[: self.max_commentary_chars].rsplit(" ", 1)[0] + "..."
            lines.append(f"{self.ITALIC_START}{english}{self.ITALIC_END}")
            lines.append("")

        # Selection reason (why this commentary)
        lines.append(
            f"Selected: {commentary.selection_reason}"
        )

        return "\n".join(lines)

    def _format_sacks_section(
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

        # Extract key sections from essay
        # We'll use a simple heuristic: first paragraph as "difficulty", middle as "insight"
        essay_sections = self._extract_essay_sections(essay.text)

        # The Difficulty (opening question/tension)
        if essay_sections.get("difficulty"):
            lines.append(f"{self.BOLD_START}THE DIFFICULTY{self.BOLD_END}")
            lines.append(essay_sections["difficulty"])
            lines.append("")

        # The Insight (core synthesis)
        if essay_sections.get("insight"):
            lines.append(f"{self.BOLD_START}THE INSIGHT{self.BOLD_END}")
            lines.append(essay_sections["insight"])
            lines.append("")

        # The Call (practical implication)
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

    def _extract_essay_sections(self, essay_text: str) -> dict[str, str]:
        """
        Extract key sections from a Sacks essay.

        Uses heuristics to identify:
        - Opening difficulty/question
        - Core insight/synthesis
        - Closing call to action

        This is a simplified extraction - could be enhanced with LLM.
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
        print(f"   DEBUG: Essay text length: {len(essay_text)}")
        if paragraphs:
            print(f"   DEBUG: Paragraph 1 preview: {paragraphs[0][:150]}...")
            if len(paragraphs) > 1:
                print(f"   DEBUG: Paragraph 2 preview: {paragraphs[1][:150]}...")

        if not paragraphs:
            return {}

        sections = {}

        # First substantial paragraph as "difficulty" (usually poses the question)
        # Look for paragraphs that pose substantive questions
        found_difficulty = False

        for i, p in enumerate(paragraphs[:6]):
            p_lower = p.lower()
            # Look for paragraphs with substantive questions (why/how/what + ?)
            if ('why' in p_lower or 'how' in p_lower or 'what' in p_lower) and '?' in p:
                sections["difficulty"] = self._truncate(p, 450)
                found_difficulty = True
                print(f"   DEBUG: Found difficulty at paragraph {i+1} with question")
                break

        if not found_difficulty and paragraphs:
            # Fall back to first substantial paragraph
            sections["difficulty"] = self._truncate(paragraphs[0], 450)
            print(f"   DEBUG: Using first paragraph as difficulty")

        # Middle section as "insight" (look for paragraphs with key Sacks synthesis words)
        insight_keywords = [
            "therefore", "thus", "this teaches", "the answer", "in other words",
            "what we learn", "the truth is", "this is why", "the key", "the point",
            "here we see", "the lesson", "this means", "we learn", "the message",
        ]

        # Look through middle paragraphs for insight
        middle_start = max(2, len(paragraphs) // 4)
        middle_end = min(len(paragraphs) - 2, 3 * len(paragraphs) // 4)

        for p in paragraphs[middle_start:middle_end]:
            p_lower = p.lower()
            if any(kw in p_lower for kw in insight_keywords):
                sections["insight"] = self._truncate(p, 450)
                print(f"   DEBUG: Found insight with keyword")
                break

        # If no insight found, use a middle paragraph
        if "insight" not in sections and len(paragraphs) > 4:
            mid_idx = len(paragraphs) // 2
            sections["insight"] = self._truncate(paragraphs[mid_idx], 450)
            print(f"   DEBUG: Using middle paragraph as insight")

        # Last substantial paragraph as "call" (usually practical application)
        # Look for action-oriented or concluding language
        call_keywords = ["we must", "we should", "let us", "our task", "the challenge",
                         "in our time", "today", "for us", "we are called", "that is why",
                         "this is what", "this is how"]

        found_call = False
        for i, p in enumerate(reversed(paragraphs[-5:])):
            p_lower = p.lower()
            if any(kw in p_lower for kw in call_keywords):
                sections["call"] = self._truncate(p, 400)
                found_call = True
                print(f"   DEBUG: Found call at paragraph {len(paragraphs)-i} with keyword")
                break

        # Fall back to last paragraph if no call found
        if not found_call and len(paragraphs) >= 2:
            sections["call"] = self._truncate(paragraphs[-1], 400)
            print(f"   DEBUG: Using last paragraph as call")

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

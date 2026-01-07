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

        # Use key verses (most important by link count)
        verses_to_show = aliyah_text.key_verses[: self.max_verses]

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

        # Commentary text (prefer English, truncate if needed)
        text = commentary.english_text or commentary.hebrew_text
        if len(text) > self.max_commentary_chars:
            text = text[: self.max_commentary_chars].rsplit(" ", 1)[0] + "..."

        lines.append(text)
        lines.append("")

        # Selection reason (why this commentary)
        lines.append(
            f"{self.ITALIC_START}Selected: {commentary.selection_reason}{self.ITALIC_END}"
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
        # Split into paragraphs
        paragraphs = [p.strip() for p in essay_text.split("\n\n") if p.strip()]

        if not paragraphs:
            return {}

        sections = {}

        # First substantial paragraph as "difficulty" (usually poses the question)
        for p in paragraphs[:3]:
            if len(p) > 100:  # Skip very short intros
                sections["difficulty"] = self._truncate(p, 300)
                break

        # Middle section as "insight" (look for paragraphs with key Sacks words)
        insight_keywords = [
            "therefore", "thus", "this teaches", "the answer", "in other words",
            "what we learn", "the truth is", "this is why", "the key",
        ]

        for p in paragraphs[2:-2]:  # Skip first and last few
            p_lower = p.lower()
            if any(kw in p_lower for kw in insight_keywords):
                sections["insight"] = self._truncate(p, 400)
                break

        # If no insight found, use a middle paragraph
        if "insight" not in sections and len(paragraphs) > 3:
            mid_idx = len(paragraphs) // 2
            sections["insight"] = self._truncate(paragraphs[mid_idx], 400)

        # Last substantial paragraph as "call" (usually practical application)
        for p in reversed(paragraphs[-3:]):
            if len(p) > 80:
                sections["call"] = self._truncate(p, 250)
                break

        return sections

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text at word boundary."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars].rsplit(" ", 1)[0]
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

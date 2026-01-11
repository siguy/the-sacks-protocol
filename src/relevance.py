"""
LLM Relevance Scoring Module (Method C)

Uses Gemini to score the relevance of Sacks essays to specific aliyot.
Supports both runtime scoring and pre-computation.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from .sacks import SacksEssay
from .aliyah import AliyahText


@dataclass
class RelevanceScore:
    """Relevance score for an essay-aliyah pair."""

    score: int  # 1-5 scale
    connection_type: str  # direct, thematic, tangential, none
    key_overlap: list[str]  # Elements from aliyah that essay addresses
    explanation: str  # Brief reasoning


@dataclass
class EssayRelevance:
    """Relevance data for an essay across all aliyot."""

    essay_title: str
    sefaria_ref: str
    aliyah_scores: dict[int, RelevanceScore]  # aliyah_num -> score
    best_aliyah: int | None  # Aliyah with highest score


SYSTEM_PROMPT = """You are a scholarly assistant evaluating the relevance of Rabbi Jonathan Sacks' essays to specific Torah portions.

Your task: Determine how directly an essay addresses the content, themes, or verses in a given aliyah (Torah reading section).

# Relevance Scale

5 - DIRECT: Essay explicitly discusses events, characters, or verses from this aliyah
4 - STRONG: Essay's central theme is clearly present in this aliyah's narrative
3 - MODERATE: Essay touches on themes visible in this aliyah, but not centrally
2 - TANGENTIAL: Loose thematic connection only
1 - NONE: No meaningful connection

# Response Format (JSON only)

{
  "score": <1-5>,
  "connection_type": "direct|strong|moderate|tangential|none",
  "key_overlap": ["<specific elements from aliyah that essay addresses>"],
  "explanation": "<1-2 sentence reasoning>"
}

Respond with only valid JSON. No additional text."""


class RelevanceScorer:
    """Scores essay relevance to aliyot using Gemini."""

    def __init__(
        self,
        model: str = "gemini-3-flash-preview",
        data_dir: Path | None = None,
    ):
        self.model = model
        self.data_dir = data_dir or Path(__file__).parent.parent / "data" / "relevance"
        self._client: Any = None

    def _get_client(self):
        """Get or create Gemini client."""
        if self._client is None:
            if genai is None:
                raise ImportError("google-genai package required. Install with: pip install google-genai")

            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("GOOGLE_API_KEY environment variable required")

            self._client = genai.Client(api_key=api_key)

        return self._client

    async def score_essay_aliyah(
        self,
        essay: SacksEssay,
        aliyah_text: AliyahText,
    ) -> RelevanceScore:
        """
        Score the relevance of an essay to a specific aliyah.

        Uses Gemini to evaluate the connection.
        """
        # Build the user prompt
        user_prompt = self._build_prompt(essay, aliyah_text)

        # Call Gemini (sync API, run in executor for async)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._call_gemini(user_prompt),
        )

        # Parse the response
        return self._parse_response(response)

    def _build_prompt(self, essay: SacksEssay, aliyah_text: AliyahText) -> str:
        """Build the prompt for relevance scoring."""
        # Get aliyah summary
        aliyah_info = aliyah_text.aliyah
        key_verses_text = "\n".join(
            f"- {v.ref}: {v.english[:150]}..." for v in aliyah_text.key_verses[:3]
        )

        # Get essay excerpt (first 800 words to stay within context limits)
        essay_words = essay.text.split()
        essay_excerpt = " ".join(essay_words[:800])
        if len(essay_words) > 800:
            essay_excerpt += "..."

        return f"""## Aliyah
**Reference:** {aliyah_info.ref} (Aliyah {aliyah_info.number})

**Key verses:**
{key_verses_text}

---

## Essay
**Title:** "{essay.title}"
**Source:** {essay.series}, {essay.parsha}

**Text:**
{essay_excerpt}

---

Rate the relevance of this essay to this aliyah."""

    def _call_gemini(self, user_prompt: str) -> str:
        """Make a synchronous call to Gemini API."""
        client = self._get_client()

        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=1024,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=0  # Disable thinking for JSON response
                ),
            )
        )

        return response.text

    def _parse_response(self, response: str) -> RelevanceScore:
        """Parse Gemini's JSON response into a RelevanceScore."""
        try:
            # Clean up response - extract JSON from markdown code blocks
            cleaned = response.strip()
            if cleaned.startswith("```"):
                parts = cleaned.split("```")
                if len(parts) >= 2:
                    cleaned = parts[1]
                    # Remove language identifier (json, JSON, etc.) with any whitespace
                    if cleaned.lower().startswith("json"):
                        cleaned = cleaned[4:].lstrip()
            cleaned = cleaned.strip()

            data = json.loads(cleaned)

            return RelevanceScore(
                score=int(data.get("score", 1)),
                connection_type=data.get("connection_type", "none"),
                key_overlap=data.get("key_overlap", []),
                explanation=data.get("explanation", ""),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Return a default low score on parse failure
            return RelevanceScore(
                score=1,
                connection_type="none",
                key_overlap=[],
                explanation=f"Parse error: {e}",
            )

    # ─────────────────────────────────────────────────────────────
    # Pre-computation methods
    # ─────────────────────────────────────────────────────────────

    async def precompute_parsha_relevance(
        self,
        parsha: str,
        essays: list[SacksEssay],
        aliyah_texts: list[AliyahText],
    ) -> dict[str, EssayRelevance]:
        """
        Pre-compute relevance scores for all essay-aliyah pairs in a parsha.

        Args:
            parsha: Parsha name
            essays: List of Sacks essays for this parsha
            aliyah_texts: List of AliyahText for all 7 aliyot

        Returns:
            Dict mapping essay title to EssayRelevance
        """
        results = {}

        for essay in essays:
            aliyah_scores = {}
            best_aliyah = None
            best_score = 0

            for aliyah_text in aliyah_texts:
                aliyah_num = aliyah_text.aliyah.number

                # Score this essay-aliyah pair
                score = await self.score_essay_aliyah(essay, aliyah_text)
                aliyah_scores[aliyah_num] = score

                if score.score > best_score:
                    best_score = score.score
                    best_aliyah = aliyah_num

                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)

            results[essay.title] = EssayRelevance(
                essay_title=essay.title,
                sefaria_ref=essay.sefaria_ref,
                aliyah_scores=aliyah_scores,
                best_aliyah=best_aliyah if best_score >= 4 else None,
            )

        return results

    def save_relevance_data(self, parsha: str, data: dict[str, EssayRelevance]) -> None:
        """Save pre-computed relevance data to YAML file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Convert to serializable format
        output = {
            "parsha": parsha,
            "essays": [],
        }

        for essay_rel in data.values():
            essay_data = {
                "title": essay_rel.essay_title,
                "sefaria_ref": essay_rel.sefaria_ref,
                "best_aliyah": essay_rel.best_aliyah,
                "aliyah_relevance": {},
            }

            for aliyah_num, score in essay_rel.aliyah_scores.items():
                essay_data["aliyah_relevance"][aliyah_num] = {
                    "score": score.score,
                    "connection": score.connection_type,
                    "overlap": score.key_overlap,
                    "note": score.explanation,
                }

            output["essays"].append(essay_data)

        # Save to file
        file_path = self.data_dir / f"{parsha.lower().replace(' ', '_')}.yaml"
        with open(file_path, "w") as f:
            yaml.dump(output, f, default_flow_style=False, allow_unicode=True)

    def load_relevance_data(self, parsha: str) -> dict[str, EssayRelevance] | None:
        """Load pre-computed relevance data from YAML file."""
        file_path = self.data_dir / f"{parsha.lower().replace(' ', '_')}.yaml"

        if not file_path.exists():
            return None

        with open(file_path) as f:
            data = yaml.safe_load(f)

        results = {}
        for essay_data in data.get("essays", []):
            aliyah_scores = {}

            for aliyah_num, score_data in essay_data.get("aliyah_relevance", {}).items():
                aliyah_scores[int(aliyah_num)] = RelevanceScore(
                    score=score_data.get("score", 1),
                    connection_type=score_data.get("connection", "none"),
                    key_overlap=score_data.get("overlap", []),
                    explanation=score_data.get("note", ""),
                )

            results[essay_data["title"]] = EssayRelevance(
                essay_title=essay_data["title"],
                sefaria_ref=essay_data.get("sefaria_ref", ""),
                aliyah_scores=aliyah_scores,
                best_aliyah=essay_data.get("best_aliyah"),
            )

        return results

    # ─────────────────────────────────────────────────────────────
    # Selection methods
    # ─────────────────────────────────────────────────────────────

    def select_best_essay(
        self,
        essays: list[SacksEssay],
        relevance_data: dict[str, EssayRelevance] | None,
        aliyah_num: int,
        threshold: int = 4,
        aliyah_keywords: list[str] | None = None,
    ) -> tuple[SacksEssay | None, RelevanceScore | None, bool]:
        """
        Select the best essay for a specific aliyah.

        Args:
            essays: Available essays
            relevance_data: Pre-computed relevance (if available)
            aliyah_num: Current aliyah number
            threshold: Minimum score to consider "relevant"
            aliyah_keywords: Keywords from aliyah for heuristic matching

        Returns:
            (selected_essay, relevance_score, is_aliyah_relevant)
        """
        if not essays:
            return None, None, False

        if relevance_data:
            # Use pre-computed scores
            best_essay = None
            best_score = None
            highest_score = 0

            for essay in essays:
                rel = relevance_data.get(essay.title)
                if rel and aliyah_num in rel.aliyah_scores:
                    score = rel.aliyah_scores[aliyah_num]
                    if score.score > highest_score:
                        highest_score = score.score
                        best_essay = essay
                        best_score = score

            if best_essay and highest_score >= threshold:
                return best_essay, best_score, True

            # No strong match - skip essay for this day
            return None, best_score, False

        # No relevance data - use heuristic title/content matching
        # Only return essay if it has a reasonable keyword match
        best_essay, match_score = self._heuristic_select(essays, aliyah_keywords)
        if match_score >= 3:  # At least 3 keyword matches
            return best_essay, None, False
        return None, None, False

    def _heuristic_select(
        self,
        essays: list[SacksEssay],
        aliyah_keywords: list[str] | None,
    ) -> tuple[SacksEssay | None, int]:
        """
        Select essay using heuristic keyword matching when no relevance data available.

        Returns:
            (essay, match_score) - essay with highest score and the score value
        """
        print(f"   DEBUG: Heuristic essay selection")
        print(f"   DEBUG: Keywords from aliyah: {aliyah_keywords}")

        if not aliyah_keywords or not essays:
            print(f"   DEBUG: No keywords or essays, returning None")
            return None, 0

        # Score each essay by keyword matches in title and first 500 chars of text
        scored = []
        keywords_lower = [kw.lower() for kw in aliyah_keywords]

        for essay in essays:
            score = 0
            title_lower = essay.title.lower()
            text_start = essay.text[:500].lower()
            matches = []

            for kw in keywords_lower:
                # Title matches weighted more heavily
                if kw in title_lower:
                    score += 3
                    matches.append(f"title:{kw}")
                if kw in text_start:
                    score += 1
                    matches.append(f"text:{kw}")

            scored.append((score, essay, matches))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Debug output: top 3 essays with scores
        print(f"   DEBUG: Essay scores (top 3):")
        for i, (score, essay, matches) in enumerate(scored[:3]):
            print(f"      {i+1}. \"{essay.title}\" - score: {score}")
            if matches:
                print(f"         Matches: {', '.join(matches[:5])}")

        # Return highest scoring essay and its score
        best_score, best_essay, _ = scored[0]
        return best_essay, best_score

    # ─────────────────────────────────────────────────────────────
    # Weekly Greedy Matching
    # ─────────────────────────────────────────────────────────────

    def compute_weekly_assignments(
        self,
        essays: list[SacksEssay],
        aliyah_texts: dict[int, "AliyahText"],
        book: str,
        threshold: int = 3,
    ) -> dict[int, tuple[SacksEssay, dict] | None]:
        """
        Compute essay-to-aliyah assignments for the week using greedy matching.

        Algorithm:
        1. Score ALL essays against ALL aliyot (verse matching + theme matching)
        2. Build score matrix
        3. Greedy assign: highest score wins, each essay used at most once
        4. Return mapping of aliyah_num -> (essay, score_data) or None

        Args:
            essays: List of Sacks essays for this parsha
            aliyah_texts: Dict mapping aliyah_num -> AliyahText
            book: Torah book name (e.g., "Exodus")
            threshold: Minimum score to assign an essay

        Returns:
            Dict mapping aliyah_num -> (essay, score_data) or None if no match
        """
        import re

        print("   📊 Computing weekly essay assignments (greedy matching)...")

        if not essays or not aliyah_texts:
            return {num: None for num in aliyah_texts.keys()}

        # Build score matrix: aliyah_num -> {essay_title: score_data}
        score_matrix: dict[int, dict[str, dict]] = {}

        for aliyah_num, aliyah_text in aliyah_texts.items():
            score_matrix[aliyah_num] = {}
            aliyah_ref = aliyah_text.aliyah.ref

            for essay in essays:
                score_data = self._score_essay_for_aliyah(
                    essay, aliyah_text, aliyah_ref, book
                )
                score_matrix[aliyah_num][essay.title] = score_data

        # Greedy matching
        assignments = self._greedy_match(score_matrix, essays, threshold)

        # Log results
        for aliyah_num in sorted(aliyah_texts.keys()):
            if aliyah_num in assignments and assignments[aliyah_num]:
                essay, score_data = assignments[aliyah_num]
                print(f"      Aliyah {aliyah_num}: \"{essay.title}\" (score: {score_data['total_score']})")
            else:
                print(f"      Aliyah {aliyah_num}: NO ESSAY")

        return assignments

    def _score_essay_for_aliyah(
        self,
        essay: SacksEssay,
        aliyah_text: "AliyahText",
        aliyah_ref: str,
        book: str,
    ) -> dict:
        """Score an essay's relevance to an aliyah using verse + theme matching."""
        import re

        result = {
            "verse_score": 0,
            "verse_matches": [],
            "theme_score": 0,
            "theme_matches": [],
            "total_score": 0,
        }

        # 1. VERSE MATCHING (10 pts each)
        essay_verses = self._extract_verse_refs(essay.text, book)
        start_ch, start_v, end_ch, end_v = self._parse_aliyah_range(aliyah_ref)

        for ch, v in essay_verses:
            if self._verse_in_range(ch, v, start_ch, start_v, end_ch, end_v):
                result["verse_matches"].append(f"{ch}:{v}")
                result["verse_score"] += 10

        # 2. THEMATIC MATCHING (3 pts each)
        aliyah_themes = self._generate_aliyah_themes(aliyah_text)
        essay_themes = self._generate_essay_themes(essay)

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

    def _extract_verse_refs(self, text: str, book: str) -> list[tuple[int, int]]:
        """Extract verse references from essay text."""
        import re
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

    def _parse_aliyah_range(self, ref: str) -> tuple[int, int, int, int]:
        """Parse aliyah reference to get start/end chapter:verse."""
        import re
        match = re.search(r'(\d+):(\d+)-(?:(\d+):)?(\d+)', ref)
        if match:
            start_ch = int(match.group(1))
            start_v = int(match.group(2))
            end_ch = int(match.group(3)) if match.group(3) else start_ch
            end_v = int(match.group(4))
            return (start_ch, start_v, end_ch, end_v)
        return (0, 0, 0, 0)

    def _verse_in_range(
        self, chapter: int, verse: int,
        start_ch: int, start_v: int,
        end_ch: int, end_v: int
    ) -> bool:
        """Check if a verse falls within an aliyah range."""
        if chapter < start_ch or chapter > end_ch:
            return False
        if chapter == start_ch and verse < start_v:
            return False
        if chapter == end_ch and verse > end_v:
            return False
        return True

    def _generate_aliyah_themes(self, aliyah_text: "AliyahText") -> set[str]:
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

    def _generate_essay_themes(self, essay: SacksEssay) -> set[str]:
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

    def _greedy_match(
        self,
        score_matrix: dict[int, dict[str, dict]],
        essays: list[SacksEssay],
        threshold: int,
    ) -> dict[int, tuple[SacksEssay, dict] | None]:
        """
        Greedy matching algorithm.

        Args:
            score_matrix: {aliyah_num: {essay_title: score_data}}
            essays: List of essays (for lookup by title)
            threshold: Minimum score to assign

        Returns:
            {aliyah_num: (essay, score_data) or None}
        """
        # Build essay lookup
        essay_by_title = {e.title: e for e in essays}

        # Flatten to list of (score, aliyah_num, essay_title, score_data)
        all_scores = []
        for aliyah_num, essays_scores in score_matrix.items():
            for essay_title, score_data in essays_scores.items():
                all_scores.append((
                    score_data["total_score"],
                    aliyah_num,
                    essay_title,
                    score_data
                ))

        # Sort by score descending
        all_scores.sort(key=lambda x: x[0], reverse=True)

        # Greedy assignment
        assignments: dict[int, tuple[SacksEssay, dict] | None] = {}
        used_essays: set[str] = set()

        for score, aliyah_num, essay_title, score_data in all_scores:
            # Skip if aliyah already has an essay or essay already used
            if aliyah_num in assignments:
                continue
            if essay_title in used_essays:
                continue
            # Skip if score below threshold
            if score < threshold:
                continue

            essay = essay_by_title.get(essay_title)
            if essay:
                assignments[aliyah_num] = (essay, score_data)
                used_essays.add(essay_title)

        # Fill in None for unassigned aliyot
        for aliyah_num in score_matrix.keys():
            if aliyah_num not in assignments:
                assignments[aliyah_num] = None

        return assignments


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of RelevanceScorer."""
    print("RelevanceScorer requires GOOGLE_API_KEY environment variable.")
    print("Use scripts/compute_relevance.py to pre-compute scores.")


if __name__ == "__main__":
    asyncio.run(main())

"""
LLM Relevance Scoring Module (Method C)

Uses Claude to score the relevance of Sacks essays to specific aliyot.
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
    import anthropic
except ImportError:
    anthropic = None

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
    """Scores essay relevance to aliyot using Claude."""

    def __init__(
        self,
        model: str = "claude-3-haiku-20240307",
        data_dir: Path | None = None,
    ):
        self.model = model
        self.data_dir = data_dir or Path(__file__).parent.parent / "data" / "relevance"
        self._client: Any = None

    def _get_client(self):
        """Get or create Anthropic client."""
        if self._client is None:
            if anthropic is None:
                raise ImportError("anthropic package required. Install with: pip install anthropic")

            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable required")

            self._client = anthropic.Anthropic(api_key=api_key)

        return self._client

    async def score_essay_aliyah(
        self,
        essay: SacksEssay,
        aliyah_text: AliyahText,
    ) -> RelevanceScore:
        """
        Score the relevance of an essay to a specific aliyah.

        Uses Claude to evaluate the connection.
        """
        # Build the user prompt
        user_prompt = self._build_prompt(essay, aliyah_text)

        # Call Claude (sync API, run in executor for async)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._call_claude(user_prompt),
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

    def _call_claude(self, user_prompt: str) -> str:
        """Make a synchronous call to Claude API."""
        client = self._get_client()

        message = client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            system=SYSTEM_PROMPT,
        )

        return message.content[0].text

    def _parse_response(self, response: str) -> RelevanceScore:
        """Parse Claude's JSON response into a RelevanceScore."""
        try:
            # Clean up response (remove any markdown code blocks)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
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

            # No strong match - return first essay without relevance claim
            return essays[0], best_score, False

        # No relevance data - use heuristic title/content matching
        best_essay = self._heuristic_select(essays, aliyah_keywords)
        return best_essay, None, False

    def _heuristic_select(
        self,
        essays: list[SacksEssay],
        aliyah_keywords: list[str] | None,
    ) -> SacksEssay:
        """
        Select essay using heuristic keyword matching when no relevance data available.
        """
        if not aliyah_keywords or not essays:
            return essays[0] if essays else None

        # Score each essay by keyword matches in title and first 500 chars of text
        scored = []
        keywords_lower = [kw.lower() for kw in aliyah_keywords]

        for essay in essays:
            score = 0
            title_lower = essay.title.lower()
            text_start = essay.text[:500].lower()

            for kw in keywords_lower:
                # Title matches weighted more heavily
                if kw in title_lower:
                    score += 3
                if kw in text_start:
                    score += 1

            scored.append((score, essay))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Return highest scoring essay (or first if no matches)
        return scored[0][1]


# ─────────────────────────────────────────────────────────────────
# Standalone usage
# ─────────────────────────────────────────────────────────────────


async def main():
    """Example usage of RelevanceScorer."""
    print("RelevanceScorer requires ANTHROPIC_API_KEY environment variable.")
    print("Use scripts/compute_relevance.py to pre-compute scores.")


if __name__ == "__main__":
    asyncio.run(main())

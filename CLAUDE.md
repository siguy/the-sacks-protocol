# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Core Goal**: Deliver daily Torah wisdom grounded in the traditional Jewish learning cycle.

**Current Implementation** generates structured content combining:
1. Today's aliyah (Torah portion section) in Hebrew with nikud and English (Koren translation)
2. Traditional commentary selected by day-of-week rotation
3. Rabbi Lord Jonathan Sacks' essay from Covenant & Conversation, with relevance scoring

Output is WhatsApp-formatted markdown saved to `output/YYYY-MM-DD_parsha.md`.

This structure is designed to be flexible and can evolve. The core principle is daily wisdom delivery synchronized with the weekly Torah reading cycle.

## Setup & Environment

```bash
# Install for development
pip install -e ".[dev]"

# Configure environment (REQUIRED)
cp .env.example .env
# Edit .env and add your Anthropic API key:
#   ANTHROPIC_API_KEY=sk-ant-...
# Get your key at: https://console.anthropic.com/
```

**Note**: The Anthropic API key is required for essay relevance scoring. Without it, the generator will fall back to heuristic keyword matching.

## Core Commands

```bash
# Generate today's output
python3 -m src.generator

# Run tests
pytest

# Lint code
ruff check src/
ruff format src/
```

## Architecture: Pipeline Flow

```
Calendar → Aliyah Text → Commentary → Sacks Essay → Formatter
   ↓           ↓             ↓            ↓            ↓
Hebrew    Key Verses    Link Graph   Relevance    WhatsApp
Calendar   + English    + Rotation    Scoring     Markdown
```

The main orchestrator is `src/generator.py`, which coordinates:
1. **Calendar** (`calendar.py`): Maps date → parsha → aliyah number via `data/aliyot.yaml`
2. **Aliyah** (`aliyah.py`): Fetches Torah text from Sefaria API v2, identifies key verses by link count
3. **Commentary** (`commentary.py`): Selects commentator by day-of-week rotation (`config/rotation.yaml`) on the most-linked verse
4. **Sacks** (`sacks.py`): Retrieves essays for this week's parsha from Sefaria
5. **Relevance** (`relevance.py`): Scores essays against aliyah using pre-computed LLM scores or heuristic keyword matching
6. **Formatter** (`formatter.py`): Extracts essay sections (difficulty/insight/call) and formats output

## Critical Implementation Details

### Sefaria API
- Base URL: `https://www.sefaria.org/api`
- All requests go through `SefariaClient` async context manager
- **Text requests** use standard `/texts/` endpoint (not v2 or v3):
  - Endpoint: `/texts/{ref}` with query params
  - Use `ven` (English version) and `vhe` (Hebrew version) query params, NOT URL path
  - Correct: `/texts/Exodus%203:1?ven=The%20Koren%20Jerusalem%20Bible`
  - Wrong: `/texts/Exodus%203:1/The%20Koren%20Jerusalem%20Bible`
- **Index requests** use v2: `/v2/index/{title}`
- **URL encoding**: Use `urllib.parse.quote(ref, safe=':;,-')` for refs in path
- **Spanning refs**: Multi-chapter ranges (e.g., "Exodus 3:16-4:17") return `isSpanning=True` and `spanningRefs` array
  - Parse `spanningRefs` to handle chapter boundaries correctly
  - Example: `["Exodus 3:16-22", "Exodus 4:1-17"]` tells you when to increment chapter number

### Verse Numbering
When building verses from API response in `aliyah.py`:
- Single chapter: Calculate `end_verse - start_verse + 1`
- Multi-chapter: Parse `spanningRefs` to determine chapter boundaries and increment chapter number at the right time
- Always slice `hebrew_texts` and `english_texts` arrays to match expected verse count

### Essay Section Extraction
The `_extract_essay_sections()` in `formatter.py` uses heuristics:
- **Difficulty**: Look for paragraphs with questions (why/how/what + ?)
- **Insight**: Search middle paragraphs for synthesis keywords ("therefore", "thus", "this teaches", "the answer")
- **Call**: Find action-oriented language in final paragraphs ("we must", "let us", "our task")
- Always truncate at sentence boundaries, not mid-sentence (check for `. ` or `? ` or `! `)

### Commentary Rotation
Daily rotation defined in `config/rotation.yaml`:
- Sunday: Rashi (foundational pshat)
- Monday: Ramban (philosophical)
- Tuesday: Midrash Rabbah (aggadic)
- Wednesday: Chassidic (Sefat Emet, Or HaChaim)
- Thursday: Ibn Ezra/Sforno (rationalist)
- Friday: Or HaChaim (mystical, Shabbat prep)

Selection uses link graph: the verse with the most commentary links is the "key verse" for that aliyah.

### Translation Source
- **Always use**: "The Koren Jerusalem Bible" for English (not JPS)
- Verify with `translation_source` field from API response
- Koren uses transliterated Hebrew names: "Moshe", "Aharon", "Yisra'el"

## Common Issues & Self-Correction

### Issue: Wrong verse count
**Problem**: API returns full chapter(s), but aliyah is a subset
**Fix**: Calculate expected verses from ref range, slice arrays to `expected_count`

### Issue: Verse numbering jumps (e.g., 3:22 → 3:23 instead of 4:1)
**Problem**: Not detecting chapter boundaries in multi-chapter refs
**Fix**: Check `text_data.get('isSpanning')` and parse `spanningRefs` to know when to increment `current_chapter`

### Issue: English translation shows JPS instead of Koren
**Problem**: Not passing version parameter correctly
**Fix**: Use `ven="The Koren Jerusalem Bible"` as query param, not in URL path

### Issue: Essay sections are mid-sentence fragments
**Problem**: Truncating at character count, not sentence boundary
**Fix**: In `_truncate()`, find last `. ` or `? ` or `! ` within max_chars before cutting

### Issue: Essay sections don't match essay title
**Problem**: Keywords matching wrong paragraphs or extraction logic broken
**Fix**: Add debug logging to show which paragraph was selected and why; verify paragraph parsing splits correctly on `\n\n` and individual `\n` with blank lines

## Data Files

- `data/aliyot.yaml`: Verse ranges for all 7 aliyot of every parsha
- `config/rotation.yaml`: Day-of-week to commentator mapping
- `data/relevance/`: Pre-computed LLM scores for essay-to-aliyah relevance
  - Currently empty (directory exists but no pre-computed scores yet)
  - Run `python3 scripts/compute_relevance.py` to generate scores
  - Without pre-computed scores, system falls back to heuristic keyword matching
  - Format: `{parsha}_{aliyah}.json` files containing essay-to-aliyah relevance scores

## Core Principles

These principles guide the current implementation and should inform future iterations:

- **Synchronized with tradition**: Delivery follows the Jewish weekly Torah reading cycle
- **Daily cadence**: One meaningful piece of wisdom per day, tied to that day's learning
- **Source integrity**: Rabbi Sacks' essays are coherent wholes; extract representative sections but never split/chunk the essay itself
- **Quality over quantity**: Better to deliver one well-chosen commentary than multiple mediocre ones

## Current Implementation Constraints

- **Aliyah-based**: Each weekday corresponds to one aliyah (Friday = aliyot 6+7)
- **Link graph drives commentary**: The most-linked verse is automatically the most important verse
- **Koren translation only**: Matches Rabbi Sacks' preference for accuracy over flowery English

## Systematic Error Detection

When making changes or debugging, cycle through these checks:

### 1. Executability Test
- Run each command in "Core Commands" to verify they work
- Check that error messages are helpful and actionable
- Verify prerequisites are met (API keys, dependencies)

### 2. File/Path Validation
- Verify all referenced files exist: `ls data/aliyot.yaml config/rotation.yaml`
- Check that documented directory structures match reality
- Ensure config files match their documented schemas

### 3. API Cross-Reference
- Compare API endpoint examples in docs vs actual code usage
- Verify function signatures match their documented usage
- Test that code examples actually run

### 4. Dependency Check
- Cross-reference imports with `pyproject.toml` dependencies
- Verify environment variables are documented and .env.example is current
- Test fresh install: `pip install -e ".[dev]"` in clean virtualenv

### 5. Output Validation
- Generate output: `python3 -m src.generator`
- Check output format matches documented structure
- Verify all three sections appear (Text, Commentary, Sacksian Lens)

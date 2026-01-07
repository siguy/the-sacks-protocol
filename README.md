# The Sacks Protocol

A wisdom extraction pipeline that delivers daily insights from Rabbi Lord Jonathan Sacks' Torah commentary, grounded in the traditional Jewish learning cycle.

## What It Does

Each day, The Sacks Protocol generates a structured message containing:

1. **The Text** - Today's aliyah (Torah portion section) with Hebrew (nikud) and English translation
2. **The Commentator** - A classical or Chassidic commentary on the key verse, rotating daily
3. **The Sacksian Lens** - Rabbi Sacks' wisdom on this week's parsha, with relevance to today's reading when available

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   DAILY GENERATION                   │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Calendar → What parsha/aliyah is today?            │
│      ↓                                               │
│  Aliyah → Fetch Hebrew + English text               │
│      ↓                                               │
│  Commentary → Find key verse, select commentator    │
│      ↓                                               │
│  Sacks → Get essays, check relevance to aliyah      │
│      ↓                                               │
│  Formatter → Generate WhatsApp-ready output         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

## Data Sources

- **Sefaria API** - Torah text, commentaries, Rabbi Sacks' Covenant & Conversation
- **Pre-computed relevance scores** - LLM-scored essay-to-aliyah mappings

## Daily Cadence

| Day | Aliyah | Commentary Track |
|-----|--------|------------------|
| Sunday | 1 | Rashi (foundational) |
| Monday | 2 | Ramban (philosophical) |
| Tuesday | 3 | Midrash (aggadic) |
| Wednesday | 4 | Chassidic (spiritual) |
| Thursday | 5 | Ibn Ezra/Sforno (rationalist) |
| Friday | 6 + 7 | Or HaChaim (mystical, Shabbat prep) |

## Setup

```bash
# Clone and install
cd the-sacks-protocol
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your Anthropic API key

# Generate today's output
python -m src.generator
```

## Project Structure

```
├── src/
│   ├── sefaria_client.py   # Sefaria API wrapper
│   ├── calendar.py         # Jewish calendar + aliyah mapping
│   ├── aliyah.py           # Aliyah text retrieval
│   ├── commentary.py       # Commentary selection (link graph + rotation)
│   ├── sacks.py            # Sacks essay retrieval
│   ├── relevance.py        # LLM relevance scoring
│   ├── formatter.py        # Output formatting
│   └── generator.py        # Main orchestrator
├── config/
│   ├── rotation.yaml       # Day → Commentator mapping
│   └── settings.yaml       # API and output settings
├── data/
│   └── relevance/          # Pre-computed essay-aliyah scores
├── scripts/
│   └── compute_relevance.py  # One-time relevance computation
└── output/                 # Generated daily outputs
```

## Philosophy

> "I have called these studies Covenant & Conversation because this, for me,
> is the essence of what Torah learning is – throughout the ages, and for us, now."
> — Rabbi Lord Jonathan Sacks

This project honors that vision by:
- Grounding each day in the primary text (aliyah)
- Layering traditional commentary (Rashi, Ramban, etc.)
- Adding Rabbi Sacks' unique synthesis of Torah and universal wisdom
- Respecting the integrity of his essays (no chunking)

## License

MIT

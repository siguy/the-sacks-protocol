#!/usr/bin/env python3
"""
Test Gemini API Integration

Tests:
1. Basic API connection
2. System prompt handling
3. JSON response parsing (matching our relevance scoring format)
"""

import os
import json
from pathlib import Path

# Load .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Import Gemini SDK
try:
    import google.generativeai as genai
except ImportError:
    print("ERROR: google-generativeai not installed")
    print("Run: pip install google-generativeai")
    exit(1)


# Same system prompt we use in relevance.py
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


def test_basic_connection():
    """Test 1: Basic API connection"""
    print("\n" + "=" * 50)
    print("TEST 1: Basic API Connection")
    print("=" * 50)

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("❌ FAILED: GOOGLE_API_KEY not found in environment")
        return False

    print(f"✓ API key found: {api_key[:10]}...")

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        response = model.generate_content("Say 'Hello, Sacks Protocol!' in exactly those words.")
        print(f"✓ Response received: {response.text[:50]}...")
        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_system_prompt():
    """Test 2: System prompt handling"""
    print("\n" + "=" * 50)
    print("TEST 2: System Prompt Handling")
    print("=" * 50)

    api_key = os.environ.get("GOOGLE_API_KEY")
    genai.configure(api_key=api_key)

    try:
        # Create model with system instruction
        model = genai.GenerativeModel(
            'gemini-2.0-flash',
            system_instruction=SYSTEM_PROMPT
        )

        # Simple test prompt
        test_prompt = """## Aliyah
**Reference:** Exodus 3:1-3:15 (Aliyah 4)

**Key verses:**
- Exodus 3:6: And He said, "I am the God of your father, the God of Avraham..."
- Exodus 3:14: And God said to Moshe, "I Will Be What I Will Be..."

---

## Essay
**Title:** "The Light at the Heart of Darkness"
**Source:** Covenant and Conversation, Shemot

**Text:**
This essay discusses the nature of faith during times of suffering and how Moses encountered God in the burning bush...

---

Rate the relevance of this essay to this aliyah."""

        response = model.generate_content(test_prompt)
        print(f"✓ Response with system prompt received")
        print(f"  Raw response: {response.text[:200]}...")
        return True, response.text

    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False, None


def test_json_parsing(response_text: str):
    """Test 3: JSON response parsing"""
    print("\n" + "=" * 50)
    print("TEST 3: JSON Response Parsing")
    print("=" * 50)

    try:
        # Clean up response (same logic as relevance.py)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        print(f"  Cleaned response: {cleaned[:150]}...")

        data = json.loads(cleaned)

        # Validate expected fields
        required_fields = ["score", "connection_type", "key_overlap", "explanation"]
        for field in required_fields:
            if field not in data:
                print(f"❌ FAILED: Missing field '{field}'")
                return False

        print(f"✓ JSON parsed successfully")
        print(f"  Score: {data['score']}")
        print(f"  Connection: {data['connection_type']}")
        print(f"  Overlap: {data['key_overlap']}")
        print(f"  Explanation: {data['explanation'][:100]}...")
        return True

    except json.JSONDecodeError as e:
        print(f"❌ FAILED: JSON parse error: {e}")
        print(f"  Raw text: {response_text}")
        return False


def main():
    print("=" * 50)
    print("GEMINI API INTEGRATION TEST")
    print("=" * 50)

    # Test 1: Basic connection
    if not test_basic_connection():
        print("\n⛔ Basic connection failed. Stopping tests.")
        return

    # Test 2: System prompt
    success, response_text = test_system_prompt()
    if not success:
        print("\n⛔ System prompt test failed. Stopping tests.")
        return

    # Test 3: JSON parsing
    if not test_json_parsing(response_text):
        print("\n⚠️  JSON parsing failed - may need response format adjustments")
        return

    print("\n" + "=" * 50)
    print("✅ ALL TESTS PASSED - Ready to swap APIs")
    print("=" * 50)


if __name__ == "__main__":
    main()

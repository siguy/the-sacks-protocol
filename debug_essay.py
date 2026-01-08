#!/usr/bin/env python3
"""Debug essay section extraction"""
import asyncio
from src.generator import DailyGenerator
from src.formatter import OutputFormatter

async def main():
    gen = DailyGenerator()
    formatter = OutputFormatter()

    # Get the essay
    from src.sefaria_client import SefariaClient
    from src.sacks import SacksRetriever

    client = SefariaClient()
    retriever = SacksRetriever(client)
    corpus = await retriever.get_essays_for_parsha('Shemot', 'Exodus')

    print(f"Found {len(corpus.essays)} essays")

    for essay in corpus.essays:
        if 'Moses Afraid' in essay.title:
            print(f"\nEssay: {essay.title}")
            print(f"Length: {len(essay.text)} chars")
            print("\n" + "="*60)
            print("FULL TEXT:")
            print("="*60)
            print(essay.text)
            print("\n" + "="*60)
            print("EXTRACTED SECTIONS:")
            print("="*60)
            sections = formatter._extract_essay_sections(essay.text)
            for key, val in sections.items():
                print(f"\n{key.upper()}:")
                print(val)

if __name__ == "__main__":
    asyncio.run(main())

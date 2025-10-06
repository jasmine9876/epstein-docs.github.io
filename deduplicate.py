#!/usr/bin/env python3
"""
Entity deduplication script using LLM to identify and merge duplicate entities.
Processes all JSON files from ./results/ and creates a dedupe.json mapping file.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict
from openai import OpenAI
from tqdm import tqdm
from dotenv import load_dotenv


class EntityDeduplicator:
    """Deduplicate entities using LLM assistance"""

    def __init__(self, api_url: str, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.model = model
        self.results_dir = Path("./results")
        self.dedupe_file = Path("./dedupe.json")

    def load_all_entities(self) -> Dict[str, Set[str]]:
        """Load all unique entities from all JSON files"""
        entities = {
            "people": set(),
            "organizations": set(),
            "locations": set()
        }

        json_files = list(self.results_dir.glob("**/*.json"))
        print(f"Found {len(json_files)} JSON files to process")

        for json_file in tqdm(json_files, desc="Loading entities"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    if "entities" in data:
                        for entity_type in ["people", "organizations", "locations"]:
                            if entity_type in data["entities"]:
                                entities[entity_type].update(data["entities"][entity_type])
            except Exception as e:
                print(f"Warning: Could not load {json_file}: {e}")

        return {k: sorted(list(v)) for k, v in entities.items()}

    def get_deduplication_prompt(self, entity_type: str) -> str:
        """Get the system prompt for deduplication"""

        if entity_type == "people":
            examples = """Examples:
{{
  "Jeffrey Epstein": ["Jeffrey Epstein", "JEFFREY EPSTEIN", "Epstein", "EPSTEIN", "J. Epstein", "Jeffrey E. Epstein", "J Epstein", "Jeffery Epstein", "Mr. Epstein", "Jeffrey E.", "Epstein's"],
  "Ghislaine Maxwell": ["Ghislaine Maxwell", "GHISLAINE MAXWELL", "Maxwell", "G. Maxwell", "Ghislane Maxwell", "Ghislain Maxwell", "Ms. Maxwell"],
  "Bill Clinton": ["Bill Clinton", "BILL CLINTON", "Clinton", "William Clinton", "William J. Clinton", "President Clinton", "William Jefferson Clinton"],
  "Prince Andrew": ["Prince Andrew", "PRINCE ANDREW", "Andrew", "Duke of York", "HRH Prince Andrew", "Prince Andrew, Duke of York"]
}}

CORRECT handling of numbered identifiers:
{{
  "Accuser 1": ["Accuser 1", "Accuser-1", "Accuser 01", "ACCUSER 1"],
  "Accuser 2": ["Accuser 2", "Accuser-2", "Accuser 02", "ACCUSER 2"],
  "Accuser 3": ["Accuser 3", "Accuser-3", "Accuser 03"],
  "Jane Doe 1": ["Jane Doe 1", "Jane Doe-1", "JANE DOE 1"],
  "Jane Doe 2": ["Jane Doe 2", "Jane Doe-2"]
}}

WRONG EXAMPLES (DO NOT DO THIS):
{{
  "Accusers 1-3": ["Accuser 1", "Accuser 2", "Accuser 3"] // WRONG - these are different people!
  "Victims": ["Victim 1", "Victim 2", "Victim 3"] // WRONG - keep them separate
  "Mr. Epstein's brother": ["Jeffrey Epstein", "Epstein"] // WRONG - use actual name
  "The President": ["Bill Clinton"] // WRONG - use actual name
  "Plaintiff's attorney": ["John Smith"] // WRONG - use actual name
}}"""
        elif entity_type == "organizations":
            examples = """Examples:
{{
  "Federal Bureau of Investigation": ["Federal Bureau of Investigation", "FBI", "F.B.I.", "FEDERAL BUREAU OF INVESTIGATION", "Federal Bureau Of Investigation"],
  "United States District Court": ["United States District Court", "U.S. District Court", "USDC", "District Court"],
  "Victoria's Secret": ["Victoria's Secret", "VICTORIA'S SECRET", "Victorias Secret", "Victoria Secret"]
}}"""
        else:  # locations
            examples = """Examples:
{{
  "New York City": ["New York City", "NEW YORK CITY", "NYC", "New York", "New York, NY", "New York City, NY", "Manhattan"],
  "Little Saint James": ["Little Saint James", "LITTLE SAINT JAMES", "Little St. James", "Little St James", "LSJ"],
  "Palm Beach": ["Palm Beach", "PALM BEACH", "Palm Beach, Florida", "Palm Beach, FL"]
}}"""

        return f"""You are an expert at identifying and merging duplicate entities in legal documents.

Given a list of {entity_type}, identify which names refer to the same entity and group them under their canonical name.

⚠️⚠️⚠️ CRITICAL WARNING ⚠️⚠️⚠️
The canonical name MUST be an actual person's PROPER NAME (First + Last).
NEVER use descriptive phrases like "Mr. X's brother" or "The defendant".
If you see "Jeffrey Epstein" in the list, that MUST be the canonical name, NOT "Mr. Epstein's brother".

CRITICAL RULES FOR CANONICAL NAMES:

**What makes a GOOD canonical name:**
- Actual proper names (e.g., "Jeffrey Epstein", not "Mr. Epstein's brother")
- Full first name + last name (e.g., "Jeffrey Epstein", not just "Epstein")
- Include middle initial if commonly used (e.g., "William J. Clinton")
- Use the most formal/complete version of the actual name

**What is a BAD canonical name (NEVER USE THESE):**
- Descriptive phrases (e.g., "Mr. Epstein's brother", "The defendant", "Plaintiff's attorney")
- Titles alone (e.g., "The President", "The Judge")
- Possessive forms (e.g., "Epstein's", "Maxwell's")
- Roles or relationships (e.g., "co-conspirator", "witness", "victim")
- Generic references (e.g., "he", "she", "defendant")

**CRITICAL: Do NOT merge numbered identifiers:**
- "Accuser 1", "Accuser 2", "Accuser 3" are DIFFERENT people - keep them separate
- "Victim 1", "Victim 2", "Victim 3" are DIFFERENT people - keep them separate
- "Witness 1", "Witness 2", "Witness 3" are DIFFERENT people - keep them separate
- "Jane Doe 1", "Jane Doe 2" are DIFFERENT people - keep them separate
- ONLY merge if the NUMBER is the same (e.g., "Accuser 1" = "Accuser-1" = "Accuser-01")

**Deduplication Rules:**
1. **Use Proper Names Only**: The canonical name MUST be an actual person's name
2. **Case Insensitive**: "EPSTEIN", "Epstein", "epstein" are all the same
3. **Prefer Full Names**: "Jeffrey Epstein" not "Epstein" or "J. Epstein"
4. **Merge Variants**:
   - Last name only → Full name (e.g., "Epstein" → "Jeffrey Epstein")
   - Initials → Full name (e.g., "J. Epstein" → "Jeffrey Epstein")
   - Titles with same person (e.g., "Mr. Epstein" → "Jeffrey Epstein")
   - Honorifics (Dr., Mr., Ms., President, Judge, etc.) → actual name
5. **OCR Errors**: Merge spelling variations (e.g., "Jeffery" = "Jeffrey")
6. **Whitespace/Punctuation**: Ignore differences in spacing, periods, commas

For PEOPLE specifically:
- The canonical name should be First Name + Last Name (or First + Middle Initial + Last)
- Merge all variants: full name, last name only, initials, titles, nicknames
- NEVER use descriptive phrases like "Mr. X's brother" as canonical

For ORGANIZATIONS:
- Merge: Full name with abbreviations (FBI = Federal Bureau of Investigation)
- Merge: Different legal forms (Inc., LLC, Corp., etc.)
- Merge: With/without "The" prefix

For LOCATIONS:
- Merge: City abbreviations (NYC = New York City)
- Merge: With/without state (Palm Beach = Palm Beach, FL)
- Merge: Common neighborhood/borough names with city

{examples}

IMPORTANT:
- Every entity must appear in exactly one group
- The canonical name MUST be a proper name (First + Last), NOT a description
- Use the most complete PROPER NAME as canonical (e.g., "Jeffrey Epstein" not "Mr. Epstein's brother")
- When in doubt between a descriptive phrase and a name, ALWAYS choose the actual name
- Merge aggressively - group all variants of the same person together
- Include all variations in the variants array, including the canonical name itself

VALIDATION:
- Ask yourself: "Is this canonical name an actual person's name?" If no, find the actual name from the variants
- Examples of GOOD canonical names: "Jeffrey Epstein", "Bill Clinton", "John Smith"
- Examples of BAD canonical names: "Mr. Epstein's brother", "The defendant", "Plaintiff"

STEP-BY-STEP PROCESS:
1. Look at the list of variants
2. Find the FULL PROPER NAME (e.g., "Jeffrey Epstein")
3. Use that as the canonical name
4. Add all other variants to the array
5. NEVER use descriptive phrases as canonical names

EXAMPLE THOUGHT PROCESS:
Variants: ["Jeffrey Epstein", "Epstein", "Mr. Epstein", "Mr. Epstein's brother", "J. Epstein"]
Question: Which is the actual person's full name?
Answer: "Jeffrey Epstein" ✓
NOT "Mr. Epstein's brother" ✗ (this is a description, not a name)
Result: {{"Jeffrey Epstein": ["Jeffrey Epstein", "Epstein", "Mr. Epstein", "Mr. Epstein's brother", "J. Epstein"]}}

Return ONLY valid JSON with NO extra text, markdown, or explanations."""

    def deduplicate_entities(self, entities: List[str], entity_type: str, batch_size: int = 30) -> Dict[str, str]:
        """Use LLM to deduplicate entities, processing in batches"""
        if not entities:
            return {}

        print(f"\nDeduplicating {len(entities)} {entity_type}...")

        # Process in batches
        all_mappings = {}
        batches = [entities[i:i + batch_size] for i in range(0, len(entities), batch_size)]

        for batch_idx, batch in enumerate(tqdm(batches, desc=f"Processing {entity_type} batches")):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": self.get_deduplication_prompt(entity_type)
                        },
                        {
                            "role": "user",
                            "content": f"Identify duplicates in this list of {entity_type}:\n\n" + "\n".join(f"- {e}" for e in batch) + "\n\nRemember: Use FULL PROPER NAMES as canonical (e.g., 'Jeffrey Epstein'), NOT descriptions (e.g., 'Mr. Epstein's brother')."
                        }
                    ],
                    temperature=0.0,  # Make it deterministic
                    max_tokens=4096
                )

                content = response.choices[0].message.content.strip()

                # Robust JSON extraction
                # 1. Try to find JSON between markdown code fences
                json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1).strip()
                else:
                    # 2. Try to find JSON between curly braces
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(0).strip()
                    else:
                        # 3. Strip markdown manually
                        if content.startswith('```json'):
                            content = content[7:]
                        elif content.startswith('```'):
                            content = content[3:]
                        if content.endswith('```'):
                            content = content[:-3]
                        content = content.strip()

                # Try to parse JSON
                try:
                    groups = json.loads(content)
                except json.JSONDecodeError as e:
                    print(f"\nJSON parsing error in batch {batch_idx}:")
                    print(f"Error: {e}")
                    print(f"Content preview: {content[:500]}")
                    # Try to salvage by finding the first complete JSON object
                    try:
                        # Find first { and matching }
                        start = content.find('{')
                        if start == -1:
                            raise ValueError("No JSON object found")

                        brace_count = 0
                        end = start
                        for i in range(start, len(content)):
                            if content[i] == '{':
                                brace_count += 1
                            elif content[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end = i + 1
                                    break

                        if end > start:
                            content = content[start:end]
                            groups = json.loads(content)
                            print(f"✓ Recovered JSON from malformed response")
                        else:
                            raise ValueError("Could not find complete JSON object")
                    except Exception as salvage_error:
                        print(f"Could not salvage JSON: {salvage_error}")
                        raise e

                # Validate and convert groups to individual mappings
                for canonical, variants in groups.items():
                    # Validate canonical name for people
                    if entity_type == "people":
                        # Check if this incorrectly merged numbered identifiers
                        # e.g., "Accusers 1-3" should be split back into separate people
                        if re.search(r'(accuser|victim|witness|jane doe|john doe)s?\s*\d+\s*-\s*\d+', canonical, re.IGNORECASE):
                            # This is wrong - split it back
                            print(f"  ⚠️  Incorrectly merged group: '{canonical}' - splitting back into individuals")
                            # Map each variant to itself
                            for variant in variants:
                                all_mappings[variant] = variant
                            continue

                        # Check for bad canonical names - be very aggressive
                        canonical_lower = canonical.lower()

                        # Pattern: anything with 's brother/sister/friend/attorney/mother/father etc
                        if re.search(r"'s\s+(brother|sister|friend|attorney|lawyer|associate|mother|father|son|daughter)", canonical_lower):
                            # Find actual name from variants
                            actual_names = [v for v in variants if not re.search(r"'s\s+(brother|sister|friend|attorney|lawyer|associate|mother|father|son|daughter)", v.lower())]
                            if actual_names:
                                # Prefer names with first and last name
                                full_names = [n for n in actual_names if len(n.split()) >= 2]
                                if full_names:
                                    # Pick the longest/most complete
                                    better_name = max(full_names, key=len)
                                    print(f"  ⚠️  Fixed bad canonical: '{canonical}' → '{better_name}'")
                                    canonical = better_name

                        # Pattern: "The X" or "A X" (defendant, plaintiff, etc)
                        elif re.search(r"^(the|a)\s+(defendant|plaintiff|witness|victim|judge|president)", canonical_lower):
                            actual_names = [v for v in variants if not re.search(r"^(the|a)\s+", v.lower()) and len(v.split()) >= 2]
                            if actual_names:
                                better_name = max(actual_names, key=len)
                                print(f"  ⚠️  Fixed bad canonical: '{canonical}' → '{better_name}'")
                                canonical = better_name

                        # Pattern: ends with possessive
                        elif canonical_lower.endswith("'s") or canonical_lower.endswith("'s"):
                            non_possessive = [v for v in variants if not (v.lower().endswith("'s") or v.lower().endswith("'s"))]
                            if non_possessive:
                                better_name = max(non_possessive, key=len)
                                print(f"  ⚠️  Fixed bad canonical: '{canonical}' → '{better_name}'")
                                canonical = better_name

                        # Pattern: just title (Mr., Ms., Dr.) alone
                        elif re.match(r"^(mr|ms|mrs|dr|judge|president)\.?\s*$", canonical_lower):
                            actual_names = [v for v in variants if len(v.split()) >= 2]
                            if actual_names:
                                better_name = max(actual_names, key=len)
                                print(f"  ⚠️  Fixed bad canonical: '{canonical}' → '{better_name}'")
                                canonical = better_name

                    for variant in variants:
                        all_mappings[variant] = canonical

            except Exception as e:
                print(f"Warning: Error processing batch {batch_idx}: {e}")
                # If batch fails, map each entity to itself
                for entity in batch:
                    if entity not in all_mappings:
                        all_mappings[entity] = entity

        return all_mappings

    def merge_batches(self, mappings: Dict[str, str]) -> Dict[str, str]:
        """Merge mappings from multiple batches to ensure consistency"""
        # Group by canonical names
        groups = defaultdict(set)
        for variant, canonical in mappings.items():
            groups[canonical].add(variant)

        # Pick the most common canonical name for each group
        final_mappings = {}
        for canonical, variants in groups.items():
            # Use the longest name as canonical (usually most complete)
            true_canonical = max(variants, key=len)
            for variant in variants:
                final_mappings[variant] = true_canonical

        return final_mappings

    def process_all(self, batch_size: int = 30) -> Dict[str, Dict[str, str]]:
        """Process all entity types"""
        print("=" * 60)
        print("ENTITY DEDUPLICATION")
        print("=" * 60)

        # Load all entities
        all_entities = self.load_all_entities()

        print(f"\nEntity counts:")
        for entity_type, entity_list in all_entities.items():
            print(f"  {entity_type}: {len(entity_list)}")

        # Deduplicate each type
        dedupe_mappings = {}
        for entity_type in ["people", "organizations", "locations"]:
            mappings = self.deduplicate_entities(
                all_entities[entity_type],
                entity_type,
                batch_size=batch_size
            )
            dedupe_mappings[entity_type] = self.merge_batches(mappings)

            # Show stats
            unique_after = len(set(dedupe_mappings[entity_type].values()))
            print(f"  {entity_type}: {len(all_entities[entity_type])} → {unique_after} unique entities")

        return dedupe_mappings

    def save_dedupe_file(self, mappings: Dict[str, Dict[str, str]]):
        """Save deduplication mappings to JSON file"""
        with open(self.dedupe_file, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Deduplication mappings saved to {self.dedupe_file}")

    def load_existing_dedupe(self) -> Dict[str, Dict[str, str]]:
        """Load existing dedupe file if it exists"""
        if self.dedupe_file.exists():
            with open(self.dedupe_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"people": {}, "organizations": {}, "locations": {}}


def main():
    load_dotenv()

    import argparse
    parser = argparse.ArgumentParser(description="Deduplicate entities using LLM")
    parser.add_argument("--api-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", help="API key")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--batch-size", type=int, default=30, help="Entities per batch (default: 30)")
    parser.add_argument("--show-stats", action="store_true", help="Show current deduplication stats and exit")

    args = parser.parse_args()

    api_url = args.api_url or os.getenv("OPENAI_API_URL")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o")

    deduplicator = EntityDeduplicator(api_url, api_key, model)

    if args.show_stats:
        # Just show stats
        existing = deduplicator.load_existing_dedupe()
        all_entities = deduplicator.load_all_entities()

        print("\nCurrent deduplication status:")
        for entity_type in ["people", "organizations", "locations"]:
            raw_count = len(all_entities[entity_type])
            if existing.get(entity_type):
                unique_count = len(set(existing[entity_type].values()))
                print(f"  {entity_type}: {raw_count} raw → {unique_count} unique")
            else:
                print(f"  {entity_type}: {raw_count} (not deduplicated)")
        return

    # Process and save
    mappings = deduplicator.process_all(batch_size=args.batch_size)
    deduplicator.save_dedupe_file(mappings)


if __name__ == "__main__":
    main()

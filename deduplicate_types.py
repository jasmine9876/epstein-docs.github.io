#!/usr/bin/env python3
"""
Document type deduplication script using LLM to merge similar types.
Groups document type variations (e.g., "Deposition", "deposition", "Deposition Transcript")
into canonical types.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List
from collections import Counter
from openai import OpenAI
from dotenv import load_dotenv


class DocumentTypeDeduplicator:
    """Deduplicate document types using LLM"""

    def __init__(self, api_url: str, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.model = model
        self.results_dir = Path("./results")
        self.output_file = Path("./dedupe_types.json")

    def collect_document_types(self) -> Counter:
        """Collect all document types from JSON files"""
        types = []

        for json_file in self.results_dir.glob("**/*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    doc_type = data.get('document_metadata', {}).get('document_type')
                    if doc_type:
                        types.append(str(doc_type).strip())
            except Exception as e:
                print(f"Warning: Could not read {json_file}: {e}")

        return Counter(types)

    def _deduplicate_in_batches(self, unique_types: List[str], type_counts: Counter) -> Dict[str, str]:
        """Deduplicate types in batches to handle large numbers"""
        batch_size = 100
        all_mappings = {}
        canonical_to_variants = {}

        # First pass: deduplicate in batches
        for i in range(0, len(unique_types), batch_size):
            batch = unique_types[i:i+batch_size]
            print(f"  Processing batch {i//batch_size + 1}/{(len(unique_types) + batch_size - 1)//batch_size} ({len(batch)} types)...")

            try:
                batch_mappings = self._deduplicate_single_batch(batch)

                # Collect mappings and track canonical types
                for original, canonical in batch_mappings.items():
                    all_mappings[original] = canonical
                    if canonical not in canonical_to_variants:
                        canonical_to_variants[canonical] = []
                    canonical_to_variants[canonical].append(original)

            except Exception as e:
                print(f"  Warning: Failed to process batch, using original names: {e}")
                for t in batch:
                    all_mappings[t] = t
                    if t not in canonical_to_variants:
                        canonical_to_variants[t] = []
                    canonical_to_variants[t].append(t)

        # Second pass: deduplicate the canonical types themselves
        # (in case different batches created similar canonical types)
        print(f"\n📋 Batch processing created {len(canonical_to_variants)} unique canonical types")
        print(f"Running final deduplication pass to merge any duplicates across batches...")

        try:
            canonical_types = list(canonical_to_variants.keys())
            canonical_mappings = self._deduplicate_final_pass(canonical_types)

            # Apply final canonical deduplication
            for original, first_canonical in all_mappings.items():
                final_canonical = canonical_mappings.get(first_canonical, first_canonical)
                all_mappings[original] = final_canonical

            # Count final canonicals
            final_canonicals = set(all_mappings.values())
            print(f"✅ Final deduplication reduced {len(canonical_to_variants)} → {len(final_canonicals)} canonical types")

        except Exception as e:
            print(f"  Warning: Failed to deduplicate canonical types: {e}")

        return all_mappings

    def _deduplicate_final_pass(self, canonical_types: List[str]) -> Dict[str, str]:
        """Final deduplication pass for canonical types from different batches"""
        if len(canonical_types) <= 1:
            return {t: t for t in canonical_types}

        prompt = f"""You are a legal document classifier performing a FINAL CLEANUP pass on canonical document types.

Your task: Merge any remaining duplicate or very similar canonical types.

⚠️⚠️⚠️ CRITICAL RULES ⚠️⚠️⚠️

1. These are ALREADY canonical types, so be conservative
2. ONLY merge if types are truly the same thing with different names:
   - "Deposition" and "Deposition Transcript" → "Deposition"
   - "Court Filing" and "Court Document" → "Court Filing"
   - "Email" and "E-mail" → "Email"

3. DO NOT merge types that are legitimately different:
   - "Letter" and "Email" are DIFFERENT (keep separate)
   - "Affidavit" and "Declaration" are DIFFERENT (keep separate)
   - "Motion" and "Memorandum" are DIFFERENT (keep separate)

4. Prefer the SHORTER, simpler canonical name when merging

5. Use these standard canonical types when possible:
   - Deposition
   - Court Filing
   - Letter
   - Email
   - Affidavit
   - Motion
   - Subpoena
   - Flight Log
   - Financial Record
   - Contract
   - Memorandum
   - Transcript
   - Exhibit
   - Declaration
   - Report

Here are the canonical types to review (sorted alphabetically):

{json.dumps(sorted(canonical_types), indent=2)}

Return ONLY valid JSON mapping each type to its final canonical form:
{{
  "Type 1": "Final Canonical Type",
  "Type 2": "Final Canonical Type",
  ...
}}

If a type is already perfect, map it to itself."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=4000
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1).strip()
        else:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0).strip()
            else:
                # Brace-counting fallback
                start = content.find('{')
                if start >= 0:
                    brace_count = 0
                    for i in range(start, len(content)):
                        if content[i] == '{':
                            brace_count += 1
                        elif content[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                content = content[start:i+1]
                                break

        try:
            mappings = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response in final pass. First 500 chars:")
            print(content[:500])
            raise

        # Validate mappings
        validated_mappings = {}
        for original, canonical in mappings.items():
            canonical = str(canonical).strip()
            if not canonical:
                canonical = original
            validated_mappings[original] = canonical

        return validated_mappings

    def _deduplicate_single_batch(self, types: List[str]) -> Dict[str, str]:
        """Deduplicate a single batch of types"""
        prompt = f"""You are a legal document classifier. Your task is to group similar document type labels into standardized canonical types.

⚠️⚠️⚠️ CRITICAL RULES ⚠️⚠️⚠️

1. The canonical type MUST be a clean, professional document type name
2. Use title case (e.g., "Deposition", "Court Filing", "Email")
3. Merge variations that mean the same thing:
   - "deposition" → "Deposition"
   - "DEPOSITION" → "Deposition"
   - "deposition transcript" → "Deposition"
   - "dep" → "Deposition"

4. Common canonical types to use:
   - Deposition
   - Court Filing
   - Letter
   - Email
   - Affidavit
   - Motion
   - Subpoena
   - Flight Log
   - Financial Record
   - Contract
   - Memorandum
   - Transcript
   - Exhibit
   - Declaration
   - Report
   - Unknown (only if truly unidentifiable)

5. Be generous with merging - if types are similar, merge them
6. Prefer shorter, cleaner canonical names

Here are the document types to deduplicate:

{json.dumps(types, indent=2)}

Return ONLY valid JSON in this exact format:
{{
  "document_type_1": "Canonical Type",
  "document_type_2": "Canonical Type",
  ...
}}

Map every input type to its canonical form. If a type is already clean, map it to itself."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=4000
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1).strip()
        else:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0).strip()
            else:
                # Brace-counting fallback
                start = content.find('{')
                if start >= 0:
                    brace_count = 0
                    for i in range(start, len(content)):
                        if content[i] == '{':
                            brace_count += 1
                        elif content[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                content = content[start:i+1]
                                break

        try:
            mappings = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response. First 500 chars:")
            print(content[:500])
            raise

        # Validate and clean up mappings
        validated_mappings = {}
        for original, canonical in mappings.items():
            canonical = str(canonical).strip()
            if not canonical:
                canonical = "Unknown"
            validated_mappings[original] = canonical

        return validated_mappings

    def deduplicate_types(self, type_counts: Counter) -> Dict[str, str]:
        """Use LLM to deduplicate document types"""

        # Get unique types sorted by frequency
        unique_types = sorted(type_counts.keys(), key=lambda x: type_counts[x], reverse=True)

        print(f"Found {len(unique_types)} unique document types")

        # If too many types, process in batches
        if len(unique_types) > 100:
            print(f"Processing in batches (too many types for single request)...")
            return self._deduplicate_in_batches(unique_types, type_counts)

        print(f"Processing single batch deduplication...")
        mappings = self._deduplicate_single_batch(unique_types)

        # Get canonical types
        canonical_types = list(set(mappings.values()))
        print(f"\n📋 Initial deduplication created {len(canonical_types)} canonical types")

        # Do a final review pass
        if len(canonical_types) > 1:
            print(f"Running final review pass for cleanup...")
            try:
                final_mappings = self._deduplicate_final_pass(canonical_types)

                # Apply final pass
                for original, first_canonical in mappings.items():
                    final_canonical = final_mappings.get(first_canonical, first_canonical)
                    mappings[original] = final_canonical

                final_canonicals = set(mappings.values())
                print(f"✅ Final review reduced {len(canonical_types)} → {len(final_canonicals)} canonical types")

            except Exception as e:
                print(f"  Warning: Final review failed: {e}")

        return mappings

    def save_mappings(self, mappings: Dict[str, str], type_counts: Counter):
        """Save deduplication mappings to JSON file"""

        # Get stats
        canonical_types = set(mappings.values())
        total_docs = sum(type_counts.values())

        output = {
            "stats": {
                "original_types": len(mappings),
                "canonical_types": len(canonical_types),
                "total_documents": total_docs,
                "reduction_percentage": round((1 - len(canonical_types) / len(mappings)) * 100, 1)
            },
            "mappings": mappings
        }

        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Saved type mappings to {self.output_file}")
        print(f"   Original types: {len(mappings)}")
        print(f"   Canonical types: {len(canonical_types)}")
        print(f"   Reduction: {output['stats']['reduction_percentage']}%")

        # Show canonical type breakdown
        canonical_counts = Counter()
        for original, canonical in mappings.items():
            canonical_counts[canonical] += type_counts[original]

        print(f"\n📊 Top canonical types:")
        for canonical, count in canonical_counts.most_common(10):
            print(f"   {canonical}: {count} documents")


def main():
    load_dotenv()

    import argparse
    parser = argparse.ArgumentParser(description="Deduplicate document types using LLM")
    parser.add_argument("--api-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", help="API key")
    parser.add_argument("--model", help="Model name")

    args = parser.parse_args()

    api_url = args.api_url or os.getenv("OPENAI_API_URL")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o")

    if not api_url or not api_key:
        print("Error: API URL and API key are required")
        print("Set OPENAI_API_URL and OPENAI_API_KEY in .env or pass via --api-url and --api-key")
        return 1

    print("=" * 60)
    print("DOCUMENT TYPE DEDUPLICATION")
    print("=" * 60)

    deduplicator = DocumentTypeDeduplicator(api_url, api_key, model)

    # Collect all document types
    type_counts = deduplicator.collect_document_types()

    if not type_counts:
        print("No document types found in results directory")
        return 1

    # Deduplicate using LLM
    mappings = deduplicator.deduplicate_types(type_counts)

    # Save results
    deduplicator.save_mappings(mappings, type_counts)

    print("\n✅ Done! Update .eleventy.js to load dedupe_types.json")


if __name__ == "__main__":
    exit(main() or 0)

#!/usr/bin/env python3
"""
Document analysis script using LLM to generate summaries and key insights.
Groups pages into documents (like .eleventy.js) and analyzes each one.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from openai import OpenAI
from tqdm import tqdm
from dotenv import load_dotenv


class DocumentAnalyzer:
    """Analyze grouped documents using LLM"""

    def __init__(self, api_url: str, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.model = model
        self.results_dir = Path("./results")
        self.analyses_file = Path("./analyses.json")

    def normalize_doc_num(self, doc_num: Optional[str]) -> Optional[str]:
        """Normalize document number to handle LLM variations"""
        if not doc_num:
            return None
        return str(doc_num).lower().replace(r'[^a-z0-9-]', '-').replace(r'-+', '-').strip('-')

    def load_and_group_documents(self) -> List[Dict]:
        """Load all JSON files and group into documents (matching .eleventy.js logic)"""
        pages = []

        # Recursively read all JSON files
        for json_file in self.results_dir.glob("**/*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    content = json.load(f)

                    relative_path = json_file.relative_to(self.results_dir)
                    pages.append({
                        'path': str(relative_path),
                        'filename': json_file.stem,
                        'folder': str(relative_path.parent) if relative_path.parent != Path('.') else 'root',
                        **content
                    })
            except Exception as e:
                print(f"Warning: Could not load {json_file}: {e}")

        print(f"Loaded {len(pages)} pages")

        # Group by normalized document number
        document_map = defaultdict(list)

        for page in pages:
            doc_num = page.get('document_metadata', {}).get('document_number')

            if not doc_num:
                # Use filename as fallback
                normalized = self.normalize_doc_num(page['filename']) or page['filename']
            else:
                normalized = self.normalize_doc_num(doc_num)

            document_map[normalized].append(page)

        # Helper to extract numeric page number
        def get_page_num(page):
            page_num = page.get('document_metadata', {}).get('page_number', 0) or 0
            if isinstance(page_num, int):
                return page_num
            # Handle formats like "24 of 66" or "24/66"
            if isinstance(page_num, str):
                # Extract first number
                match = re.search(r'(\d+)', page_num)
                if match:
                    return int(match.group(1))
            return 0

        # Convert to sorted documents
        documents = []
        for normalized_num, doc_pages in document_map.items():
            # Sort pages by page number
            doc_pages.sort(key=get_page_num)

            # Get metadata
            first_page = doc_pages[0]
            raw_doc_nums = list(set(
                p.get('document_metadata', {}).get('document_number')
                for p in doc_pages
                if p.get('document_metadata', {}).get('document_number')
            ))

            # Combine full text from all pages
            full_text = '\n\n--- PAGE BREAK ---\n\n'.join(
                p.get('full_text', '') for p in doc_pages
            )

            # Collect all entities
            all_entities = {
                'people': set(),
                'organizations': set(),
                'locations': set(),
                'dates': set(),
                'reference_numbers': set()
            }

            for page in doc_pages:
                if 'entities' in page:
                    for key in all_entities.keys():
                        if key in page['entities']:
                            all_entities[key].update(page['entities'][key])

            documents.append({
                'unique_id': normalized_num,
                'document_number': raw_doc_nums[0] if len(raw_doc_nums) == 1 else normalized_num,
                'page_count': len(doc_pages),
                'full_text': full_text,
                'document_metadata': first_page.get('document_metadata', {}),
                'entities': {k: sorted(list(v)) for k, v in all_entities.items()}
            })

        print(f"Grouped into {len(documents)} documents")
        return sorted(documents, key=lambda d: d['document_number'])

    def get_analysis_prompt(self) -> str:
        """Get the system prompt for document analysis"""
        return """You are an expert legal document analyst specializing in court documents, depositions, and legal filings.

Analyze the provided document and return a concise summary with key insights.

Your analysis should include:
1. **Document Type**: What kind of document is this? (deposition, court filing, letter, email, affidavit, etc.)
2. **Key Topics**: What are the main subjects/topics discussed? (2-3 bullet points)
3. **Key People**: Who are the most important people mentioned and their roles?
4. **Significance**: Why is this document potentially important? What does it reveal or establish?
5. **Summary**: A 2-3 sentence summary of the document's content

Be factual, concise, and focus on what makes this document notable or significant.

Return ONLY valid JSON in this format:
{
  "document_type": "string",
  "key_topics": ["topic1", "topic2", "topic3"],
  "key_people": [
    {"name": "person name", "role": "their role or significance in this doc"}
  ],
  "significance": "Why this document matters (1-2 sentences)",
  "summary": "Brief summary (2-3 sentences)"
}"""

    def analyze_document(self, document: Dict) -> Optional[Dict]:
        """Analyze a single document using LLM"""
        try:
            # Limit text length for API (keep first ~8000 chars if too long)
            full_text = document['full_text']
            if len(full_text) > 8000:
                full_text = full_text[:8000] + "\n\n[... document continues ...]"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.get_analysis_prompt()
                    },
                    {
                        "role": "user",
                        "content": f"Analyze this document:\n\n{full_text}"
                    }
                ],
                temperature=0.2,
                max_tokens=1000
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

            analysis = json.loads(content)

            return {
                'document_id': document['unique_id'],
                'document_number': document['document_number'],
                'page_count': document['page_count'],
                'analysis': analysis
            }

        except Exception as e:
            print(f"Error analyzing document {document['document_number']}: {e}")
            return None

    def analyze_all(self, limit: Optional[int] = None) -> List[Dict]:
        """Analyze all documents"""
        print("=" * 60)
        print("DOCUMENT ANALYSIS")
        print("=" * 60)

        # Load existing analyses to resume
        existing_analyses = {}
        if self.analyses_file.exists():
            try:
                with open(self.analyses_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    existing_analyses = {a['document_id']: a for a in data.get('analyses', [])}
                print(f"Found {len(existing_analyses)} existing analyses")
            except Exception as e:
                print(f"Could not load existing analyses: {e}")

        documents = self.load_and_group_documents()

        if limit:
            documents = documents[:limit]
            print(f"Limited to {limit} documents for this run")

        analyses = []
        skipped = 0

        for doc in tqdm(documents, desc="Analyzing documents"):
            # Skip if already analyzed
            if doc['unique_id'] in existing_analyses:
                analyses.append(existing_analyses[doc['unique_id']])
                skipped += 1
                continue

            analysis = self.analyze_document(doc)
            if analysis:
                analyses.append(analysis)
                # Save incrementally
                self.save_analyses(analyses)

        print(f"\n✅ Analyzed {len(analyses) - skipped} new documents")
        print(f"   Skipped {skipped} already-analyzed documents")
        print(f"   Total analyses: {len(analyses)}")

        return analyses

    def save_analyses(self, analyses: List[Dict]):
        """Save analyses to JSON file"""
        output = {
            'total': len(analyses),
            'analyses': analyses
        }

        with open(self.analyses_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)


def main():
    load_dotenv()

    import argparse
    parser = argparse.ArgumentParser(description="Analyze documents using LLM")
    parser.add_argument("--api-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", help="API key")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--limit", type=int, help="Limit number of documents to analyze")
    parser.add_argument("--force", action="store_true", help="Re-analyze all documents (ignore existing)")

    args = parser.parse_args()

    api_url = args.api_url or os.getenv("OPENAI_API_URL")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o")

    analyzer = DocumentAnalyzer(api_url, api_key, model)

    # Clear existing if force flag
    if args.force and analyzer.analyses_file.exists():
        analyzer.analyses_file.unlink()
        print("Removed existing analyses (--force mode)")

    analyses = analyzer.analyze_all(limit=args.limit)
    analyzer.save_analyses(analyses)

    print(f"\n✅ Saved analyses to {analyzer.analyses_file}")


if __name__ == "__main__":
    main()

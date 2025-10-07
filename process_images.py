#!/usr/bin/env python3
"""
Image processing script for OCR and entity extraction using OpenAI-compatible API.
Processes images from Downloads folder and extracts structured data.
"""

import os
import json
import re
import base64
from pathlib import Path
from typing import Dict, List, Optional
import concurrent.futures
from dataclasses import dataclass, asdict
from openai import OpenAI
from tqdm import tqdm
import argparse
from dotenv import load_dotenv


@dataclass
class ProcessingResult:
    """Structure for processing results"""
    filename: str
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


class ImageProcessor:
    """Process images using OpenAI-compatible vision API"""

    def __init__(self, api_url: str, api_key: str, model: str = "gpt-4o", index_file: str = "processing_index.json", downloads_dir: Optional[str] = None):
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.model = model
        self.downloads_dir = Path(downloads_dir) if downloads_dir else Path.home() / "Downloads"
        self.index_file = index_file
        self.processed_files = self.load_index()

    def load_index(self) -> set:
        """Load the index of already processed files"""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r') as f:
                    data = json.load(f)
                    return set(data.get('processed_files', []))
            except Exception as e:
                print(f"⚠️  Warning: Could not load index file: {e}")
                return set()
        return set()

    def save_index(self, failed_files=None):
        """Save the current index of processed files"""
        data = {
            'processed_files': sorted(list(self.processed_files)),
            'last_updated': str(Path.cwd())
        }
        if failed_files:
            data['failed_files'] = failed_files

        with open(self.index_file, 'w') as f:
            json.dump(data, f, indent=2)

    def mark_processed(self, filename: str):
        """Mark a file as processed and update index"""
        self.processed_files.add(filename)
        self.save_index()

    def get_image_files(self) -> List[Path]:
        """Get all image files from Downloads folder (recursively)"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
        image_files = []

        for ext in image_extensions:
            image_files.extend(self.downloads_dir.glob(f'**/*{ext}'))
            image_files.extend(self.downloads_dir.glob(f'**/*{ext.upper()}'))

        return sorted(image_files)

    def get_relative_path(self, file_path: Path) -> str:
        """Get relative path from downloads directory for unique indexing"""
        try:
            return str(file_path.relative_to(self.downloads_dir))
        except ValueError:
            # If file is not relative to downloads_dir, use full path
            return str(file_path)

    def get_unprocessed_files(self) -> List[Path]:
        """Get only files that haven't been processed yet"""
        all_files = self.get_image_files()
        unprocessed = [f for f in all_files if self.get_relative_path(f) not in self.processed_files]
        return unprocessed

    def encode_image(self, image_path: Path) -> str:
        """Encode image to base64"""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def get_system_prompt(self) -> str:
        """Get the system prompt for structured extraction"""
        return """You are an expert OCR and document analysis system.
Extract ALL text from the image in READING ORDER to create a digital twin of the document.

IMPORTANT: Transcribe text exactly as it appears on the page, from top to bottom, left to right, including:
- All printed text
- All handwritten text (inline where it appears)
- Stamps and annotations (inline where they appear)
- Signatures (note location)

Preserve the natural reading flow. Mix printed and handwritten text together in the order they appear.

Return ONLY valid JSON in this exact structure:
{
  "document_metadata": {
    "page_number": "string or null",
    "document_number": "string or null",
    "date": "string or null",
    "document_type": "string or null",
    "has_handwriting": true/false,
    "has_stamps": true/false
  },
  "full_text": "Complete text transcription in reading order. Include ALL text - printed, handwritten, stamps, etc. - exactly as it appears from top to bottom.",
  "text_blocks": [
    {
      "type": "printed|handwritten|stamp|signature|other",
      "content": "text content",
      "position": "top|middle|bottom|header|footer|margin"
    }
  ],
  "entities": {
    "people": ["list of person names"],
    "organizations": ["list of organizations"],
    "locations": ["list of locations"],
    "dates": ["list of dates found"],
    "reference_numbers": ["list of any reference/ID numbers"]
  },
  "additional_notes": "Any observations about document quality, redactions, damage, etc."
}"""

    def fix_json_with_llm(self, base64_image: str, broken_json: str, error_msg: str) -> dict:
        """Ask the LLM to fix its own broken JSON"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.get_system_prompt()
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract all text and entities from this image. Return only valid JSON."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                },
                {
                    "role": "assistant",
                    "content": broken_json
                },
                {
                    "role": "user",
                    "content": f"Your JSON response has an error: {error_msg}\n\nPlease fix the JSON and return ONLY the corrected valid JSON. Do not explain, just return the fixed JSON."
                }
            ],
            max_tokens=4096,
            temperature=0.1
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON using same logic
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1).strip()
        else:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0).strip()

        return json.loads(content)

    def process_image(self, image_path: Path) -> ProcessingResult:
        """Process a single image through the API"""
        try:
            # Encode image
            base64_image = self.encode_image(image_path)

            # Make API call using OpenAI client
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract all text and entities from this image. Return only valid JSON."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4096,
                temperature=0.1
            )

            # Parse response
            content = response.choices[0].message.content
            original_content = content  # Keep original for retry

            # Robust JSON extraction
            content = content.strip()

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
                extracted_data = json.loads(content)
            except json.JSONDecodeError as e:
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
                        extracted_data = json.loads(content)
                    else:
                        raise ValueError("Could not find complete JSON object")
                except Exception:
                    # Last resort: Ask LLM to fix its JSON
                    try:
                        extracted_data = self.fix_json_with_llm(base64_image, original_content, str(e))
                    except Exception:
                        # Save ORIGINAL LLM response to errors directory (not our extracted version)
                        self.save_broken_json(self.get_relative_path(image_path), original_content)
                        # If even that fails, raise the original error
                        raise e

            return ProcessingResult(
                filename=self.get_relative_path(image_path),
                success=True,
                data=extracted_data
            )

        except Exception as e:
            return ProcessingResult(
                filename=self.get_relative_path(image_path),
                success=False,
                error=str(e)
            )

    def process_all(self, max_workers: int = 5, limit: Optional[int] = None, resume: bool = True) -> List[ProcessingResult]:
        """Process all images with parallel processing"""
        if resume:
            image_files = self.get_unprocessed_files()
            total_files = len(self.get_image_files())
            already_processed = len(self.processed_files)
            print(f"Found {total_files} total image files")
            print(f"Already processed: {already_processed}")
            print(f"Remaining to process: {len(image_files)}")
        else:
            image_files = self.get_image_files()
            print(f"Found {len(image_files)} image files to process")

        if limit:
            image_files = image_files[:limit]
            print(f"Limited to {limit} files for this run")

        if not image_files:
            print("No files to process!")
            return []

        results = []
        failed_files = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.process_image, img): img for img in image_files}

            with tqdm(total=len(image_files), desc="Processing images") as pbar:
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    results.append(result)

                    # Save individual result to file
                    if result.success:
                        self.save_individual_result(result)
                        tqdm.write(f"✅ Processed: {result.filename}")
                    else:
                        # Track failed files
                        failed_files.append({
                            'filename': result.filename,
                            'error': result.error
                        })
                        tqdm.write(f"❌ Failed: {result.filename} - {result.error}")

                    # Mark as processed regardless of success/failure
                    self.mark_processed(result.filename)

                    pbar.update(1)

        # Save failed files to index for reference
        if failed_files:
            self.save_index(failed_files=failed_files)
            print(f"\n⚠️  {len(failed_files)} files failed - logged in {self.index_file}")

        return results

    def save_individual_result(self, result: ProcessingResult):
        """Save individual result to ./results/folder/imagename.json"""
        # Create output path mirroring the source structure
        result_path = Path("./results") / result.filename
        result_path = result_path.with_suffix('.json')

        # Create parent directories
        result_path.parent.mkdir(parents=True, exist_ok=True)

        # Save the extracted data
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result.data, f, indent=2, ensure_ascii=False)

    def save_broken_json(self, filename: str, broken_content: str):
        """Save broken JSON to errors directory"""
        error_path = Path("./errors") / filename
        error_path = error_path.with_suffix('.json')

        # Create parent directories
        error_path.parent.mkdir(parents=True, exist_ok=True)

        # Save the broken content as-is
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(broken_content)

    def save_results(self, results: List[ProcessingResult], output_file: str = "processed_results.json"):
        """Save summary results to JSON file"""
        output_data = {
            "total_processed": len(results),
            "successful": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "results": [asdict(r) for r in results]
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Summary saved to {output_file}")
        print(f"   Individual results saved to ./results/")
        print(f"   Successful: {output_data['successful']}")
        print(f"   Failed: {output_data['failed']}")


def main():
    # Load environment variables
    load_dotenv()

    parser = argparse.ArgumentParser(description="Process images with OCR and entity extraction")
    parser.add_argument("--api-url", help="OpenAI-compatible API base URL (default: from .env or OPENAI_API_URL)")
    parser.add_argument("--api-key", help="API key (default: from .env or OPENAI_API_KEY)")
    parser.add_argument("--model", help="Model name (default: from .env, OPENAI_MODEL, or meta-llama/Llama-4-Maverick-17B-128E-Instruct)")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel workers (default: 5)")
    parser.add_argument("--limit", type=int, help="Limit number of images to process (for testing)")
    parser.add_argument("--output", default="processed_results.json", help="Output JSON file")
    parser.add_argument("--index", default="processing_index.json", help="Index file to track processed files")
    parser.add_argument("--downloads-dir", default="./downloads", help="Directory containing images (default: ./downloads)")
    parser.add_argument("--no-resume", action="store_true", help="Process all files, ignoring index")

    args = parser.parse_args()

    # Get values from args or environment variables
    api_url = args.api_url or os.getenv("OPENAI_API_URL", "http://...")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY", "abcd1234")
    model = args.model or os.getenv("OPENAI_MODEL", "meta-llama/Llama-4-Maverick-17B-128E-Instruct")

    processor = ImageProcessor(
        api_url=api_url,
        api_key=api_key,
        model=model,
        index_file=args.index,
        downloads_dir=args.downloads_dir
    )

    results = processor.process_all(
        max_workers=args.workers,
        limit=args.limit,
        resume=not args.no_resume
    )

    processor.save_results(results, args.output)


if __name__ == "__main__":
    main()

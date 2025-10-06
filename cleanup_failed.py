#!/usr/bin/env python3
"""
Cleanup script for failed OCR processing.
Finds files marked as processed but with no valid JSON output, and optionally removes them from the index.
"""

import os
import json
from pathlib import Path
import argparse
from typing import Set, List, Dict


class FailureCleanup:
    """Clean up failed processing attempts"""

    def __init__(self, index_file: str = "processing_index.json", downloads_dir: str = "./downloads", results_dir: str = "./results"):
        self.index_file = Path(index_file)
        self.downloads_dir = Path(downloads_dir)
        self.results_dir = Path(results_dir)

    def load_index(self) -> Dict:
        """Load the processing index"""
        if not self.index_file.exists():
            print(f"❌ Index file not found: {self.index_file}")
            return {"processed_files": [], "failed_files": []}

        with open(self.index_file, 'r') as f:
            return json.load(f)

    def get_relative_path(self, file_path: Path) -> str:
        """Get relative path from downloads directory"""
        try:
            return str(file_path.relative_to(self.downloads_dir))
        except ValueError:
            return str(file_path)

    def check_json_exists(self, relative_path: str) -> bool:
        """Check if JSON output exists for this file"""
        # Convert image path to JSON path
        json_path = self.results_dir / Path(relative_path).with_suffix('.json')
        return json_path.exists()

    def check_json_valid(self, relative_path: str) -> bool:
        """Check if JSON output is valid"""
        json_path = self.results_dir / Path(relative_path).with_suffix('.json')
        if not json_path.exists():
            return False

        try:
            with open(json_path, 'r') as f:
                json.load(f)
            return True
        except Exception:
            return False

    def find_failures(self) -> Dict[str, List[str]]:
        """Find all types of failures"""
        index_data = self.load_index()
        processed_files = set(index_data.get('processed_files', []))
        explicit_failures = index_data.get('failed_files', [])

        failures = {
            'no_json': [],           # Marked processed but no JSON exists
            'invalid_json': [],      # JSON exists but is invalid/corrupt
            'explicit_failed': [],   # Listed in failed_files
            'orphaned_json': []      # JSON exists but not in processed list (shouldn't happen)
        }

        print("🔍 Scanning for failures...\n")

        # Check each processed file
        for relative_path in processed_files:
            if not self.check_json_exists(relative_path):
                failures['no_json'].append(relative_path)
            elif not self.check_json_valid(relative_path):
                failures['invalid_json'].append(relative_path)

        # Add explicit failures
        for failure in explicit_failures:
            filename = failure.get('filename') if isinstance(failure, dict) else failure
            failures['explicit_failed'].append(filename)

        # Find orphaned JSON files (exist but not marked as processed)
        if self.results_dir.exists():
            for json_file in self.results_dir.glob("**/*.json"):
                relative_path = str(json_file.relative_to(self.results_dir).with_suffix(''))
                # Add back the original extension (assuming .jpg, could be others)
                for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
                    potential_path = relative_path + ext
                    if potential_path in processed_files:
                        break
                else:
                    # Not found with any extension
                    failures['orphaned_json'].append(str(json_file.relative_to(self.results_dir)))

        return failures

    def show_report(self, failures: Dict[str, List[str]]):
        """Display failure report"""
        print("=" * 70)
        print("FAILURE REPORT")
        print("=" * 70)

        total_failures = sum(len(v) for k, v in failures.items() if k != 'orphaned_json')

        if failures['no_json']:
            print(f"\n❌ NO JSON OUTPUT ({len(failures['no_json'])} files)")
            print("   Files marked as processed but no JSON result exists:")
            for f in failures['no_json'][:10]:
                print(f"   - {f}")
            if len(failures['no_json']) > 10:
                print(f"   ... and {len(failures['no_json']) - 10} more")

        if failures['invalid_json']:
            print(f"\n⚠️  INVALID JSON ({len(failures['invalid_json'])} files)")
            print("   JSON file exists but is corrupt/invalid:")
            for f in failures['invalid_json'][:10]:
                print(f"   - {f}")
            if len(failures['invalid_json']) > 10:
                print(f"   ... and {len(failures['invalid_json']) - 10} more")

        if failures['explicit_failed']:
            print(f"\n📋 EXPLICITLY FAILED ({len(failures['explicit_failed'])} files)")
            print("   Listed in failed_files in the index:")
            for f in failures['explicit_failed'][:10]:
                print(f"   - {f}")
            if len(failures['explicit_failed']) > 10:
                print(f"   ... and {len(failures['explicit_failed']) - 10} more")

        if failures['orphaned_json']:
            print(f"\n👻 ORPHANED JSON ({len(failures['orphaned_json'])} files)")
            print("   JSON files exist but not marked as processed (shouldn't happen):")
            for f in failures['orphaned_json'][:10]:
                print(f"   - {f}")
            if len(failures['orphaned_json']) > 10:
                print(f"   ... and {len(failures['orphaned_json']) - 10} more")

        print("\n" + "=" * 70)
        print(f"TOTAL FAILURES: {total_failures}")
        print("=" * 70)

    def cleanup(self, failures: Dict[str, List[str]], delete_invalid_json: bool = False):
        """Remove failed files from processed list"""
        index_data = self.load_index()
        processed_files = set(index_data.get('processed_files', []))

        files_to_remove = set()

        # Files to remove from processed list (so they can be retried)
        files_to_remove.update(failures['no_json'])
        files_to_remove.update(failures['invalid_json'])
        files_to_remove.update(failures['explicit_failed'])

        # Remove from processed list
        original_count = len(processed_files)
        processed_files -= files_to_remove
        removed_count = original_count - len(processed_files)

        # Update index
        index_data['processed_files'] = sorted(list(processed_files))
        index_data['failed_files'] = []  # Clear failed files list

        # Save updated index
        with open(self.index_file, 'w') as f:
            json.dump(index_data, f, indent=2)

        print(f"\n✅ Removed {removed_count} files from processed list")
        print(f"   These files will be retried on next run")

        # Optionally delete invalid JSON files
        if delete_invalid_json and failures['invalid_json']:
            deleted = 0
            for relative_path in failures['invalid_json']:
                json_path = self.results_dir / Path(relative_path).with_suffix('.json')
                if json_path.exists():
                    json_path.unlink()
                    deleted += 1
            print(f"🗑️  Deleted {deleted} invalid JSON files")


def main():
    parser = argparse.ArgumentParser(description="Clean up failed OCR processing attempts")
    parser.add_argument("--doit", action="store_true", help="Actually perform cleanup (default: dry run)")
    parser.add_argument("--delete-invalid-json", action="store_true", help="Also delete invalid JSON files")
    parser.add_argument("--index", default="processing_index.json", help="Index file path")
    parser.add_argument("--downloads-dir", default="./downloads", help="Downloads directory")
    parser.add_argument("--results-dir", default="./results", help="Results directory")

    args = parser.parse_args()

    cleanup = FailureCleanup(
        index_file=args.index,
        downloads_dir=args.downloads_dir,
        results_dir=args.results_dir
    )

    # Find failures
    failures = cleanup.find_failures()

    # Show report
    cleanup.show_report(failures)

    # Check if there's anything to clean
    total_failures = sum(len(v) for k, v in failures.items() if k != 'orphaned_json')
    if total_failures == 0:
        print("\n✨ No failures found - everything looks good!")
        return

    # Perform cleanup if requested
    if args.doit:
        print("\n🚨 PERFORMING CLEANUP...")
        response = input("Are you sure? This will remove failed files from the processed list. (yes/no): ")
        if response.lower() == 'yes':
            cleanup.cleanup(failures, delete_invalid_json=args.delete_invalid_json)
            print("\n✅ Cleanup complete!")
        else:
            print("❌ Cleanup cancelled")
    else:
        print("\n💡 This was a DRY RUN - no changes made")
        print("   Run with --doit to actually remove failed files from the processed list")
        print("   Add --delete-invalid-json to also delete corrupt JSON files")


if __name__ == "__main__":
    main()

# Epstein Files Archive

An automatically processed, OCR'd, searchable archive of publicly released documents related to the Jeffrey Epstein case.

## About

This project automatically processes thousands of scanned document pages using AI-powered OCR to:
- Extract and preserve all text (printed and handwritten)
- Identify and index entities (people, organizations, locations, dates)
- Reconstruct multi-page documents from individual scans
- Provide a searchable web interface to explore the archive

**This is a public service project.** All documents are from public releases. This archive makes them more accessible and searchable.

## Features

- **Full OCR**: Extracts both printed and handwritten text from all documents
- **Entity Extraction**: Automatically identifies and indexes:
  - People mentioned
  - Organizations
  - Locations
  - Dates
  - Reference numbers
- **Document Reconstruction**: Groups scanned pages back into complete documents
- **Searchable Interface**: Browse by person, organization, location, date, or document type
- **Static Site**: Fast, lightweight, works anywhere

## Project Structure

```
.
├── process_images.py       # Python script to OCR images using AI
├── requirements.txt         # Python dependencies
├── .env.example            # Example environment configuration
├── downloads/              # Place document images here
├── results/                # Extracted JSON data per document
├── src/                    # 11ty source files for website
├── .eleventy.js            # Static site generator configuration
└── _site/                  # Generated static website (after build)
```

## Setup

### 1. Install Dependencies

**Python (for OCR processing):**
```bash
pip install -r requirements.txt
```

**Node.js (for website generation):**
```bash
npm install
```

### 2. Configure API

Copy `.env.example` to `.env` and configure your OpenAI-compatible API endpoint:

```bash
cp .env.example .env
# Edit .env with your API details
```

### 3. Process Documents

Place document images in the `downloads/` directory, then run:

```bash
python process_images.py

# Options:
# --limit N          # Process only N images (for testing)
# --workers N        # Number of parallel workers (default: 5)
# --no-resume        # Process all files, ignore index
```

The script will:
- Process each image through the OCR API
- Extract text, entities, and metadata
- Save results to `./results/{folder}/{imagename}.json`
- Track progress in `processing_index.json` (resume-friendly)

### 4. Generate Website

Build the static site from the processed data:

```bash
npm run build    # Build static site to _site/
npm start        # Development server with live reload
```

## How It Works

1. **Document Processing**: Images are sent to an AI vision model that extracts:
   - All text in reading order
   - Document metadata (page numbers, document numbers, dates)
   - Named entities (people, orgs, locations)
   - Text type annotations (printed, handwritten, stamps)

2. **Document Grouping**: Individual page scans are automatically grouped by document number and sorted by page number to reconstruct complete documents

3. **Static Site Generation**: 11ty processes the JSON data to create:
   - Index pages for all entities
   - Individual document pages with full text
   - Search and browse interfaces

## Performance

- Processes ~2,000 pages into ~400 multi-page documents
- Handles LLM inconsistencies in document number formatting
- Resume-friendly processing (skip already-processed files)
- Parallel processing with configurable workers

## Contributing

This is an open archive project. Contributions welcome:
- Report issues with OCR accuracy
- Suggest UI improvements
- Add additional document sources
- Improve entity extraction

## Support This Project

If you find this archive useful, consider supporting its maintenance and hosting:

**Bitcoin**: `bc1qmahlh5eql05w30cgf5taj3n23twmp0f5xcvnnz`

## Deployment

The site is automatically deployed to GitHub Pages on every push to the main branch.

### GitHub Pages Setup

1. Push this repository to GitHub: `https://github.com/epstein-docs/epstein-docs`
2. Go to Settings → Pages
3. Source: GitHub Actions
4. The workflow will automatically build and deploy the site

The site will be available at: `https://epstein-docs.github.io/epstein-docs/`

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

The code in this repository is open source and free to use. The documents themselves are public records.

**Repository**: https://github.com/epstein-docs/epstein-docs

## Disclaimer

This is an independent archival project. Documents are sourced from public releases. The maintainers make no representations about completeness or accuracy of the archive.

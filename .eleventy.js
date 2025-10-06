const fs = require('fs');
const path = require('path');

module.exports = function(eleventyConfig) {
  // Copy results directory to output
  eleventyConfig.addPassthroughCopy({ "./results": "documents" });

  // Cache the documents data - only compute once
  let cachedDocuments = null;

  function getDocuments() {
    if (cachedDocuments) {
      return cachedDocuments;
    }
    const resultsDir = path.join(__dirname, './results');
    const pages = [];

    function readDocuments(dir, relativePath = '') {
      const entries = fs.readdirSync(dir, { withFileTypes: true });

      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        const relPath = path.join(relativePath, entry.name);

        if (entry.isDirectory()) {
          readDocuments(fullPath, relPath);
        } else if (entry.name.endsWith('.json')) {
          try {
            const content = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
            pages.push({
              path: relPath,
              filename: entry.name.replace('.json', ''),
              folder: relativePath || 'root',
              ...content
            });
          } catch (e) {
            console.error(`Error reading ${fullPath}:`, e.message);
          }
        }
      }
    }

    readDocuments(resultsDir);

    // Normalize function to handle LLM inconsistencies in document numbers
    const normalizeDocNum = (docNum) => {
      if (!docNum) return null;
      // Convert to lowercase, remove all non-alphanumeric except hyphens, collapse multiple hyphens
      return String(docNum)
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-+|-+$/g, '');
    };

    // Group pages by NORMALIZED document_number to handle LLM variations
    const documentMap = new Map();

    pages.forEach(page => {
      // Use document_number from metadata to group pages of the same document
      const rawDocNum = page.document_metadata?.document_number;

      // Skip pages without a document number
      if (!rawDocNum) {
        console.warn(`Page ${page.filename} has no document_number, using filename as fallback`);
        const fallbackKey = normalizeDocNum(page.filename) || page.filename;
        if (!documentMap.has(fallbackKey)) {
          documentMap.set(fallbackKey, []);
        }
        documentMap.get(fallbackKey).push(page);
        return;
      }

      // Normalize the document number to group variants together
      const normalizedDocNum = normalizeDocNum(rawDocNum);

      if (!documentMap.has(normalizedDocNum)) {
        documentMap.set(normalizedDocNum, []);
      }
      documentMap.get(normalizedDocNum).push(page);
    });

    // Convert to array and sort pages within each document
    const documents = Array.from(documentMap.entries()).map(([normalizedDocNum, docPages]) => {

      // Sort pages by page number
      docPages.sort((a, b) => {
        const pageA = parseInt(a.document_metadata?.page_number) || 0;
        const pageB = parseInt(b.document_metadata?.page_number) || 0;
        return pageA - pageB;
      });

      // Combine all entities from all pages
      const allEntities = {
        people: new Set(),
        organizations: new Set(),
        locations: new Set(),
        dates: new Set(),
        reference_numbers: new Set()
      };

      docPages.forEach(page => {
        if (page.entities) {
          Object.keys(allEntities).forEach(key => {
            if (page.entities[key]) {
              page.entities[key].forEach(item => allEntities[key].add(item));
            }
          });
        }
      });

      // Get metadata from first page
      const firstPage = docPages[0];

      // Get all unique folders that contain pages of this document
      const folders = [...new Set(docPages.map(p => p.folder))];

      // Get all unique raw document numbers (for display)
      const rawDocNums = [...new Set(docPages.map(p => p.document_metadata?.document_number).filter(Boolean))];

      return {
        unique_id: normalizedDocNum,  // Normalized version for unique URLs
        document_number: rawDocNums.length === 1 ? rawDocNums[0] : normalizedDocNum, // Show original if consistent, else normalized
        raw_document_numbers: rawDocNums, // All variations found
        pages: docPages,
        page_count: docPages.length,
        document_metadata: firstPage.document_metadata,
        entities: {
          people: Array.from(allEntities.people),
          organizations: Array.from(allEntities.organizations),
          locations: Array.from(allEntities.locations),
          dates: Array.from(allEntities.dates),
          reference_numbers: Array.from(allEntities.reference_numbers)
        },
        full_text: docPages.map(p => p.full_text).join('\n\n--- PAGE BREAK ---\n\n'),
        folder: folders.join(', '),  // Show all folders if document spans multiple
        folders: folders  // Keep array for reference
      };
    });

    cachedDocuments = documents;
    return documents;
  }

  // Add global data - load all pages and group into documents
  eleventyConfig.addGlobalData("documents", getDocuments);

  // Build indices from grouped documents
  eleventyConfig.addGlobalData("indices", () => {
    const documentsData = getDocuments();

    const people = new Map();
    const organizations = new Map();
    const locations = new Map();
    const dates = new Map();
    const documentTypes = new Map();

    documentsData.forEach(doc => {
      // People
      if (doc.entities?.people) {
        doc.entities.people.forEach(person => {
          if (!people.has(person)) people.set(person, []);
          people.get(person).push(doc);
        });
      }

      // Organizations
      if (doc.entities?.organizations) {
        doc.entities.organizations.forEach(org => {
          if (!organizations.has(org)) organizations.set(org, []);
          organizations.get(org).push(doc);
        });
      }

      // Locations
      if (doc.entities?.locations) {
        doc.entities.locations.forEach(loc => {
          if (!locations.has(loc)) locations.set(loc, []);
          locations.get(loc).push(doc);
        });
      }

      // Dates
      if (doc.entities?.dates) {
        doc.entities.dates.forEach(date => {
          if (!dates.has(date)) dates.set(date, []);
          dates.get(date).push(doc);
        });
      }

      // Document types
      const docType = doc.document_metadata?.document_type;
      if (docType) {
        if (!documentTypes.has(docType)) documentTypes.set(docType, []);
        documentTypes.get(docType).push(doc);
      }
    });

    return {
      people: Array.from(people.entries()).map(([name, docs]) => ({ name, docs, count: docs.length })).sort((a, b) => b.count - a.count),
      organizations: Array.from(organizations.entries()).map(([name, docs]) => ({ name, docs, count: docs.length })).sort((a, b) => b.count - a.count),
      locations: Array.from(locations.entries()).map(([name, docs]) => ({ name, docs, count: docs.length })).sort((a, b) => b.count - a.count),
      dates: Array.from(dates.entries()).map(([name, docs]) => ({ name, docs, count: docs.length })).sort((a, b) => b.count - a.count),
      documentTypes: Array.from(documentTypes.entries()).map(([name, docs]) => ({ name, docs, count: docs.length })).sort((a, b) => b.count - a.count)
    };
  });

  return {
    dir: {
      input: "src",
      output: "_site",
      includes: "_includes"
    },
    pathPrefix: "/"
  };
};

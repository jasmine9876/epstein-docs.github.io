const fs = require('fs');
const path = require('path');

module.exports = function(eleventyConfig) {
  // Copy results directory to output
  eleventyConfig.addPassthroughCopy({ "./results": "documents" });

  // Load deduplication mappings if available
  let dedupeMappings = { people: {}, organizations: {}, locations: {} };
  const dedupeFile = path.join(__dirname, 'dedupe.json');
  if (fs.existsSync(dedupeFile)) {
    try {
      dedupeMappings = JSON.parse(fs.readFileSync(dedupeFile, 'utf8'));
      console.log('✅ Loaded deduplication mappings from dedupe.json');
    } catch (e) {
      console.warn('⚠️  Could not load dedupe.json:', e.message);
    }
  } else {
    console.log('ℹ️  No dedupe.json found - entities will not be deduplicated');
  }

  // Load document type deduplication mappings if available
  let typeDedupeMap = {};
  const typeDedupeFile = path.join(__dirname, 'dedupe_types.json');
  if (fs.existsSync(typeDedupeFile)) {
    try {
      const data = JSON.parse(fs.readFileSync(typeDedupeFile, 'utf8'));
      typeDedupeMap = data.mappings || {};
      console.log('✅ Loaded document type mappings from dedupe_types.json');
    } catch (e) {
      console.warn('⚠️  Could not load dedupe_types.json:', e.message);
    }
  } else {
    console.log('ℹ️  No dedupe_types.json found - document types will not be deduplicated');
  }

  // Helper function to apply deduplication mapping
  function applyDedupe(entityType, entityName) {
    if (!entityName) return entityName;
    return dedupeMappings[entityType]?.[entityName] || entityName;
  }

  // Helper function to normalize document types (for grouping)
  function normalizeDocType(docType) {
    if (!docType) return null;
    const trimmed = String(docType).trim();

    // Apply deduplication mapping if available
    const canonical = typeDedupeMap[trimmed] || trimmed;

    return canonical.toLowerCase().trim();
  }

  // Helper function to format document types for display (title case)
  function formatDocType(docType) {
    if (!docType) return 'Unknown';
    const trimmed = String(docType).trim();

    // Apply deduplication mapping if available
    const canonical = typeDedupeMap[trimmed] || trimmed;

    // Return the canonical name (already in proper case from dedupe script)
    return canonical;
  }

  // Helper function to normalize dates to consistent format
  function normalizeDate(dateStr) {
    if (!dateStr) return null;

    const str = String(dateStr).trim();

    // Already in ISO format (YYYY-MM-DD)
    if (/^\d{4}-\d{2}-\d{2}$/.test(str)) {
      return str;
    }

    // Just a year (YYYY)
    if (/^\d{4}$/.test(str)) {
      return `${str}-00-00`;
    }

    // Try to parse various date formats
    const months = {
      'jan': '01', 'january': '01',
      'feb': '02', 'february': '02',
      'mar': '03', 'march': '03',
      'apr': '04', 'april': '04',
      'may': '05',
      'jun': '06', 'june': '06',
      'jul': '07', 'july': '07',
      'aug': '08', 'august': '08',
      'sep': '09', 'september': '09',
      'oct': '10', 'october': '10',
      'nov': '11', 'november': '11',
      'dec': '12', 'december': '12'
    };

    // "February 15, 2005" or "Feb 15, 2005"
    const match1 = str.match(/^(\w+)\s+(\d{1,2}),?\s+(\d{4})$/i);
    if (match1) {
      const month = months[match1[1].toLowerCase()];
      if (month) {
        const day = match1[2].padStart(2, '0');
        return `${match1[3]}-${month}-${day}`;
      }
    }

    // "15 February 2005" or "15 Feb 2005"
    const match2 = str.match(/^(\d{1,2})\s+(\w+)\s+(\d{4})$/i);
    if (match2) {
      const month = months[match2[2].toLowerCase()];
      if (month) {
        const day = match2[1].padStart(2, '0');
        return `${match2[3]}-${month}-${day}`;
      }
    }

    // "2005/02/15" or "2005.02.15"
    const match3 = str.match(/^(\d{4})[\/\.](\d{1,2})[\/\.](\d{1,2})$/);
    if (match3) {
      const month = match3[2].padStart(2, '0');
      const day = match3[3].padStart(2, '0');
      return `${match3[1]}-${month}-${day}`;
    }

    // "02/15/2005" or "02.15.2005" (US format)
    const match4 = str.match(/^(\d{1,2})[\/\.](\d{1,2})[\/\.](\d{4})$/);
    if (match4) {
      const month = match4[1].padStart(2, '0');
      const day = match4[2].padStart(2, '0');
      return `${match4[3]}-${month}-${day}`;
    }

    // Couldn't parse - return original
    return str;
  }

  // Helper function to format dates for display
  function formatDate(normalizedDate) {
    if (!normalizedDate) return 'Unknown Date';

    // Year only (YYYY-00-00)
    if (normalizedDate.endsWith('-00-00')) {
      return normalizedDate.substring(0, 4);
    }

    // Full date (YYYY-MM-DD)
    const match = normalizedDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
      const months = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                      'July', 'August', 'September', 'October', 'November', 'December'];
      const year = match[1];
      const month = parseInt(match[2]);
      const day = parseInt(match[3]);

      if (month > 0 && month <= 12) {
        return `${months[month]} ${day}, ${year}`;
      }
    }

    // Fallback
    return normalizedDate;
  }

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

      // Apply deduplication to document entities
      const deduplicatedEntities = {
        people: [...new Set(Array.from(allEntities.people).map(p => applyDedupe('people', p)))],
        organizations: [...new Set(Array.from(allEntities.organizations).map(o => applyDedupe('organizations', o)))],
        locations: [...new Set(Array.from(allEntities.locations).map(l => applyDedupe('locations', l)))],
        dates: [...new Set(Array.from(allEntities.dates).map(d => {
          const normalized = normalizeDate(d);
          return normalized ? formatDate(normalized) : d;
        }))],
        reference_numbers: Array.from(allEntities.reference_numbers)
      };

      // Normalize document metadata
      const normalizedMetadata = {
        ...firstPage.document_metadata,
        document_type: firstPage.document_metadata?.document_type
          ? formatDocType(firstPage.document_metadata.document_type)
          : null,
        date: firstPage.document_metadata?.date
          ? formatDate(normalizeDate(firstPage.document_metadata.date))
          : firstPage.document_metadata?.date
      };

      return {
        unique_id: normalizedDocNum,  // Normalized version for unique URLs
        document_number: rawDocNums.length === 1 ? rawDocNums[0] : normalizedDocNum, // Show original if consistent, else normalized
        raw_document_numbers: rawDocNums, // All variations found
        pages: docPages,
        page_count: docPages.length,
        document_metadata: normalizedMetadata,
        entities: deduplicatedEntities,
        full_text: docPages.map(p => p.full_text).join('\n\n--- PAGE BREAK ---\n\n'),
        folder: folders.join(', '),  // Show all folders if document spans multiple
        folders: folders  // Keep array for reference
      };
    });

    cachedDocuments = documents;
    return documents;
  }

  // Load document analyses if available
  eleventyConfig.addGlobalData("analyses", () => {
    const analysesFile = path.join(__dirname, 'analyses.json');
    if (fs.existsSync(analysesFile)) {
      try {
        const data = JSON.parse(fs.readFileSync(analysesFile, 'utf8'));
        const analyses = data.analyses || [];

        // Apply document type deduplication to analyses
        if (Object.keys(typeDedupeMap).length > 0) {
          analyses.forEach(analysis => {
            if (analysis.analysis?.document_type) {
              const original = analysis.analysis.document_type;
              const canonical = typeDedupeMap[original] || original;
              analysis.analysis.document_type = canonical;
            }
          });
        }

        console.log(`✅ Loaded ${analyses.length} document analyses`);
        return analyses;
      } catch (e) {
        console.warn('⚠️  Could not load analyses.json:', e.message);
        return [];
      }
    }
    console.log('ℹ️  No analyses.json found - run analyze_documents.py to generate');
    return [];
  });

  // Get unique canonical document types from analyses
  eleventyConfig.addGlobalData("analysisDocumentTypes", () => {
    const analysesFile = path.join(__dirname, 'analyses.json');
    if (!fs.existsSync(analysesFile)) {
      return [];
    }

    try {
      const data = JSON.parse(fs.readFileSync(analysesFile, 'utf8'));
      const analyses = data.analyses || [];

      // Collect unique canonical types
      const typesSet = new Set();
      analyses.forEach(analysis => {
        if (analysis.analysis?.document_type) {
          let docType = analysis.analysis.document_type;

          // Apply deduplication if available
          if (Object.keys(typeDedupeMap).length > 0) {
            docType = typeDedupeMap[docType] || docType;
          }

          typesSet.add(docType);
        }
      });

      const uniqueTypes = Array.from(typesSet).sort();
      console.log(`✅ Found ${uniqueTypes.length} unique canonical document types for filters`);
      return uniqueTypes;
    } catch (e) {
      console.warn('⚠️  Could not load document types:', e.message);
      return [];
    }
  });

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
      // People (with deduplication)
      if (doc.entities?.people) {
        doc.entities.people.forEach(person => {
          const canonicalName = applyDedupe('people', person);
          if (!people.has(canonicalName)) people.set(canonicalName, []);
          people.get(canonicalName).push(doc);
        });
      }

      // Organizations (with deduplication)
      if (doc.entities?.organizations) {
        doc.entities.organizations.forEach(org => {
          const canonicalName = applyDedupe('organizations', org);
          if (!organizations.has(canonicalName)) organizations.set(canonicalName, []);
          organizations.get(canonicalName).push(doc);
        });
      }

      // Locations (with deduplication)
      if (doc.entities?.locations) {
        doc.entities.locations.forEach(loc => {
          const canonicalName = applyDedupe('locations', loc);
          if (!locations.has(canonicalName)) locations.set(canonicalName, []);
          locations.get(canonicalName).push(doc);
        });
      }

      // Dates (normalize for grouping)
      if (doc.entities?.dates) {
        doc.entities.dates.forEach(date => {
          const normalized = normalizeDate(date);
          if (normalized) {
            if (!dates.has(normalized)) dates.set(normalized, []);
            dates.get(normalized).push(doc);
          }
        });
      }

      // Document types (normalize for grouping)
      const docType = doc.document_metadata?.document_type;
      if (docType) {
        const normalized = normalizeDocType(docType);
        if (normalized) {
          if (!documentTypes.has(normalized)) documentTypes.set(normalized, []);
          documentTypes.get(normalized).push(doc);
        }
      }
    });

    // Deduplicate document arrays (remove duplicate document references)
    const dedupeDocArray = (docs) => {
      const seen = new Set();
      return docs.filter(doc => {
        if (seen.has(doc.unique_id)) return false;
        seen.add(doc.unique_id);
        return true;
      });
    };

    return {
      people: Array.from(people.entries()).map(([name, docs]) => ({
        name,
        docs: dedupeDocArray(docs),
        count: dedupeDocArray(docs).length
      })).sort((a, b) => b.count - a.count),
      organizations: Array.from(organizations.entries()).map(([name, docs]) => ({
        name,
        docs: dedupeDocArray(docs),
        count: dedupeDocArray(docs).length
      })).sort((a, b) => b.count - a.count),
      locations: Array.from(locations.entries()).map(([name, docs]) => ({
        name,
        docs: dedupeDocArray(docs),
        count: dedupeDocArray(docs).length
      })).sort((a, b) => b.count - a.count),
      dates: Array.from(dates.entries()).map(([normalizedDate, docs]) => ({
        name: formatDate(normalizedDate),  // Display formatted version
        normalizedDate,  // Keep normalized for sorting
        docs: dedupeDocArray(docs),
        count: dedupeDocArray(docs).length
      })).sort((a, b) => {
        // Sort by normalized date (YYYY-MM-DD format sorts correctly)
        return b.normalizedDate.localeCompare(a.normalizedDate);
      }),
      documentTypes: Array.from(documentTypes.entries()).map(([normalizedType, docs]) => ({
        name: formatDocType(normalizedType),  // Display formatted version
        docs: dedupeDocArray(docs),
        count: dedupeDocArray(docs).length
      })).sort((a, b) => b.count - a.count)
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

// Connect to socket with specific configuration
console.log("Connecting to Socket.IO...");
const socket = io({
  transports: ['polling', 'websocket'],  // Start with polling for better compatibility
  reconnection: true,                    // Enable reconnection
  reconnectionAttempts: 10,              // Try to reconnect 10 times
  reconnectionDelay: 1000,               // Start with 1 second delay
  reconnectionDelayMax: 5000,            // Maximum 5 seconds delay
  timeout: 20000,                        // Connection timeout
  forceNew: true,                        // Force a new connection
  path: '/socket.io'                     // Explicit path
});

// Handle case ID form submission
document.getElementById('caseIdForm').addEventListener('submit', function(e) {
  e.preventDefault();

  // Get case ID
  const caseId = document.getElementById('caseId').value.trim();

  if (!caseId) {
    alert('Please enter a valid case ID');
    return;
  }

  // Disable form and show loading message
  document.getElementById('startScrapeBtn').disabled = true;
  document.getElementById('startScrapeBtn').innerHTML =
    '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Starting...';

  // Submit the case ID to start scraping
  fetch('/start-scrape', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ caseId })
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      // Hide the form and show status cards
      document.getElementById('case-id-form-container').style.display = 'none';
      document.getElementById('status-cards').style.display = 'flex';
      document.getElementById('case-id').textContent = caseId;

      // Show log container and add initial entry
      const logContainer = document.getElementById('log-container');
      logContainer.innerHTML = '<div class="log-info">Starting scrape for case ID: ' + caseId + '</div>';

      // Make sure process log section is visible
      document.getElementById('process-log-section').style.display = 'block';
    } else {
      // Show error
      alert(data.error || 'Error starting scrape');
      document.getElementById('startScrapeBtn').disabled = false;
      document.getElementById('startScrapeBtn').textContent = 'Start Scraping';
    }
  })
  .catch(error => {
    console.error('Error:', error);
    alert('Error: ' + error.message);
    document.getElementById('startScrapeBtn').disabled = false;
    document.getElementById('startScrapeBtn').textContent = 'Start Scraping';
  });
});

// No form submission needed - using automatic database lookup

// Add connection event handlers
socket.on('connect', () => {
  console.log('Connected to server with session ID:', socket.id);
  // Update UI to show connected status
  const statusElement = document.getElementById('status');
  if (statusElement) {
    statusElement.innerHTML = '<span class="badge bg-success">Connected</span>';
  }

  // Try to reconnect to any ongoing process
  if (socket.id) {
    socket.emit('join_session', {
      clientId: socket.id,
      timestamp: new Date().toISOString()
    });
  }
});

socket.on('connect_error', (error) => {
  console.error('Connection error:', error);
  // Update UI to show error
  const statusElement = document.getElementById('status');
  if (statusElement) {
    statusElement.innerHTML = '<span class="badge bg-danger">Connection Error</span>';
  }
});

socket.on('disconnect', (reason) => {
  console.log('Disconnected:', reason);
  // Update UI to show disconnected status
  const statusElement = document.getElementById('status');
  if (statusElement) {
    statusElement.innerHTML = '<span class="badge bg-warning">Disconnected</span>';
  }
});
let timerInterval;
let startTime;

// Elements
const logContainer = document.getElementById('log-container');
const progressBar = document.getElementById('progress-bar');
const timerElement = document.getElementById('timer');
const resultsContainer = document.getElementById('results-container');
const statusElement = document.getElementById('status');
const caseIdElement = document.getElementById('case-id');
const totalFeesElement = document.getElementById('total-fees');
const approvedFeesElement = document.getElementById('approved-fees');
const totalAmountElement = document.getElementById('total-amount');
const approvedAmountElement = document.getElementById('approved-amount');
const downloadLinks = document.getElementById('download-links');

// Handle log messages
socket.on('log', (data) => {
  const logEntry = document.createElement('div');
  logEntry.className = `log-${data.type}`;
  logEntry.textContent = data.message;
  logContainer.appendChild(logEntry);
  logContainer.scrollTop = logContainer.scrollHeight;
  
  // Update progress bar based on log messages
  updateProgressBar(data.message);
});

// Handle timer updates
socket.on('timer-start', (data) => {
  startTime = new Date(data.startTime);
  clearInterval(timerInterval);
  timerInterval = setInterval(updateTimer, 1000);
  caseIdElement.textContent = data.caseId;
});

// Handle database results from automatic lookup
socket.on('database_results', (data) => {
  // The Database Search Results table has been removed since it's redundant
  console.log(`Received ${data.count} database results:`, data);

  // If there's a fallback, show a notification in the log
  if (data.results && data.results.some(fee => fee.is_fallback)) {
    const fallbackMessage = data.results.find(fee => fee.is_fallback)?.message ||
                          "No specific lienholder found. Using Standard amounts.";

    // Add a notification to the log
    const logEntry = document.createElement('div');
    logEntry.className = 'log-warning';
    logEntry.innerHTML = `<strong>Database Lookup Note:</strong> ${fallbackMessage}`;

    const logContainer = document.getElementById('log-container');
    if (logContainer) {
      logContainer.appendChild(logEntry);
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  }

  // Log the query parameters and results count
  const logMessage = document.createElement('div');
  logMessage.className = 'log-info';
  logMessage.innerHTML = `<strong>Database Search:</strong> Found ${data.count} matching fees for client=${data.queryInfo?.client_name || 'Unknown'}, lienholder=${data.queryInfo?.lienholder_name || 'Unknown'}, fee_type=${data.queryInfo?.fee_type || 'Unknown'}`;

  // If we have database fee results, try to update the card immediately
  if (data.results && data.results.length > 0) {
    const databaseFeeContainer = document.getElementById('database-fee-card-container');
    const databaseFeeElement = document.getElementById('database-fee');
    
    if (databaseFeeElement && databaseFeeContainer) {
      const amount = data.results[0].amount;
      databaseFeeElement.textContent = typeof amount === 'number' ? `$${amount.toFixed(2)}` : amount;
      console.log("Updated database fee display with:", amount);
    }
  }

  const logContainer = document.getElementById('log-container');
  if (logContainer) {
    logContainer.appendChild(logMessage);
    logContainer.scrollTop = logContainer.scrollHeight;
  }

  // Database results are shown directly in the main fee tables now
  console.log(`Database search completed: Found ${data.count} fee records`);
});

// Handle database notices (like fallback to Standard lienholder)
socket.on('database_notice', (data) => {
  // Add notice to log container
  const logEntry = document.createElement('div');
  logEntry.className = `log-${data.type}`;
  logEntry.innerHTML = `<strong>${data.type === 'warning' ? '⚠️' : 'ℹ️'}</strong> ${data.message}`;
  logContainer.appendChild(logEntry);
  logContainer.scrollTop = logContainer.scrollHeight;
});

// Handle completion
socket.on('process-complete', (data) => {
  clearInterval(timerInterval);
  statusElement.innerHTML = '<span class="badge bg-success">Completed</span>';
  progressBar.style.width = '100%';
  progressBar.classList.remove('progress-bar-animated');

  // Show results section
  resultsContainer.style.display = 'block';

  // Update case information
  const clientNameElement = document.getElementById('client-name');
  const lienHolderNameElement = document.getElementById('lien-holder-name');
  const repoTypeElement = document.getElementById('repo-type');
  const databaseFeeContainer = document.getElementById('database-fee-card-container');
  const databaseFeeElement = document.getElementById('database-fee');

  if (data.caseInfo) {
    clientNameElement.textContent = data.caseInfo.clientName || 'Not available';
    lienHolderNameElement.textContent = data.caseInfo.lienHolderName || 'Not available';
    repoTypeElement.textContent = data.caseInfo.repoType || 'Not available';

    console.log("Looking for database fee in data:", {
      databaseFees: data.databaseFees || [],
      allFeesTable: data.allFeesTable ? data.allFeesTable.filter(f => f.source === 'Database') : []
    });

    // Check if we have database fees to display
    if (data.databaseFees && data.databaseFees.length > 0) {
      const databaseFee = data.databaseFees[0];
      console.log("Found database fee in databaseFees:", databaseFee);
      if (databaseFeeElement) databaseFeeElement.textContent = databaseFee.amount || '$0.00';
    } else {
      // Try to get the database fee from allFeesTable if databaseFees array is empty
      const dbFeeFromAllFees = data.allFeesTable ? data.allFeesTable.find(fee => fee.source === 'Database') : null;
      
      if (dbFeeFromAllFees) {
        console.log("Found database fee in allFeesTable:", dbFeeFromAllFees);
        if (databaseFeeElement) databaseFeeElement.textContent = dbFeeFromAllFees.amount || '$0.00';
      } else {
        // As a last resort, check the log for database fee information
        const logEntries = document.querySelectorAll('#log-container .log-info');
        let foundDatabaseFee = false;
        
        for (const entry of logEntries) {
          if (entry.textContent.includes("Found repo fee in database: $")) {
            const match = entry.textContent.match(/Found repo fee in database: \$([\d.]+)/);
            if (match && match[1]) {
              console.log("Found database fee in log entries:", match[1]);
              databaseFeeElement.textContent = '$' + match[1];
              foundDatabaseFee = true;
              break;
            }
          }
        }
        
        if (!foundDatabaseFee) {
          console.log("No database fees found anywhere");
        }
      }
    }
  }

  // Update hidden summary stats elements (they're still in the DOM but not visible)
  if (totalFeesElement) totalFeesElement.textContent = data.summary?.totalFees || '0';
  if (approvedFeesElement) approvedFeesElement.textContent = data.summary?.approvedFees || '0';
  if (totalAmountElement) totalAmountElement.textContent = data.summary?.totalAmount || '$0.00';
  if (approvedAmountElement) approvedAmountElement.textContent = data.summary?.approvedAmount || '$0.00';

  // IMPORTANT: Process all fees for the three-table structure
  processFeesIntoTables(data);
  
  // Add download links
  downloadLinks.innerHTML = '';
  const placeholder = document.querySelector('.download-placeholder');

  if (data.files && Array.isArray(data.files) && data.files.length > 0) {
    // Hide placeholder if it exists
    if (placeholder) placeholder.style.display = 'none';

    console.log("Adding download links for files:", data.files);

    data.files.forEach(file => {
      const button = document.createElement('a');
      button.href = file.url;
      button.className = 'btn btn-primary me-2 mb-2';
      button.download = file.filename;
      button.innerHTML = `<i class="bi bi-download"></i> ${file.label}`;
      downloadLinks.appendChild(button);
    });
  } else {
    console.log("No files available for download");

    // Show placeholder message
    if (placeholder) {
      placeholder.style.display = 'block';
    } else {
      // Create a message if the placeholder doesn't exist
      const message = document.createElement('div');
      message.className = 'alert alert-info mt-2';
      message.innerHTML = `<i class="bi bi-info-circle"></i> No download files available. Please check server configuration.`;
      downloadLinks.appendChild(message);
    }
  }
});

// Process fees into category-specific tables
function processFeesIntoTables(data) {
  console.log("Processing fees into category-specific tables, data structure:", data);

  // Create container for all category tables
  const resultsSection = document.querySelector('.card-body');

  // Clear any existing category tables
  const existingCategoryContainers = document.querySelectorAll('.category-table-container');
  existingCategoryContainers.forEach(container => container.remove());

  // Get the category tables container
  const categoryTablesContainer = document.getElementById('category-tables-container');
  if (!categoryTablesContainer) {
    console.error("Category tables container not found!");
    return;
  }

  // Clear the container
  categoryTablesContainer.innerHTML = '';

  // Check if we have the new category-grouped structure
  if (data.categoryGroupedFees && Object.keys(data.categoryGroupedFees).length > 0) {
    console.log("Found categoryGroupedFees object with", Object.keys(data.categoryGroupedFees).length, "categories");
    createCategoryTables(data.categoryGroupedFees, data.categoryStyles || {
      'predefined': '#e3f2fd',  // Light Blue
      'keys': '#fff8e1',        // Soft Amber
      'other': '#e0f2f1'        // Soft Teal
    });
    return;
  }

  // Fallback to the old three-table structure if needed
  console.log("No categoryGroupedFees found, falling back to three-table structure");

  // Get the correct data structure for the three tables
  let predefinedFees = [];
  let keysFees = [];
  let otherFees = [];

  // Check if we have the specialized tables format
  if (data.categorizedFees && typeof data.categorizedFees === 'object') {
    console.log("Found categorizedFees object:", data.categorizedFees);
    predefinedFees = data.categorizedFees.predefinedFeesTable || [];
    keysFees = data.categorizedFees.keysFeesTable || [];
    otherFees = data.categorizedFees.otherFeesTable || [];

    // Also check for direct top-level properties
    if (predefinedFees.length === 0 && Array.isArray(data.predefinedFeesTable)) {
      predefinedFees = data.predefinedFeesTable;
    }
    if (keysFees.length === 0 && Array.isArray(data.keysFeesTable)) {
      keysFees = data.keysFeesTable;
    }
    if (otherFees.length === 0 && Array.isArray(data.otherFeesTable)) {
      otherFees = data.otherFeesTable;
    }
  }
  // Fallback to splitting allFeesTable if specialized tables aren't available
  else if (Array.isArray(data.allFeesTable) && data.allFeesTable.length > 0) {
    const allFees = data.allFeesTable;
    console.log("Using allFeesTable with", allFees.length, "fees");

    // Split fees based on category and references
    predefinedFees = allFees.filter(fee =>
      fee.category !== 'Other' &&
      !isKeysFee(fee.category, fee.referenceSentence || '')
    );

    keysFees = allFees.filter(fee =>
      isKeysFee(fee.category, fee.referenceSentence || '')
    );

    otherFees = allFees.filter(fee =>
      fee.category === 'Other' &&
      !isKeysFee(fee.category, fee.referenceSentence || '')
    );
  }
  // Direct reading of fees from data structure as a last resort
  else if (Array.isArray(data.fees)) {
    console.log("Using direct fees array with", data.fees.length, "fees");
    const allFees = data.fees;

    // Split fees based on category and references
    predefinedFees = allFees.filter(fee =>
      (fee.category && fee.category !== 'Other') &&
      !isKeysFee(fee.category, fee.referenceSentence || '')
    );

    keysFees = allFees.filter(fee =>
      isKeysFee(fee.category || '', fee.referenceSentence || '')
    );

    otherFees = allFees.filter(fee =>
      (!fee.category || fee.category === 'Other') &&
      !isKeysFee(fee.category || '', fee.referenceSentence || '')
    );
  }

  // Check if we need to add additional fees to the "Other" category
  if (Array.isArray(data.additionalFees) && data.additionalFees.length > 0) {
    console.log("Adding", data.additionalFees.length, "additional fees to Other category");
    // Only add if we're not already using allFeesTable (which would include them)
    if (!Array.isArray(data.allFeesTable) || data.allFeesTable.length === 0) {
      otherFees = [...otherFees, ...data.additionalFees];
    }
  }

  console.log("Fee counts before processing - Predefined:", predefinedFees.length,
              "Keys:", keysFees.length, "Other:", otherFees.length);

  // Normalize sources for all fees
  predefinedFees = normalizeFeeSources(predefinedFees);
  keysFees = normalizeFeeSources(keysFees);
  otherFees = normalizeFeeSources(otherFees);

  // Make sure reference sentences are properly displayed
  predefinedFees = ensureReferenceSentences(predefinedFees);
  keysFees = ensureReferenceSentences(keysFees);
  otherFees = ensureReferenceSentences(otherFees);

  // Remove any database source fees - they should only appear in the card
  predefinedFees = predefinedFees.filter(fee => fee.source !== 'Database');
  keysFees = keysFees.filter(fee => fee.source !== 'Database');
  otherFees = otherFees.filter(fee => fee.source !== 'Database');

  console.log("Fee counts after processing - Predefined:", predefinedFees.length,
              "Keys:", keysFees.length, "Other:", otherFees.length);

  // Convert to category-grouped structure for display
  const categoryGroupedFees = {};

  // Group predefined fees by category
  predefinedFees.forEach(fee => {
    const category = fee.category || 'Unknown';
    const categoryLower = category.toLowerCase();

    if (!categoryGroupedFees[categoryLower]) {
      categoryGroupedFees[categoryLower] = {
        displayName: category,
        sanitizedName: sanitizeCategoryName(category),
        type: 'predefined',
        fees: []
      };
    }

    categoryGroupedFees[categoryLower].fees.push(fee);
  });

  // Add Keys fees
  if (keysFees.length > 0) {
    categoryGroupedFees['keys fee'] = {
      displayName: 'Keys Fee',
      sanitizedName: 'keys-fee',
      type: 'keys',
      fees: keysFees
    };
  }

  // Group other fees by category
  otherFees.forEach(fee => {
    const category = fee.category || 'Other';
    const categoryLower = category.toLowerCase();

    if (!categoryGroupedFees[categoryLower]) {
      categoryGroupedFees[categoryLower] = {
        displayName: category,
        sanitizedName: sanitizeCategoryName(category),
        type: 'other',
        fees: []
      };
    }

    categoryGroupedFees[categoryLower].fees.push(fee);
  });

  // Create tables for each category
  createCategoryTables(categoryGroupedFees, data.categoryStyles || {
    'predefined': '#e3f2fd',  // Light Blue
    'keys': '#fff8e1',        // Soft Amber
    'other': '#e0f2f1'        // Soft Teal
  });
}

// Helper function to sanitize category name for HTML ID
function sanitizeCategoryName(category) {
  if (!category) return 'unknown';
  return category.toLowerCase().replace(/[^a-z0-9]/g, '-');
}

// Create tables for each category
function createCategoryTables(categoryGroupedFees, categoryStyles) {
  console.log("Creating category-specific tables with", Object.keys(categoryGroupedFees).length, "categories");

  // Get the container for the tables
  const categoryTablesContainer = document.getElementById('category-tables-container');
  if (!categoryTablesContainer) {
    console.error("Category tables container not found!");
    return;
  }

  // Create a container for all category tables
  categoryTablesContainer.innerHTML = '';

  // Sort categories: predefined first, then keys, then other
  const sortedCategories = Object.values(categoryGroupedFees).sort((a, b) => {
    const typeOrder = { 'predefined': 1, 'keys': 2, 'other': 3 };
    if (typeOrder[a.type] !== typeOrder[b.type]) {
      return typeOrder[a.type] - typeOrder[b.type];
    }
    return a.displayName.localeCompare(b.displayName);
  });

  // Create a table for each category
  sortedCategories.forEach(category => {
    createCategoryTable(category, categoryTablesContainer, categoryStyles);
  });
}

// Create a table for a specific category
function createCategoryTable(category, container, categoryStyles) {
  console.log(`Creating table for category: ${category.displayName} (${category.type}) with ${category.fees.length} fees`);

  // Create container for this category
  const categoryContainer = document.createElement('div');
  categoryContainer.className = `category-table-container ${category.type}-category card card-accent-${getCategoryAccentClass(category.type)}`;
  categoryContainer.id = `category-${category.sanitizedName}`;

  // Create heading
  const heading = document.createElement('h3');
  heading.textContent = category.displayName;
  categoryContainer.appendChild(heading);

  // Create table
  const tableResponsive = document.createElement('div');
  tableResponsive.className = 'table-responsive';

  const table = document.createElement('table');
  table.className = `table table-hover category-table ${category.type}-table`;

  // Create table header
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');

  // Add table headers
  const headers = ['Date', 'Amount', 'Status', 'Source', 'Reference'];
  headers.forEach(headerText => {
    const th = document.createElement('th');
    th.textContent = headerText;
    headerRow.appendChild(th);
  });

  thead.appendChild(headerRow);
  table.appendChild(thead);

  // Create table body
  const tbody = document.createElement('tbody');

  // Check if we have fees for this category
  if (category.fees.length === 0) {
    // Empty state
    const emptyRow = document.createElement('tr');
    const emptyCell = document.createElement('td');
    emptyCell.colSpan = headers.length;
    emptyCell.className = 'empty-category-message';
    emptyCell.textContent = `No ${category.displayName} fees found`;
    emptyRow.appendChild(emptyCell);
    tbody.appendChild(emptyRow);
  } else {
    // Add fees to the table
    category.fees.forEach(fee => {
      const row = document.createElement('tr');

      // Date cell
      const dateCell = document.createElement('td');
      if (fee.date && fee.date.trim()) {
        dateCell.innerHTML = `<span style="font-weight: bold;">${fee.date}</span>`;
      } else {
        dateCell.innerHTML = '<span style="color: #999;">No date</span>';
      }
      row.appendChild(dateCell);

      // Amount cell
      const amountCell = document.createElement('td');
      amountCell.textContent = fee.amount || '$0.00';
      row.appendChild(amountCell);

      // Status cell
      const statusCell = document.createElement('td');
      if (fee.approved === 'Yes' || fee.isApproved === true) {
        statusCell.innerHTML = '<span class="badge bg-success">Approved</span>';
      } else {
        statusCell.innerHTML = '<span class="badge bg-warning">Likely</span>';
      }
      row.appendChild(statusCell);

      // Source cell
      const sourceCell = document.createElement('td');
      let sourceClass = '';
      if (fee.source === 'My Summary') {
        sourceClass = 'my-summary-source';
      } else if (fee.source === 'Updates' || fee.source === 'Case Page') {
        sourceClass = 'updates-source';
      } else if (fee.source === 'Database' || fee.source === 'Azure SQL') {
        sourceClass = 'database-source';
      }
      sourceCell.innerHTML = `<span class="tab-source ${sourceClass}">${fee.source}</span>`;
      row.appendChild(sourceCell);

      // Reference cell
      const referenceCell = document.createElement('td');
      const referenceSentence = fee.referenceSentence || '';
      // No truncation - show full reference
      referenceCell.innerHTML = `<div class="ref-text">${referenceSentence}</div>`;
      row.appendChild(referenceCell);

      tbody.appendChild(row);
    });
  }

  table.appendChild(tbody);
  tableResponsive.appendChild(table);
  categoryContainer.appendChild(tableResponsive);

  // Add the category container to the main container
  container.appendChild(categoryContainer);
}

// Helper function to get the appropriate accent class for a category type
function getCategoryAccentClass(categoryType) {
  switch(categoryType) {
    case 'predefined':
      return 'info';
    case 'keys':
      return 'warning';
    case 'other':
      return 'success';
    default:
      return 'primary';
  }
}

// Helper function to check if a fee is a Keys Fee based on category or reference
function isKeysFee(category, reference) {
  const keysTerms = ['key fee', 'keys fee', 'key charge', 'keys charge'];

  // Check if the category contains key-related terms
  if (category && keysTerms.some(term => category.toLowerCase().includes(term))) {
    return true;
  }

  // Check if the reference sentence contains key-related terms
  if (reference && keysTerms.some(term => reference.toLowerCase().includes(term))) {
    return true;
  }

  return false;
}

// Helper function to normalize fee sources
function normalizeFeeSources(fees) {
  return fees.map(fee => {
    const normalizedFee = {...fee};
    
    // Normalize source names
    if (normalizedFee.source === 'Case Page') {
      normalizedFee.source = 'Updates';
    } else if (!normalizedFee.source || normalizedFee.source === '') {
      normalizedFee.source = 'Updates'; // Default to Updates for empty sources
    }
    
    return normalizedFee;
  });
}

// Helper function to ensure fees have proper reference sentences
function ensureReferenceSentences(fees) {
  return fees.map(fee => {
    const normalizedFee = {...fee};
    
    // If referenceSentence is missing but content exists, use content
    if (!normalizedFee.referenceSentence && normalizedFee.content) {
      normalizedFee.referenceSentence = normalizedFee.content;
    }
    
    // If we have context in the amounts array, use it as fallback
    if (!normalizedFee.referenceSentence && 
        normalizedFee.amounts && 
        normalizedFee.amounts.length > 0 &&
        normalizedFee.amounts[0].context) {
      normalizedFee.referenceSentence = normalizedFee.amounts[0].context;
    }
    
    // Last resort fallback
    if (!normalizedFee.referenceSentence) {
      normalizedFee.referenceSentence = normalizedFee.category || 'Unknown';
    }
    
    return normalizedFee;
  });
}

// Handle errors
socket.on('process-error', (data) => {
  console.error('Process error received:', data);

  // Clear timer if it's running
  clearInterval(timerInterval);

  // Update status
  statusElement.innerHTML = '<span class="badge bg-danger">Error</span>';

  // Add error to log container
  const errorLogEntry = document.createElement('div');
  errorLogEntry.className = 'log-error';
  errorLogEntry.textContent = `[ERROR] ${data.error}`;
  logContainer.appendChild(errorLogEntry);

  // Add stack trace as collapsible section if available
  if (data.details) {
    // Create expandable details section
    const detailsContainer = document.createElement('div');
    detailsContainer.className = 'error-details mt-2 mb-4';

    // Create toggle button
    const toggleButton = document.createElement('button');
    toggleButton.className = 'btn btn-sm btn-outline-danger mb-2';
    toggleButton.textContent = 'Show Error Details';
    toggleButton.onclick = function() {
      const detailsElement = document.getElementById('error-stack-trace');
      if (detailsElement.style.display === 'none') {
        detailsElement.style.display = 'block';
        this.textContent = 'Hide Error Details';
      } else {
        detailsElement.style.display = 'none';
        this.textContent = 'Show Error Details';
      }
    };

    // Create stack trace pre element
    const stackTrace = document.createElement('pre');
    stackTrace.id = 'error-stack-trace';
    stackTrace.className = 'bg-dark text-light p-3 rounded';
    stackTrace.style.display = 'none';
    stackTrace.style.maxHeight = '300px';
    stackTrace.style.overflow = 'auto';
    stackTrace.style.fontSize = '0.8rem';
    stackTrace.textContent = data.details;

    // Add to container
    detailsContainer.appendChild(toggleButton);
    detailsContainer.appendChild(stackTrace);
    logContainer.appendChild(detailsContainer);
  }

  // Make sure log container scrolls to bottom
  logContainer.scrollTop = logContainer.scrollHeight;

  // Update progress bar to show error state
  progressBar.style.width = '100%';
  progressBar.classList.remove('bg-primary', 'bg-success');
  progressBar.classList.add('bg-danger');
});

// Update timer display
function updateTimer() {
  if (!startTime) return;
  
  const now = new Date();
  const elapsed = now - startTime;
  
  const hours = Math.floor(elapsed / 3600000).toString().padStart(2, '0');
  const minutes = Math.floor((elapsed % 3600000) / 60000).toString().padStart(2, '0');
  const seconds = Math.floor((elapsed % 60000) / 1000).toString().padStart(2, '0');
  
  timerElement.textContent = `${hours}:${minutes}:${seconds}`;
}

// Update progress bar based on log messages
function updateProgressBar(message) {
  let progress = 0;
  
  if (message.includes('Launching browser')) progress = 5;
  else if (message.includes('Navigating to login page')) progress = 10;
  else if (message.includes('Login successful')) progress = 15;
  else if (message.includes('Successfully navigated to case')) progress = 20;
  else if (message.includes('Clicking on Updates tab')) progress = 25;
  else if (message.includes('Updates tab loaded successfully')) progress = 30;
  else if (message.includes('Loading all updates')) progress = 35;
  else if (message.includes('Waiting for all updates to load')) progress = 40;
  else if (message.includes('All updates appear to be loaded')) progress = 48;
  else if (message.includes('Reached maximum wait time')) progress = 48;
  else if (message.includes('Updates loading completed')) progress = 50;
  else if (message.includes('Scraping updates')) progress = 55;
  else if (message.includes('Scraped')) progress = 60;
  else if (message.includes('Extracting fee information')) progress = 65;
  else if (message.includes('Generating fees table')) progress = 70;
  else if (message.includes('Saving raw update data')) progress = 75;
  else if (message.includes('Saving fee update data')) progress = 80;
  else if (message.includes('Saving all fees table')) progress = 85;
  else if (message.includes('Generating CSV files')) progress = 90;
  else if (message.includes('Generating HTML fees table')) progress = 95;
  else if (message.includes('Successfully scraped')) progress = 100;
  
  if (progress > 0) {
    progressBar.style.width = `${progress}%`;
    progressBar.setAttribute('aria-valuenow', progress);
  }
}
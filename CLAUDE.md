# CLAUDE.md - RDN Fee Scraper

## 🔍 Overview

**RDN Fee Scraper** is a web application that automates the extraction and categorization of fees from the Recovery Database Network (RDN) platform. It logs into RDN, navigates to case pages, extracts structured case and fee data, matches against fee matrices and whitelists, and outputs validated results.

## ⚡ Performance Optimization

**Command to start the optimized scraper:**
```bash
python server-upgraded.py
```

The scraper has been optimized for improved performance with the following enhancements:

1. **JavaScript-Based Extraction:** Direct JavaScript execution for more efficient element finding
2. **Reduced Wait Times:** Shorter timeouts and more responsive dynamic waiting
3. **Efficient DOM Traversal:** Limited search depth and element processing
4. **Optimized Regular Expressions:** Pre-compiled patterns and better matching strategies
5. **Memory Efficiency:** Limited context window size and truncated content storage

### Key Optimized Operations

| Operation | Before | After | Notes |
|-----------|--------|-------|-------|
| My Summary Tab Scraping | ~400s | ~30s | Implemented direct JavaScript extraction for fee amounts |
| Updates Tab Loading | ~60s | ~15s | Reduced wait times, improved detection of stable state |
| Updates Tab Scraping | ~30s | ~5-10s | Used JS for direct extraction limiting to 50 elements |
| Fee Extraction | Variable | Fixed | Pre-compiled regex, early termination, skipping non-fee content |

### Performance Timing Output

The optimized code now includes automatic performance timing for all critical operations:
```
[HH:MM:SS] Login operation took: X.XXXs
[HH:MM:SS] Navigate to case operation took: X.XXXs
[HH:MM:SS] Case information extraction took: X.XXXs
[HH:MM:SS] My Summary tab scraping took: X.XXXs
[HH:MM:SS] Load all updates operation took: X.XXXs
[HH:MM:SS] Total scrape_updates_tab operation took: X.XXXs
[HH:MM:SS] Fee table generation took: X.XXXs
[HH:MM:SS] Total scraping process took: X.XXXs
```

## 🧩 Modular Flow Summary

1. **Login Module**  
   - Authenticates via username, password, security code  
   - Maintains session cookies or token  
   - No Case ID at this stage

2. **Case Access Module**  
   - Prompts for Case ID only after successful login  
   - Navigates directly to case page

3. **Case Information Module**  
   - Immediately extracts:
     - Client Name  
     - Lien Holder Name  
     - Repo Type (adjacent to "Order To" label)
     - 🆕 Database Inferred Fee Card Info (when available)

4. **Repo Fee Module**  
   - Looks up repo fees based on case metadata  
   - Uses fallback standard fee when needed

5. **My Summary Fees Module**  
   - Navigates to **My Summary** tab  
   - ✅ Extracts **all fee-type items**, including:
     - Fee label  
     - Amount  
     - Approval status  
     - Reference or note text  

6. **Updates Fees Module**  
   - Navigates to **Updates** tab  
   - ✅ Parses narrative content to extract **fee mentions**
   - Normalizes to same structure as My Summary results
   - Extracts **entire sentence** from the `<div class="details">` block for reference

7. **Fee Matching Module**  
   - ✅ Matches **both repo and pre-approved non-repo fees**
   - Uses a **predefined whitelist** of **non-repo fee types**
   - Flags matching fees as valid and classifies them as "pre-approved"
   - Any extracted fee not found in the repo matrix or whitelist is passed to Other Fees Module

8. **Other Fees Module**  
   - Catches valid-looking but unlisted fees  
   - Logs them with full context for auditing
   - Preserves original category names for non-whitelist fees

9. **UI Rendering & Output Module**  
   - ⚠️ **Important**: Fees from source = "Database" **must be excluded** from the main table
   - Database-derived results must be displayed in a card beside the "Repo Type" card
   - Rename "Case Page" source to "Updates" in all displays
   - Split fees into three distinct tables:
     - Table 1: Predefined Categories (whitelist)
     - Table 2: Keys Fees (separate with yellow background)
     - Table 3: Other Categories (non-whitelist, yellow background)
   - Remove duplicate fee entries from all tables
   - Generate consolidated HTML report and JSON files

## 🧩 Case Information Section (Cards)

This section displays key metadata in card format. Each card contains a title and value.

Cards to Render:
- Client Name
- Lien Holder
- Repo Type
- 🆕 Involuntary Repo Fee (from Database)
  - Only show this if fee source is "Database"
  - Must follow same visual styling as other cards

Example Card:
```html
<div class="card info-card">
  <h4>Involuntary Repo Fee</h4>
  <p>$385.00</p>
</div>
```

## 📊 Fee Tables Structure

### 📌 Category-Specific Tables

- Create a separate table for EACH unique fee category
- Every category gets its own dedicated table, regardless of whether it's predefined, keys, or other
- Table title should be the category name (e.g., "Field Visit", "Dolly Fees", "Holding Fee")
- Group fees case-insensitively (e.g., "holding fee", "Holding Fee", and "HOLDING FEE" all go in same table)
- Use sanitized versions of category names for HTML element IDs (replace spaces with hyphens)

### 📌 Table Styling

- Tables should use professional, subtle background colors
- **Predefined Categories** (whitelist):
  - Light Blue: `#e3f2fd` for tables like:
    - Field Visit
    - Flatbed Fees
    - Dolly Fees
    - Mileage/ Fuel
    - Incentive
    - Frontend (for Impound)
    - LPR Invoulantry Repo
    - Finder's fee
    - CR AND PHOTOS FEE
    - Fuel Surcharge
    - LPR REPOSSESSION
    - OTHER
    - SKIP REPOSSESSION
    - Bonus

- **Keys Fee**:
  - Soft Amber: `#fff8e1` for all Keys Fee tables

- **Other Categories**:
  - Soft Teal: `#e0f2f1` for tables showing categories not in the predefined whitelist, like:
    - "Holding Fee"
    - "Impound Storage"
    - "Towing Fee"

### 📌 Table Contents

- Exclude database-derived fees from all tables
- Source: Must be "My Summary" or "Updates" only (normalized from "Case Page")
- Each table should show all fees of that specific category with complete reference sentences
- Standard table headers: Date, Amount, Status, Source, Reference

### 📌 Table HTML Structure

```html
<div class="category-table-container" id="category-{sanitized-category-name}">
  <h3>{Category Name}</h3>
  <table class="table table-hover category-table {category-type}-table">
    <thead>
      <tr>
        <th>Date</th>
        <th>Amount</th>
        <th>Status</th>
        <th>Source</th>
        <th>Reference</th>
      </tr>
    </thead>
    <tbody>
      <!-- All fees of this category -->
    </tbody>
  </table>
</div>
```

## 💡 Reference Sentence Handling

- Extract entire sentence from the `<div class="details">` block in the update section
- Do not truncate or cut off mid-paragraph
- Preserve full context

## 🔁 Deduplication Logic

- Use priority ordering:
  1. Database
  2. My Summary
  3. Updates
- Normalize category and reference sentence before comparison

```python
def deduplicate(fees):
  seen = set()
  unique = []
  for fee in sorted(fees, key=lambda f: priority_map[f["source"]]):
      key = (fee["amount"], normalize(fee["category"]), normalize(fee["reference"]))
      if key not in seen:
          seen.add(key)
          unique.append(fee)
  return unique
```

## 💳 Database Fee Display

If repo type is Involuntary, display:

```html
<div class="card info-card">
  <h4>{{Fee Type Extracted from web}}</h4>
  <p>$385.00</p>
</div>
```

Never show database fees in the fee tables.

## 🧾 Output Files

### JSON Exports
- `raw_updates.json`: All update entries
- `summary_fees.json`: All My Summary entries
- `fee_table.json`: Final classified fee output (predefined + keys + others)

### HTML Report Structure
- Table 1: Predefined Fees
- Table 2: Keys Fee Table (yellow)
- Table 3: Other Categories Table (yellow)
- Repo Fee Card (if applicable)

## ✅ UI Rules

| Field | Rule |
|-------|------|
| Category | Use the actual category name as table title |
| Table Organization | One table per unique category |
| Styling | Professional colors based on category type |
| Reference | Full sentence from `<div class="details">` |
| Source | "My Summary" or "Updates" only |
| Category Grouping | Case-insensitive (e.g., "holding fee" = "Holding Fee") |

## ✅ Summary

- 🔵 **Predefined Categories**: Light blue background - One table per whitelist category
- 🟡 **Keys Fee**: Soft amber background - Dedicated table for Keys Fee
- 🟢 **Other Categories**: Soft teal background - One table per unique non-whitelist category
- 🔁 Deduplicate with source priority
- 💬 Use full detail sentence as reference
- 📦 Show database repo fee in a card
- 🧩 Dynamically generate tables for all unique categories

## Common Issues & Solutions

### 1. Socket.IO Connection Problems

**Issue**: Client-side Socket.IO connection fails with errors like "The client is using an unsupported version of the Socket.IO or Engine.IO protocols"

**Solutions**:
- Use CDN-hosted Socket.IO client: `<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>`
- Configure client with polling transport first: `transports: ['polling', 'websocket']`
- Add explicit path if needed: `path: '/socket.io'`
- Add `forceNew: true` to force a new connection
- Set async_mode explicitly in server: `socketio = SocketIO(app, async_mode='threading')`

### 2. Missing CSS & JS Files

**Issue**: 404 errors for dashboard.css, case-form.js, or other static files

**Solutions**:
- Set `static_url_path=''` in Flask app initialization
- Explicitly serve static files in routes if needed
- Check relative paths in HTML files
- Ensure directories exist in public folder

### 3. Browser Automation Failures

**Issue**: Selenium fails to launch or control Chrome properly

**Solutions**:
- Verify Chrome is installed and up-to-date
- Use headless mode for testing: Set `config["browser"]["headless"] = True`
- Increase timeouts: Set `config["browser"]["default_timeout"] = 600000`
- Add more robust error handling with screenshots for error investigation
- In scrape_thread, ensure thread is set to daemon: `scrape_thread.daemon = True`

### 4. Thread Management

**Issue**: Threading issues with scraper or Socket.IO

**Solutions**:
- Use `async_mode='threading'` with Flask-SocketIO
- For Socket.IO server, set `use_reloader=False` to avoid duplicate threads
- Make scrape threads daemon threads: `scrape_thread.daemon = True`
- Use thread locks for any shared resources
- Reset global flags in finally blocks

### 5. Command Syntax

**Common commands**:
- Start application: `python server.py`
- Start optimized version: `python server-upgraded.py`
- Apply UI fixes: `python run-fixed-complete.py`
- Install dependencies: `pip install -r requirements.txt`
- Restart with clean cache: `python -m flask --app server.py clear_cache && python server.py`

### 6. Pre-approved Non-Repo Fee Whitelist

The following fee types are considered pre-approved non-repo fees:
- Field Visit
- Flatbed Fees
- Dolly Fees
- Mileage/ Fuel
- Incentive
- Frontend (for Impound)
- LPR Invoulantry Repo
- Finder's fee
- CR AND PHOTOS FEE
- Fuel Surcharge
- LPR REPOSSESSION
- OTHER
- SKIP REPOSSESSION
- Bonus
- Keys Fee

### 7. Socket.IO Configuration

**Socket.IO Server Configuration**:
```python
socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   logger=True,
                   engineio_logger=True,
                   async_mode='threading')
```

**Socket.IO Client Configuration**:
```javascript
const socket = io({
  transports: ['polling', 'websocket'],
  reconnection: true,
  reconnectionAttempts: 10,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  timeout: 20000,
  forceNew: true,
  path: '/socket.io'
});
```

### 8. Flask Configuration

**Flask Static Files Configuration**:
```python
app = Flask(__name__, static_folder='public', static_url_path='')
```

**Flask Socket.IO Run Configuration**:
```python
socketio.run(
    app,
    host='0.0.0.0',
    port=5555,
    debug=False,
    allow_unsafe_werkzeug=True,
    use_reloader=False
)
```

# Reference Documents 
These files are stored in example folder:
- Updates Page Layout is stored in updates.html
- My Summary Page Layout is stored in sample.html

# Rules for Coding
Use the Coding Standards for Python for respective version.
Solve all syntax errors and ensure code runs without exceptions.
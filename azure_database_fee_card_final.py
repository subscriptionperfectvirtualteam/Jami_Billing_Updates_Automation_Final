#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Azure Database Fee Card Implementation for RDN Fee Scraper

This script enhances the RDN Fee Scraper by adding a dedicated card in the case information section
that displays fee data from the Azure database after executing SQL queries with client, 
lien holder, and fee type details.

It is built on top of the final-solution.py and modifies the HTML report generation 
to show the database-derived fee prominently as a card in the case information section.
"""

import os
import sys
import time
import datetime
import importlib.util
import types

# Header to display when running
print("=" * 80)
print("RDN FEE SCRAPER - AZURE DATABASE FEE CARD IMPLEMENTATION")
print("=" * 80)
print("This version implements an enhanced Azure Database Fee Card:")
print("1. Adds a dedicated card in the case information section")
print("2. Shows database fee details after SQL query execution")
print("3. Links client, lien holder, and fee type details")
print("4. Maintains all previous fixes and enhancements")
print("=" * 80)
print()

# Path to the original script
server_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server-upgraded.py")

# Load the original module
print(f"Loading the original script from: {server_script_path}")
spec = importlib.util.spec_from_file_location("server_module", server_script_path)
server_module = importlib.util.module_from_spec(spec)

# Execute the module to load all its contents
spec.loader.exec_module(server_module)

# Modified generate_fees_table function
def generate_fees_table(fee_updates):
    """Generate a fees table with enhanced handling of database fees and duplicates"""
    start = time.time()
    server_module.log('Generating fees table with Azure database fee card handling...')
    
    # 1. Replace "Case Page" with "Updates" in all fee updates
    for fee in fee_updates:
        if fee.get('source') == 'Case Page':
            fee['source'] = 'Updates'
            
    # 2. Separate database fees to handle them specially
    database_fees = []
    non_database_fees = []
    
    # Check if we have case information to lookup repo fees
    repo_fee_lookup_performed = False
    repo_fee_data = None

    # 3. Check if we have case information for database lookup
    if server_module.config.get('current_case_info'):
        # Make sure these are defined properly before use
        case_client_name = server_module.config['current_case_info'].get('clientName', '')
        case_lienholder_name = server_module.config['current_case_info'].get('lienHolderName', '')
        case_repo_type = server_module.config['current_case_info'].get('repoType', 'Involuntary Repo')

        # Apply validation for database lookup
        if case_client_name and case_client_name != "Not found" and case_lienholder_name and case_lienholder_name != "Not found":
            server_module.log(f"Looking up repo fee information for client={case_client_name}, lienholder={case_lienholder_name}, fee_type={case_repo_type}")
            
            # Use our lookup_repo_fee function to get database fee
            try:
                repo_fee_data = server_module.lookup_repo_fee(case_client_name, case_lienholder_name, case_repo_type)
            except Exception as lookup_error:
                server_module.log(f"Error during lookup_repo_fee: {str(lookup_error)}", "error")
                import traceback
                server_module.log(traceback.format_exc(), "error")

            if repo_fee_data:
                repo_fee_lookup_performed = True
                server_module.log(f"Found repo fee in database: ${repo_fee_data['amount']:.2f}")
                
                # Store the database fee in global config for reference in HTML report
                server_module.config['database_fee_amount'] = float(repo_fee_data['amount'])
                server_module.config['database_fee_details'] = repo_fee_data
                
                # Create a database fee entry but not added to all_fees_table
                db_fee_entry = {
                    'date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    'amount': f"${float(repo_fee_data['amount']):.2f}",
                    'type': 'Database Lookup',
                    'approver': 'System',
                    'referenceSentence': f"Involuntary Repo: Database lookup for {case_repo_type} - {case_client_name} / {case_lienholder_name}",
                    'approved': 'Yes',
                    'category': case_repo_type,
                    'source': 'Database',
                    'originalCategory': case_repo_type,
                    'matched': True,
                    'matchedAs': 'Repo Fee Matrix',
                    'is_database_fee': True,
                    'query_details': {
                        'client': case_client_name,
                        'lienholder': case_lienholder_name,
                        'fee_type': case_repo_type,
                        'is_fallback': repo_fee_data.get('is_fallback', False),
                        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'db_id': repo_fee_data.get('fd_id', 'N/A')
                    }
                }
                
                # Add to our database fees list
                database_fees.append(db_fee_entry)
                
                if repo_fee_data.get('is_fallback'):
                    server_module.log(f"Note: {repo_fee_data.get('message', 'Using Standard lienholder fallback')}")
            else:
                server_module.log(f"No matching repo fee found in database for {case_client_name}/{case_lienholder_name}/{case_repo_type}", "warning")
        else:
            server_module.log("Missing client or lienholder information, skipping repo fee lookup", "warning")
    else:
        server_module.log("No case information available, skipping repo fee lookup", "warning")

    # 4. Sort the remaining fees and process them
    my_summary_count = sum(1 for fee in fee_updates if fee.get('source') == 'My Summary')
    case_page_count = sum(1 for fee in fee_updates if fee.get('source') == 'Case Page')
    updates_count = len(fee_updates) - my_summary_count - case_page_count
    server_module.log(f'Processing {len(fee_updates)} total fees: {my_summary_count} from My Summary, {updates_count} from Updates, {case_page_count} Key Fees, and {len(database_fees)} from Database')

    # 5. Create structured table data - with de-duplication
    all_fees_table = []
    categorized_fees = []  # Keep for backward compatibility
    additional_fees = []   # Keep for backward compatibility

    # Create a set to track unique fees to avoid duplicates
    unique_fee_tracker = set()

    # 6. Sort the fees by source priority for proper de-duplication
    def get_source_priority(update):
        source = update.get('source', 'Updates')
        # Priority: My Summary > Updates (Case Page is renamed to Updates)
        if source == 'My Summary':
            return 0  # Highest priority
        else:  # Updates or anything else
            return 1  # Lower priority

    # Sort fee_updates by source priority
    sorted_updates = sorted(fee_updates, key=get_source_priority)

    # 7. Process all fees (except database fees) with better tracking of duplicates
    for update in sorted_updates:
        for amount_info in update.get('amounts', []):
            try:
                amount_value = float(amount_info.get('amount', 0))
                # Skip invalid amounts
                if amount_value <= 0:
                    continue

                fee_context = amount_info.get('context', '').strip()
                # Create a unique identifier for this fee
                source = update.get('source', 'Updates')
                date = update.get('date', '')
                fee_label = update.get('feeLabel', '')  # Include feeLabel from My Summary entries
                context_snippet = fee_context[:50].strip() if fee_context else ""

                # Handle specific fee types
                fee_type = amount_info.get('feeType', '')  # Special handling for key fees

                # Normalize key fee types for better deduplication
                normalized_fee_type = fee_type.lower() if fee_type else ""
                normalized_fee_label = fee_label.lower() if fee_label else ""

                # Check for various forms of key fees to standardize
                if any(key_term in normalized_fee_type for key_term in ['key', 'push']):
                    normalized_fee_type = 'keys_fee'
                if any(key_term in normalized_fee_label for key_term in ['key', 'push']):
                    normalized_fee_label = 'keys_fee'

                # Create a robust unique identifier that covers all key aspects
                unique_id = f"{source}_{amount_value:.2f}_{normalized_fee_label or normalized_fee_type}_{context_snippet[:30]}"

                # Skip duplicate fees based on the unique ID
                if unique_id in unique_fee_tracker:
                    server_module.log(f'Skipping duplicate fee: ${amount_value:.2f} from {source}')
                    continue

                # Add this unique ID to our tracker
                unique_fee_tracker.add(unique_id)
                fee_label = update.get('feeLabel', 'Unknown Fee')

                # Determine category based on source and fee information
                if source == 'Case Page':
                    # For Case Page key fees, always use Keys Fee category
                    category = 'Keys Fee'
                    server_module.log(f"Using Keys Fee category for Case Page fee: ${amount_value:.2f}")
                elif fee_type:
                    # Use explicit fee_type if provided (from specialized regex patterns)
                    category = fee_type
                    server_module.log(f"Using explicit fee type from pattern: {category}")
                elif fee_label:
                    # Otherwise use fee_label from My Summary
                    category = fee_label
                else:
                    category = 'Unknown Fee'

                # Check if this is a pre-approved non-repo fee based on category
                is_pre_approved_non_repo = False
                original_category = category  # Store the original category name

                # Store key fee information in the reference, but set category to "Other"
                is_key_fee = False
                if 'key' in category.lower() or 'push to start' in category.lower():
                    is_key_fee = True
                    original_category = 'Keys Fee'  # Save this for reference section
                    category = 'Other'  # Set category to "Other" as required
                    server_module.log(f"Detected key fee, setting category to 'Other' and keeping 'Keys Fee' in reference")

                # Try to match with predefined categories
                if category:
                    category_lower = category.lower().strip()
                    matched_category = None

                    # FIRST: Handle special cases if this is not a key fee
                    # Key fees should always use category "Other" with reference "Keys Fee"
                    if not is_key_fee and category_lower in ['keys fee', 'key fee']:
                        is_pre_approved_non_repo = True
                        matched_category = 'Keys Fee'  # Use the canonical form
                        category = 'Other'  # Ensure all key fees go to Other
                        server_module.log(f"Exact match for key fee: '{category}' → 'Keys Fee'")

                    # SECOND: Try exact match for all pre-approved fees
                    if not is_pre_approved_non_repo:
                        for fee_name in server_module.config["pre_approved_fees"]:
                            fee_name_lower = fee_name.lower().strip()
                            if category_lower == fee_name_lower:
                                is_pre_approved_non_repo = True
                                matched_category = fee_name  # Use the exact name from the predefined list
                                server_module.log(f"Matched pre-approved non-repo fee (exact match): original='{category}', matched='{fee_name}'")
                                break

                    # THIRD: Try partial match - more thorough approach
                    if not is_pre_approved_non_repo:
                        best_match = None
                        best_match_score = 0

                        for fee_name in server_module.config["pre_approved_fees"]:
                            fee_name_lower = fee_name.lower().strip()

                            # Check for containment in either direction
                            if fee_name_lower in category_lower:
                                score = len(fee_name_lower) / len(category_lower)  # Reward longer matches
                                if score > best_match_score:
                                    best_match = fee_name
                                    best_match_score = score

                            elif category_lower in fee_name_lower:
                                score = len(category_lower) / len(fee_name_lower)  # Reward longer matches
                                if score > best_match_score:
                                    best_match = fee_name
                                    best_match_score = score

                        if best_match and best_match_score > 0.5:  # Require a good match
                            is_pre_approved_non_repo = True
                            matched_category = best_match
                            server_module.log(f"Matched pre-approved non-repo fee (partial match with score {best_match_score:.2f}): original='{category}', matched='{best_match}'")

                    # If we found a match, use the standardized category name
                    # Otherwise, set to "Other" but keep the original name in reference
                    if is_pre_approved_non_repo and matched_category and not is_key_fee:
                        category = matched_category
                    elif is_key_fee or 'key' in category.lower():
                        # For all key fees, set category to "Other"
                        category = "Other"

                # Create simplified fee entry with proper categorization for fees

                # For key fees, set reference to "Keys Fee" and category to "Other"
                display_category = category
                reference_text = ""

                if is_key_fee or 'key' in category.lower():
                    # For key fees, always use "Other" as category
                    display_category = "Other"
                    # But keep "Keys Fee" in the reference for visibility
                    reference_text = f"Keys Fee: {fee_context}"
                    server_module.log(f"Setting key fee display to category 'Other' with reference 'Keys Fee'")
                else:
                    # For non-key fees, use normal rules
                    reference_text = fee_context if is_pre_approved_non_repo else f"{original_category}: {fee_context}"

                fee_entry = {
                    'date': date,
                    'amount': f"${amount_value:.2f}",
                    'type': update.get('type', ''),
                    'approver': update.get('user', ''),
                    'referenceSentence': reference_text,
                    'approved': 'Yes' if (update.get('isApproved') or
                                        amount_info.get('isExplicitlyApproved') or
                                        source == 'Case Page' or
                                        source == 'Database' or
                                        is_pre_approved_non_repo) else 'Likely',  # Mark pre-approved non-repo fees as approved
                    'category': display_category,
                    'source': source,
                    'originalCategory': original_category,  # Add this to store the original category
                    'matched': True if source == 'Case Page' or
                                    source == 'Database' or
                                    is_pre_approved_non_repo else False,  # Mark pre-approved non-repo fees as matched
                    'matchedAs': 'Repo Fee Matrix' if source == 'Database' else
                                ('Pre-approved Non-Repo' if source == 'Case Page' or is_pre_approved_non_repo else
                                ('My Summary' if source == 'My Summary' else 'Unmatched'))
                }

                all_fees_table.append(fee_entry)
                additional_fees.append(fee_entry.copy())
            except (ValueError, TypeError) as e:
                # Log error and continue with next fee
                server_module.log(f"Error processing fee: {str(e)}", "error")
                continue
    
    # 8. Store database fee information in a special variable for the HTML report
    if database_fees:
        # Add database fees to configuration for HTML report access
        server_module.config['database_fees'] = database_fees
    
    # 9. Generate statistics (but don't add database fees to the main table)
    my_summary_entries = sum(1 for fee in all_fees_table if fee.get('source') == 'My Summary')
    update_entries = sum(1 for fee in all_fees_table if fee.get('source') in ['Updates', 'Case Page'])
    database_entries = len(database_fees)

    server_module.log(f"Generated fees table with {len(all_fees_table)} entries ({my_summary_entries} from My Summary, {update_entries} from Updates, {database_entries} from Database)")

    # Log some examples for debugging if any entries exist
    if all_fees_table:
        server_module.log(f"Sample fee entry: {all_fees_table[0]}")

    end = time.time()
    server_module.log(f"Fee table generation took: {end - start:.3f}s")

    return {
        'allFeesTable': all_fees_table,
        'categorizedFees': categorized_fees,
        'additionalFees': additional_fees,
        'databaseFees': database_fees  # Add database fees separately
    }

# Override the dashboard.js functions to add the database fee card in the Case Information section
def update_web_ui_js():
    """Update the dashboard.js file to add the database fee card"""
    dashboard_js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "js", "dashboard.js")
    if not os.path.exists(dashboard_js_path):
        server_module.log(f"Warning: Could not find dashboard.js at {dashboard_js_path}", "warning")
        return False
    
    try:
        with open(dashboard_js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        
        # Find where the case information cards are updated
        card_update_pattern = "// Update case information cards"
        card_update_section = "// Update case information cards"
        
        if card_update_pattern in js_content:
            modified_js = js_content.replace(
                card_update_pattern,
                """// Update case information cards
  // Add database fee card if available
  const dbFee = data.databaseFee || null;
  if (dbFee) {
    if (!$('#database-fee-card').length) {
      // Create a new database fee card with stats-card styling to match other cards
      const dbFeeCard = $(`
        <div class="col-md-3">
          <div class="card stats-card">
            <div class="card-body text-center">
              <h5 class="card-title">Involuntary Repo Fee</h5>
              <p class="card-text" id="database-fee">${dbFee}</p>
            </div>
          </div>
        </div>
      `);
      // Append after other cards
      $('.case-info-cards .row').append(dbFeeCard);
    } else {
      // Update existing card
      $('#database-fee').text(dbFee);
    }
  }
                
  // Continue with existing case information updates"""
            )
            
            with open(dashboard_js_path, 'w', encoding='utf-8') as f:
                f.write(modified_js)
            
            server_module.log("Successfully updated dashboard.js to add database fee card", "info")
            return True
        else:
            server_module.log("Could not find section to modify in dashboard.js", "warning")
            return False
    except Exception as e:
        server_module.log(f"Error updating dashboard.js: {str(e)}", "error")
        return False

# Modified generate_html_report function
def generate_html_report(case_id, updates, fee_updates, all_fees_table, categorized_fees, additional_fees, my_summary_fees=None):
    """Generate HTML report for the scraped data with enhanced Azure Database Fee Card"""
    start = time.time()
    server_module.log('Generating HTML report with Azure Database Fee Card...')

    # Get case info from config if available
    case_info = server_module.config.get('current_case_info', {})
    client_name = case_info.get('clientName', 'Unknown Client')
    lien_holder = case_info.get('lienHolderName', 'Unknown Lien Holder')
    repo_type = case_info.get('repoType', 'Unknown Repo Type')

    # Generate the report date
    report_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. Get database fee amount - should only be shown next to Repo Type
    database_fee_amount = 0.00
    database_fee_entry = None
    try:
        if 'database_fee_amount' in server_module.config:
            database_fee_amount = float(server_module.config['database_fee_amount'])
        elif 'database_fees' in server_module.config and server_module.config['database_fees']:
            database_fee_entry = server_module.config['database_fees'][0]
            database_fee_amount = float(database_fee_entry['amount'].replace('$', ''))
    except (ValueError, KeyError, IndexError):
        database_fee_amount = 0.00
    
    # 2. Replace "Case Page" with "Updates" in all fee entries and include database fee in table
    filtered_fees = []

    # First add the database fee if available
    if database_fee_entry and database_fee_amount > 0:
        # Create a formatted fee entry for the table display
        db_fee_for_table = {
            'date': datetime.datetime.now().strftime("%Y-%m-%d"),
            'amount': f"${database_fee_amount:.2f}",
            'type': 'Database Fee',
            'approver': 'Azure SQL',
            'referenceSentence': f"Database Lookup: Involuntary Repo fee for {client_name} / {lien_holder}",
            'approved': 'Yes',
            'category': 'Involuntary Repo Fee',
            'source': 'Azure SQL',
            'originalCategory': 'Involuntary Repo Fee',
            'matched': True,
            'matchedAs': 'Repo Fee Matrix'
        }
        filtered_fees.append(db_fee_for_table)
        server_module.log(f"Added Azure SQL database fee (${database_fee_amount:.2f}) to fee table", "info")

    # Then add all other fees
    for fee in all_fees_table:
        # Now include database fees - only skip duplicates
        if (fee.get('source') == 'Database' or fee.get('is_database_fee', True)) and database_fee_entry:
            # We've already added the database fee, so skip duplicates
            continue

        # Rename "Case Page" to "Updates"
        if fee.get('source') == 'Case Page':
            fee['source'] = 'Updates'

        filtered_fees.append(fee)
    
    # 3. Remove any remaining duplicates based on amount, category and context
    unique_fees = []
    unique_identifiers = set()
    
    for fee in filtered_fees:
        # Create a unique identifier based on amount, category and first part of reference
        amount = fee.get('amount', '').replace('$', '').strip()
        category = fee.get('category', '').strip()
        source = fee.get('source', '').strip()
        reference = fee.get('referenceSentence', '')[:30].strip()  # First 30 chars for comparison
        
        # Create a unique identifier
        fee_id = f"{amount}_{category}_{reference}"
        
        if fee_id not in unique_identifiers:
            unique_identifiers.add(fee_id)
            unique_fees.append(fee)
    
    # 4. Count unique fees (excluding database fee)
    unique_fees_count = len(unique_fees)

    # 5. Calculate total amount (including database fee)
    total_amount = sum([float(fee['amount'].replace('$', '')) for fee in unique_fees])
    total_amount += database_fee_amount  # Add database fee to total
    
    # 6. Separate fees into predefined categories and other fees
    predefined_fees = []
    other_fees = []

    for fee in unique_fees:
        # Categorize based on category and reference text
        category = fee.get('category', '')
        reference = fee.get('referenceSentence', '')
        source = fee.get('source', '')

        # Always put Azure SQL database fees in the predefined categories
        if source == 'Azure SQL':
            predefined_fees.append(fee)
        # Check if this is a key fee or "Other" category
        elif category == 'Other' or ('key' in reference.lower() and 'fee' in reference.lower()):
            other_fees.append(fee)
        else:
            predefined_fees.append(fee)
    
    # 7. Count fees by source (with renamed sources)
    fees_by_source = {}
    
    # Add database fee to source counts if present
    if database_fee_amount > 0:
        fees_by_source['Database'] = {'count': 1, 'amount': database_fee_amount}
    
    # Add remaining fees to counts
    for fee in unique_fees:
        source = fee.get('source', 'Unknown')
        if source not in fees_by_source:
            fees_by_source[source] = {'count': 0, 'amount': 0.0}
        fees_by_source[source]['count'] += 1
        fees_by_source[source]['amount'] += float(fee['amount'].replace('$', ''))

    # 8. Build HTML report
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RDN Fee Report - Case {case_id}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; color: #333; }}
            h1, h2, h3, h4 {{ color: #2c3e50; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f5f5f5; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .summary {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            .fees-container {{ margin-bottom: 30px; }}
            .other-fees {{ background-color: #f9edcf; padding: 15px; border-radius: 5px; margin-top: 20px; }}
            .amount {{ text-align: right; }}
            .approved {{ color: green; }}
            .not-approved {{ color: orange; }}
            .section {{ margin-bottom: 30px; }}
            .db-fee {{ color: #3498db; font-weight: bold; }}
            .card-container {{ display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; }}
            .info-card {{ flex: 1; min-width: 200px; background-color: #ecf0f1; padding: 15px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .info-card h4 {{ margin-top: 0; color: #2c3e50; }}
            .info-card p {{ margin-bottom: 0; font-size: 1.2em; }}
            .database-card {{ flex: 1; min-width: 200px; background-color: #ecf0f1; padding: 15px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .database-fees-card {{ background-color: #d4ebf2; padding: 15px; border-radius: 5px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <h1>RDN Fee Report</h1>

        <div class="summary">
            <h2>Case Summary</h2>
            <div class="card-container">
                <div class="info-card">
                    <h4>Client Name</h4>
                    <p>{client_name}</p>
                </div>
                <div class="info-card">
                    <h4>Lien Holder</h4>
                    <p>{lien_holder}</p>
                </div>
                <div class="info-card">
                    <h4>Repo Type</h4>
                    <p>{repo_type}</p>
                </div>
    """

    # Add database fee card if available - with styling that matches the other cards
    if database_fee_amount > 0:
        html += f"""
                <div class="info-card">
                    <h4>Involuntary Repo Fee</h4>
                    <p>${database_fee_amount:.2f}</p>
                </div>
        """

    html += f"""
            </div>
            <p><strong>Case ID:</strong> {case_id}</p>
            <p><strong>Report Date:</strong> {report_date}</p>
        </div>
    """

    # Add Azure Database section with lookup details
    if database_fee_amount > 0 and database_fee_entry:
        query_details = database_fee_entry.get('query_details', {})
        db_client = query_details.get('client', client_name)
        db_lienholder = query_details.get('lienholder', lien_holder)
        db_fee_type = query_details.get('fee_type', repo_type)
        db_timestamp = query_details.get('timestamp', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        db_id = query_details.get('db_id', 'N/A')
        is_fallback = query_details.get('is_fallback', False)
        fallback_message = "Standard fee used (specific lienholder not found)" if is_fallback else "Exact match for lienholder"
        
        html += f"""
        <div class="database-fees-card">
            <h3>Azure Database Lookup Results</h3>
            <p><strong>Date:</strong> {db_timestamp}</p>
            <p><strong>Database Query:</strong> Client="{db_client}", Lienholder="{db_lienholder}", Fee Type="{db_fee_type}"</p>
            <p><strong>Amount:</strong> ${database_fee_amount:.2f}</p>
            <p><strong>Match Type:</strong> {fallback_message}</p>
            <p><strong>Database ID:</strong> {db_id}</p>
        </div>
        """

    html += """
        <div class="section">
            <h2>Fee Summary</h2>
    """

    # Only show summary count if there are fees
    if unique_fees_count > 0 or database_fee_amount > 0:
        html += f"""
            <p><strong>Total Unique Fees Extracted:</strong> {unique_fees_count + (1 if database_fee_amount > 0 else 0)}</p>
            <p><strong>Total Amount:</strong> ${total_amount:.2f}</p>
        """

        # Only add sources table if there are fees
        if fees_by_source:
            html += """
            <h3>Fees by Source</h3>
            <table>
                <tr>
                    <th>Source</th>
                    <th>Count</th>
                    <th>Total Amount</th>
                </tr>
            """

            # Add source breakdown rows
            for source, data in fees_by_source.items():
                html += f"""
                <tr>
                    <td>{source}</td>
                    <td>{data['count']}</td>
                    <td class="amount">${data['amount']:.2f}</td>
                </tr>
                """

            html += """
            </table>
            """
    else:
        html += """
            <p>No fees were extracted for this case.</p>
        """

    html += """
        </div>
        <div class="fees-container">
    """

    # Only add predefined fees section if there are any
    if predefined_fees:
        html += """
            <h2>Predefined Categories Fees</h2>
            <table>
                <tr>
                    <th>Date</th>
                    <th>Category</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Reference Sentence</th>
                </tr>
        """

        # Add predefined fee rows
        for fee in predefined_fees:
            approved_class = "approved" if fee.get('approved') == 'Yes' else "not-approved"
                
            html += f"""
                    <tr>
                        <td>{fee.get('date', '')}</td>
                        <td>{fee.get('category', '')}</td>
                        <td class="amount">{fee.get('amount', '$0.00')}</td>
                        <td class="{approved_class}">{fee.get('approved', 'Unknown')}</td>
                        <td>{fee.get('source', '')}</td>
                        <td>{fee.get('referenceSentence', '')[:100]}...</td>
                    </tr>
            """

        html += """
            </table>
        """
        
    # Add Other Fees section if there are any
    if other_fees:
        html += """
            <div class="other-fees">
                <h2>Other Fees</h2>
                <table>
                    <tr>
                        <th>Date</th>
                        <th>Category</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Source</th>
                        <th>Reference Sentence</th>
                    </tr>
        """
        
        # Add other fee rows
        for fee in other_fees:
            approved_class = "approved" if fee.get('approved') == 'Yes' else "not-approved"
                
            html += f"""
                    <tr>
                        <td>{fee.get('date', '')}</td>
                        <td>{fee.get('category', '')}</td>
                        <td class="amount">{fee.get('amount', '$0.00')}</td>
                        <td class="{approved_class}">{fee.get('approved', 'Unknown')}</td>
                        <td>{fee.get('source', '')}</td>
                        <td>{fee.get('referenceSentence', '')[:100]}...</td>
                    </tr>
            """
            
        html += """
                </table>
            </div>
        """
    
    html += """
        </div>

        <footer>
            <p>Generated by RDN Fee Scraper - Azure Database Fee Card Implementation</p>
        </footer>
    </body>
    </html>
    """

    end = time.time()
    server_module.log(f"HTML report generation took: {end - start:.3f}s")
    
    return html

# Modified socket.io handler to send database fee data
def update_socketio_handlers():
    """Update the Socket.IO event handlers to include database fee data"""
    # Try to find the Socket.IO event handler function
    try:
        # Get original handler for sending case information
        original_handle_case_info = server_module.handle_case_info
        
        # Define new handler with database fee
        def handle_case_info_with_database_fee(case_id, case_info):
            """Enhanced handler for case info that includes database fee"""
            
            # Check if database fee is available
            database_fee = None
            if hasattr(server_module.config, 'database_fee_amount'):
                database_fee = f"${server_module.config.database_fee_amount:.2f}"
            elif 'database_fee_amount' in server_module.config:
                database_fee = f"${server_module.config['database_fee_amount']:.2f}"
            elif 'database_fees' in server_module.config and server_module.config['database_fees']:
                try:
                    fee_entry = server_module.config['database_fees'][0]
                    database_fee = fee_entry.get('amount', '$0.00') 
                except:
                    database_fee = None
                    
            # Call original handler first
            original_result = original_handle_case_info(case_id, case_info)
            
            # Add database fee if available
            if database_fee:
                if isinstance(original_result, dict):
                    original_result['databaseFee'] = database_fee
                
            return original_result
            
        # Replace original handler with enhanced version
        server_module.handle_case_info = handle_case_info_with_database_fee
        server_module.log("Successfully updated Socket.IO handler to include database fee data", "info")
        return True
    except Exception as e:
        server_module.log(f"Error updating Socket.IO handlers: {str(e)}", "error")
        return False

# Override the functions in the server module
server_module.generate_fees_table = generate_fees_table
server_module.generate_html_report = generate_html_report

# Try to update UI components
update_socketio_handlers()
update_web_ui_js()

# Create a batch file for easy execution
batch_file_path = "run_azure_database_fee_card.bat"
with open(batch_file_path, 'w', encoding='utf-8') as f:
    f.write('''@echo off
echo Starting RDN Fee Scraper with Azure Database Fee Card Implementation...
echo.
echo Checking for Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH. Please install Python 3.8 or higher.
    pause
    exit /b 1
)

python azure_database_fee_card_final.py
pause''')

print(f"Created {batch_file_path} for easy execution")
print("To run the solution with Azure Database Fee Card, simply execute:")
print(f"- Windows: {batch_file_path}")

# Import the database fee card handler to install Socket.IO event handlers
try:
    import database_fee_card_handler
    print("Database fee card handlers installed successfully")
except Exception as e:
    print(f"Error importing database fee card handler: {str(e)}")
    import traceback
    print(traceback.format_exc())

# Call the main function
print("Starting the application with Azure Database Fee Card implementation...")
server_module.main()
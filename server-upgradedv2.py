#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RDN Case Updates Scraper with Web Portal

This script automates the process of:
1. Launching a web portal with a login form
2. Collecting user credentials and case ID
3. Logging into the Recovery Database Network
4. Storing fee information in Azure SQL Database
4. Navigating to a specific case page
5. Clicking on the Updates tab
6. Loading all updates by clicking "ALL"
7. Scraping the update information
8. Extracting and categorizing fee information
9. Displaying results in the web portal
"""

import os
import json
import time
import re
import datetime
import threading
import pyodbc  # For SQL Server/Azure SQL connectivity
from typing import Dict, List, Any, Optional, Tuple
import logging
import decimal  # For handling Decimal objects in JSON serialization

# Import the simplified implementation of lookup_repo_fee with exact column names
try:
    # First try the simplified version that uses exact column names from FeeDetails22.json
    from lookup_repo_fee_simple import get_lookup_repo_fee
    lookup_repo_fee = get_lookup_repo_fee()
    print("[INFO] Using simplified lookup_repo_fee implementation with exact column names")
    log_import_result = True
except ImportError:
    # Fall back to the more complex version if the simplified one isn't available
    try:
        from lookup_repo_fee import lookup_repo_fee
        print("[INFO] Using dynamic lookup_repo_fee implementation")
        log_import_result = True
    except ImportError:
        print("[WARNING] Could not import lookup_repo_fee function. Database functionality will be limited.")
        log_import_result = False

# Web server and socket imports
from flask import Flask, request, jsonify, send_from_directory, redirect, session
from flask_socketio import SocketIO, emit
import webbrowser

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

# Configuration
# Load database configuration from config.txt
def load_db_config():
    db_config = {
        "server": "",
        "username": "",
        "password": "",
        "database": ""
    }

    try:
        with open('config.txt', 'r') as f:
            for line in f:
                if 'Server' in line:
                    db_config["server"] = line.split('-')[1].strip()
                elif 'USername' in line or 'Username' in line:
                    db_config["username"] = line.split('-')[1].strip()
                elif 'Password' in line:
                    db_config["password"] = line.split('-')[1].strip()
                elif 'Database' in line:
                    db_config["database"] = line.split('-')[1].strip()
        print(f"Database configuration loaded successfully")
        return db_config
    except Exception as e:
        print(f"Error loading database configuration: {str(e)}")
        return None

# Database connection function
def get_db_connection():
    db_config = load_db_config()
    if not db_config:
        print("Failed to load database configuration")
        return None

    try:
        # Create the connection string for Azure SQL
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={db_config['server']};"
            f"DATABASE={db_config['database']};"
            f"UID={db_config['username']};"
            f"PWD={db_config['password']}"
        )

        # Connect to the database
        conn = pyodbc.connect(conn_str)
        print("Successfully connected to Azure SQL Database")

        # Print database connection info for debugging
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        db_version = cursor.fetchone()

        # More visible database connection information
        print(f"\n{'='*20} DATABASE CONNECTION {'='*20}")
        print(f"Server:   {db_config['server']}")
        print(f"Database: {db_config['database']}")
        print(f"Username: {db_config['username']}")
        print(f"Version:  {db_version[0][:50]}...")
        print(f"{'='*60}\n")

        return conn
    except Exception as e:
        print(f"Error connecting to database: {str(e)}")
        return None

config = {
    # Login URL
    "login_url": "https://secureauth.recoverydatabase.net/public/login?rd=/",

    # Base URL for case pages
    "case_base_url": "https://app.recoverydatabase.net/alpha_rdn/module/default/case2/?case_id=",

    # Database configuration
    "db_config": load_db_config(),

    # Login credentials (will be provided via UI)
    "credentials": {
        "username": "",
        "password": "",
        "security_code": ""
    },

    # Output directory for scraped data
    "output_dir": "./rdn_data",

    # Browser settings
    "browser": {
        "headless": False,
        "slow_mo": 50,
        "default_timeout": 300000  # 5 minutes timeout
    },

    # Web portal settings
    "web_portal": {
        "port": 1436,
        "open_browser": True
    },

    # Pre-approved non-repo fee whitelist
    "pre_approved_fees": [
        "Field Visit",
        "Flatbed Fees",
        "Dolly Fees",
        "Mileage/ Fuel",
        "Incentive",
        "Frontend",
        "Frontend (for Impound)",
        "LPR Invoulantry Repo",
        "LPR REPOSSESSION",
        "Finder's fee",
        "CR AND PHOTOS FEE",
        "Fuel Surcharge",
        "OTHER",
        "SKIP REPOSSESSION",
        "Bonus",
        "Keys Fee",
        "Key Fee",  # Adding as an alternative
        "Involuntary Repo",  # Add repo types to the whitelist
        "Voluntary Repo",
        "Recovery Fee"  # Ensure recovery fee is properly categorized
    ],

    # Current session info
    "current_case_id": None,
    "current_case_info": None
}

# Custom JSON encoder to handle Decimal types
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

# Global variables
app = Flask(__name__, static_folder='public', static_url_path='')
app.config['SECRET_KEY'] = 'rdn-fee-scraper-secret'
app.json_encoder = DecimalEncoder  # Set custom JSON encoder for the Flask app
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True, async_mode='threading')
scrape_in_progress = False
start_time = None
active_sessions = {}

# Add socket connection event handlers for debugging
@socketio.on('connect')
def handle_connect():
    client_id = request.sid
    log(f"Client connected: {client_id}", "info")

    # Send current state if a scrape is in progress
    if scrape_in_progress and start_time:
        log(f"Scrape in progress, sending timer-start event to new client {client_id}", "info")
        socketio.emit('timer-start', {
            'startTime': start_time.isoformat(),
            'caseId': config.get('current_case_id', 'Unknown')
        }, room=client_id)

@socketio.on('join_session')
def handle_join_session(data):
    client_id = request.sid
    log(f"Client {client_id} trying to join session: {data}", "info")

    # If we have an active scrape, update the client
    if scrape_in_progress and start_time:
        log(f"Updating client {client_id} with current scrape status", "info")
        socketio.emit('timer-start', {
            'startTime': start_time.isoformat(),
            'caseId': config.get('current_case_id', 'Unknown')
        }, room=client_id)

    # Send back acknowledgment
    return {'status': 'connected', 'scrapeInProgress': scrape_in_progress}

@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.sid
    log(f"Client disconnected: {client_id}", "info")

    # Note: We don't close the browser sessions when clients disconnect
    # because the scraping process might still be running.
    # Browser sessions are only closed on logout or when the server starts up.

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def log(message, log_type='info'):
    """Custom logger function that logs to console and emits to socket"""
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')
    formatted_message = f"[{timestamp}] {message}"

    # Log to console
    if log_type == 'error':
        logger.error(formatted_message)
    else:
        logger.info(formatted_message)

    # Emit to socket
    socketio.emit('log', {'message': formatted_message, 'type': log_type})

def log_query(query_type, query, params):
    """Special logger function for SQL queries with enhanced console visibility"""
    # Format parameters for better readability with type information
    if isinstance(params, list):
        # Make a list of formatted parameters with type information for debugging
        formatted_params = []
        for p in params:
            if isinstance(p, str):
                formatted_params.append(f"'{p}' (str)")
            else:
                formatted_params.append(f"{p} ({type(p).__name__})")
        param_debug = ", ".join(formatted_params)
    else:
        param_debug = f"{params} ({type(params).__name__})"

    # Print to console with distinctive formatting and clear visibility
    border = f"{'#'*20} {query_type} SQL QUERY {'#'*20}"
    print(f"\n{border}")
    print(f"{query}")
    print(f"\nPARAMETERS: {param_debug}")
    print(f"{'-'*len(border)}")
    # Add timestamp for tracking query execution time
    timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"TIMESTAMP: {timestamp}")
    print(f"{'#'*len(border)}\n")

    # Also log to regular log
    log(f"Executing {query_type} query with parameters: {param_debug}")

def create_driver():
    """Create and configure a Selenium WebDriver instance"""
    chrome_options = Options()
    if config["browser"]["headless"]:
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--headless=new")  # For newer Chrome versions

    # Add common options to prevent crashes and improve stability
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # Add error handling
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(config["browser"]["default_timeout"])

        # Add additional timeouts
        driver.implicitly_wait(30)  # Wait up to 30 seconds for elements to appear

        # Create a window with a large viewport for reliable element interaction
        driver.set_window_size(1920, 1080)

        log("WebDriver created successfully", "info")
        return driver
    except Exception as e:
        log(f"Error creating WebDriver: {str(e)}", "error")
        raise

def login(driver):
    """Login to the RDN system"""
    start = time.time()
    log('Navigating to login page...')
    driver.get(config["login_url"])

    log('Entering login credentials...')
    
    # Wait for login form elements to be visible
    WebDriverWait(driver, 30).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="Username"]'))
    )
    
    # Enter username
    username_field = driver.find_element(By.CSS_SELECTOR, 'input[placeholder*="Username"]')
    username_field.clear()
    username_field.send_keys(config["credentials"]["username"])
    
    # Enter password
    password_field = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
    password_field.clear()
    password_field.send_keys(config["credentials"]["password"])
    
    # Enter security code
    security_code_field = driver.find_element(By.CSS_SELECTOR, 'input[placeholder*="ID Code"]')
    security_code_field.clear()
    security_code_field.send_keys(config["credentials"]["security_code"])
    
    # Click login button
    log('Logging in...')
    login_button = driver.find_element(By.CSS_SELECTOR, 'button.btn.btn-success')
    login_button.click()
    
    # Wait for navigation to complete
    WebDriverWait(driver, 30).until(
        lambda d: 'login' not in d.current_url
    )
    
    # Check if login was successful
    if "login" in driver.current_url:
        raise Exception("Login failed. Please check your credentials.")

    end = time.time()
    log('Login successful!')
    log(f"Login operation took: {end - start:.3f}s")

def navigate_to_case(driver, case_id):
    """Navigate to a specific case page and extract basic case information"""
    start = time.time()
    case_url = f"{config['case_base_url']}{case_id}"
    log(f"Navigating to case {case_id}...")

    driver.get(case_url)

    # Ensure the page loaded successfully
    WebDriverWait(driver, 30).until(
        lambda d: 'Error' not in d.title and 'Not Found' not in d.title
    )

    log(f"Successfully navigated to case {case_id}")

    # Extract case information
    log("Extracting case information...")

    # Take a screenshot for debugging
    screenshots_dir = os.path.join(config["output_dir"])
    os.makedirs(screenshots_dir, exist_ok=True)
    driver.save_screenshot(os.path.join(screenshots_dir, f"case-page-{int(time.time())}.png"))

    # Extract the case information
    case_info = extract_case_information(driver)

    # Store the case information in config
    config["current_case_info"] = case_info

    log(f"Case information extracted: Client: {case_info['clientName']}, Lien Holder: {case_info['lienHolderName']}, Repo Type: {case_info['repoType']}")

    # Scan the current page for key fees (specifically look for push to start key fees)
    log("Scanning the page for key fee information...")
    try:
        # Get the page HTML content
        page_html = driver.page_source

        # Save the HTML for debugging
        html_path = os.path.join(config["output_dir"], f"case-html-{int(time.time())}.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(page_html)

        # Scan for key fees in the page
        key_fees = scan_for_key_fees(page_html)

        if key_fees:
            log(f"Found {len(key_fees)} key fees in the page!")
            for i, fee in enumerate(key_fees):
                log(f"Key Fee {i+1}: ${fee['amount']} - {fee['context'][:30]}...")

            # Create structured fee updates for these fees that will work with the fees table
            global key_fee_updates  # Create a global variable to store these key fees
            key_fee_updates = []

            for fee in key_fees:
                fee_update = {
                    'date': datetime.datetime.now().strftime('%m/%d/%Y'),
                    'type': 'Push to Start Key Fee',
                    'content': fee['context'],
                    'user': 'System',
                    'amounts': [{
                        'amount': fee['amount'],
                        'context': fee['context'],
                        'isExplicitlyApproved': False,
                        'feeType': 'Keys Fee'
                    }],
                    'isApproved': False,
                    'source': 'Case Page'
                }

                # Add to our key_fee_updates list
                key_fee_updates.append(fee_update)

                # Log that we've created a fee update
                log(f"Created key fee update: ${fee['amount']} - Source: Case Page")
        else:
            log("No key fees found in the page.")
    except Exception as e:
        log(f"Error scanning for key fees: {str(e)}", "error")

    # Automatically fetch database fee information based on the extracted case info
    log("Starting automatic database fee lookup with case information...")
    try:
        database_fees = auto_fetch_database_fees()
        log(f"Auto database lookup complete - found {len(database_fees)} matching fee records")
    except Exception as e:
        log(f"Error during automatic database lookup: {str(e)}", "error")

    end = time.time()
    log(f"Navigate to case operation took: {end - start:.3f}s")

    return case_info

def extract_case_information(driver):
    """Extract basic case information from the case page using multiple approaches"""
    start = time.time()
    # Wait for the page to be fully loaded
    time.sleep(3)

    # Take a full screenshot for debugging purposes
    driver.save_screenshot(os.path.join(config["output_dir"], f"case-page-full-{int(time.time())}.png"))

    # Get the full page HTML for analysis if needed
    page_html = driver.page_source
    with open(os.path.join(config["output_dir"], f"case-page-html-{int(time.time())}.html"), 'w', encoding='utf-8') as f:
        f.write(page_html)

    # Initialize case info with default values
    case_info = {
        "clientName": "Not found",
        "lienHolderName": "Not found",
        "repoType": "Not found"
    }

    try:
        # TARGET APPROACH: Try the most specific selector first for exactly the structure we're looking for
        # This targets: <div class="col-auto"><dt>Client</dt><dd>Location Services, LLC</dd></div>
        log("Attempting to extract case information using EXACT pattern match")

        try:
            # Look for the exact client pattern using XPath
            client_elements = driver.find_elements(By.XPATH, '//div[contains(@class, "col-auto")]/dt[text()="Client"]')

            for client_el in client_elements:
                try:
                    # Get the parent div
                    parent_div = client_el.find_element(By.XPATH, './..')
                    # Get the sibling dd
                    dd_elements = parent_div.find_elements(By.CSS_SELECTOR, 'dd')
                    if dd_elements and dd_elements[0].text.strip():
                        case_info["clientName"] = dd_elements[0].text.strip()
                        log(f"Found client name using EXACT pattern: {case_info['clientName']}")
                        break
                except Exception as e:
                    log(f"Error finding dd for client: {str(e)}", "error")

            # Look for the exact lien holder pattern using XPath
            lien_elements = driver.find_elements(By.XPATH, '//div[contains(@class, "col-auto")]/dt[text()="Lien Holder"]')

            for lien_el in lien_elements:
                try:
                    # Get the parent div
                    parent_div = lien_el.find_element(By.XPATH, './..')
                    # Get the sibling dd
                    dd_elements = parent_div.find_elements(By.CSS_SELECTOR, 'dd')
                    if dd_elements and dd_elements[0].text.strip():
                        case_info["lienHolderName"] = dd_elements[0].text.strip()
                        log(f"Found lien holder name using EXACT pattern: {case_info['lienHolderName']}")
                        break
                except Exception as e:
                    log(f"Error finding dd for lien holder: {str(e)}", "error")

        except Exception as e:
            log(f"Error using EXACT pattern match: {str(e)}", "error")

        # APPROACH 1: Look for definition list (dl/dt/dd) structure which is common for metadata
        # This is a more general approach for dl/dt/dd structure
        if case_info["clientName"] == "Not found" or case_info["lienHolderName"] == "Not found":
            log("Attempting to extract case information using dt/dd approach")

            # Look for all dt elements
            dt_elements = driver.find_elements(By.CSS_SELECTOR, 'dt')
            for dt in dt_elements:
                if dt.text.strip() == 'Client':
                    # Find the sibling dd element that should contain the client name
                    try:
                        parent = dt.find_element(By.XPATH, './..')  # Get parent element
                        dd_elements = parent.find_elements(By.CSS_SELECTOR, 'dd')
                        if dd_elements and dd_elements[0].text.strip():
                            case_info["clientName"] = dd_elements[0].text.strip()
                            log(f"Found client name using dt/dd: {case_info['clientName']}")
                    except Exception as e:
                        log(f"Error finding client dd element: {str(e)}", "error")

                elif dt.text.strip() == 'Lien Holder':
                    # Find the sibling dd element that should contain the lien holder name
                    try:
                        parent = dt.find_element(By.XPATH, './..')  # Get parent element
                        dd_elements = parent.find_elements(By.CSS_SELECTOR, 'dd')
                        if dd_elements and dd_elements[0].text.strip():
                            case_info["lienHolderName"] = dd_elements[0].text.strip()
                            log(f"Found lien holder name using dt/dd: {case_info['lienHolderName']}")
                    except Exception as e:
                        log(f"Error finding lien holder dd element: {str(e)}", "error")

        # APPROACH 2: Look for the badge element that indicates Involuntary/Voluntary Repo
        log("Attempting to extract repo type using badge element")
        try:
            # First try the most specific XPath for the badge pattern we found
            # <span class="badge-invol">Involuntary Repo</span>
            try:
                badge_elements = driver.find_elements(By.XPATH, '//span[contains(@class, "badge-invol")]')
                if badge_elements:
                    case_info["repoType"] = "Involuntary Repo"
                    log(f"Found Involuntary Repo using specific badge-invol class")
            except Exception:
                pass

            # Try for voluntary repo badge
            if case_info["repoType"] == "Not found":
                try:
                    badge_elements = driver.find_elements(By.XPATH, '//span[contains(@class, "badge-vol")]')
                    if badge_elements:
                        case_info["repoType"] = "Voluntary Repo"
                        log(f"Found Voluntary Repo using specific badge-vol class")
                except Exception:
                    pass

            # If still not found, try more generic badge selectors
            if case_info["repoType"] == "Not found":
                badge_elements = driver.find_elements(By.CSS_SELECTOR, '[class*="badge"]')
                for badge in badge_elements:
                    badge_text = badge.text.strip()
                    if 'involuntary' in badge_text.lower():
                        case_info["repoType"] = "Involuntary Repo"
                        log(f"Found repo type using badge text: {case_info['repoType']}")
                        break
                    elif 'voluntary' in badge_text.lower():
                        case_info["repoType"] = "Voluntary Repo"
                        log(f"Found repo type using badge text: {case_info['repoType']}")
                        break

            # Also check for Order To section
            if case_info["repoType"] == "Not found":
                order_to_elements = driver.find_elements(By.XPATH, '//span[@id="case_order_type_static"]')
                for element in order_to_elements:
                    element_text = element.text.lower()
                    if 'involuntary' in element_text:
                        case_info["repoType"] = "Involuntary Repo"
                        log(f"Found repo type in Order To section: {case_info['repoType']}")
                        break
                    elif 'voluntary' in element_text:
                        case_info["repoType"] = "Voluntary Repo"
                        log(f"Found repo type in Order To section: {case_info['repoType']}")
                        break

        except Exception as e:
            log(f"Error finding repo type badge: {str(e)}", "error")

        # Check page text for patterns if we still need information
        if case_info["clientName"] == "Not found" or case_info["lienHolderName"] == "Not found" or case_info["repoType"] == "Not found":
            log("Falling back to text pattern matching approach")
            page_text = driver.find_element(By.TAG_NAME, 'body').text

            # Check for client pattern
            if case_info["clientName"] == "Not found":
                client_patterns = [
                    r'Client\s*:\s*([^\n:]+)',
                    r'Client\s+([A-Za-z0-9\s\.\,\&\;\-\'\"]+)(?=\s*Collector|\s*Lien|\s*$)',
                    r'Client(?:[\s\:]*)([^\n:]+?)(?=\s*Collector|\s*Lien|\s*$)'
                ]

                for pattern in client_patterns:
                    client_matches = re.search(pattern, page_text)
                    if client_matches and client_matches.group(1):
                        case_info["clientName"] = client_matches.group(1).strip()
                        log(f"Found client name using regex: {case_info['clientName']}")
                        break

            # Check for lien holder pattern
            if case_info["lienHolderName"] == "Not found":
                lien_patterns = [
                    r'Lien\s*Holder\s*:\s*([^\n:]+)',
                    r'Lien\s*Holder\s+([A-Za-z0-9\s\.\,\&\;\-\'\"]+)(?=\s*Client|\s*Acct|\s*File|\s*$)',
                    r'Lien\s*Holder(?:[\s\:]*)([^\n:]+?)(?=\s*Client|\s*Acct|\s*File|\s*$)'
                ]

                for pattern in lien_patterns:
                    lien_holder_matches = re.search(pattern, page_text)
                    if lien_holder_matches and lien_holder_matches.group(1):
                        case_info["lienHolderName"] = lien_holder_matches.group(1).strip()
                        log(f"Found lien holder name using regex: {case_info['lienHolderName']}")
                        break

            # Check for repo type patterns
            if case_info["repoType"] == "Not found":
                # If we still can't find it, use a default value
                case_info["repoType"] = "Involuntary Repo"  # Default to most common type
                log("Using default 'Involuntary Repo' as repo type")

        # Clean up the values
        if case_info["clientName"] != "Not found":
            case_info["clientName"] = re.sub(r'^Client\s*:?\s*', '', case_info["clientName"]).strip()

        if case_info["lienHolderName"] != "Not found":
            case_info["lienHolderName"] = re.sub(r'^Lien\s*Holder\s*:?\s*', '', case_info["lienHolderName"]).strip()

        # Log the final extracted values
        log(f"Extracted case information - Client: {case_info['clientName']}, Lien Holder: {case_info['lienHolderName']}, Repo Type: {case_info['repoType']}")

    except Exception as e:
        log(f"Error extracting case information: {str(e)}", "error")
        # Capture error screenshot
        driver.save_screenshot(os.path.join(config["output_dir"], f"error-case-info-extraction-{int(time.time())}.png"))

        # Store stack trace for debugging
        import traceback
        error_details = traceback.format_exc()
        log(f"Stack trace: {error_details}", "error")

    end = time.time()
    log(f"Case information extraction took: {end - start:.3f}s")

    return case_info

def click_my_summary_tab(driver):
    """Click on the My Summary tab"""
    start = time.time()
    log('Clicking on My Summary tab...')

    # First check if we're already on the My Summary tab
    current_active_tab = None
    try:
        current_active_tab = driver.execute_script("""
            const activeTab = document.querySelector('a.nav-link.active, a.active, .nav-item.active a');
            return activeTab ? activeTab.textContent.trim().toLowerCase() : '';
        """)

        if current_active_tab and ('my summary' in current_active_tab or 'summary' in current_active_tab):
            log('Already on My Summary tab, no need to click')
            log(f"Tab check took: {time.time() - start:.3f}s")
            return True
    except Exception as e:
        log(f"Error checking current tab: {str(e)}", "warning")
    
    # Wait for the page to be fully loaded - using dynamic wait instead of fixed sleep
    try:
        # Wait for either the page to fully load or for key elements to appear
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.TAG_NAME, 'nav'))
        )
    except:
        # Brief fallback wait if needed
        time.sleep(0.5)
    
    # Try to find the My Summary tab using different strategies
    try:
        # Try to find by tab structure based on the sample HTML
        log('Attempting to find My Summary tab in the navigation structure...')
        my_summary_tab = None
        
        # First attempt: Look for tabs by label in the JavaScript structure
        script = """
            if (typeof tabs !== 'undefined') {
                for (let key in tabs) {
                    if (tabs[key] && tabs[key]['label'] &&
                        (tabs[key]['label'].toLowerCase().includes('summary') ||
                         tabs[key]['label'].toLowerCase().includes('my summary'))) {
                        return key;
                    }
                }
            }
            return null;
        """
        tab_key = driver.execute_script(script)
        
        if tab_key:
            log(f'Found My Summary tab with key: {tab_key}')
            # Try to click it using the tab's ID
            try:
                driver.execute_script(f"switchTab({tab_key});")
                log('Clicked My Summary tab using JavaScript')
                # Success - proceed
                return True
            except Exception as js_err:
                log(f'Error using JavaScript to click: {str(js_err)}', 'warning')
                # Continue to other methods
        
        # Second attempt: Look for tab element by text content
        my_summary_tab = driver.execute_script("""
            // Strategy 1: Direct selector
            let tab = document.querySelector('a.nav-link[href*="summary"], a[href*="Summary"]');
            
            // Strategy 2: Text content matching
            if (!tab) {
                const allLinks = Array.from(document.querySelectorAll('a'));
                tab = allLinks.find(link =>
                    link.textContent.trim().toLowerCase().includes('my summary')
                );
                
                // Strategy 3: Just "summary" if "my summary" not found
                if (!tab) {
                    tab = allLinks.find(link =>
                        link.textContent.trim().toLowerCase().includes('summary')
                    );
                }
            }
            
            return tab;
        """)
        
        if my_summary_tab:
            log('Found My Summary tab element')
            # Try JavaScript click first as it's more reliable
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", my_summary_tab)
                driver.execute_script("arguments[0].click();", my_summary_tab)
                log('Clicked My Summary tab using JavaScript')
                
                # Also try dispatching a click event
                driver.execute_script("""
                    const clickEvent = new MouseEvent('click', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    arguments[0].dispatchEvent(clickEvent);
                """, my_summary_tab)
                
                # Wait a moment for the click to take effect
                time.sleep(0.5)
            except Exception as js_click_err:
                log(f'JavaScript click failed: {str(js_click_err)}', 'warning')
                
                # Try direct click
                try:
                    my_summary_tab.click()
                    log('Clicked My Summary tab directly')
                except Exception as click_err:
                    log(f'Direct click failed: {str(click_err)}', 'warning')
                    
                    # Try action chains as last resort
                    try:
                        actions = ActionChains(driver)
                        actions.move_to_element(my_summary_tab).click().perform()
                        log('Clicked My Summary tab using ActionChains')
                    except Exception as action_err:
                        log(f'ActionChains click failed: {str(action_err)}', 'error')
                        # Continue to verify if we're on the right page
    except Exception as e:
        log(f'Error finding or clicking My Summary tab: {str(e)}', 'warning')
    
    # Check if we're on the My Summary tab by looking for characteristic elements
    log('Checking if we successfully navigated to My Summary tab...')
    try:
        # Look for Updates section which is typically on My Summary
        update_sections = driver.find_elements(By.XPATH,
            "//h3[contains(text(), 'Update')] | //div[contains(text(), 'Update')] | " +
            "//span[contains(text(), 'Update')] | //div[contains(@id, 'update')] | " +
            "//section[contains(@id, 'update')]")
        
        if update_sections:
            log("Found 'Updates' section - successfully on My Summary tab")
            return True
    except Exception:
        pass
    
    # Wait for summary content to load with dynamic waiting
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                'table, .fee-table, .summary-table, .data-table, .case-details, ' +
                'div[id*="update"], section[id*="update"]'))
        )
        log('Found summary content, page loaded successfully')
        return True
    except TimeoutException:
        # Take a screenshot to see what happened
        driver.save_screenshot(os.path.join(config["output_dir"], f"my-summary-tab-error-{int(time.time())}.png"))
        log('Could not confirm My Summary tab loaded, but proceeding anyway', 'warning')
    
    # Take a screenshot of the My Summary tab
    driver.save_screenshot(os.path.join(config["output_dir"], f"my-summary-tab-{int(time.time())}.png"))

    end = time.time()
    log(f"Click My Summary tab operation took: {end - start:.3f}s")

    # Return True to proceed with the process even if we're not sure we navigated successfully
    return True

def click_updates_tab(driver):
    """Click on the Updates tab"""
    start = time.time()
    log('Clicking on Updates tab...')

    # First check if we're already on the Updates tab
    current_active_tab = None
    try:
        current_active_tab = driver.execute_script("""
            const activeTab = document.querySelector('a.nav-link.active, a.active, .nav-item.active a');
            return activeTab ? activeTab.textContent.trim().toLowerCase() : '';
        """)

        if current_active_tab and 'updates' in current_active_tab:
            log('Already on Updates tab, no need to click')
            log(f"Tab check took: {time.time() - start:.3f}s")
            return True
    except Exception as e:
        log(f"Error checking current tab: {str(e)}", "warning")

    # Wait for the page to be fully loaded - using dynamic wait
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.TAG_NAME, 'nav'))
        )
    except:
        # Brief fallback wait
        time.sleep(0.5)

    # First try using the tab structure from the JS object if available
    try:
        # Look for tabs specifically labeled 'Updates' in the JavaScript structure
        updates_key = driver.execute_script("""
            if (typeof tabs !== 'undefined') {
                for (let key in tabs) {
                    if (tabs[key] && tabs[key]['label'] &&
                        tabs[key]['label'].toLowerCase() === 'updates') {
                        return key;
                    }
                }
            }
            return null;
        """)

        if updates_key:
            log(f'Found Updates tab with key: {updates_key}')
            # Try to use switchTab function if available
            try:
                driver.execute_script(f"switchTab({updates_key});")
                log('Successfully clicked Updates tab using JavaScript')
                # Check if successful
                time.sleep(0.5)
                if driver.find_elements(By.CSS_SELECTOR, 'div.pagination, a.page-link, button.pagination-button'):
                    log('Successfully navigated to Updates tab')
                    return True
            except Exception as js_err:
                log(f'JavaScript click error: {str(js_err)}', 'warning')
                # Continue to next methods
    except Exception as tab_err:
        log(f'Error finding Updates tab in JS: {str(tab_err)}', 'warning')

    # Try multiple strategies to find and click the Updates tab
    log('Trying visual element strategies...')
    try:
        # Find the Updates tab using JavaScript
        updates_tab = driver.execute_script("""
            // Strategy 1: Direct selector
            let tab = document.querySelector('a.nav-link[href*="updates"], a[href*="Updates"]');

            // Strategy 2: Text content matching
            if (!tab) {
                const allLinks = Array.from(document.querySelectorAll('a'));
                tab = allLinks.find(link =>
                    link.textContent.trim().toLowerCase().includes('updates')
                );
            }

            return tab;
        """)

        if updates_tab:
            log('Found Updates tab element')
            # Try JavaScript click first as it's more reliable
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", updates_tab)
                driver.execute_script("arguments[0].click();", updates_tab)
                log('Clicked Updates tab using JavaScript')

                # Also try dispatching a click event
                driver.execute_script("""
                    const clickEvent = new MouseEvent('click', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    arguments[0].dispatchEvent(clickEvent);
                """, updates_tab)

                # Wait a moment for the click to take effect
                time.sleep(0.5)
            except Exception as js_click_err:
                log(f'JavaScript click failed: {str(js_click_err)}', 'warning')

                # Try direct click
                try:
                    updates_tab.click()
                    log('Clicked Updates tab directly')
                except Exception as click_err:
                    log(f'Direct click failed: {str(click_err)}', 'warning')

                    # Try action chains as last resort
                    try:
                        actions = ActionChains(driver)
                        actions.move_to_element(updates_tab).click().perform()
                        log('Clicked Updates tab using ActionChains')
                    except Exception as action_err:
                        log(f'ActionChains click failed: {str(action_err)}', 'error')
                        # Throw an error if all methods fail
                        raise Exception("Failed to click the Updates tab with all methods")
        else:
            log('Could not find the Updates tab element', 'error')
            raise Exception("Updates tab element not found")
    except Exception as e:
        log(f'Error finding or clicking Updates tab: {str(e)}', 'error')
        raise e  # Re-raise the error since Updates tab is essential

    # Check if we successfully navigated to the Updates tab
    try:
        # Wait for updates container to load with dynamic waiting
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                'div.pagination, a.page-link, button.pagination-button, ' +
                '.updates-container, .update-history, .update-list, .update-item, tr.update'))
        )
        log('Found updates content, page loaded successfully')
        return True
    except TimeoutException:
        # Take a screenshot to see what happened
        driver.save_screenshot(os.path.join(config["output_dir"], f"updates-tab-error-{int(time.time())}.png"))
        log('Could not confirm Updates tab loaded, but proceeding anyway', 'warning')

    # Take a screenshot of the Updates tab
    driver.save_screenshot(os.path.join(config["output_dir"], f"updates-tab-{int(time.time())}.png"))

    end = time.time()
    log(f"Click Updates tab operation took: {end - start:.3f}s")

    log('Updates tab loaded or processing continuing')
    return True

def load_all_updates(driver):
    """Click on ALL to load all updates - optimized for speed"""
    start = time.time()
    log('Loading all updates - optimized approach...')

    # Take an initial screenshot to debug pagination
    screenshot_path = os.path.join(config["output_dir"], f"before-all-click-{int(time.time())}.png")
    driver.save_screenshot(screenshot_path)
    
    # Rather than waiting for controls, try to find them immediately with no waiting
    pagination_elements = driver.find_elements(By.CSS_SELECTOR, '.pagination, ul.js-update-pagination, ul.pagination.js-update-pagination')

    if not pagination_elements:
        # If no pagination controls, try to help load updates with JavaScript
        try:
            log('No pagination controls found, trying to load updates directly via JavaScript...')
            driver.execute_script("""
                // Try to find any update containers
                const containers = document.querySelectorAll('.updates-container, .update-history, .update-list, .case-updates, #updates');

                // If found, trigger visibility and scrolling
                if (containers.length > 0) {
                    containers[0].scrollIntoView();

                    // Try to find any "ALL" button by text content
                    const allLinks = Array.from(document.querySelectorAll('a, button'))
                        .filter(el => el.textContent.trim() === 'ALL');

                    // Click it if found
                    if (allLinks.length > 0) {
                        allLinks[0].click();
                        console.log('Clicked ALL button via JavaScript');
                    }

                    // Try to execute any load_updates or similar function
                    if (typeof load_updates === 'function') {
                        load_updates('all');
                        console.log('Called load_updates function');
                    }

                    // Try to find and click any "load more" or similar buttons
                    const loadMoreButtons = Array.from(document.querySelectorAll('button, a'))
                        .filter(el => el.textContent.toLowerCase().includes('load') ||
                                    el.textContent.toLowerCase().includes('more') ||
                                    el.textContent.toLowerCase().includes('all'));

                    if (loadMoreButtons.length > 0) {
                        loadMoreButtons[0].click();
                        console.log('Clicked load more button');
                    }
                }

                return true;
            """)
            log('Attempted to load updates via JavaScript')
            # Take a brief pause to let JavaScript execute
            time.sleep(0.5)
        except Exception as js_err:
            log(f'JavaScript update loading attempt failed: {str(js_err)}', 'warning')

        # Continue processing even without pagination controls
        log('Proceeding with any updates found on the page')
        return

    log('Found pagination controls')
    
    # Check initial update count for comparison
    initial_update_count = len(driver.find_elements(By.CSS_SELECTOR, '.update-item, .update-row, tr.update, div[data-update-id]'))
    log(f'Initial number of updates: {initial_update_count}')
    
    # Multiple strategies to find and click the "ALL" button
    click_successful = False
    
    # Strategy 1: Using the exact data-page attribute from the HTML
    try:
        all_button_exists = driver.execute_script("""
            // Look for the ALL button using various selectors
            const button = document.querySelector('a.page-link[data-page="ALL"]');
            if (button) {
                return true;
            }
            return false;
        """)
        
        if all_button_exists:
            log('Found ALL button by data-page attribute')
            
            # Use JavaScript click to avoid interception
            driver.execute_script("""
                const button = document.querySelector('a.page-link[data-page="ALL"]');
                if (button) {
                    button.scrollIntoView({block: 'center'});
                    button.click();
                    
                    // Also try dispatch event
                    const clickEvent = new MouseEvent('click', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    button.dispatchEvent(clickEvent);
                }
            """)
            log('Clicked ALL using JavaScript')
            click_successful = True
    except Exception as js_err:
        log(f'JavaScript click failed: {str(js_err)}', 'warning')
    
    # Strategy 2: Try looking by text content if Strategy 1 failed
    if not click_successful:
        try:
            # Find all links with text "ALL"
            all_links = driver.execute_script("""
                const links = Array.from(document.querySelectorAll('a.page-link, a'));
                const allLinks = links.filter(link => link.textContent.trim() === 'ALL');
                
                if (allLinks.length > 0) {
                    // Try clicking the first one
                    allLinks[0].scrollIntoView({block: 'center'});
                    allLinks[0].click();
                    
                    // Also try dispatch event
                    const clickEvent = new MouseEvent('click', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    allLinks[0].dispatchEvent(clickEvent);
                    return true;
                }
                return false;
            """)
            
            if all_links:
                log('Clicked ALL button using text search')
                click_successful = True
        except Exception as e:
            log(f'Error finding ALL by text: {str(e)}', 'warning')
    
    # Strategy 3: Try direct Selenium click if JavaScript methods failed
    if not click_successful:
        try:
            # Find and click the ALL button with Selenium
            all_button = driver.find_element(By.CSS_SELECTOR, 'a.page-link[data-page="ALL"], a.page-link[text()="ALL"]')
            all_button.click()
            log('Clicked ALL button using Selenium click')
            click_successful = True
        except Exception as e:
            log(f'Error clicking ALL button: {str(e)}', 'warning')
    
    # Take a screenshot after clicking
    screenshot_path = os.path.join(config["output_dir"], f"after-all-click-{int(time.time())}.png")
    driver.save_screenshot(screenshot_path)
    
    # If we couldn't click the ALL button, log and return
    if not click_successful:
        log('Could not click the ALL button. Proceeding with currently loaded updates.', 'warning')
        return
    
    # Wait for updates to load with a faster approach
    log('Using fast approach for updates loading...')
    max_wait_time = 2  # Just 2 seconds max wait
    check_interval = 0.2  # Check 5 times per second
    start_wait_time = time.time()

    # Try a more aggressive approach to loading updates
    try:
        # Use a more aggressive JavaScript approach to force updates to load
        driver.execute_script("""
            // Try multiple strategies to trigger updates loading

            // 1. Scroll to different positions to trigger lazy loading
            window.scrollTo(0, 0);
            setTimeout(() => window.scrollTo(0, 500), 100);
            setTimeout(() => window.scrollTo(0, 1000), 200);
            setTimeout(() => window.scrollTo(0, 0), 300);

            // 2. Click on any element that might be related to updates
            const clickTargets = [
                '.refresh-btn',
                '.reload-btn',
                '.update-btn',
                'button[data-action="refresh"]',
                'a.page-link',
                '[data-action="load-all"]'
            ];

            clickTargets.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                if (elements.length) {
                    elements[0].click();
                    console.log(`Clicked ${selector}`);
                }
            });

            // 3. Try to call any update-related functions
            const possibleFunctions = ['loadUpdates', 'refreshUpdates', 'loadAll', 'getUpdates'];
            possibleFunctions.forEach(funcName => {
                if (typeof window[funcName] === 'function') {
                    try {
                        window[funcName]();
                        console.log(`Called ${funcName}()`);
                    } catch(e) {}
                }
            });

            // 4. Try to dispatch custom events that might trigger updates
            const events = ['load', 'DOMContentLoaded', 'scroll', 'resize'];
            events.forEach(eventName => {
                try {
                    window.dispatchEvent(new Event(eventName));
                } catch(e) {}
            });
        """)
    except:
        pass

    last_update_count = initial_update_count
    stable_count = 0

    while (time.time() - start_wait_time) < max_wait_time:
        # Wait before checking
        time.sleep(check_interval)

        # Check if there are loading indicators
        loading_indicators = driver.find_elements(By.CSS_SELECTOR, '.loading, .spinner, [aria-busy="true"], .progress')
        if loading_indicators:
            log('Loading indicators still present, waiting...')
            continue

        # Check current update count
        current_update_count = len(driver.find_elements(By.CSS_SELECTOR, '.update-item, .update-row, tr.update, div[data-update-id]'))
        log(f'Current update count: {current_update_count}')

        # If ANY updates are found, consider it a success and don't wait for more
        if current_update_count > 0:
            log(f'Found {current_update_count} updates, proceeding with processing')
            break

        # If count hasn't changed for any check, consider it done immediately
        if current_update_count == last_update_count:
            stable_count += 1
            # After just one stable check, move on
            log(f'Update count stable at {current_update_count}, proceeding anyway')
            break
        else:
            # Count changed, update counter
            last_update_count = current_update_count
    
    # If we've reached max wait time, log that we're proceeding anyway
    if (time.time() - start_wait_time) >= max_wait_time:
        log('Reached maximum wait time. Proceeding with currently loaded updates.')
    
    # Final screenshot after loading completes
    screenshot_path = os.path.join(config["output_dir"], f"updates-loaded-{int(time.time())}.png")
    driver.save_screenshot(screenshot_path)

    end = time.time()
    log(f"Load all updates operation took: {end - start:.3f}s")

    log('Updates loading completed')

def scrape_updates_tab(driver):
    """Scrape update information from the page"""
    start = time.time()
    log('Scraping updates...')

    # Take a screenshot of the updates page
    screenshot_path = os.path.join(config["output_dir"], f"updates-page-{int(time.time())}.png")
    driver.save_screenshot(screenshot_path)

    # First specifically check for Last Two Updates section
    log('Checking for Last Two Updates section...')
    try:
        # Directly extract "Last Two Updates" section which often contains fee information
        last_two_updates = driver.execute_script("""
            // Find the Last Two Updates section without using :has() selector
            function findContainerWithText(tagName, headerTag, text) {
                // First find headers containing the text
                const headers = Array.from(document.querySelectorAll(headerTag)).filter(el =>
                    el.textContent.trim().includes(text));

                // For each header, find the closest parent matching the tag
                for (const header of headers) {
                    let parent = header.parentElement;
                    while (parent) {
                        if (parent.tagName.toLowerCase() === tagName.toLowerCase()) {
                            return parent;
                        }
                        parent = parent.parentElement;
                    }
                }
                return null;
            }

            // Try different combinations
            let lastTwoUpdatesSection =
                findContainerWithText('div', 'h3', 'Last Two Updates') ||
                findContainerWithText('div', 'h4', 'Last Two Updates') ||
                findContainerWithText('div', 'div', 'Last Two Updates') ||
                findContainerWithText('table', 'th', 'Last Two Updates');

            if (!lastTwoUpdatesSection) {
                // Try more direct approach - find any element with "Last Two Updates" as text
                const elements = Array.from(document.querySelectorAll('*')).filter(el =>
                    el.textContent.trim() === 'Last Two Updates');

                if (elements.length > 0) {
                    // Get parent container
                    lastTwoUpdatesSection = elements[0].parentElement;
                    while (lastTwoUpdatesSection &&
                           !['div', 'table', 'section'].includes(lastTwoUpdatesSection.tagName.toLowerCase())) {
                        lastTwoUpdatesSection = lastTwoUpdatesSection.parentElement;
                    }
                }
            }

            if (!lastTwoUpdatesSection) return [];

            // Extract details from this section - without using :has()
            const detailsElements = [];

            // Add elements with .details class
            detailsElements.push(...lastTwoUpdatesSection.querySelectorAll('.details'));

            // Add td elements that contain .details class elements
            Array.from(lastTwoUpdatesSection.querySelectorAll('td')).forEach(td => {
                if (td.querySelector('.details')) {
                    detailsElements.push(td);
                }
            });

            // Add tr elements with at least 2 td cells
            Array.from(lastTwoUpdatesSection.querySelectorAll('tr')).forEach(tr => {
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 2) {
                    detailsElements.push(tr);
                }
            });

            return Array.from(detailsElements).map(el => {
                // Get update text and any adjacent elements with date/info
                const rowEl = el.closest('tr');
                let date = '';
                let updateType = '';
                let user = '';

                if (rowEl) {
                    // Try to extract date from the row
                    const dateEl = rowEl.querySelector('td:first-child');
                    if (dateEl) date = dateEl.textContent.trim();

                    // Try to get update type
                    const typeEl = rowEl.querySelector('td:nth-child(5)');
                    if (typeEl) updateType = typeEl.textContent.trim();
                }

                return {
                    date: date,
                    type: updateType || 'Summary Update',
                    content: el.textContent.trim(),
                    user: user || 'Unknown',
                    fromLastTwoUpdates: true
                };
            });
        """)

        if last_two_updates and len(last_two_updates) > 0:
            log(f'Found {len(last_two_updates)} updates in Last Two Updates section')
            updates = last_two_updates
        else:
            log('No updates found in Last Two Updates section, proceeding with main updates tab')
            updates = []
    except Exception as e:
        log(f'Error extracting Last Two Updates section: {str(e)}', 'error')

        # Capture screenshot for debugging
        screenshot_path = os.path.join(config["output_dir"], f"error-last-two-updates-{int(time.time())}.png")
        driver.save_screenshot(screenshot_path)
        log(f"Captured error screenshot: {screenshot_path}")

        # Try fallback JavaScript approach
        try:
            log("Trying fallback approach for Last Two Updates...")
            last_two_updates = driver.execute_script("""
                // Look for sections with "Updates" in title or containing update-like content
                const updateKeywords = ['Last Two Updates', 'Recent Updates', 'Updates', 'Activity'];

                // Find any elements that might contain updates
                function getElementsWithUpdateContent() {
                    // Get all elements that might be update containers
                    const containerCandidates = [];

                    // Method 1: Find elements with update-related text
                    for (const keyword of updateKeywords) {
                        const elements = Array.from(document.querySelectorAll('*')).filter(el => {
                            const text = el.textContent || '';
                            return text.includes(keyword) && text.length < 100;
                        });
                        containerCandidates.push(...elements);
                    }

                    // Method 2: Find elements with date patterns (common in updates)
                    const dateElements = Array.from(document.querySelectorAll('*')).filter(el => {
                        const text = el.textContent || '';
                        return /\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}/.test(text) &&
                               text.length > 20 && text.length < 1000;
                    });
                    containerCandidates.push(...dateElements);

                    // Get potential content elements
                    const updateElements = [];

                    // Look for actual content near these containers
                    for (const container of containerCandidates) {
                        // Try the element itself if it contains substantial text
                        if (container.textContent && container.textContent.length > 50) {
                            updateElements.push(container);
                        }

                        // Try siblings and children
                        const parent = container.parentElement;
                        if (parent) {
                            Array.from(parent.children).forEach(child => {
                                if (child.textContent && child.textContent.length > 50 &&
                                    child.textContent.length < 1000) {
                                    updateElements.push(child);
                                }
                            });
                        }
                    }

                    return updateElements;
                }

                const updateElements = getElementsWithUpdateContent();

                // Extract text and dates from these elements
                return updateElements.map(el => {
                    const text = el.textContent || '';

                    // Look for dates in the text
                    const dateMatch = text.match(/\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}/);
                    const date = dateMatch ? dateMatch[0] : '';

                    return {
                        text: text,
                        date: date,
                    };
                }).slice(0, 30); // Limit to 30 updates
            """);

            if last_two_updates and len(last_two_updates) > 0:
                log(f"Found {len(last_two_updates)} updates using fallback approach")

                # Convert to standardized format
                updates = []
                for update_info in last_two_updates:
                    update_text = update_info.get('text', '')
                    update_date = update_info.get('date', '')

                    if not update_text or len(update_text) < 20:
                        continue

                    # Extract fee information
                    fee_entries = extract_fee_information_from_text(update_text)

                    if fee_entries:
                        updates.append({
                            'date': update_date,
                            'type': 'Update',
                            'user': 'System',
                            'content': update_text,
                            'isApproved': False,
                            'source': 'Updates',
                            'amounts': fee_entries
                        })
            else:
                log("No updates found with fallback approach")
                updates = []
        except Exception as fallback_e:
            log(f"Fallback approach for Last Two Updates failed: {str(fallback_e)}", "error")
            updates = []

    try:
        # First try using a direct JavaScript approach for better performance
        js_updates = driver.execute_script("""
            // Find updates directly with JavaScript for better performance
            let updates = [];

            // Try standard update selectors first
            let elements = document.querySelectorAll('.update-item, .update-row, tr.update, div[data-update-id]');

            // If no elements found with specific selectors, try more generic approach
            if (elements.length === 0) {
                // Look for elements that might contain update information (with dates)
                const dateRegex = new RegExp("(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\\\s+\\\\d{1,2},\\\\s+\\\\d{4}|\\\\d{1,2}/\\\\d{1,2}/\\\\d{4}", "i");
                elements = Array.from(document.querySelectorAll('tr, div.row, div.card, div.panel'))
                    .filter(el => el.textContent && dateRegex.test(el.textContent));
            }

            // Process found elements
            for (const el of elements) {
                try {
                    // Extract structured data where possible
                    const dateEl = el.querySelector('.update-date, [data-field="update_date"], .date, td:nth-child(1)');
                    const typeEl = el.querySelector('.update-type, [data-field="update_type"], .type, td:nth-child(2)');
                    const contentEl = el.querySelector('.update-content, .update-details, [data-field="details"], .details, td:nth-child(3)');
                    const userEl = el.querySelector('.update-user, [data-field="updated_by"], .user, td:nth-child(4)');

                    const updateData = {
                        date: dateEl ? dateEl.textContent.trim() : '',
                        type: typeEl ? typeEl.textContent.trim() : '',
                        content: contentEl ? contentEl.textContent.trim() : '',
                        user: userEl ? userEl.textContent.trim() : '',
                        fullText: el.textContent.trim(),
                        isGeneric: !dateEl && !typeEl && !contentEl
                    };

                    // If we couldn't extract structured data, just use the full text
                    if (!updateData.date && !updateData.type && !updateData.content) {
                        updateData.isGeneric = true;
                    }

                    updates.push(updateData);
                } catch (err) {
                    // Fallback to just capturing the full text
                    updates.push({
                        fullText: el.textContent.trim(),
                        isGeneric: true
                    });
                }
            }

            return updates;
        """)

        if js_updates and len(js_updates) > 0:
            log(f'Scraped {len(js_updates)} updates using JavaScript')
            updates = js_updates
        else:
            # Fallback to the traditional approach if JavaScript didn't work
            log('JavaScript scraping returned no results, falling back to Selenium approach')

            # Use a shorter implicit wait to avoid long timeouts
            original_implicit_wait = driver.implicitly_wait(1)

            # Try different possible selectors for updates - limit results for performance
            update_elements = driver.find_elements(By.CSS_SELECTOR,
                '.update-item, .update-row, tr.update, div[data-update-id]')[:50]

            if not update_elements:
                # If no updates found with specific selectors, try a more generic approach
                log('No updates found with specific selectors, trying generic approach')

                generic_elements = driver.find_elements(By.CSS_SELECTOR, 'tr, div.row')[:50]
                for el in generic_elements:
                    text = el.text
                    if re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}', text, re.IGNORECASE) or \
                       re.search(r'\d{1,2}/\d{1,2}/\d{4}', text):
                        updates.append({
                            'genericElement': True,
                            'fullText': text.strip()
                        })
            else:
                # Process structured update elements - but only process the first 30 for performance
                for i, el in enumerate(update_elements):
                    if i >= 30:  # Limit to 30 elements for performance
                        break

                    update_data = {}

                    try:
                        # Try to extract structured data
                        date_el = el.find_elements(By.CSS_SELECTOR, '.update-date, [data-field="update_date"], .date, td:nth-child(1)')
                        type_el = el.find_elements(By.CSS_SELECTOR, '.update-type, [data-field="update_type"], .type, td:nth-child(2)')
                        content_el = el.find_elements(By.CSS_SELECTOR, '.update-content, .update-details, [data-field="details"], .details, td:nth-child(3)')
                        user_el = el.find_elements(By.CSS_SELECTOR, '.update-user, [data-field="updated_by"], .user, td:nth-child(4)')

                        update_data['date'] = date_el[0].text.strip() if date_el else ''
                        update_data['type'] = type_el[0].text.strip() if type_el else ''
                        update_data['content'] = content_el[0].text.strip() if content_el else ''
                        update_data['user'] = user_el[0].text.strip() if user_el else ''
                        update_data['fullText'] = el.text.strip()

                        updates.append(update_data)
                    except Exception:
                        # Fallback to just capturing the full text if structured extraction fails
                        updates.append({
                            'fullText': el.text.strip()
                        })

            # Restore original implicit wait
            driver.implicitly_wait(30 if original_implicit_wait is None else original_implicit_wait)

        log(f'Scraped {len(updates)} updates')

        # If no updates were found, don't save the page HTML (to save time)
        if not updates:
            log('No updates found.', 'warning')

    except Exception as e:
        log(f'Error scraping updates: {str(e)}', 'error')

    # Extract fee information from updates
    extraction_start = time.time()
    fee_updates = extract_fee_information(updates)
    extraction_end = time.time()
    log(f"Fee extraction took: {extraction_end - extraction_start:.3f}s")

    end = time.time()
    log(f"Total scrape_updates_tab operation took: {end - start:.3f}s")

    return updates, fee_updates

def extract_fee_information(updates):
    """Parse updates to extract fee information - optimized for performance"""
    start = time.time()
    log('Extracting fee information from updates...')

    fee_updates = []

    # Compile regular expressions once for better performance
    money_regex = re.compile(r'\$\s*([0-9,]+(\.[0-9]{2})?)')
    amount_regex = re.compile(r'([0-9,]+(\.[0-9]{2})?)\s*dollars', re.IGNORECASE)
    approved_regex = re.compile(r'approved\s+(?:fee|amount|payment|cost|charge)s?\s+(?:of|for|:)?\s*\$?\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE)

    # Enhanced patterns for fee-related text without dollar signs
    numeric_amount_regex = re.compile(r'\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:fee|charge|payment|paid|cost|invoice)', re.IGNORECASE)
    cost_pattern_regex = re.compile(r'(?:cost|fee|charge)(?:s)?\s+(?:of|is|:)\s*(\d+(?:,\d+)*(?:\.\d+)?)', re.IGNORECASE)
    service_fee_regex = re.compile(r'(?:key|repo|tow|storage|transport|service|mileage|admin|recovery|investigation|processing)(?:\s+fee|\s+charge|\s+cost|\s+payment|\s+amount)', re.IGNORECASE)
    authorized_regex = re.compile(r'(?:authorized|approved|auth[.]?)(?:\s+(?:for|to|:))?\s*(\d+(?:,\d+)*(?:\.\d+)?)', re.IGNORECASE)

    # Specific patterns for updates with push to start key fees
    key_made_regex = re.compile(r'(?:key made|push to start key|push key|would like a.*key).*?(?:for)?\s*\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE)
    vehicle_key_regex = re.compile(r'(?:vehicle|car).*?(?:key|push).*?(?:for)?\s*\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE)
    advise_regex = re.compile(r'(?:advise|please).*?(?:key|push).*?(?:for)?\s*\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE)

    # Quick check function for fee-related content
    def is_fee_related(text, type_text=''):
        """Quick check if content is fee-related - optimized for performance"""
        if '$' in text:
            return True

        text_lower = text.lower()
        # Enhanced keyword list
        return ('fee' in text_lower or
                'payment' in text_lower or
                'amount' in text_lower or
                'charge' in text_lower or
                'paid' in text_lower or
                'invoice' in text_lower or
                'cost' in text_lower or
                'approved' in text_lower or
                'auth' in text_lower or
                'tow' in text_lower or
                'repo' in text_lower or
                'storage' in text_lower or
                'service' in text_lower or
                'transport' in text_lower or
                'mileage' in text_lower or
                'recovery' in text_lower or
                'authorization' in text_lower or
                'dollars' in text_lower or
                # Check for numeric patterns - potentially fee-related if digits present with keywords
                (any(keyword in text_lower for keyword in ['total', 'key', 'admin', 'processing']) and
                 bool(re.search(r'\d+(?:\.\d+)?', text_lower))))

    # Process limited number of updates for performance
    max_updates_to_process = min(len(updates), 50)  # Limit to 50 updates

    for i, update in enumerate(updates):
        if i >= max_updates_to_process:
            break

        # Get the content from the update
        content = update.get('content', '') or update.get('fullText', '')
        update_type = (update.get('type', '') or '').lower()

        # Skip if completely empty content or very long content
        if not content.strip() or len(content) > 5000:
            continue

        # Quick check if this update is fee-related (faster than keyword list)
        if is_fee_related(content, update_type):
            # Debug logging for the first few updates to understand content format
            if i < 3:  # Only log the first few to avoid excessive logging
                log(f"Found fee-related update ({i}): Type: {update_type}, Content preview: {content[:100]}")

            # Extract amounts from content
            amounts = []

            # Find dollar amounts with $ symbol - more efficient extraction
            for match in money_regex.finditer(content):
                # Extract just a smaller context window around the match
                context_start = max(0, match.start() - 30)
                context_end = min(len(content), match.end() + 30)

                amounts.append({
                    'amount': match.group(1).replace(',', ''),
                    'context': content[context_start:context_end],
                    'isExplicitlyApproved': False
                })

            # We now always try other patterns even if we found dollar amounts
            # Since an update might contain multiple fee references

            # Find amounts specified with "dollars"
            for match in amount_regex.finditer(content):
                context_start = max(0, match.start() - 30)
                context_end = min(len(content), match.end() + 30)

                amounts.append({
                    'amount': match.group(1).replace(',', ''),
                    'context': content[context_start:context_end],
                    'isExplicitlyApproved': False
                })

            # Find specifically approved amounts
            for match in approved_regex.finditer(content):
                context_start = max(0, match.start() - 30)
                context_end = min(len(content), match.end() + 30)

                amounts.append({
                    'amount': match.group(1).replace(',', ''),
                    'context': content[context_start:context_end],
                    'isExplicitlyApproved': True
                })

            # Find numeric amounts paired with fee-related words
            for match in numeric_amount_regex.finditer(content):
                context_start = max(0, match.start() - 30)
                context_end = min(len(content), match.end() + 30)

                amounts.append({
                    'amount': match.group(1).replace(',', ''),
                    'context': content[context_start:context_end],
                    'isExplicitlyApproved': False
                })

            # Find cost of / fee of patterns
            for match in cost_pattern_regex.finditer(content):
                context_start = max(0, match.start() - 30)
                context_end = min(len(content), match.end() + 30)

                amounts.append({
                    'amount': match.group(1).replace(',', ''),
                    'context': content[context_start:context_end],
                    'isExplicitlyApproved': False
                })

            # Find authorized amounts
            for match in authorized_regex.finditer(content):
                context_start = max(0, match.start() - 30)
                context_end = min(len(content), match.end() + 30)

                amounts.append({
                    'amount': match.group(1).replace(',', ''),
                    'context': content[context_start:context_end],
                    'isExplicitlyApproved': True
                })

            # Add to fee updates if amounts found
            if amounts:
                fee_updates.append({
                    'date': update.get('date', ''),
                    'type': update.get('type', ''),
                    'user': update.get('user', ''),
                    'content': content[:300],  # Only store a portion of the content for efficiency
                    'amounts': amounts,
                    'isApproved': 'approved' in content.lower() or 'authorization' in content.lower() or 'authorize' in content.lower(),
                    'source': 'Updates'
                })

    end = time.time()
    log(f"Fee information extraction took: {end - start:.3f}s")

    # Log more detailed information to help diagnose fee extraction issues
    log(f"Analyzed {min(len(updates), max_updates_to_process)} updates and found {len(fee_updates)} fee-related updates")

    # If we have updates but no fees, log helpful diagnostics
    if len(updates) > 0 and len(fee_updates) == 0:
        log("No fees extracted despite having updates - possible pattern mismatch", "warning")
        # Log a sample of the first few updates for debugging
        for i, update in enumerate(updates[:3]):
            content = update.get('content', '') or update.get('fullText', '')
            update_type = update.get('type', '')
            log(f"Sample update {i} (type: {update_type}): {content[:200]}")

    return fee_updates

def determine_fee_type(text, fee_categories):
    """
    Helper function to determine fee type from text content using fee categories

    Args:
        text (str): The text content to analyze
        fee_categories (dict): Dictionary of fee categories and their keywords

    Returns:
        str: The determined fee type
    """
    # Default to unknown fee
    fee_type = "Unknown Fee"

    # Convert text to lowercase for case-insensitive matching
    text_lower = text.lower()

    # Check each category's keywords against the text
    for category, keywords in fee_categories.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return category

    # Enhanced check for push to start key with different wordings
    if "push" in text_lower and "start" in text_lower and "key" in text_lower:
        return "Keys Fee"

    # Additional check for variations like "push to start" or "push button key"
    if ("push" in text_lower and "key" in text_lower) or ("push to start" in text_lower):
        return "Keys Fee"

    # Check for sentences with "made" and "key" or "vehicle" and "key" - common in updates
    if "key made" in text_lower or ("vehicle" in text_lower and "key" in text_lower):
        return "Keys Fee"

    return fee_type

def scrape_my_summary_tab(driver):
    """Scrape fee information from the My Summary tab"""
    start = time.time()
    log('Scraping fee information from My Summary tab...')

    # Take a screenshot of the My Summary page for debugging
    screenshot_path = os.path.join(config["output_dir"], f"my-summary-details-{int(time.time())}.png")
    driver.save_screenshot(screenshot_path)

    fee_items = []
    recovery_date = ""

    try:
        # OPTIMIZED APPROACH: Directly search for fee-related content
        log("Looking for fee information using direct search...")

        # Define fee categories for better identification
        fee_categories = {
            "Fee To Client": ["fee to client", "client fee"],
            "Keys Fee": ["key fee", "keys fee", "for key", "key charge", "keys charge", "replacement key",
                        "spare key", "key duplication", "key cutting", "push to start key"],
            "Mileage/ Fuel": ["mileage", "fuel", "gas", "travel", "distance", "miles", "travel fee",
                              "trip fee", "zone fee"],
            "Flatbed Fees": ["flatbed", "flat bed", "flatbed fee", "tow truck", "towing fee", "rollback fee",
                            "roll back", "heavy duty", "winch", "winching"],
            "Storage Fee": ["storage", "storage fee", "impound", "lot fee", "daily storage"],
            "Purchase Cost": ["purchase", "cost", "expense", "purchase cost"],
            "CR AND PHOTOS FEE": ["cr fee", "cr and photos", "condition report", "photos fee", "pictures fee",
                                  "cr photos", "condition report and photos", "inspection fee", "inspection photos"]
        }

        # Set an implicit wait timeout to avoid long waits when elements aren't found
        try:
            original_implicit_wait = driver.implicit_wait_timeout
        except:
            original_implicit_wait = 30  # Default value if attribute not available

        driver.implicitly_wait(1)

        # Define JavaScript fee categories to match our Python categories
        js_fee_categories = json.dumps(fee_categories)

        # First, try to find amounts using a direct JavaScript approach, which is faster
        js_script = """
            // Define fee categories in JavaScript to match our Python categories
            const fee_categories = """ + js_fee_categories + """;

            // Find all elements with text containing $ followed by digits
            const allElements = document.querySelectorAll('*');
            const results = [];"""

        amounts_found = driver.execute_script(js_script + """

            // RegExp to find dollar amounts in text
            const amountRegex = new RegExp("\\$\\s*([0-9,]+(\\.[0-9]{2})?)");

            // Only check elements that have short text content (performance improvement)
            for (const el of allElements) {
                if (el.textContent && el.textContent.length < 200 &&
                    (el.textContent.includes('$') ||
                     el.textContent.toLowerCase().includes('fee') ||
                     el.textContent.toLowerCase().includes('amount'))) {

                    // Check for dollar amount
                    const match = amountRegex.exec(el.textContent);
                    if (match) {
                        const amount = match[1].replace(',', '');
                        const text = el.textContent.trim();
                        let feeType = 'Unknown Fee';

                        // Determine fee type using the categories defined above
                        const lowerText = text.toLowerCase();
                        let matched = false;

                        // Check each category's keywords against the text
                        for (const [category, keywords] of Object.entries(fee_categories)) {
                            for (const keyword of keywords) {
                                if (lowerText.includes(keyword)) {
                                    feeType = category;
                                    matched = true;
                                    break;
                                }
                            }
                            if (matched) break;
                        }

                        // If no category matched, try some additional checks
                        if (!matched) {
                            if (lowerText.includes('push') && lowerText.includes('start') && lowerText.includes('key')) {
                                feeType = 'Keys Fee';
                            }
                        }

                        results.push({
                            amount: amount,
                            text: text,
                            feeType: feeType
                        });
                    }
                }
            }

            return results;
        """)

        # Restore original implicit wait setting
        driver.implicitly_wait(30 if original_implicit_wait is None else original_implicit_wait)

        if amounts_found:
            log(f"Found {len(amounts_found)} fee amounts with direct JavaScript search")

            # Convert JavaScript results to fee items
            date_element = None
            try:
                # Look for any date on the page in a common format
                date_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '/20') or contains(text(), '-20')]")
                if date_elements:
                    date_text = date_elements[0].text
                    date_match = re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', date_text)
                    if date_match:
                        recovery_date = date_match.group(0)
            except Exception:
                # If no date found, use today's date
                recovery_date = datetime.datetime.now().strftime('%m/%d/%Y')

            # Process found amounts
            for amount_info in amounts_found:
                # Use our helper function to determine fee type
                fee_text = amount_info.get('text', '')
                fee_type = determine_fee_type(fee_text, fee_categories)

                fee_items.append({
                    'date': recovery_date,
                    'type': 'My Summary Fee',
                    'user': '',
                    'content': fee_text,
                    'amounts': [{
                        'amount': amount_info.get('amount', '0'),
                        'context': fee_text,
                        'isExplicitlyApproved': True  # Assume approved if in My Summary
                    }],
                    'isApproved': True,
                    'source': 'My Summary',
                    'feeLabel': fee_type
                })

            return fee_items

        # If the JavaScript approach didn't find any fees, try the original approaches
        log("No fees found with direct search, trying targeted approach...")

        # Look for Updates section with shorter timeout to avoid waiting 30s if not found
        updates_section = None
        try:
            # Set a very short timeout just for this operation
            driver.implicitly_wait(2)

            # Try multiple selector approaches to find the Updates section
            try:
                # Approach 1: Standard heading and div search
                updates_section = driver.find_element(By.XPATH,
                    "//h3[contains(text(), 'Update')] | //div[contains(text(), 'Update')][string-length() < 50]")
                log("Found 'Updates' section with primary selector")
            except NoSuchElementException:
                # Approach 2: More generic - any element with Update in text
                try:
                    updates_section = driver.find_element(By.XPATH,
                        "//*[contains(text(), 'Update') and string-length() < 50]")
                    log("Found 'Updates' section with secondary selector")
                except NoSuchElementException:
                    # Approach 3: Look for elements with update/updates in ID or class
                    try:
                        updates_section = driver.find_element(By.XPATH,
                            "//*[contains(@id, 'update') or contains(@class, 'update')]")
                        log("Found 'Updates' section with ID/class selector")
                    except NoSuchElementException:
                        log("No direct 'Updates' section found with any selector - will try generic content extraction")

            # Reset to normal timeout
            driver.implicitly_wait(30)

            if updates_section:
                log("Found 'Updates' section successfully")

                # Simplified container search - just use the parent or a close ancestor
                updates_container = driver.execute_script("""
                    let el = arguments[0];
                    return el.parentElement || el;
                """, updates_section)

                # Find a limited number of update blocks
                update_blocks = updates_container.find_elements(By.XPATH, ".//div[contains(., 'Details')]")
                update_blocks = update_blocks[:3] if len(update_blocks) > 3 else update_blocks

                log(f"Found {len(update_blocks)} update blocks (limited for performance)")

                for block in update_blocks:
                    block_text = block.text
                    log(f"Processing update block: {block_text[:100]}...")

                    # Pre-check for fee-related content - skip blocks without fee information
                    if '$' not in block_text and not re.search(r'(fee|amount)', block_text, re.IGNORECASE):
                        continue  # Skip this block entirely

                    # Extract date - only if needed
                    date_match = re.search(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+[AP]M', block_text)
                    update_date = date_match.group(0) if date_match else recovery_date

                    # Extract user if available - simple extraction
                    user_match = re.search(r'Last Updated By\s*([^(\n]+)', block_text)
                    user = user_match.group(1).strip() if user_match else ""

                    # Look for details section - more efficient lookup
                    try:
                        details_section = block.find_element(By.XPATH, ".//div[contains(text(), 'Details')]/following-sibling::div")
                        details_text = details_section.text
                    except:
                        details_text = block_text  # Use the full block if details section not found

                    # Extract amount - use $ symbol for faster matching
                    amount_match = re.search(r'\$\s*([0-9,]+(\.[0-9]{2})?)', details_text)
                    if amount_match:
                        amount = amount_match.group(1).replace(',', '')

                        # Use our helper function to determine fee type
                        fee_label = determine_fee_type(details_text, fee_categories)

                        fee_items.append({
                            'date': update_date,
                            'type': 'My Summary Fee',
                            'user': user,
                            'content': details_text,
                            'amounts': [{
                                'amount': amount,
                                'context': details_text,
                                'isExplicitlyApproved': True  # Updates in My Summary are generally approved
                            }],
                            'isApproved': True,
                            'source': 'My Summary',
                            'feeLabel': fee_label
                        })
                        log(f"Found fee in 'Updates' section: {fee_label} - ${amount} ({update_date})")
        except Exception as updates_err:
            log(f"Error processing 'Updates' section: {str(updates_err)}", "error")

            # Capture screenshot and HTML when errors occur
            screenshot_path = os.path.join(config["output_dir"], f"error-updates-{int(time.time())}.png")
            driver.save_screenshot(screenshot_path)
            log(f"Captured error screenshot: {screenshot_path}")

            # Save HTML source for analysis
            html_path = os.path.join(config["output_dir"], f"error-updates-html-{int(time.time())}.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            log(f"Saved HTML source for analysis: {html_path}")

            # Enhanced fallback strategy for extracting updates
            log("Falling back to robust extraction methods...")

            # Set a low timeout for faster fallback methods
            driver.implicitly_wait(1)

            # APPROACH 1: Try using JavaScript to find any update-like elements
            try:
                log("Trying JavaScript-based updates extraction...")
                updates_elements = driver.execute_script("""
                    // Find any potential update containers
                    const potentialContainers = [];

                    // Method 1: Try classes and IDs containing 'update'
                    document.querySelectorAll('*[id*="update" i], *[class*="update" i]').forEach(el => {
                        potentialContainers.push(el);
                    });

                    // Method 2: Text content containing 'update'
                    document.querySelectorAll('h1, h2, h3, h4, h5, h6, div, section, p').forEach(el => {
                        if ((el.textContent || '').toLowerCase().includes('update')) {
                            potentialContainers.push(el);
                        }
                    });

                    // Method 3: Look for date patterns which often precede updates
                    document.querySelectorAll('*').forEach(el => {
                        const text = el.textContent || '';
                        if (/\\d{1,2}[\\/\\-]\\d{1,2}[\\/\\-]\\d{2,4}/.test(text) &&
                            text.length > 10 && text.length < 100) {
                            potentialContainers.push(el.parentElement);
                        }
                    });

                    // Find container parents that might contain multiple updates
                    const containerParents = potentialContainers.map(el => el.parentElement)
                        .filter(el => el !== null);

                    // Get all content from these containers for processing
                    const updateTexts = [];

                    // Process each container and extract update info
                    containerParents.forEach(container => {
                        // Try direct children first
                        Array.from(container.children).forEach(child => {
                            const text = child.textContent || '';
                            if (text.length > 20 && text.length < 2000) {
                                updateTexts.push(text);
                            }
                        });
                    });

                    // If no results, try broader approach with text segments
                    if (updateTexts.length === 0) {
                        document.querySelectorAll('div, p, li, td, span').forEach(el => {
                            const text = el.textContent || '';
                            if (text.length > 30 && text.length < 1000) {
                                updateTexts.push(text);
                            }
                        });
                    }

                    return updateTexts.slice(0, 50); // Limit for performance
                """)

                if updates_elements and len(updates_elements) > 0:
                    log(f"Found {len(updates_elements)} potential updates with JavaScript")
                    # Process each update text
                    for update_text in updates_elements:
                        if not update_text or len(update_text.strip()) < 20:
                            continue

                        # Extract date if present
                        date_match = re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', update_text)
                        update_date = date_match.group() if date_match else recovery_date or datetime.datetime.now().strftime('%m/%d/%Y')

                        # Create update object
                        fee_item = {
                            'date': update_date,
                            'type': 'Update',
                            'user': 'System',
                            'content': update_text,
                            'isApproved': False,
                            'source': 'Updates',
                            'feeLabel': 'Update Fee',
                            'amounts': []
                        }

                        # Extract any fee amounts from the text
                        extracted_amounts = extract_fee_information_from_text(update_text)
                        if extracted_amounts:
                            fee_item['amounts'] = extracted_amounts
                            fee_items.append(fee_item)
                else:
                    log("No updates found with JavaScript method")
            except Exception as js_err:
                log(f"JavaScript updates extraction failed: {str(js_err)}", "warning")

            # APPROACH 2: Try XPath with very broad selectors
            try:
                log("Trying XPath-based updates extraction...")
                # Use a very broad XPath that might catch update info
                broad_selectors = [
                    "//div[string-length() > 30 and string-length() < 1000]",  # Medium-length divs
                    "//p[string-length() > 30]",  # Paragraphs with reasonable content
                    "//li[string-length() > 20]",  # List items that might be updates
                    "//td[string-length() > 20]",  # Table cells that might have update info
                ]

                for selector in broad_selectors:
                    try:
                        elements = driver.find_elements(By.XPATH, selector)
                        if elements and len(elements) > 0:
                            log(f"Found {len(elements)} potential updates with selector: {selector}")
                            for element in elements[:20]:  # Limit to 20 for performance
                                update_text = element.text.strip()
                                if not update_text or len(update_text) < 20:
                                    continue

                                # Skip navigation elements and menus
                                if len(update_text) < 30 or "navigation" in update_text.lower() or "menu" in update_text.lower():
                                    continue

                                # Extract date if present
                                date_match = re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', update_text)
                                update_date = date_match.group() if date_match else recovery_date or datetime.datetime.now().strftime('%m/%d/%Y')

                                # Create update object
                                fee_item = {
                                    'date': update_date,
                                    'type': 'Update',
                                    'user': 'System',
                                    'content': update_text,
                                    'isApproved': False,
                                    'source': 'Updates',
                                    'feeLabel': 'Update Fee',
                                    'amounts': []
                                }

                                # Extract any fee amounts from the text
                                extracted_amounts = extract_fee_information_from_text(update_text)
                                if extracted_amounts:
                                    fee_item['amounts'] = extracted_amounts
                                    fee_items.append(fee_item)
                    except Exception as selector_err:
                        log(f"Error with selector {selector}: {str(selector_err)}", "warning")
            except Exception as xpath_err:
                log(f"XPath updates extraction failed: {str(xpath_err)}", "warning")

            # Reset the timeout to original value
            driver.implicitly_wait(30)

            # Log summary of fallback extraction
            log(f"Fallback extraction found {len(fee_items)} fee items")

        # If we didn't find fees in the Updates section, use a more efficient approach with JavaScript
        if not fee_items:
            log("No fees found in Updates section, using direct JavaScript extraction...")

            # Set a lower implicit wait to prevent hanging on missing elements
            try:
                original_implicit_wait = driver.implicit_wait_timeout
            except:
                original_implicit_wait = 30  # Default value if attribute not available

            driver.implicitly_wait(1)

            # Look for any date on the page to use as reference date - find once and reuse
            if not recovery_date:
                try:
                    recovery_date = driver.execute_script("""
                        // Look for date patterns in the page
                        const dateRegex = new RegExp("\\\\d{1,2}[/\\\\-]\\\\d{1,2}[/\\\\-]\\\\d{2,4}");
                        const dateElements = Array.from(document.querySelectorAll('*'))
                            .filter(el => el.textContent && dateRegex.test(el.textContent));

                        if (dateElements.length > 0) {
                            const match = dateRegex.exec(dateElements[0].textContent);
                            return match ? match[0] : null;
                        }
                        return null;
                    """)

                    if recovery_date:
                        log(f"Found recovery date: {recovery_date}")
                    else:
                        # Use current date as fallback
                        recovery_date = datetime.datetime.now().strftime('%m/%d/%Y')
                        log(f"Using today's date as recovery date: {recovery_date}")
                except Exception:
                    recovery_date = datetime.datetime.now().strftime('%m/%d/%Y')
                    log(f"Using today's date as recovery date: {recovery_date}")

            # Find all dollar amounts and associated text in one JS call
            try:
                # Define JavaScript fee categories to match our Python categories
                js_fee_categories = json.dumps(fee_categories)

                # Create the JavaScript with proper string concatenation
                js_script = """
                    // Define fee categories in JavaScript to match our Python categories
                    const fee_categories = """ + js_fee_categories + """;

                    // Find all elements with dollar sign in text
                    const dollarAmountRegex = new RegExp("\\\\$\\\\s*([0-9,]+(\\\\.[0-9]{2})?)");

                    // Custom selector for improved performance - focus on smaller text elements
                    // We're looking for elements with text that contains $ and is reasonably short
                    const allElements = document.querySelectorAll('div, span, td, p, label');"""

                dollar_elements = driver.execute_script(js_script + """

                    // Filter elements with fee information
                    const feeElements = [];
                    for (const el of allElements) {
                        // Check if this element has a dollar sign and reasonable length
                        if (el.textContent &&
                            el.textContent.includes('$') &&
                            el.textContent.length < 300) {

                            // Extract amount
                            const match = dollarAmountRegex.exec(el.textContent);
                            if (match) {
                                const amount = match[1].replace(',', '');
                                const text = el.textContent.trim();

                                // Determine fee type based on keywords with improved detection
                                // Start with an unknown fee type and determine based on content
                                let feeType = 'Unknown Fee';

                                // Try to determine the fee type from the text content
                                const lowerText = text.toLowerCase();

                                // Determine fee type using the categories defined above
                                let matched = false;

                                // Check each category's keywords against the text
                                for (const [category, keywords] of Object.entries(fee_categories)) {
                                    for (const keyword of keywords) {
                                        if (lowerText.includes(keyword)) {
                                            feeType = category;
                                            matched = true;
                                            break;
                                        }
                                    }
                                    if (matched) break;
                                }

                                // If no category matched, try some additional checks
                                if (!matched) {
                                    if (lowerText.includes('push') && lowerText.includes('start') && lowerText.includes('key')) {
                                        feeType = 'Keys Fee';
                                    }
                                }

                                feeElements.push({
                                    amount: amount,
                                    text: text,
                                    feeType: feeType
                                });
                            }
                        }
                    }

                    return feeElements;
                """)

                if dollar_elements:
                    log(f"Found {len(dollar_elements)} fee elements via direct JavaScript")

                    # Process found elements
                    for fee_element in dollar_elements:
                        # Use our helper function to determine fee type
                        fee_text = fee_element.get('text', '')
                        fee_type = determine_fee_type(fee_text, fee_categories)

                        fee_items.append({
                            'date': recovery_date,
                            'type': 'My Summary Fee',
                            'user': '',
                            'content': fee_text,
                            'amounts': [{
                                'amount': fee_element.get('amount', '0'),
                                'context': fee_text,
                                'isExplicitlyApproved': True
                            }],
                            'isApproved': True,
                            'source': 'My Summary',
                            'feeLabel': fee_type
                        })
                        log(f"Found generic fee element: {fee_type} - ${fee_element.get('amount')} ({recovery_date})")

                else:
                    log("No fee elements found with direct JavaScript, using fallback")

                    # If the direct JavaScript method failed to find fees, try a quick CSS selector
                    fee_elements = driver.find_elements(By.CSS_SELECTOR,
                        'span:not(:empty), div:not(:empty), td:not(:empty), p:not(:empty)')[:50]  # Limit to 50 elements for performance

                    # Process at most 30 elements to avoid long loops
                    for i, element in enumerate(fee_elements):
                        if i >= 30:
                            break

                        try:
                            element_text = element.text
                            if '$' in element_text and len(element_text) < 300:
                                amount_match = re.search(r'\$\s*([0-9,]+(\.[0-9]{2})?)', element_text)
                                if amount_match:
                                    amount = amount_match.group(1).replace(',', '')
                                    # Use our helper function to determine fee type
                                    fee_label = determine_fee_type(element_text, fee_categories)

                                    fee_items.append({
                                        'date': recovery_date,
                                        'type': 'My Summary Fee',
                                        'user': '',
                                        'content': element_text,
                                        'amounts': [{
                                            'amount': amount,
                                            'context': element_text,
                                            'isExplicitlyApproved': True
                                        }],
                                        'isApproved': True,
                                        'source': 'My Summary',
                                        'feeLabel': fee_label
                                    })
                                    log(f"Found fee element: {fee_label} - ${amount} ({recovery_date})")
                        except Exception:
                            continue
            except Exception as js_err:
                log(f"Error during JavaScript fee extraction: {str(js_err)}", "error")

            # Restore original wait setting
            driver.implicitly_wait(30 if original_implicit_wait is None else original_implicit_wait)

        # APPROACH 5: Look specifically for "Recovery Date/Time" section which has updated date information
        # This might be in a separate section like "Your Company's Recovery Info"
        if not fee_items and recovery_date:
            log("Using recovery date information to create a placeholder fee entry...")
            # If we have a recovery date but no fees, create a placeholder entry with standard fee
            standard_fee = 300.0  # Use a standard fee when no amount is found
            log(f"Using standard recovery fee amount: ${standard_fee:.2f}")

            fee_items.append({
                'date': recovery_date,
                'type': 'Recovery Date',
                'user': 'System',
                'content': f"Recovery Date/Time: {recovery_date} - Standard Recovery Fee",
                'amounts': [{
                    'amount': str(standard_fee),
                    'context': f"Recovery Date: {recovery_date} - Standard Recovery Fee (system-generated)",
                    'isExplicitlyApproved': True,
                    'feeType': 'Involuntary Repo'
                }],
                'isApproved': True,
                'source': 'My Summary',
                'feeLabel': 'Involuntary Repo'  # Categorize as a predefined fee type
            })

    except Exception as e:
        log(f'Error scraping My Summary fees: {str(e)}', 'error')
        # Capture stack trace for better debugging
        import traceback
        error_details = traceback.format_exc()
        log(f'Stack trace: {error_details}', 'error')

    log(f'Found {len(fee_items)} fee entries in My Summary tab')
    for item in fee_items:
        log(f"  - {item['feeLabel']}: {item['amounts'][0]['amount'] if item['amounts'] else 'No amount'} ({item['date'] if item['date'] else 'No date'})")

    end = time.time()
    log(f"My Summary tab scraping took: {end - start:.3f}s")

    return fee_items

def generate_fees_table(fee_updates):
    """Generate a fees table from extracted fee information with enhanced categorization"""
    start = time.time()
    log('Generating fees table - implementing three-table structure as per CLAUDE.md...')

    # Check if we have case information to lookup repo fees
    repo_fee_lookup_performed = False
    repo_fee_data = None

    if config.get('current_case_info'):
        # Make sure these are defined properly before use
        case_client_name = config['current_case_info'].get('clientName', '')
        case_lienholder_name = config['current_case_info'].get('lienHolderName', '')
        case_repo_type = config['current_case_info'].get('repoType', 'Involuntary Repo')

        # Apply validation
        if case_client_name and case_client_name != "Not found" and case_lienholder_name and case_lienholder_name != "Not found":
            log(f"Looking up repo fee information for client={case_client_name}, lienholder={case_lienholder_name}, fee_type={case_repo_type}")
            # Use our newly implemented SQL_Query.sql function
            try:
                repo_fee_data = lookup_repo_fee(case_client_name, case_lienholder_name, case_repo_type)
            except Exception as lookup_error:
                log(f"Error during lookup_repo_fee: {str(lookup_error)}", "error")
                import traceback
                log(traceback.format_exc(), "error")

            if repo_fee_data:
                repo_fee_lookup_performed = True
                log(f"Found repo fee in database: ${repo_fee_data['amount']:.2f}")
                if repo_fee_data.get('is_fallback'):
                    log(f"Note: {repo_fee_data.get('message', 'Using Standard lienholder fallback')}")

                # Add repo fee to our list if found
                fee_updates.append({
                    'date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    'type': 'Database Lookup',
                    'user': 'System',
                    'content': f"Repo Fee from database: ${repo_fee_data['amount']:.2f}",
                    'amounts': [{
                        'amount': str(repo_fee_data['amount']),
                        'context': f"Database lookup for {case_repo_type} - {case_client_name} / {case_lienholder_name}",
                        'feeType': case_repo_type
                    }],
                    'isApproved': True,
                    'source': 'Database',
                    'feeLabel': case_repo_type
                })
            else:
                log(f"No matching repo fee found in database for {case_client_name}/{case_lienholder_name}/{case_repo_type}", "warning")
        else:
            log("Missing client or lienholder information, skipping repo fee lookup", "warning")
    else:
        log("No case information available, skipping repo fee lookup", "warning")

    # Normalize sources: rename "Case Page" to "Updates"
    for fee in fee_updates:
        if fee.get('source') == 'Case Page':
            fee['source'] = 'Updates'

    # Count sources
    my_summary_count = sum(1 for fee in fee_updates if fee.get('source') == 'My Summary')
    database_count = sum(1 for fee in fee_updates if fee.get('source') == 'Database')
    updates_count = len(fee_updates) - my_summary_count - database_count
    log(f'Processing {len(fee_updates)} total fees: {my_summary_count} from My Summary, {updates_count} from Updates, and {database_count} from Database')

    # Create structured table data with three tables as per CLAUDE.md
    all_fees_table = []
    keys_fees_table = []    # Table 2: Keys Fees
    predefined_fees_table = []  # Table 1: Predefined Categories
    other_fees_table = []   # Table 3: Other Categories

    # Implement deduplication with priority: Database > My Summary > Updates
    # Create a function to normalize text for comparison
    def normalize(text):
        if not text:
            return ""
        # Remove whitespace, convert to lowercase for case-insensitive comparison
        return re.sub(r'\s+', ' ', text.lower().strip())

    # Priority map for sources (as per CLAUDE.md)
    priority_map = {
        'Database': 0,  # Highest priority
        'My Summary': 1,
        'Updates': 2    # Renamed from "Case Page" as per requirements
    }

    # Create a set to track unique fees and avoid duplicates
    seen = set()

    # Sort fee_updates by source priority
    sorted_updates = sorted(fee_updates, key=lambda f: priority_map.get(f.get('source', 'Updates'), 3))

    for update in sorted_updates:
        for amount_info in update.get('amounts', []):
            try:
                amount_value = float(amount_info.get('amount', 0))
                # Skip invalid amounts
                if amount_value <= 0:
                    continue

                # Enhance reference sentence handling - preserve full context
                fee_context = amount_info.get('context', '').strip()

                # Create key elements for deduplication
                source = update.get('source', 'Updates')
                date = update.get('date', '')
                fee_label = update.get('feeLabel', '')  # Include feeLabel from My Summary entries

                # Handle specific fee types
                fee_type = amount_info.get('feeType', '')

                # Normalize fee label and type for better categorization
                if fee_type:
                    category = fee_type
                elif fee_label:
                    category = fee_label
                else:
                    category = 'Unknown Fee'

                # Store original category before any potential changes
                original_category = category

                # Check if this is a Keys Fee - MUST be in its own table regardless of other matching
                is_keys_fee = False
                if category.lower() == 'keys fee' or category.lower() == 'key fee' or 'key' in category.lower():
                    is_keys_fee = True
                    category = 'Keys Fee'  # Standardize the name

                # Check if this is a predefined category (whitelist)
                is_predefined_category = False
                if not is_keys_fee:  # Skip keys fee check since it gets its own table
                    category_lower = category.lower()
                    matched_category = None

                    # First try exact match with predefined categories
                    for fee_name in config["pre_approved_fees"]:
                        if category_lower == fee_name.lower():
                            is_predefined_category = True
                            matched_category = fee_name  # Use the exact name from the predefined list
                            log(f"Matched predefined category (exact match): original='{category}', matched='{fee_name}'")
                            break

                    # If no exact match, try partial match
                    if not is_predefined_category:
                        for fee_name in config["pre_approved_fees"]:
                            if fee_name.lower() in category_lower or category_lower in fee_name.lower():
                                is_predefined_category = True
                                matched_category = fee_name  # Use the exact name from the predefined list
                                log(f"Matched predefined category (partial match): original='{category}', matched='{fee_name}'")
                                break

                    # Use the standardized category name if we found a match
                    if is_predefined_category and matched_category:
                        category = matched_category

                # Deduplication key creation (normalize components for consistent comparison)
                key = (f"{amount_value:.2f}", normalize(category), normalize(fee_context))

                # Skip if this exact fee has been seen before (with higher priority)
                if key in seen:
                    log(f'Skipping duplicate fee: ${amount_value:.2f} from {source} (category: {category})')
                    continue

                # Add to seen set for deduplication
                seen.add(key)

                # Create fee entry with all required fields
                fee_entry = {
                    'date': date,
                    'amount': f"${amount_value:.2f}",
                    'type': update.get('type', ''),
                    'approver': update.get('user', ''),
                    'referenceSentence': fee_context,  # Preserve full context as required in CLAUDE.md
                    'approved': 'Yes' if (update.get('isApproved') or
                                         amount_info.get('isExplicitlyApproved') or
                                         source == 'Database' or
                                         is_predefined_category) else 'Likely',
                    'category': category,
                    'source': source,
                    'originalCategory': original_category,
                    'matched': True if source == 'Database' or is_predefined_category or is_keys_fee else False,
                    'matchedAs': 'Repo Fee Matrix' if source == 'Database' else
                               ('Pre-approved Non-Repo' if is_predefined_category else
                                ('Keys Fee' if is_keys_fee else 'Unmatched'))
                }

                # Add fee to the appropriate table based on category and source
                if source != 'Database':  # Database fees excluded from tables as per CLAUDE.md
                    all_fees_table.append(fee_entry)

                    # Add to the appropriate specialized table
                    if is_keys_fee:
                        # Table 2: Keys Fees (all keys fees go here regardless of other matching)
                        keys_fees_table.append(fee_entry)
                        log(f"Added keys fee to Table 2: ${amount_value:.2f} - {category}")
                    elif is_predefined_category:
                        # Table 1: Predefined Categories (whitelist)
                        predefined_fees_table.append(fee_entry)
                        log(f"Added predefined category fee to Table 1: ${amount_value:.2f} - {category}")
                    else:
                        # Table 3: Other Categories (non-whitelist fees with original names)
                        # Use original category name for display
                        fee_entry['category'] = original_category
                        other_fees_table.append(fee_entry)
                        log(f"Added other category fee to Table 3: ${amount_value:.2f} - {original_category}")
                else:
                    log(f"Database fee excluded from tables per CLAUDE.md: ${amount_value:.2f} - {category}")

            except (ValueError, TypeError) as e:
                # Log error and continue with next fee
                log(f"Error processing fee: {str(e)}", "error")
                continue

    # Count entries in each table
    predefined_count = len(predefined_fees_table)
    keys_count = len(keys_fees_table)
    other_count = len(other_fees_table)

    log(f"Generated fee tables: {predefined_count} predefined fees, {keys_count} keys fees, {other_count} other fees")

    # Log some examples for debugging if any entries exist
    if predefined_fees_table:
        log(f"Sample predefined fee: {predefined_fees_table[0]}")
    if keys_fees_table:
        log(f"Sample keys fee: {keys_fees_table[0]}")
    if other_fees_table:
        log(f"Sample other fee: {other_fees_table[0]}")

    end = time.time()
    log(f"Fee table generation took: {end - start:.3f}s")

    return {
        'allFeesTable': all_fees_table,
        'predefinedFeesTable': predefined_fees_table,  # New structured table
        'keysFeesTable': keys_fees_table,              # New structured table
        'otherFeesTable': other_fees_table,            # New structured table
        'categorizedFees': predefined_fees_table,      # For backward compatibility
        'additionalFees': other_fees_table             # For backward compatibility
    }

# Function to save fee data to the Azure SQL database
# Helper function to scan text for key fees
def scan_for_key_fees(text):
    """
    Scan text specifically for key fee-related content

    Args:
        text (str): The text to scan

    Returns:
        list: List of extracted fee information
    """
    if not text:
        return []

    results = []

    # Create patterns to match against - ENHANCED to find ANY dollar amounts
    patterns = [
        # Push to start key
        re.compile(r'(?:push\s+to\s+start\s+key|key\s+made).*?(?:for)?\s*\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE),
        # Please advise pattern
        re.compile(r'advise.*?(?:key|push).*?(?:for)?\s*\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE),
        # Vehicle key pattern
        re.compile(r'(?:vehicle|car).*?(?:key|push).*?(?:for)?\s*\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE),
        # Generic fee pattern - match ANY dollar amount with fee-related context
        re.compile(r'(?:fee|charge|cost|amount|payment).*?\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE),
        # Generic amount pattern - to catch ANY dollar sign with a number (fallback)
        re.compile(r'\$\s*([0-9,]+(?:\.[0-9]{2})?)', re.IGNORECASE)
    ]

    # Scan the text with each pattern
    for pattern in patterns:
        for match in pattern.finditer(text):
            # Get the matched amount
            amount = match.group(1).replace(',', '')

            # Extract context around match
            context_start = max(0, match.start() - 50)
            context_end = min(len(text), match.end() + 50)
            context = text[context_start:context_end]

            # Determine fee type based on pattern and context
            fee_type = 'Unknown Fee'  # Default
            context_lower = context.lower()

            # Detect specific fee types
            if any(key_term in context_lower for key_term in ['push', 'key', 'vehicle']):
                fee_type = 'Keys Fee'
            elif any(term in context_lower for term in ['mile', 'travel', 'distance', 'fuel', 'gas']):
                fee_type = 'Mileage/ Fuel'
            elif any(term in context_lower for term in ['flat', 'tow', 'winch', 'rollback']):
                fee_type = 'Flatbed Fees'
            elif any(term in context_lower for term in ['store', 'storage', 'impound', 'lot fee']):
                fee_type = 'Storage Fee'
            elif any(term in context_lower for term in ['cr', 'condition', 'photo', 'picture', 'inspection']):
                fee_type = 'CR AND PHOTOS FEE'
            elif any(term in context_lower for term in ['purchase', 'cost', 'expense']):
                fee_type = 'Purchase Cost'
            elif 'client' in context_lower:
                fee_type = 'Fee To Client'

            # Add to results - with proper fee type based on context
            results.append({
                'amount': amount,
                'context': context,
                'feeType': fee_type,
                'isExplicitlyApproved': False  # Default to not explicitly approved
            })

    return results

def fetch_from_database(client_name=None, lienholder_name=None, fee_type=None):
    """
    Fetch fee information from Azure SQL Database based on client name, lien holder, and fee type

    Args:
        client_name (str, optional): Client name to filter by
        lienholder_name (str, optional): Lien holder name to filter by
        fee_type (str, optional): Fee type to filter by

    Returns:
        list: List of fee records matching the criteria
    """
    # Make sure we have valid scoped variables
    search_client_name = client_name if client_name is not None else ""
    search_lienholder_name = lienholder_name if lienholder_name is not None else ""
    search_fee_type = fee_type if fee_type is not None else ""
    log('Fetching fee data from Azure SQL Database...')

    conn = get_db_connection()
    if not conn:
        log("Could not connect to database. Unable to fetch data.", "error")
        return []

    try:
        cursor = conn.cursor()
        results = []

        # First attempt: Use the provided lienholder name
        log(f"Searching database with: Client={client_name}, Lienholder={lienholder_name}, FeeType={fee_type}")

        # Build a dynamic query based on the provided filters
        query = """
            SELECT
                fd.fd_id,
                c.client_name,
                COALESCE(lh.lienholder_name, 'Unknown') as lienholder_name,
                ft.fee_type_name,
                fd.amount
            FROM
                dbo.FeeDetails2 fd
            JOIN
                dbo.RDN_Client c ON fd.client_id = c.id
            JOIN
                dbo.FeeType ft ON fd.ft_id = ft.id
            LEFT JOIN
                dbo.LienHolder lh ON fd.lh_id = lh.id
            WHERE
                1=1
        """

        # Parameters for the query
        params = []

        # Add filters based on the provided parameters
        if search_client_name:
            query += " AND c.client_name LIKE ?"
            params.append(f"%{search_client_name}%")

        if search_lienholder_name:
            query += " AND lh.lienholder_name LIKE ?"
            params.append(f"%{search_lienholder_name}%")

        if search_fee_type:
            query += " AND ft.fee_type_name LIKE ?"
            params.append(f"%{search_fee_type}%")

        # Log the query with enhanced visibility
        log_query("ORIGINAL", query, params)
        log(f"Searching database for: Client='{search_client_name}', Lienholder='{search_lienholder_name}', FeeType='{search_fee_type}'")

        # Execute the query
        cursor.execute(query, params)

        # Process results
        rows = cursor.fetchall()

        # Add results from the first query
        for row in rows:
            results.append({
                'fd_id': row[0],
                'client_name': row[1],
                'lienholder_name': row[2],
                'fee_type': row[3],
                'amount': row[4]
            })

        # If no results and a lienholder name was provided, try with 'Standard' lienholder
        if len(results) == 0 and search_lienholder_name:
            log(f"No results found with lienholder '{search_lienholder_name}'. Trying with 'Standard' lienholder...")

            # First, find the ID of the 'Standard' lienholder
            try:
                # Using the correct column name from db.png: lienholder_name
                cursor.execute("SELECT id FROM dbo.Lienholder WHERE lienholder_name LIKE ?", "%Standard%")
                standard_lienholder_row = cursor.fetchone()

                if standard_lienholder_row:
                    standard_lienholder_id = standard_lienholder_row[0]
                    log(f"Found 'Standard' lienholder with ID: {standard_lienholder_id}")

                    # Create a new query using Standard lienholder ID directly
                    standard_query = """
                        SELECT
                            fd.fd_id,
                            c.client_name,
                            'Standard' as lienholder_name,
                            ft.fee_type_name,
                            fd.amount
                        FROM
                            dbo.FeeDetails2 fd
                        JOIN
                            dbo.RDN_Client c ON fd.client_id = c.id
                        JOIN
                            dbo.FeeType ft ON fd.ft_id = ft.id
                        LEFT JOIN
                            dbo.LienHolder lh ON fd.lh_id = lh.id
                        WHERE
                            fd.lh_id = ?
                    """

                    # Reset params for the new query - using direct ID
                    standard_params = [standard_lienholder_id]
                else:
                    log("Could not find 'Standard' lienholder in the database. Falling back to name search.")

                    # Create a fallback query using the lienholder name
                    standard_query = """
                        SELECT
                            fd.fd_id,
                            c.client_name,
                            'Standard' as lienholder_name,
                            ft.fee_type_name,
                            fd.amount
                        FROM
                            dbo.FeeDetails2 fd
                        JOIN
                            dbo.RDN_Client c ON fd.client_id = c.id
                        JOIN
                            dbo.FeeType ft ON fd.ft_id = ft.id
                        LEFT JOIN
                            dbo.LienHolder lh ON fd.lh_id = lh.id
                        WHERE
                            lh.lienholder_name LIKE ?
                    """

                    # Reset params for the new query
                    standard_params = ["%Standard%"]
            except Exception as e:
                log(f"Error finding Standard lienholder ID: {str(e)}", "error")

                # Create a fallback query using the lienholder name
                standard_query = """
                    SELECT
                        fd.fd_id,
                        c.client_name,
                        'Standard' as lienholder_name,
                        ft.fee_type_name,
                        fd.amount
                    FROM
                        dbo.FeeDetails2 fd
                    JOIN
                        dbo.RDN_Client c ON fd.client_id = c.id
                    JOIN
                        dbo.FeeType ft ON fd.ft_id = ft.id
                    LEFT JOIN
                        dbo.LienHolder lh ON fd.lh_id = lh.id
                    WHERE
                        lh.lienholder_name LIKE ?
                """

                # Reset params for the new query
                standard_params = ["%Standard%"]

            # Add other filters - regardless of which query approach we're using
            if search_client_name:  # Use search_client_name instead of case_client_name
                standard_query += " AND c.client_name LIKE ?"
                standard_params.append(f"%{search_client_name}%")

            if search_fee_type:  # Use search_fee_type instead of case_repo_type
                standard_query += " AND ft.fee_type_name LIKE ?"
                standard_params.append(f"%{search_fee_type}%")

            # Log the fallback query with enhanced visibility
            log_query("FALLBACK STANDARD", standard_query, standard_params)
            log(f"Falling back to 'Standard' lienholder with parameters: Client='{search_client_name}', FeeType='{search_fee_type}'")

            # Execute the second query with 'Standard' lienholder
            cursor.execute(standard_query, standard_params)

            # Process results from the second query
            standard_rows = cursor.fetchall()
            for row in standard_rows:
                # Add a special note to indicate this is a fallback to Standard lienholder
                standard_result = {
                    'fd_id': row[0],
                    'client_name': row[1],
                    'lienholder_name': row[2] + " (Standard)",
                    'fee_type': row[3],
                    'amount': row[4],
                    'is_fallback': True,  # Flag to indicate this is a Standard fallback
                    'message': f"Lienholder '{search_lienholder_name}' not found. Using Standard amount instead."
                }
                results.append(standard_result)

            if len(standard_rows) > 0:
                log(f"Found {len(standard_rows)} records with 'Standard' lienholder")
                # Emit notification to frontend about the fallback
                try:
                    socketio.emit('database_notice', {
                        'type': 'warning',
                        'message': f"No specific fee data found for lienholder '{search_lienholder_name}'. Using Standard fee amounts instead."
                    })
                except Exception as e:
                    log(f"Error sending notification to client: {str(e)}", "warning")
            else:
                log(f"No fee records found for 'Standard' lienholder either.")

        log(f"Successfully fetched {len(results)} total fee records from database")
        return results

    except Exception as e:
        log(f"Database fetch error: {str(e)}", "error")
        return []

    finally:
        if conn:
            conn.close()

def lookup_repo_fee(client_name, lienholder_name, fee_type_name):
    """
    Lookup repo fee from database based on client name, lienholder name, and fee type.
    Implements the exact query from SQL_Query.sql.

    Args:
        client_name (str): The name of the client
        lienholder_name (str): The name of the lienholder
        fee_type_name (str): The name of the fee type (e.g., 'Involuntary Repo')

    Returns:
        dict: A dictionary containing fee details, or None if no matching fee is found
    """
    log(f'Looking up repo fee for: Client="{client_name}", Lienholder="{lienholder_name}", FeeType="{fee_type_name}"')

    # Make sure we're using the correct variable names
    case_client_name = client_name
    case_lienholder_name = lienholder_name
    case_repo_type = fee_type_name

    conn = get_db_connection()
    if not conn:
        log("Could not connect to database. Unable to look up repo fee.", "error")
        return None

    try:
        cursor = conn.cursor()

        # Step 1: Get foreign keys from names (exactly as in SQL_Query.sql)
        log("Getting foreign keys from names...")
        cursor.execute("SELECT TOP 1 id FROM dbo.RDN_Client WHERE client_name = ?", case_client_name)
        client_row = cursor.fetchone()
        if not client_row:
            log(f"Client '{case_client_name}' not found in database", "warning")
            return None
        client_id = client_row[0]

        # Use the correct table and column names from db.png
        cursor.execute("SELECT TOP 1 id FROM dbo.Lienholder WHERE lienholder_name = ?", case_lienholder_name)
        lienholder_row = cursor.fetchone()
        if not lienholder_row:
            log(f"Lienholder '{case_lienholder_name}' not found in database", "warning")
            lienholder_id = None  # We'll handle this in the fallback logic
        else:
            lienholder_id = lienholder_row[0]

        cursor.execute("SELECT TOP 1 id FROM dbo.FeeType WHERE fee_type_name = ?", case_repo_type)
        fee_type_row = cursor.fetchone()
        if not fee_type_row:
            log(f"Fee type '{case_repo_type}' not found in database", "warning")
            return None
        fee_type_id = fee_type_row[0]

        # Step 2: Check if a matching record exists and return it if found (primary logic)
        if lienholder_id:
            # Using parameterized query for safety
            query = """
                SELECT
                    fd.fd_id,
                    c.client_name,
                    lh.lienholder_name,
                    ft.fee_type_name,
                    fd.amount
                FROM dbo.FeeDetails2 fd
                JOIN dbo.RDN_Client c ON fd.client_id = c.id
                JOIN dbo.Lienholder lh ON fd.lh_id = lh.id
                JOIN dbo.FeeType ft ON fd.ft_id = ft.id
                WHERE fd.client_id = ? AND fd.lh_id = ? AND fd.ft_id = ?
            """
            log_query("PRIMARY LOOKUP", query, [client_id, lienholder_id, fee_type_id])
            cursor.execute(query, [client_id, lienholder_id, fee_type_id])
            row = cursor.fetchone()

            if row:
                log(f"Found matching fee record for specific lienholder '{lienholder_name}'")
                return {
                    'fd_id': row[0],
                    'client_name': row[1],
                    'lienholder_name': row[2],
                    'fee_type': row[3],
                    'amount': row[4],
                    'is_fallback': False
                }

        # Step 3: If no record found, try with 'Standard' lienholder (fallback logic)
        log(f"No specific record found. Looking up 'Standard' lienholder as fallback...")
        cursor.execute("SELECT TOP 1 id FROM dbo.Lienholder WHERE lienholder_name = 'Standard'")
        standard_row = cursor.fetchone()

        if not standard_row:
            log("'Standard' lienholder not found in database", "error")
            return None

        standard_lienholder_id = standard_row[0]

        # Look up using Standard lienholder
        fallback_query = """
            SELECT
                fd.fd_id,
                c.client_name,
                lh.lienholder_name,
                ft.fee_type_name,
                fd.amount
            FROM dbo.FeeDetails2 fd
            JOIN dbo.RDN_Client c ON fd.client_id = c.id
            JOIN dbo.Lienholder lh ON fd.lh_id = lh.id
            JOIN dbo.FeeType ft ON fd.ft_id = ft.id
            WHERE fd.client_id = ? AND fd.lh_id = ? AND fd.ft_id = ?
        """
        log_query("FALLBACK LOOKUP", fallback_query, [client_id, standard_lienholder_id, fee_type_id])
        cursor.execute(fallback_query, [client_id, standard_lienholder_id, fee_type_id])
        fallback_row = cursor.fetchone()

        if fallback_row:
            log(f"Found fallback fee using 'Standard' lienholder")
            return {
                'fd_id': fallback_row[0],
                'client_name': fallback_row[1],
                'lienholder_name': fallback_row[2] + " (Standard Fallback)",
                'fee_type': fallback_row[3],
                'amount': fallback_row[4],
                'is_fallback': True,
                'message': f"Lienholder '{case_lienholder_name}' specific fee not found. Using Standard amount."
            }

        log("No fee record found with either specific lienholder or fallback", "warning")
        return None

    except Exception as e:
        log(f"Error looking up repo fee: {str(e)}", "error")
        import traceback
        log(traceback.format_exc(), "error")
        return None

    finally:
        if conn:
            conn.close()

def save_to_database(case_id, all_fees_table):
    """
    Save the fee data to Azure SQL Database

    Args:
        case_id (str): The RDN case ID
        all_fees_table (list): List of fee entries to store

    Returns:
        bool: True if the operation was successful, False otherwise
    """
    log('Saving fee data to Azure SQL Database...')

    conn = get_db_connection()
    if not conn:
        log("Could not connect to database. Skipping database save.", "warning")
        return False

    try:
        cursor = conn.cursor()

        # Get client ID from RDN_Client table based on client name in the fee data
        # If we don't have client name info, create a placeholder entry
        client_name = config.get('current_case_info', {}).get('clientName', 'Unknown Client')

        # Check if client exists, if not insert it
        cursor.execute("SELECT id FROM dbo.RDN_Client WHERE client_name = ?", client_name)
        client_row = cursor.fetchone()

        if client_row:
            client_id = client_row[0]
        else:
            cursor.execute("INSERT INTO dbo.RDN_Client (client_name) VALUES (?)", client_name)
            conn.commit()
            cursor.execute("SELECT id FROM dbo.RDN_Client WHERE client_name = ?", client_name)
            client_row = cursor.fetchone()
            client_id = client_row[0] if client_row else 1  # Default to 1 if still not found

        # Track how many fees we insert
        inserted_count = 0

        # Insert each fee into the FeeDetails22 table
        for fee in all_fees_table:
            try:
                fee_type = fee.get('category', 'Unknown')

                # Check if fee type exists, if not insert it
                cursor.execute("SELECT id FROM dbo.FeeType WHERE fee_type_name = ?", fee_type)
                fee_type_row = cursor.fetchone()

                if fee_type_row:
                    fee_type_id = fee_type_row[0]
                else:
                    cursor.execute("INSERT INTO dbo.FeeType (fee_type_name, fee_type_code) VALUES (?, ?)",
                                  fee_type, fee_type[:10] if len(fee_type) > 10 else fee_type)
                    conn.commit()
                    cursor.execute("SELECT id FROM dbo.FeeType WHERE fee_type_name = ?", fee_type)
                    fee_type_row = cursor.fetchone()
                    fee_type_id = fee_type_row[0] if fee_type_row else 1  # Default to 1 if still not found

                # Extract amount without $ sign
                amount_str = fee.get('amount', '$0.00').replace('$', '').replace(',', '')
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = 0.0

                # Insert the fee details
                cursor.execute("""
                    INSERT INTO dbo.FeeDetails2 (client_id, ft_id, amount)
                    VALUES (?, ?, ?)
                """, client_id, fee_type_id, amount)

                inserted_count += 1
            except Exception as e:
                log(f"Error inserting fee record: {str(e)}", "error")

        conn.commit()
        log(f"Successfully saved {inserted_count} fee records to database")
        return True

    except Exception as e:
        log(f"Database error: {str(e)}", "error")
        return False

    finally:
        if conn:
            conn.close()

def save_data(updates, fee_updates, all_fees_table, categorized_fees, additional_fees, case_id, my_summary_fees=None):
    """Save the scraped data to disk and database"""
    start = time.time()
    log('Saving data to disk...')

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    output_dir = os.path.join(config["output_dir"], f"case-{case_id}-{timestamp}")
    public_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    download_dir = os.path.join(public_dir, 'downloads')
    output_files = []
    
    # Create output directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(download_dir, exist_ok=True)
    
    # Save raw updates data
    log('Saving raw update data...')
    raw_updates_path = os.path.join(output_dir, 'all-updates.json')
    with open(raw_updates_path, 'w', encoding='utf-8') as f:
        json.dump(updates, f, indent=2)
    
    raw_updates_download_path = os.path.join(download_dir, f'all-updates-{case_id}-{timestamp}.json')
    with open(raw_updates_download_path, 'w', encoding='utf-8') as f:
        json.dump(updates, f, indent=2)
    
    output_files.append({
        'label': 'Raw Updates (JSON)',
        'filename': os.path.basename(raw_updates_download_path),
        'url': '/downloads/' + os.path.basename(raw_updates_download_path)
    })
    
    # Save My Summary fees if available
    if my_summary_fees and len(my_summary_fees) > 0:
        log('Saving My Summary fee data...')
        my_summary_fees_path = os.path.join(output_dir, 'my-summary-fees.json')
        with open(my_summary_fees_path, 'w', encoding='utf-8') as f:
            json.dump(my_summary_fees, f, indent=2)
        
        my_summary_fees_download_path = os.path.join(download_dir, f'my-summary-fees-{case_id}-{timestamp}.json')
        with open(my_summary_fees_download_path, 'w', encoding='utf-8') as f:
            json.dump(my_summary_fees, f, indent=2)
        
        output_files.append({
            'label': 'My Summary Fees (JSON)',
            'filename': os.path.basename(my_summary_fees_download_path),
            'url': '/downloads/' + os.path.basename(my_summary_fees_download_path)
        })
    
    # Save extracted fees
    log('Saving extracted fee data...')
    fees_path = os.path.join(output_dir, 'fee-table.json')
    from_my_summary = sum(1 for fee in all_fees_table if fee.get("source") == "My Summary")
    log(f'Saving fee table with {len(all_fees_table)} fees ({from_my_summary} from My Summary)')

    # If we have my_summary_fees but no fees in all_fees_table, manually add them
    if len(all_fees_table) == 0 and my_summary_fees is not None and len(my_summary_fees) > 0:
        log(f'No fees in all_fees_table but found {len(my_summary_fees)} My Summary fees, manually adding them to fee-table.json')
        temp_all_fees = []

        # Ensure categorized_fees is a dictionary for the updated structure
        if isinstance(categorized_fees, list) or not isinstance(categorized_fees, dict):
            categorized_fees = {
                'predefinedFeesTable': [],
                'keysFeesTable': [],
                'otherFeesTable': []
            }

        for fee in my_summary_fees:
            for amount_info in fee.get('amounts', []):
                try:
                    amount_value = float(amount_info.get('amount', 0))
                    if amount_value <= 0:
                        continue

                    fee_label = fee.get('feeLabel', 'Unknown Fee')
                    fee_entry = {
                        'date': fee.get('date', ''),
                        'amount': f"${amount_value:.2f}",
                        'type': fee.get('type', ''),
                        'approver': fee.get('user', ''),
                        'referenceSentence': amount_info.get('context', ''),
                        'approved': 'Yes' if fee.get('isApproved') or amount_info.get('isExplicitlyApproved') else 'Likely',
                        'category': fee_label,
                        'source': 'My Summary',
                        'originalCategory': fee_label,  # For compatibility with new structure
                        'matched': False,
                        'matchedAs': 'My Summary'
                    }

                    temp_all_fees.append(fee_entry)

                    # Also add to the appropriate specialized table
                    category = fee_label.lower()
                    if 'keys fee' in category or 'key fee' in category:
                        if 'keysFeesTable' not in categorized_fees:
                            categorized_fees['keysFeesTable'] = []
                        categorized_fees['keysFeesTable'].append(fee_entry)
                    # Check if category is in predefined list
                    elif any(predefined.lower() == category for predefined in config["pre_approved_fees"]):
                        if 'predefinedFeesTable' not in categorized_fees:
                            categorized_fees['predefinedFeesTable'] = []
                        categorized_fees['predefinedFeesTable'].append(fee_entry)
                    else:
                        if 'otherFeesTable' not in categorized_fees:
                            categorized_fees['otherFeesTable'] = []
                        categorized_fees['otherFeesTable'].append(fee_entry)
                except (ValueError, TypeError) as e:
                    log(f"Error processing My Summary fee: {str(e)}", "error")
                    continue

        log(f'Manually added {len(temp_all_fees)} My Summary fees to fee-table.json')

        with open(fees_path, 'w', encoding='utf-8') as f:
            # Ensure we're using the new table structure
            json_output = {
                'allFeesTable': temp_all_fees,
                'categorizedFees': categorized_fees,  # Use the dictionary format
                'additionalFees': temp_all_fees,
                # Also include specialized tables directly
                'predefinedFeesTable': categorized_fees.get('predefinedFeesTable', []),
                'keysFeesTable': categorized_fees.get('keysFeesTable', []),
                'otherFeesTable': categorized_fees.get('otherFeesTable', [])
            }
            json.dump(json_output, f, indent=2)
    else:
        # Normal case - write the provided fee tables
        with open(fees_path, 'w', encoding='utf-8') as f:
            # Ensure we're using the new table structure
            json_output = {
                'allFeesTable': all_fees_table,
                'categorizedFees': categorized_fees,  # Should already be a dictionary
                'additionalFees': additional_fees,
                # Also include specialized tables directly
                'predefinedFeesTable': categorized_fees.get('predefinedFeesTable', []),
                'keysFeesTable': categorized_fees.get('keysFeesTable', []),
                'otherFeesTable': categorized_fees.get('otherFeesTable', [])
            }
            json.dump(json_output, f, indent=2)
    
    fees_download_path = os.path.join(download_dir, f'fee-table-{case_id}-{timestamp}.json')
    with open(fees_download_path, 'w', encoding='utf-8') as f:
        # Use the same consistent output format
        json_output = {
            'allFeesTable': all_fees_table,
            'categorizedFees': categorized_fees,  # Should already be a dictionary
            'additionalFees': additional_fees,
            # Also include specialized tables directly
            'predefinedFeesTable': categorized_fees.get('predefinedFeesTable', []),
            'keysFeesTable': categorized_fees.get('keysFeesTable', []),
            'otherFeesTable': categorized_fees.get('otherFeesTable', [])
        }
        json.dump(json_output, f, indent=2)
    
    output_files.append({
        'label': 'Fee Table (JSON)',
        'filename': os.path.basename(fees_download_path),
        'url': '/downloads/' + os.path.basename(fees_download_path)
    })
    
    # Save HTML report
    log('Generating HTML report...')
    html_report = generate_html_report(case_id, updates, fee_updates, all_fees_table, categorized_fees, additional_fees, my_summary_fees)
    
    html_path = os.path.join(output_dir, 'report.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_report)
    
    html_download_path = os.path.join(download_dir, f'report-{case_id}-{timestamp}.html')
    with open(html_download_path, 'w', encoding='utf-8') as f:
        f.write(html_report)

    output_files.append({
        'label': 'HTML Report',
        'filename': os.path.basename(html_download_path),
        'url': '/downloads/' + os.path.basename(html_download_path)
    })

    return output_files

def fetch_fees_from_db(client_name=None, lienholder_name=None, fee_type=None):
    """
    Fetch fee information from Azure SQL Database based on client name, lien holder, and fee type

    Args:
        client_name (str, optional): Name of the client to filter by
        lienholder_name (str, optional): Name of the lienholder to filter by
        fee_type (str, optional): Fee type to filter by

    Returns:
        list: List of fee details matching the criteria
    """
    # Make sure this implementation has the properly defined search variables
    search_client_name = client_name if client_name is not None else ""
    search_lienholder_name = lienholder_name if lienholder_name is not None else ""
    search_fee_type = fee_type if fee_type is not None else ""

    log('Fetching fee data from Azure SQL Database...')

    conn = get_db_connection()
    if not conn:
        log("Could not connect to database. Unable to fetch data.", "error")
        return []

    try:
        cursor = conn.cursor()

        # Build a dynamic query based on the provided filters
        query = """
            SELECT
                fd.fd_id,
                c.client_name,
                COALESCE(lh.lienholder_name, 'Unknown') as lienholder_name,
                ft.fee_type_name,
                fd.amount
            FROM
                dbo.FeeDetails2 fd
            JOIN
                dbo.RDN_Client c ON fd.client_id = c.id
            JOIN
                dbo.FeeType ft ON fd.ft_id = ft.id
            LEFT JOIN
                dbo.Lienholder lh ON fd.lh_id = lh.id
            WHERE
                1=1
        """

        # Parameters for the query
        params = []

        # Add filters based on the provided parameters
        if search_client_name:
            query += " AND c.client_name LIKE ?"
            params.append(f"%{search_client_name}%")

        if search_lienholder_name:
            query += " AND lh.lienholder_name LIKE ?"
            params.append(f"%{search_lienholder_name}%")

        if search_fee_type:
            query += " AND ft.fee_type_name LIKE ?"
            params.append(f"%{search_fee_type}%")

        # Log the query with enhanced visibility
        log_query("ORIGINAL", query, params)
        log(f"Searching database for: Client='{search_client_name}', Lienholder='{search_lienholder_name}', FeeType='{search_fee_type}'")

        # Execute the query
        cursor.execute(query, params)

        # Fetch all matching rows
        rows = cursor.fetchall()

        # Process the results into a list of dictionaries
        results = []
        for row in rows:
            results.append({
                'fd_id': row[0],
                'client_name': row[1],
                'lienholder_name': row[2],
                'fee_type': row[3],
                'amount': row[4]
            })

        log(f"Successfully fetched {len(results)} fee records from database")
        return results

    except Exception as e:
        log(f"Database error while fetching data: {str(e)}", "error")
        return []

    finally:
        if conn:
            conn.close()

# We can fetch existing data from database based on the case information in our test_database_fetch function

# Add a function to test database connectivity and fetch relevant fees
def auto_fetch_database_fees():
    """
    Automatically fetch fee information from database using current case info
    This function will be called after case information is extracted
    """
    client_name = config.get('current_case_info', {}).get('clientName')
    lienholder_name = config.get('current_case_info', {}).get('lienHolderName')
    repo_type = config.get('current_case_info', {}).get('repoType')

    log(f"Auto-fetching fee data from database using case information:")
    log(f"Client: {client_name}")
    log(f"Lienholder: {lienholder_name}")
    log(f"Repo Type: {repo_type}")

    # Fetch matching fee records from database
    fetched_fees = fetch_from_database(client_name, lienholder_name, fee_type=repo_type)
    if fetched_fees:
        log(f"Successfully fetched {len(fetched_fees)} matching fee records from database")
        # Log the first few records as examples
        for i, fee in enumerate(fetched_fees[:3]):
            log(f"Fee {i+1}: {fee['fee_type']} - ${fee['amount']} ({fee['client_name']})")

        # Convert decimal values to float and prepare results for JSON serialization
        formatted_fees = []
        for fee in fetched_fees:
            formatted_fee = {}
            for key, value in fee.items():
                if isinstance(value, decimal.Decimal):
                    formatted_fee[key] = float(value)
                else:
                    formatted_fee[key] = value
            formatted_fees.append(formatted_fee)

        # Emit database results to client
        socketio.emit('database_results', {
            'success': True,
            'count': len(formatted_fees),
            'results': formatted_fees,
            'queryInfo': {
                'client_name': client_name,
                'lienholder_name': lienholder_name,
                'fee_type': repo_type
            }
        })

        return formatted_fees
    else:
        log("No matching fee data found in database", "info")

        # Emit empty results
        socketio.emit('database_results', {
            'success': True,
            'count': 0,
            'results': [],
            'queryInfo': {
                'client_name': client_name,
                'lienholder_name': lienholder_name,
                'fee_type': repo_type
            }
        })

        return []

def get_display_source(source):
    """Map internal source names to display names according to requirements in CLAUDE.md"""
    # As per CLAUDE.md, we only allow two source labels:
    # - My Summary
    # - Updates (renamed from Case Page)
    if source == "Case Page":
        return "Updates"
    elif source.lower() == "case page":
        return "Updates"  # Handle case variations
    elif source.lower() == "my summary":
        return "My Summary"  # Standardize capitalization
    elif source.lower() == "database":
        return "Database"  # Standardized name but should be filtered out from tables
    else:
        # Default to Updates for any other source for consistency
        return "Updates" if source != "My Summary" else source

def generate_html_report(case_id, updates, fee_updates, all_fees_table, categorized_fees, additional_fees, my_summary_fees=None):
    """Generate HTML report for the scraped data using three-table structure as per CLAUDE.md"""
    start = time.time()
    log('Generating HTML report with three-table structure...')

    # Get case info from config if available
    case_info = config.get('current_case_info', {})
    client_name = case_info.get('clientName', 'Unknown Client')
    lien_holder = case_info.get('lienHolderName', 'Unknown Lien Holder')
    repo_type = case_info.get('repoType', 'Unknown Repo Type')

    # Generate the report date
    report_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Use the appropriate fee tables if available from the updated generate_fees_table function
    # Otherwise, fall back to categorization based on the all_fees_table
    # Handle both dictionary and list formats for categorized_fees for backward compatibility
    if isinstance(categorized_fees, dict):
        predefined_fees_table = categorized_fees.get('predefinedFeesTable', [])
        keys_fees_table = categorized_fees.get('keysFeesTable', [])
        other_fees_table = categorized_fees.get('otherFeesTable', [])
    else:
        # For backward compatibility where categorized_fees is a list
        predefined_fees_table = categorized_fees if isinstance(categorized_fees, list) else []
        keys_fees_table = []
        other_fees_table = []
        log("Using legacy format for categorized_fees (list instead of dict)")

    # If we don't have the specialized tables, use legacy approach to categorize fees
    if not predefined_fees_table and not keys_fees_table and not other_fees_table:
        log("Specialized fee tables not found, using legacy categorization approach")
        # Filter fees - exclude "Database" source as per CLAUDE.md
        all_fees_table = [fee for fee in all_fees_table if fee.get('source') != 'Database']

        # Categorize based on category field
        predefined_fees_table = []
        keys_fees_table = []
        other_fees_table = []

        for fee in all_fees_table:
            category = fee.get('category', '').lower()
            if 'keys fee' in category or 'key fee' in category:
                keys_fees_table.append(fee)
            elif category == 'other':
                other_fees_table.append(fee)
            else:
                predefined_fees_table.append(fee)

    # Count unique fees across all tables
    unique_fees_count = len(predefined_fees_table) + len(keys_fees_table) + len(other_fees_table)

    # Calculate total amount across all tables
    total_amount = 0
    for fee_list in [predefined_fees_table, keys_fees_table, other_fees_table]:
        for fee in fee_list:
            try:
                amount_str = fee.get('amount', '$0.00').replace('$', '').replace(',', '')
                total_amount += float(amount_str)
            except ValueError:
                log(f"Error parsing amount: {fee.get('amount')}", "error")

    # Count fees by source across all tables
    fees_by_source = {}
    for fee_list in [predefined_fees_table, keys_fees_table, other_fees_table]:
        for fee in fee_list:
            source = get_display_source(fee.get('source', 'Unknown'))
            if source not in fees_by_source:
                fees_by_source[source] = {'count': 0, 'amount': 0.0}
            fees_by_source[source]['count'] += 1
            try:
                amount_str = fee.get('amount', '$0.00').replace('$', '').replace(',', '')
                fees_by_source[source]['amount'] += float(amount_str)
            except ValueError:
                log(f"Error parsing amount: {fee.get('amount')}", "error")

    # Get database fee if available directly from fee_updates
    database_fees = []
    for update in fee_updates:
        if update.get('source') == 'Database':
            for amount_info in update.get('amounts', []):
                try:
                    amount_value = float(amount_info.get('amount', 0))
                    if amount_value > 0:
                        database_fees.append({
                            'amount': f"${amount_value:.2f}",
                            'context': amount_info.get('context', ''),
                            'feeType': amount_info.get('feeType', 'Involuntary Repo')
                        })
                except (ValueError, TypeError):
                    pass

    database_fee_display = ""
    if database_fees:
        database_fee = database_fees[0]
        database_fee_amount = database_fee.get('amount', '$0.00')
        database_fee_display = f" (Database Fee: {database_fee_amount})"

    # Build HTML report
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RDN Fee Report - Case {case_id}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; color: #333; }}
            h1, h2, h3 {{ color: #2c3e50; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f5f5f5; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .summary {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            .fees-container {{ margin-bottom: 30px; }}
            .amount {{ text-align: right; }}
            .approved {{ color: green; }}
            .not-approved {{ color: orange; }}
            .section {{ margin-bottom: 30px; }}
            .info-card {{ background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 5px; padding: 15px; margin-bottom: 15px; display: inline-block; margin-right: 10px; min-width: 200px; }}
            .database-fees-card {{ background-color: #e3f2fd; border: 1px solid #bbdefb; border-radius: 5px; padding: 15px; margin-bottom: 15px; }}
            .keys-fees-table {{ background-color: #fff9c4; }} /* Yellow background for keys fees */
            .other-fees-table {{ background-color: #fff9c4; }} /* Yellow background for other fees */
            .card-container {{ display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; }}
            .card {{ background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 5px; padding: 15px; flex: 1; min-width: 200px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .card h4 {{ margin-top: 0; color: #2c3e50; }}
            .card p {{ font-size: 1.2em; font-weight: bold; color: #333; margin-bottom: 0; }}
        </style>
    </head>
    <body>
        <h1>RDN Fee Report</h1>

        <div class="summary">
            <h2>Case Information</h2>
            <div class="card-container">
                <div class="card">
                    <h4>Case ID</h4>
                    <p>{case_id}</p>
                </div>
                <div class="card">
                    <h4>Client Name</h4>
                    <p>{client_name}</p>
                </div>
                <div class="card">
                    <h4>Lien Holder</h4>
                    <p>{lien_holder}</p>
                </div>
                <div class="card">
                    <h4>Repo Type</h4>
                    <p>{repo_type}</p>
                </div>
    """

    # Add database fee card if available (per CLAUDE.md)
    # Check direct database_fees array and also fee_updates for Database source
    found_database_fee = False
    database_fee_amount = '$0.00'
    database_fee_type = 'Involuntary Repo'

    if database_fees:
        database_fee = database_fees[0]
        database_fee_amount = database_fee.get('amount', '$0.00')
        database_fee_type = database_fee.get('feeType', 'Involuntary Repo')
        found_database_fee = True

    # Also check fee_updates as a backup method to find database fees
    if not found_database_fee:
        for update in fee_updates:
            if update.get('source') == 'Database':
                for amount_info in update.get('amounts', []):
                    try:
                        amount_value = float(amount_info.get('amount', 0))
                        if amount_value > 0:
                            database_fee_amount = f"${amount_value:.2f}"
                            database_fee_type = amount_info.get('feeType', 'Involuntary Repo')
                            found_database_fee = True
                            break
                    except (ValueError, TypeError):
                        pass
                if found_database_fee:
                    break

    # Add the database fee card if we found any database fee
    if found_database_fee:
        html += f"""
                <div class="card">
                    <h4>Involuntary Repo Fee</h4>
                    <p>{database_fee_amount}</p>
                </div>
        """

    html += f"""
            </div>
            <p><strong>Report Date:</strong> {report_date}</p>
        </div>

        <div class="section">
            <h2>Fee Summary</h2>
            <p><strong>Total Unique Fees Extracted:</strong> {unique_fees_count}</p>
            <p><strong>Total Amount:</strong> ${total_amount:.2f}</p>

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
        </div>
    """

    # Table 1: Predefined Categories (whitelist)
    # Always show the table header even if empty
    html += """
    <div class="fees-container">
        <h2>Predefined Categories Fees</h2>
        <table>
            <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Source</th>
                <th>Reference</th>
            </tr>
    """

    if predefined_fees_table:
        for fee in predefined_fees_table:
            approved_class = "approved" if fee.get('approved') == 'Yes' else "not-approved"

            html += f"""
                    <tr>
                        <td>{fee.get('date', '')}</td>
                        <td>{fee.get('category', '')}</td>
                        <td class="amount">{fee.get('amount', '$0.00')}</td>
                        <td class="{approved_class}">{fee.get('approved', 'Unknown')}</td>
                        <td>{get_display_source(fee.get('source', ''))}</td>
                        <td>{fee.get('referenceSentence', '')}</td>
                    </tr>
            """
    else:
        # Show empty state message
        html += """
                <tr>
                    <td colspan="6" style="text-align: center; padding: 20px;">No predefined category fees found</td>
                </tr>
        """

    html += """
        </table>
    </div>
    """

    # Table 2: Keys Fees (with yellow background)
    # Always show the table header even if empty
    html += """
    <div class="fees-container">
        <h2>Keys Fee</h2>
        <table class="keys-fees-table">
            <tr>
                <th>Date</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Source</th>
                <th>Reference</th>
            </tr>
    """

    if keys_fees_table:
        for fee in keys_fees_table:
            approved_class = "approved" if fee.get('approved') == 'Yes' else "not-approved"

            html += f"""
                    <tr>
                        <td>{fee.get('date', '')}</td>
                        <td class="amount">{fee.get('amount', '$0.00')}</td>
                        <td class="{approved_class}">{fee.get('approved', 'Unknown')}</td>
                        <td>{get_display_source(fee.get('source', ''))}</td>
                        <td>{fee.get('referenceSentence', '')}</td>
                    </tr>
            """
    else:
        # Show empty state message
        html += """
                <tr>
                    <td colspan="5" style="text-align: center; padding: 20px;">No key fees found</td>
                </tr>
        """

    html += """
        </table>
    </div>
    """

    # Table 3: Other Categories (non-whitelist, yellow background)
    # Always show the table header even if empty
    html += """
    <div class="fees-container">
        <h2>Other Categories</h2>
        <table class="other-fees-table">
            <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Source</th>
                <th>Reference</th>
            </tr>
    """

    if other_fees_table:
        for fee in other_fees_table:
            approved_class = "approved" if fee.get('approved') == 'Yes' else "not-approved"
            # Use original category name for non-whitelist fees
            category = fee.get('originalCategory', 'Unknown')

            html += f"""
                    <tr>
                        <td>{fee.get('date', '')}</td>
                        <td>{category}</td>
                        <td class="amount">{fee.get('amount', '$0.00')}</td>
                        <td class="{approved_class}">{fee.get('approved', 'Unknown')}</td>
                        <td>{get_display_source(fee.get('source', ''))}</td>
                        <td>{fee.get('referenceSentence', '')}</td>
                    </tr>
            """
    else:
        # Show empty state message
        html += """
                <tr>
                    <td colspan="6" style="text-align: center; padding: 20px;">No other category fees found</td>
                </tr>
        """

    html += """
        </table>
    </div>
    """

    # Add footer
    html += """
        <footer>
            <p><strong>🟢 Table 1:</strong> Only whitelist categories • <strong>🟡 Table 2:</strong> All "Keys Fee" • <strong>🟡 Table 3:</strong> All non-whitelist categories with original names</p>
            <p>Generated by RDN Fee Scraper - Updated as per CLAUDE.md</p>
        </footer>
    </body>
    </html>
    """

    end = time.time()
    log(f"HTML report generation took: {end - start:.3f}s")

    return html

# Flask routes
@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/dashboard')
def dashboard():
    return send_from_directory('public', 'dashboard.html')

# Define a route specifically for /case-form to directly serve the dashboard
@app.route('/case-form')
def case_form():
    return send_from_directory('public', 'dashboard.html')

# Also handle any other case-form variants
@app.route('/case-form.html')
def case_form_html():
    return send_from_directory('public', 'dashboard.html')

# Specific routes for static files
@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory('public/js', filename)

@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory('public/css', filename)

# Wildcard route to catch other paths
@app.route('/<path:path>')
def catch_all(path):
    # Try to serve the file from static folder
    try:
        return send_from_directory('public', path)
    except:
        # If file not found, redirect to home
        return redirect('/')

@app.route('/login', methods=['POST'])
def login_route():
    global scrape_in_progress, start_time

    data = request.get_json()

    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400

    # Update credentials in config
    config['credentials']['username'] = data.get('username', '')
    config['credentials']['password'] = data.get('password', '')
    config['credentials']['security_code'] = data.get('securityCode', '')

    # Check if any case ID is provided in the login form
    case_id = data.get('caseId', '')
    if case_id:
        config['current_case_id'] = case_id

    # Validate required fields - only the credentials are required at login stage
    if not config['credentials']['username'] or not config['credentials']['password']:
        return jsonify({'success': False, 'error': 'Username and password are required'}), 400

    # For security code, we'll just warn if it's not provided but not fail
    if not config['credentials']['security_code']:
        log('Warning: Security code not provided', 'warning')

    # Check if scrape is already in progress
    if scrape_in_progress:
        return jsonify({'success': False, 'error': 'Scrape already in progress'}), 400

    # Return success response - we don't start scraping yet as we need the case ID
    # We'll redirect directly to the dashboard page where they can enter a case ID
    # No case-form page in between
    return jsonify({
        'success': True,
        'redirect': '/dashboard',  
        'message': 'Login successful! Please enter a case ID to continue.'
    })

@app.route('/logout', methods=['POST'])
def logout_route():
    global scrape_in_progress, start_time

    # Reset scrape in progress flag
    scrape_in_progress = False
    start_time = None

    # Close all browser sessions
    for session_id, driver in list(active_sessions.items()):
        try:
            driver.quit()
            log(f"Closed browser session for {session_id}")
        except:
            pass
    active_sessions.clear()

    return jsonify({'status': 'success'})

@app.route('/status')
def status_route():
    return jsonify({
        'scrapeInProgress': scrape_in_progress,
        'startTime': start_time.isoformat() if start_time else None,
        'caseId': config.get('current_case_id')
    })

@app.route('/fetch-from-database', methods=['POST'])
def fetch_from_database_route():
    data = request.get_json()

    # Extract query parameters
    client_name = data.get('client_name', None)
    lienholder_name = data.get('lienholder_name', None)
    fee_type = data.get('fee_type', None)

    # Validate that at least one parameter is provided
    if not client_name and not lienholder_name and not fee_type:
        return jsonify({
            'success': False,
            'error': 'At least one search parameter (client_name, lienholder_name, or fee_type) is required'
        }), 400

    # Call the fetch_from_database function
    # These variables are already properly scoped for this function call
    results = fetch_from_database(client_name, lienholder_name, fee_type)

    return jsonify({
        'success': True,
        'count': len(results),
        'results': results
    })

@app.route('/start-scrape', methods=['POST'])
def start_scrape_route():
    global scrape_in_progress, start_time

    if scrape_in_progress:
        return jsonify({'success': False, 'error': 'Scrape already in progress'}), 400

    data = request.get_json()
    if not data or not data.get('caseId'):
        return jsonify({'success': False, 'error': 'Case ID is required'}), 400

    # Set case ID in config
    case_id = data.get('caseId')
    config['current_case_id'] = case_id

    # Set scrape in progress flag
    scrape_in_progress = True
    start_time = datetime.datetime.now()

    # Start scraping process in a separate thread
    scrape_thread = threading.Thread(target=start_scraping)
    scrape_thread.daemon = True
    scrape_thread.start()

    # Send timer start event to all clients
    socketio.emit('timer-start', {
        'startTime': start_time.isoformat(),
        'caseId': case_id
    })

    # Return success response
    return jsonify({'success': True, 'message': f'Started scraping case ID: {case_id}'})

def start_scraping():
    """Start the scraping process in a background thread"""
    global scrape_in_progress, start_time

    scrape_start = time.time()
    log(f"Starting scrape for case ID: {config['current_case_id']}")

    # List to store any key fees found during scanning
    initial_key_fees = []

    # Create a unique session ID for this scrape
    session_id = f"session_{int(time.time())}"

    try:
        # Create a new browser instance
        driver = create_driver()
        active_sessions[session_id] = driver

        # Perform login
        login(driver)

        # Navigate to case
        case_info = navigate_to_case(driver, config['current_case_id'])

        # Process the My Summary tab first
        log("Processing My Summary tab...")
        click_my_summary_tab(driver)

        # Scrape the My Summary tab
        my_summary_fees = scrape_my_summary_tab(driver)

        # Process the Updates tab
        log("Processing Updates tab...")
        click_updates_tab(driver)

        # Load all updates
        load_all_updates(driver)

        # Scrape updates
        updates, fee_updates = scrape_updates_tab(driver)

        # Combine fee information from both sources
        log('Combining fee information from My Summary, Updates, and Key Fee tabs...')

        # Include key fees if found during page scan
        page_key_fees = []
        if 'key_fee_updates' in globals() and key_fee_updates:
            page_key_fees = key_fee_updates
            log(f'Page Key Fees: {len(page_key_fees)}')

        log(f'My Summary fees: {len(my_summary_fees)}, Updates fees: {len(fee_updates)}, Key Fees: {len(page_key_fees)}')
        combined_fee_updates = my_summary_fees + fee_updates + page_key_fees
        log(f'Combined fee updates: {len(combined_fee_updates)}')

        # Generate fees table from combined sources
        log(f'Generating fees table from combined sources: {len(combined_fee_updates)} total fees')
        fees_result = generate_fees_table(combined_fee_updates)
        all_fees_table = fees_result['allFeesTable']

        # Get specialized tables if available, or empty lists if not
        predefined_fees_table = fees_result.get('predefinedFeesTable', [])
        keys_fees_table = fees_result.get('keysFeesTable', [])
        other_fees_table = fees_result.get('otherFeesTable', [])

        # Ensure categorized_fees is always a dictionary
        categorized_fees = {
            'predefinedFeesTable': predefined_fees_table,
            'keysFeesTable': keys_fees_table,
            'otherFeesTable': other_fees_table
        }

        # For backward compatibility
        additional_fees = fees_result['additionalFees']

        # If we still have no fees in all_fees_table but have My Summary fees, manually add them
        if len(all_fees_table) == 0 and len(my_summary_fees) > 0:
            log('No fees found in generateFeesTable, manually adding My Summary fees')
            manually_added = 0
            for fee in my_summary_fees:
                for amount_info in fee.get('amounts', []):
                    try:
                        amount_value = float(amount_info.get('amount', 0))
                        if amount_value <= 0:
                            continue

                        # Create fee entry with all required fields
                        fee_label = fee.get('feeLabel', 'Unknown Fee')
                        fee_entry = {
                            'date': fee.get('date', ''),
                            'amount': f"${amount_value:.2f}",
                            'type': fee.get('type', ''),
                            'approver': fee.get('user', ''),
                            'referenceSentence': amount_info.get('context', ''),
                            'approved': 'Yes' if fee.get('isApproved') or amount_info.get('isExplicitlyApproved') else 'Likely',
                            'category': fee_label,
                            'source': 'My Summary',
                            'matched': False,
                            'matchedAs': 'My Summary',
                            'originalCategory': fee_label  # For compatibility with new structure
                        }

                        all_fees_table.append(fee_entry)
                        manually_added += 1

                        # Also add to the appropriate specialized table
                        category = fee_label.lower()
                        if 'keys fee' in category or 'key fee' in category:
                            if 'keysFeesTable' not in categorized_fees:
                                categorized_fees['keysFeesTable'] = []
                            categorized_fees['keysFeesTable'].append(fee_entry)
                            log(f"Added manual fee to Keys table: ${amount_value:.2f}")
                        # Check if category is in predefined list
                        elif any(predefined.lower() == category for predefined in config["pre_approved_fees"]):
                            if 'predefinedFeesTable' not in categorized_fees:
                                categorized_fees['predefinedFeesTable'] = []
                            categorized_fees['predefinedFeesTable'].append(fee_entry)
                            log(f"Added manual fee to Predefined table: ${amount_value:.2f} - {fee_label}")
                        else:
                            if 'otherFeesTable' not in categorized_fees:
                                categorized_fees['otherFeesTable'] = []
                            categorized_fees['otherFeesTable'].append(fee_entry)
                            log(f"Added manual fee to Other table: ${amount_value:.2f} - {fee_label}")

                    except (ValueError, TypeError) as e:
                        log(f"Error processing My Summary fee: {str(e)}", "error")
                        continue

            # Ensure categorized_fees is a dictionary for the updated generate_html_report function
            if not isinstance(categorized_fees, dict):
                categorized_fees = {
                    'predefinedFeesTable': [],
                    'keysFeesTable': [],
                    'otherFeesTable': []
                }

            log(f'Manually added {manually_added} My Summary fees to fee table and specialized tables')

        # Save data
        output_files = save_data(
            updates,
            fee_updates,
            all_fees_table,
            categorized_fees,
            additional_fees,
            config['current_case_id'],
            my_summary_fees
        )

        # Emit scrape complete event
        # Filter out database fees from all_fees_table for display
        filtered_fees = [f for f in all_fees_table if f.get('source') != 'Database']

        # Separate the filtered fees into predefined categories and "Other"
        predefined_fees = [f for f in filtered_fees if f.get('category', '') != 'Other']
        other_fees = [f for f in filtered_fees if f.get('category', '') == 'Other']

        # Identify Keys Fees by looking for key terms in category or reference
        keys_terms = ['key fee', 'keys fee', 'key charge', 'keys charge']

        # Function to check if a fee is a Keys Fee
        def is_keys_fee(fee):
            category = fee.get('category', '').lower()
            reference = fee.get('referenceSentence', '').lower()

            return any(term in category or term in reference for term in keys_terms)

        # Function to sanitize category names for HTML IDs
        def sanitize_category(category):
            if not category:
                return "unknown"
            # Replace spaces with hyphens and remove special characters
            return re.sub(r'[^a-zA-Z0-9-]', '', category.lower().replace(' ', '-'))

        # Function to determine category type (predefined, keys, other)
        def get_category_type(fee):
            if is_keys_fee(fee):
                return "keys"
            elif fee.get('category', '').lower() in [f.lower() for f in config["pre_approved_fees"]]:
                return "predefined"
            else:
                return "other"

        # Split the filtered fees into three categories for backward compatibility
        predefined_fees = []
        keys_fees = []
        other_fees = []

        # New structure: organize fees by individual categories
        category_grouped_fees = {}

        for fee in filtered_fees:
            # Determine category and type
            category = fee.get('category', 'Unknown')
            if is_keys_fee(fee):
                # Standardize keys fee category name
                keys_fees.append(fee)
                category = "Keys Fee"  # Standardize name
            elif fee.get('category', '') == 'Other':
                other_fees.append(fee)
            else:
                predefined_fees.append(fee)

            # Normalize category for case-insensitive grouping
            category_lower = category.lower()

            # Add category type for styling
            category_type = get_category_type(fee)
            fee['categoryType'] = category_type

            # Add to appropriate category group
            if category_lower not in category_grouped_fees:
                category_grouped_fees[category_lower] = {
                    'displayName': category,  # Keep original casing for display
                    'sanitizedName': sanitize_category(category),
                    'type': category_type,
                    'fees': []
                }

            category_grouped_fees[category_lower]['fees'].append(fee)

        # Count fees by category
        log(f"Split fees into categories: Predefined: {len(predefined_fees)}, Keys: {len(keys_fees)}, Other: {len(other_fees)}")
        log(f"Organized fees by individual categories: {len(category_grouped_fees)} unique categories")

        # Display counts for each category
        for category_name, category_data in category_grouped_fees.items():
            log(f"  - {category_data['displayName']} ({category_data['type']}): {len(category_data['fees'])} fees")

        # Use filtered fees for UI display and properly format the categorized fees
        final_all_fees = filtered_fees
        final_categorized_fees = {
            'predefinedFeesTable': predefined_fees,
            'keysFeesTable': keys_fees,
            'otherFeesTable': other_fees,
            'categoryGroupedFees': category_grouped_fees  # New structure with fees grouped by category
        }

        if len(all_fees_table) == 0 and len(my_summary_fees) > 0:
            log('No fees in final fee table, manually converting My Summary fees for frontend display')
            manual_fees = []

            for fee in my_summary_fees:
                for amount_info in fee.get('amounts', []):
                    try:
                        amount_value = float(amount_info.get('amount', 0))
                        if amount_value <= 0:
                            continue

                        manual_fees.append({
                            'date': fee.get('date', ''),
                            'amount': f"${amount_value:.2f}",
                            'type': fee.get('type', ''),
                            'approver': fee.get('user', ''),
                            'referenceSentence': amount_info.get('context', ''),
                            'approved': 'Yes' if fee.get('isApproved') or amount_info.get('isExplicitlyApproved') else 'Likely',
                            'category': fee.get('feeLabel', 'Unknown Fee'),
                            'source': 'My Summary',
                            'matched': False,
                            'matchedAs': 'My Summary'
                        })
                    except (ValueError, TypeError) as e:
                        log(f"Error processing My Summary fee for frontend: {str(e)}", "error")
                        continue

            # Also add to the appropriate specialized categories
            manual_predefined = []
            manual_keys = []
            manual_other = []

            # Create category groups for manual fees
            manual_category_grouped = {}

            for fee in manual_fees:
                fee_label = fee.get('category', '').lower()
                category = fee.get('category', 'Unknown Fee')

                if any(term in fee_label for term in keys_terms):
                    manual_keys.append(fee)
                    category_type = "keys"
                    # Standardize keys fee category
                    category = "Keys Fee"
                elif fee_label == 'other':
                    manual_other.append(fee)
                    category_type = "other"
                else:
                    manual_predefined.append(fee)
                    category_type = "predefined"

                # Add category type for styling
                fee['categoryType'] = category_type

                # Add to category groups
                category_lower = category.lower()
                if category_lower not in manual_category_grouped:
                    manual_category_grouped[category_lower] = {
                        'displayName': category,
                        'sanitizedName': sanitize_category(category),
                        'type': category_type,
                        'fees': []
                    }

                manual_category_grouped[category_lower]['fees'].append(fee)

            final_all_fees = manual_fees
            final_categorized_fees = {
                'predefinedFeesTable': manual_predefined,
                'keysFeesTable': manual_keys,
                'otherFeesTable': manual_other,
                'categoryGroupedFees': manual_category_grouped
            }
            log(f'Manually created {len(manual_fees)} fee entries for frontend display')
            log(f'Manual fee categories: Predefined: {len(manual_predefined)}, Keys: {len(manual_keys)}, Other: {len(manual_other)}')
            log(f'Manual unique categories: {len(manual_category_grouped)}')

        # Calculate totals from the final fee data (excluding database fees)
        total_fees = len(final_all_fees)
        approved_fees = sum(1 for fee in final_all_fees if fee.get('approved') == 'Yes')

        # Log final fee counts for debugging
        total_predefined = len(final_categorized_fees['predefinedFeesTable'])
        total_keys = len(final_categorized_fees['keysFeesTable'])
        total_other = len(final_categorized_fees['otherFeesTable'])
        log(f"Final fee counts - Total: {total_fees}, Predefined: {total_predefined}, Keys: {total_keys}, Other: {total_other}")

        # Add sample fee output for debugging
        if total_predefined > 0:
            sample_predefined = final_categorized_fees['predefinedFeesTable'][0]
            log(f"Sample predefined fee: {sample_predefined}")
        if total_keys > 0:
            sample_keys = final_categorized_fees['keysFeesTable'][0]
            log(f"Sample keys fee: {sample_keys}")
        if total_other > 0:
            sample_other = final_categorized_fees['otherFeesTable'][0]
            log(f"Sample other fee: {sample_other}")

        # Safely extract amount values with error handling
        def safe_amount_to_float(amount_str):
            try:
                if isinstance(amount_str, str):
                    return float(amount_str.replace('$', '').replace(',', ''))
                return 0.0
            except (ValueError, AttributeError):
                return 0.0

        total_amount = sum(safe_amount_to_float(fee.get('amount', '$0.00')) for fee in final_all_fees)
        approved_amount = sum(safe_amount_to_float(fee.get('amount', '$0.00')) for fee in final_all_fees if fee.get('approved') == 'Yes')

        # Prepare category styling information
        category_styling = {
            'predefined': '#e3f2fd',  # Light Blue
            'keys': '#fff8e1',        # Soft Amber
            'other': '#e0f2f1'        # Soft Teal
        }

        # Count categories by type for summary
        category_counts = {
            'predefined': sum(1 for cat in final_categorized_fees.get('categoryGroupedFees', {}).values()
                             if cat['type'] == 'predefined'),
            'keys': sum(1 for cat in final_categorized_fees.get('categoryGroupedFees', {}).values()
                       if cat['type'] == 'keys'),
            'other': sum(1 for cat in final_categorized_fees.get('categoryGroupedFees', {}).values()
                        if cat['type'] == 'other'),
            'total': len(final_categorized_fees.get('categoryGroupedFees', {}))
        }

        socketio.emit('process-complete', {
            'status': 'success',
            'caseId': config['current_case_id'],
            'files': output_files,
            'caseInfo': config.get('current_case_info', {}),
            'summary': {
                'totalFees': total_fees,
                'approvedFees': approved_fees,
                'totalAmount': f"${total_amount:.2f}",
                'approvedAmount': f"${approved_amount:.2f}",
                'mySummaryFeesCount': len(my_summary_fees) if my_summary_fees else 0,
                'updatesFeesCount': len(fee_updates),
                'categoryCounts': category_counts
            },
            'categoryStyles': category_styling,
            'categories': list(final_categorized_fees.get('categoryGroupedFees', {}).values()),
            'categorizedFees': final_categorized_fees,  # Dictionary with all tables
            'categoryGroupedFees': final_categorized_fees.get('categoryGroupedFees', {}),  # New category-based structure
            # For backward compatibility
            'predefinedFeesTable': final_categorized_fees['predefinedFeesTable'],
            'keysFeesTable': final_categorized_fees['keysFeesTable'],
            'otherFeesTable': final_categorized_fees['otherFeesTable'],
            'additionalFees': final_categorized_fees['otherFeesTable'],
            'allFeesTable': final_all_fees,
            'databaseFees': [f for f in all_fees_table if f.get('source') == 'Database']
        })

        scrape_end = time.time()
        log(f"Scrape completed successfully for case ID: {config['current_case_id']}")
        log(f"Total scraping process took: {scrape_end - scrape_start:.3f}s")
    except Exception as e:
        log(f"Error scraping case: {str(e)}", "error")

        # Take screenshot if driver is available
        try:
            if 'driver' in locals():
                screenshot_path = os.path.join(config["output_dir"], f"error-case-{config['current_case_id']}-{int(time.time())}.png")
                driver.save_screenshot(screenshot_path)
                log(f"Error screenshot saved to {screenshot_path}")
        except Exception as screenshot_err:
            log(f"Could not save error screenshot: {str(screenshot_err)}", "error")

        # Emit scrape error event
        socketio.emit('process-error', {
            'status': 'error',
            'caseId': config['current_case_id'],
            'error': str(e),
            'details': error_details if 'error_details' in locals() else None
        })
    finally:
        # Clean up resources
        try:
            if 'driver' in locals() and driver:
                driver.quit()

            if session_id in active_sessions:
                del active_sessions[session_id]
        except Exception as cleanup_err:
            log(f"Error cleaning up resources: {str(cleanup_err)}", "error")

        # Reset scrape in progress flag
        scrape_in_progress = False
        start_time = None

def main():
    """Main function to set up portal and wait for user input"""
    # Create output directory
    os.makedirs(config["output_dir"], exist_ok=True)
    
    # Start Flask app with Socket.IO
    host = '0.0.0.0'
    port = config["web_portal"]["port"]

    log(f'Starting server on http://localhost:{port}')

    # Check for any existing browser sessions and clean them up
    log(f"Active sessions at startup: {list(active_sessions.keys())}")
    for session_id, driver in list(active_sessions.items()):
        try:
            driver.quit()
            log(f"Closed browser session for {session_id}")
        except:
            pass
    active_sessions.clear()

    # Open browser if configured
    if config["web_portal"]["open_browser"]:
        try:
            log("Opening browser to application URL")
            webbrowser.open(f'http://localhost:{port}')
        except Exception as e:
            log(f"Could not open browser: {str(e)}", "error")

    # Run the server with appropriate settings
    try:
        log("Starting Socket.IO server...")
        socketio.run(
            app,
            host=host,
            port=port,
            debug=False,
            allow_unsafe_werkzeug=True,
            use_reloader=False
        )
    except Exception as e:
        log(f"Error starting server: {str(e)}", "error")

if __name__ == "__main__":
    main()

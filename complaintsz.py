from playwright.sync_api import sync_playwright
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import os
import time
import json
import hashlib
from dotenv import load_dotenv

# === Load environment variables and API keys ===
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Google Sheets setup
CREDENTIALS_FILE = "service_account.json"
SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Zomato Complaints"  # Ensure this matches your sheet tab name

def init_gsheet():
    """Initializes and returns the Google Sheet worksheet object."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)
        print(f"✅ Successfully connected to Google Sheet: '{SHEET_NAME}' -> '{WORKSHEET_NAME}'")
        return sheet
    except Exception as e:
        print(f"❌ Error connecting to Google Sheet: {e}")
        raise  # Re-raise to stop execution if sheet connection fails

OUTLET_IDS = [
    "19595894", "19595967", "19501574", "20547934", "20647827", "20183353", "57750", "21134281", "20996205", "19501520", "18422924",
]

# --- START: Gemini-based parsing and deduplication functions ---

def generate_complaint_hash(parsed_complaint: dict) -> str:
    """Generates a unique hash for a complaint for deduplication."""
    complaint_id = parsed_complaint.get("Complaint ID", "").strip()
    timestamp = parsed_complaint.get("Timestamp", "").strip()
    # Prioritize Complaint ID, fallback to Timestamp if ID is missing
    unique_str = complaint_id if complaint_id else timestamp
    if not unique_str:
        # Fallback to a hash of the entire dict if no unique identifier is found
        return hashlib.sha256(json.dumps(parsed_complaint, sort_keys=True).encode('utf-8')).hexdigest()
    return hashlib.sha256(unique_str.encode('utf-8')).hexdigest()

def parse_complaint_with_gemini(raw_text: str, outlet_id: str) -> dict | None:
    """
    Parses the raw text of a Zomato complaint details page using Gemini.
    Extracts structured information into a dictionary.
    """
    prompt = f"""
You are an expert at parsing Zomato complaint details from their partner portal.
Extract the following fields from the provided raw text.
Focus only on the details of the *currently displayed complaint*.

Required Fields (must always be present):
- Reason: The primary reason for the complaint (e.g., "Order was delivered late").
- Status: The current status of the complaint (e.g., "OPEN", "RESOLVED", "DISMISSED").
- Complaint ID: The unique identifier for the complaint (e.g., "Complaint ID: 1234567890").
- Timestamp: The full date and time of the complaint (e.g., "11:04 AM | Monday, Jul 22").
- Description: The detailed description of the customer's issue, usually found just before "Order details".
- Customer History: The section detailing customer's past order behavior (e.g., "Good customer history").

Optional Fields (include only if found):
- Refund Amount: The amount of refund requested or processed (e.g., "Refund requested: ₹100"). If present, extract only the amount or "requested".
- Customer Name: The name of the customer.

Instructions:
- Return the result as a compact JSON object. Do NOT use markdown or code block wrappers.
- If a required field is missing, use an empty string ("").
- For "Refund Amount", extract only the value (e.g., "₹100" or "requested"). If not found, use an empty string.
- For "Complaint ID", extract only the ID number, not the "Complaint ID:" prefix.
- For "Timestamp", extract the full date and time string as displayed.
- For "Description", capture the main text describing the complaint.
- For "Customer History", capture the relevant lines describing the customer's history.
- Ensure the JSON is valid and compact.

Raw Complaint Text:
{raw_text}
"""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            [{"role": "user", "parts": [prompt]}],
            generation_config={"temperature": 0}
        )

        raw_content = response.text.strip()
        cleaned = raw_content.replace("```json", "").replace("```", "").strip()

        parsed_data = json.loads(cleaned)

        # Add outlet_id to the parsed data for the sheet
        parsed_data["Outlet ID"] = outlet_id

        return parsed_data

    except json.JSONDecodeError as e:
        print(f"⚠️ Failed to parse Gemini response as JSON for outlet {outlet_id}: {e}")
        print("Raw Gemini Response (JSONDecodeError):", raw_content)
        return None
    except Exception as e:
        print(f"⚠️ Gemini API error for outlet {outlet_id}: {e}")
        return None

def append_complaint_to_sheet(sheet, parsed_complaint: dict, seen_hashes: set):
    """Appends a parsed complaint to the Google Sheet if it's not a duplicate."""
    try:
        complaint_id = parsed_complaint.get("Complaint ID", "").strip()
        if not complaint_id:
            print("⚠️ Skipping append: No valid Complaint ID found in parsed complaint.")
            return

        complaint_hash = generate_complaint_hash(parsed_complaint)
        if complaint_hash in seen_hashes:
            print(f"⏭️ Duplicate complaint detected for ID: {complaint_id}. Hash: {complaint_hash}")
            return  # Skip appending if duplicate

        # Define the order of columns as they should appear in the sheet
        row_data = [
            parsed_complaint.get("Outlet ID", ""),
            parsed_complaint.get("Reason", ""),
            parsed_complaint.get("Status", ""),
            parsed_complaint.get("Refund Amount", ""),
            parsed_complaint.get("Complaint ID", ""),
            parsed_complaint.get("Timestamp", ""),
            parsed_complaint.get("Description", ""),
            parsed_complaint.get("Customer History", ""),
            parsed_complaint.get("Customer Name", "")
        ]
        
        sheet.append_row(row_data, value_input_option="USER_ENTERED")
        seen_hashes.add(complaint_hash)

        print(f"📤 Structured complaint appended to sheet for ID: {complaint_id}")
    except Exception as e:
        print(f"⚠️ Failed to write structured complaint row to Google Sheet: {e}")

def wait_for_element_with_retry(page, selector, timeout=10000, retries=3):
    """Wait for element with retry logic."""
    for attempt in range(retries):
        try:
            page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1}/{retries} failed for selector '{selector}': {e}")
            if attempt < retries - 1:
                page.wait_for_timeout(2000)
            else:
                return False
    return False

def safe_click(page, selector, timeout=5000):
    """Safely click an element with error handling."""
    try:
        element = page.wait_for_selector(selector, timeout=timeout)
        if element:
            element.click()
            return True
    except Exception as e:
        print(f"⚠️ Failed to click selector '{selector}': {e}")
    return False

def scrape_and_push_complaints():
    """Main function to orchestrate Zomato complaint scraping and pushing to sheet."""
    print("🚀 Starting Zomato complaint scraping process...")
    sheet = init_gsheet()

    print("📊 Loading existing complaints from sheet for deduplication...")
    existing_rows = sheet.get_all_values()[1:]  # Skip header row
    seen_hashes = set()
    for row in existing_rows:
        if len(row) > 4:
            complaint_id_from_sheet = row[4].strip()
            timestamp_from_sheet = row[5].strip() if len(row) > 5 else ""
            if complaint_id_from_sheet:
                complaint_hash = generate_complaint_hash({"Complaint ID": complaint_id_from_sheet, "Timestamp": timestamp_from_sheet})
                seen_hashes.add(complaint_hash)
    print(f"📊 Loaded {len(seen_hashes)} existing complaint hashes from sheet.")

    try:
        with sync_playwright() as p:
            # Launch browser in headless mode with optimized arguments
            browser = p.chromium.launch(
                headless=True,  # Run in headless mode
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-features=TranslateUI',
                    '--disable-extensions',
                    '--disable-component-extensions-with-background-pages',
                    '--disable-default-apps',
                    '--mute-audio',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor,IsolateOrigins,site-per-process',
                    '--disable-blink-features=AutomationControlled',
                    '--window-size=1920,1080',
                    '--start-maximized',
                    '--disable-infobars',
                    '--disable-notifications',
                    '--disable-popup-blocking'
                ]
            )

            # Create context with anti-detection settings optimized for headless
            try:
                context = browser.new_context(
                    storage_state="zomato_login.json" if os.path.exists("zomato_login.json") else None,
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    bypass_csp=True,
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Cache-Control': 'max-age=0'
                    }
                )

                # Enhanced anti-detection script for headless mode
                context.add_init_script("""
                    // Override the navigator.webdriver property
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    // Mock navigator properties
                    window.navigator.chrome = {
                        runtime: {},
                        loadTimes: function() {},
                        csi: function() {},
                        webstore: {}
                    };
                    
                    // Override plugins
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    
                    // Override languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    
                    // Override permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                    
                    // Mock screen properties
                    Object.defineProperty(screen, 'colorDepth', {
                        get: () => 24
                    });
                    
                    Object.defineProperty(screen, 'pixelDepth', {
                        get: () => 24
                    });
                    
                    // Remove headless indicators
                    delete navigator.__proto__.webdriver;
                    
                    // Mock getBattery API
                    navigator.getBattery = () => Promise.resolve({
                        charging: true,
                        chargingTime: 0,
                        dischargingTime: Infinity,
                        level: 1
                    });
                """)
            except Exception as e:
                print(f"⚠️ Could not load storage state or create context: {e}. Creating new context.")
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )

            page = context.new_page()
            
            # Set longer timeout for navigation and add error handling
            page.set_default_timeout(60000)  # Increased timeout for headless mode
            page.set_default_navigation_timeout(60000)
            
            try:
                print("🌐 Navigating to Zomato partner portal...")
                
                # Navigate with better error handling
                try:
                    page.goto("https://www.zomato.com/partners/onlineordering/customerIssues/", 
                             wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(8000)  # Increased wait time for headless
                    
                    # Wait for page to be fully loaded
                    page.wait_for_load_state("networkidle", timeout=30000)
                    
                except Exception as nav_error:
                    print(f"❌ Navigation failed: {nav_error}")
                    print("🔄 Retrying navigation...")
                    page.goto("https://www.zomato.com/partners/onlineordering/customerIssues/", 
                             wait_until="load", timeout=60000)
                    page.wait_for_timeout(10000)

                # Handle potential popups/overlays with better targeting
                print("🔧 Handling potential popups...")
                try:
                    # Try to dismiss any modal or overlay
                    page.evaluate("""
                        // Close any potential modals
                        const modals = document.querySelectorAll('[role="dialog"], .modal, .overlay, .popup');
                        modals.forEach(modal => {
                            if (modal.style) modal.style.display = 'none';
                        });
                        
                        // Click dismiss buttons
                        const dismissButtons = document.querySelectorAll('[aria-label*="close"], [aria-label*="dismiss"], .close, .dismiss');
                        dismissButtons.forEach(btn => {
                            if (btn.click) btn.click();
                        });
                    """)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

                for idx, outlet_id in enumerate(OUTLET_IDS):
                    print(f"\n🔁 Processing Outlet ID: {outlet_id} ({idx + 1}/{len(OUTLET_IDS)})")

                    try:
                        # Wait for and click outlet dropdown with better error handling
                        dropdown_selector = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[1]/div/div[2]/span"
                        
                        if not wait_for_element_with_retry(page, dropdown_selector, timeout=15000):
                            print(f"❌ Could not find outlet dropdown for {outlet_id}. Skipping.")
                            continue
                        
                        # Scroll to element and click
                        page.locator(dropdown_selector).scroll_into_view_if_needed()
                        page.wait_for_timeout(1000)
                        page.click(dropdown_selector)
                        page.wait_for_timeout(2000)  # Increased wait time

                        # Clear previous selection if not first outlet
                        if idx > 0:
                            prev_id = OUTLET_IDS[idx - 1]
                            try:
                                page.locator(f"text=ID: {prev_id}").first.click()
                                page.wait_for_timeout(1000)
                            except:
                                pass

                        # Enter outlet ID with better targeting
                        input_selector = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[2]/div[1]/div/div/div/div/div/div/div/input"
                        
                        # Clear and fill input
                        page.locator(input_selector).clear()
                        page.wait_for_timeout(500)
                        page.fill(input_selector, outlet_id)
                        page.wait_for_timeout(2000)
                        
                        # Select the outlet
                        page.locator(f"text=ID: {outlet_id}").first.click()
                        page.wait_for_timeout(1500)

                        # Click apply/search button
                        apply_button_selector = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[2]/div[4]/div[2]"
                        page.click(apply_button_selector)
                        page.wait_for_timeout(5000)  # Increased wait time for results

                        # Find view details buttons with better error handling
                        try:
                            view_buttons = page.locator(".css-1ttmdgu > .css-c4te0e > .css-19i1v5i").filter(has_text="View details")
                            total = view_buttons.count()
                            print(f"🔍 Found {total} complaints for outlet {outlet_id}.")
                        except Exception as e:
                            print(f"⚠️ Error finding view buttons: {e}")
                            total = 0

                        if total == 0:
                            print(f"ℹ️ No complaints found for outlet {outlet_id}. Moving to next outlet.")
                            continue

                        for i in range(total):
                            try:
                                print(f"\n🕵️ Processing complaint {i+1}/{total} for outlet {outlet_id}")
                                
                                # Re-locate view buttons to avoid stale references
                                view_buttons = page.locator(".css-1ttmdgu > .css-c4te0e > .css-19i1v5i").filter(has_text="View details")
                                
                                if view_buttons.count() <= i:
                                    print(f"⚠️ Not enough 'View details' buttons found for complaint {i+1}/{total}. Skipping.")
                                    continue

                                # Click view details with better error handling
                                try:
                                    view_buttons.nth(i).scroll_into_view_if_needed()
                                    page.wait_for_timeout(1000)
                                    view_buttons.nth(i).click()
                                    page.wait_for_timeout(5000)  # Increased wait time for modal
                                except Exception as click_error:
                                    print(f"⚠️ Failed to click view details button: {click_error}")
                                    continue

                                # Try to click "Order details" if available
                                try:
                                    order_details_xpath = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[2]/div/div[1]/div[3]/div[1]/div/div[2]/div/div[2]"
                                    if page.locator(order_details_xpath).first.is_visible(timeout=3000):
                                        page.locator(order_details_xpath).first.click()
                                        page.wait_for_timeout(2000)
                                except Exception:
                                    print("    ℹ️ 'Order details' not found or not clickable. Continuing...")

                                # Extract complaint text with better error handling
                                try:
                                    raw_text = page.locator("body").inner_text(timeout=15000)
                                except Exception as text_error:
                                    print(f"⚠️ Failed to extract text: {text_error}")
                                    continue

                                # Parse with Gemini
                                parsed_complaint = parse_complaint_with_gemini(raw_text, outlet_id)

                                if parsed_complaint:
                                    complaint_id = parsed_complaint.get("Complaint ID", "").strip()
                                    status = parsed_complaint.get("Status", "").upper()

                                    if complaint_id:
                                        print(f"✅ Parsed complaint {complaint_id} (Status: {status})")
                                        append_complaint_to_sheet(sheet, parsed_complaint, seen_hashes)
                                    else:
                                        print(f"⚠️ Skipped: No valid Complaint ID found")
                                else:
                                    print(f"❌ Failed to parse complaint {i+1}")

                                # Close modal with multiple methods
                                try:
                                    page.keyboard.press("Escape")
                                    page.wait_for_timeout(2000)
                                    
                                    # Also try clicking close button if escape doesn't work
                                    close_buttons = page.locator("[aria-label*='close'], .close, [data-testid*='close']")
                                    if close_buttons.count() > 0:
                                        close_buttons.first.click()
                                        page.wait_for_timeout(1000)
                                except Exception:
                                    pass

                                # Verify modal is closed and refresh page for next complaint
                                if i < total - 1:  # Don't refresh on last complaint
                                    print("    🔄 Refreshing for next complaint...")
                                    page.reload(wait_until="domcontentloaded", timeout=60000)
                                    page.wait_for_timeout(5000)
                                    
                                    # Wait for stable state
                                    page.wait_for_load_state("networkidle", timeout=30000)

                                    # Handle popups after refresh
                                    try:
                                        page.evaluate("""
                                            const modals = document.querySelectorAll('[role="dialog"], .modal, .overlay, .popup');
                                            modals.forEach(modal => {
                                                if (modal.style) modal.style.display = 'none';
                                            });
                                        """)
                                        page.wait_for_timeout(1000)
                                    except:
                                        pass

                                    # Re-select outlet with better error handling
                                    try:
                                        page.click(dropdown_selector, timeout=10000)
                                        page.wait_for_timeout(2000)
                                        page.fill(input_selector, outlet_id)
                                        page.wait_for_timeout(2000)
                                        page.locator(f"text=ID: {outlet_id}").first.click()
                                        page.wait_for_timeout(1500)
                                        page.click(apply_button_selector)
                                        page.wait_for_timeout(5000)
                                    except Exception as reselect_error:
                                        print(f"⚠️ Error re-selecting outlet: {reselect_error}")
                                        break

                            except Exception as e:
                                print(f"❌ Error processing complaint {i+1}/{total} for outlet {outlet_id}: {e}")
                                # Try to close any open modals
                                try:
                                    page.keyboard.press("Escape")
                                    page.wait_for_timeout(1000)
                                except:
                                    pass
                                continue

                    except Exception as e:
                        print(f"❌ Error processing outlet {outlet_id}: {e}")
                        continue

                    print(f"✅ Completed outlet {outlet_id}")
                    page.wait_for_timeout(3000)

            except Exception as e:
                print(f"❌ Critical error during scraping: {e}")
            finally:
                print("🧹 Cleaning up browser...")
                try:
                    context.close()
                except:
                    pass
                try:
                    browser.close()
                except:
                    pass

    except Exception as e:
        print(f"❌ Failed to initialize Playwright: {e}")

    print("✅ Scraping completed successfully!")

if __name__ == "__main__":
    scrape_and_push_complaints()
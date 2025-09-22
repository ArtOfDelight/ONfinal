from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os

# ========== Google Sheet Setup ==========
CREDENTIALS_FILE = "service_account.json"
SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Zomato Live"

def init_gsheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)

# ========== Dropdowns & Metrics ==========
DROPDOWNS_TO_CLICK = [
    "Average Rating", "Bad Orders", "Online %",
    "Kitchen Preparation Time", "Menu to Order",
    "New Users", "Sales from Ads"
]

METRICS = [
    "Delivered orders", "Market share", "Average rating", "Rated orders", "Bad orders",
    "Rejected orders", "Delayed orders", "Poor rated orders", "Total complaints",
    "Online %", "Offline time", "Kitchen preparation time", "Food order ready accuracy",
    "Impressions", "Impressions to menu", "Menu to order", "Menu to cart", "Cart to order",
    "New users", "Repeat users", "Lapsed users", "Ads orders"
]

# ========== Utility Functions ==========
def click_dropdowns_in_frames(page, labels):
    for label in labels:
        found = False
        for frame in page.frames:
            try:
                element = frame.locator(f"text={label}").first
                if element.is_visible():
                    element.click()
                    page.wait_for_timeout(1000)
                    print(f"✅ Clicked '{label}'")
                    found = True
                    break
            except:
                continue
        if not found:
            print(f"⚠️ '{label}' not found in any frame")

def select_yesterday_date_zomato(page):
    """Selects yesterday's date in Zomato's calendar using rdrDayNumber class."""
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_day = yesterday.day
    yesterday_month = yesterday.strftime("%B")
    yesterday_year = yesterday.year
    
    print(f"Selecting yesterday's date: {yesterday_day} {yesterday_month} {yesterday_year}")
    
    try:
        # Wait for calendar to load
        page.wait_for_timeout(2000)
        
        # Get all calendar day buttons with rdrDayNumber class
        day_buttons = page.locator("button.rdrDay .rdrDayNumber span").all()
        
        if not day_buttons:
            print("No calendar day buttons found")
            return False
        
        print(f"Found {len(day_buttons)} calendar day buttons")
        
        # Parse all day numbers to identify calendar structure
        day_numbers = []
        for i, button in enumerate(day_buttons):
            try:
                day_text = button.inner_text().strip()
                if day_text.isdigit():
                    day_numbers.append((i, int(day_text)))
                else:
                    day_numbers.append((i, 0))  # Invalid day
            except:
                day_numbers.append((i, 0))  # Failed to get text
        
        print(f"Day numbers found: {[num for _, num in day_numbers if num > 0]}")
        
        # Calculate button offset (detect previous month days)
        button_offset = 0
        if day_numbers and day_numbers[0][1] > 20:  # First day > 20 indicates previous month
            # Find where current month starts (when numbers reset to 1)
            for i, (btn_idx, day_num) in enumerate(day_numbers[1:], 1):
                if day_num == 1 and day_numbers[i-1][1] > day_num:
                    button_offset = i
                    print(f"Calendar starts with previous month days. Current month starts at button {i}")
                    break
        
        # Find target button position
        target_button_index = None
        for btn_idx, day_num in day_numbers:
            if day_num == yesterday_day and btn_idx >= button_offset:
                target_button_index = btn_idx
                break
        
        if target_button_index is None:
            print(f"Could not find button for day {yesterday_day}")
            return False
        
        # Click the target button
        target_button = day_buttons[target_button_index]
        
        # Get button text to verify
        try:
            button_text = target_button.inner_text()
            print(f"Clicking button with text: '{button_text}' at position {target_button_index}")
        except:
            print(f"Clicking button at position {target_button_index}")
        
        # Click the date button
        target_button.click()
        page.wait_for_timeout(1000)
        
        # Click it again to ensure selection (double-click pattern)
        target_button.click()
        page.wait_for_timeout(1000)
        
        print(f"Successfully selected yesterday's date: {yesterday_day}")
        
        # Click Apply button to confirm date selection
        print("Clicking Apply button to confirm date selection...")
        apply_clicked = False
        
        # Try the specific XPath first
        try:
            apply_button = page.locator("xpath=//*[@id='modal']/div/div/div[2]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div[3]/div/div/div[2]/div")
            if apply_button.is_visible():
                # Get button text to verify
                try:
                    button_text = apply_button.inner_text()
                    print(f"Found Apply button with text: '{button_text}'")
                except:
                    print("Could not retrieve Apply button text")
                
                apply_button.click()
                print("Apply button clicked using specific XPath.")
                apply_clicked = True
                page.wait_for_timeout(2000)
            else:
                print("Apply button XPath not visible")
        except Exception as e:
            print(f"Apply button XPath failed: {e}")
        
        if not apply_clicked:
            print("Warning: Could not click Apply button using XPath")
            return False
        
        print("Date selection and confirmation completed successfully")
        return True
        
    except Exception as e:
        print(f"Error selecting yesterday's date: {e}")
        return False

def extract_third_last_values(text, metrics):
    result = {}
    for metric in metrics:
        pattern = rf"{re.escape(metric)}\s*\n((?:.*\n)+?)\n"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            numbers = re.findall(r"[\d,.]+%?|₹[\d,.]+", match.group(1))
            if len(numbers) >= 3:
                result[metric] = numbers[0]  # First value = third last column in report
            elif numbers:
                result[metric] = numbers[0]
            else:
                result[metric] = "N/A"
        else:
            result[metric] = "Not found"
    return result

# ========== Main Scraper ==========
def scrape_multiple_outlets(outlet_ids, report_date_label):
    sheet = init_gsheet()

    with sync_playwright() as p:
        browser = None
        context = None
        page = None
        
        # Try multiple browser configurations to avoid protocol errors
        browser_configs = [
            # Config 1: Chromium with maximum HTTP2 fixes
            {
                'browser_type': 'chromium',
                'args': [
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-http2",
                    "--disable-features=VizDisplayCompositor",
                    "--disable-web-security",
                    "--disable-features=TranslateUI",
                    "--disable-dev-shm-usage",
                    "--allow-running-insecure-content",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                    "--disable-ipc-flooding-protection",
                    "--force-http1"  # Force HTTP1 instead of HTTP2
                ]
            },
            # Config 2: Firefox fallback
            {
                'browser_type': 'firefox',
                'args': []
            },
            # Config 3: Webkit fallback
            {
                'browser_type': 'webkit', 
                'args': []
            }
        ]
        
        page_loaded = False
        
        for config in browser_configs:
            try:
                print(f"Trying {config['browser_type']} browser...")
                
                if config['browser_type'] == 'chromium':
                    browser = p.chromium.launch(headless=True, args=config['args'])
                elif config['browser_type'] == 'firefox':
                    browser = p.firefox.launch(headless=True)
                elif config['browser_type'] == 'webkit':
                    browser = p.webkit.launch(headless=True)
                
                # Enhanced context with multiple fallback strategies
                context = browser.new_context(
                    storage_state="zomato_login.json" if os.path.exists("zomato_login.json") else None,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    ignore_https_errors=True,
                    java_script_enabled=True,
                    accept_downloads=False,
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Cache-Control": "max-age=0"
                    }
                )
                
                page = context.new_page()
                
                # Set additional page properties
                page.set_default_navigation_timeout(120000)  # 2 minutes timeout
                page.set_default_timeout(60000)  # 1 minute for elements
                
                print("Navigating to Zomato Partner Reporting Page...")
                
                # Multiple URL attempts with different strategies
                urls_to_try = [
                    "https://www.zomato.com/partners/onlineordering/reporting/",
                    "https://www.zomato.com/partners/onlineordering/", 
                    "https://www.zomato.com/partners/",
                    "https://partners.zomato.com/onlineordering/reporting/",
                    "https://partners.zomato.com/"
                ]
                
                for url_idx, url in enumerate(urls_to_try):
                    print(f"Trying URL {url_idx + 1}/{len(urls_to_try)}: {url}")
                    
                    try:
                        # Strategy 1: Load with commit wait
                        page.goto(url, wait_until='commit', timeout=30000)
                        page.wait_for_timeout(2000)
                        page.wait_for_load_state('domcontentloaded', timeout=30000) 
                        print(f"Successfully loaded with commit strategy: {url}")
                        page_loaded = True
                        break
                        
                    except Exception as e1:
                        print(f"Commit strategy failed: {e1}")
                        try:
                            # Strategy 2: Load with domcontentloaded
                            page.goto(url, wait_until='domcontentloaded', timeout=45000)
                            print(f"Successfully loaded with domcontentloaded: {url}")
                            page_loaded = True
                            break
                            
                        except Exception as e2:
                            print(f"Domcontentloaded strategy failed: {e2}")
                            try:
                                # Strategy 3: Load with networkidle
                                page.goto(url, wait_until='networkidle', timeout=60000)
                                print(f"Successfully loaded with networkidle: {url}")
                                page_loaded = True
                                break
                                
                            except Exception as e3:
                                print(f"Networkidle strategy failed: {e3}")
                                try:
                                    # Strategy 4: Basic load without wait conditions
                                    page.goto(url, timeout=30000)
                                    page.wait_for_timeout(3000)  # Just wait 3 seconds
                                    print(f"Successfully loaded with basic strategy: {url}")
                                    page_loaded = True
                                    break
                                    
                                except Exception as e4:
                                    print(f"Basic strategy failed: {e4}")
                                    continue
                
                if page_loaded:
                    break  # Success with this browser config
                else:
                    # Clean up failed attempt
                    if browser:
                        browser.close()
                        browser = None
                        
            except Exception as browser_error:
                print(f"{config['browser_type']} browser failed completely: {browser_error}")
                if browser:
                    try:
                        browser.close()
                    except:
                        pass
                    browser = None
                continue
        
        if not page_loaded:
            raise Exception("All browsers and strategies failed. Cannot access Zomato partner page.")
        
        print(f"Successfully connected using {config['browser_type']} browser")

        page.wait_for_timeout(5000)

        try:
            okay_btn = page.locator("text=Okay")
            if okay_btn.is_visible():
                okay_btn.click()
                page.wait_for_timeout(1000)
        except:
            page.mouse.click(500, 300)

        try:
            print("🖱️ Clicking on 'View Business Reports'...")
            report_btn = page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[1]/div[2]")
            report_btn.click()
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"❌ Error clicking View Business Reports: {e}")

        for idx, outlet_id in enumerate(outlet_ids):
            print(f"\n🔁 Processing ID: {outlet_id}")

            # Open All Outlets dropdown
            page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[2]/div/div/div/span/span[2]").click()
            page.wait_for_timeout(1000)

            if idx == 0:
                try:
                    print("Switching to Daily view...")
                    page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[2]/div/div/div[1]/div/div[1]/div[2]/span/span").click()
                    page.wait_for_timeout(2000)
                    
                    print("Opening calendar by clicking 'Select date range'...")
                    # Click on the calendar opener element
                    calendar_opener_clicked = False
                    
                    # Try the specific XPath first
                    try:
                        calendar_opener = page.locator("xpath=//*[@id='modal']/div/div/div[2]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div[1]/div/span/span")
                        if calendar_opener.is_visible():
                            # Get button text to verify
                            try:
                                button_text = calendar_opener.inner_text()
                                print(f"Found calendar opener with text: '{button_text}'")
                            except:
                                print("Could not retrieve calendar opener text")
                            
                            calendar_opener.click()
                            print("Calendar opened using specific XPath.")
                            calendar_opener_clicked = True
                            page.wait_for_timeout(2000)
                        else:
                            print("Calendar opener XPath not visible")
                    except Exception as e:
                        print(f"Calendar opener XPath failed: {e}")
                    
                    # Try alternative selectors if XPath fails
                    if not calendar_opener_clicked:
                        print("Trying alternative selectors for calendar opener...")
                        alternative_selectors = [
                            "text=Select date range",
                            "span:has-text('Select date range')",
                            "[class*='date']:has-text('Select')",
                            "[class*='range']:has-text('Select')"
                        ]
                        
                        for selector in alternative_selectors:
                            try:
                                element = page.locator(selector).first
                                if element.is_visible():
                                    element.click()
                                    print(f"Calendar opened using selector: {selector}")
                                    calendar_opener_clicked = True
                                    page.wait_for_timeout(2000)
                                    break
                            except:
                                continue
                    
                    if not calendar_opener_clicked:
                        print("Could not find calendar opener, proceeding with date selection...")
                    
                    print("Automatically selecting yesterday's date...")
                    if not select_yesterday_date_zomato(page):
                        print("Automatic date selection failed, falling back to manual selection")
                        input(f"\nPlease change the date to {report_date_label} manually on dashboard, then press Enter...\n")
                    else:
                        print("Successfully selected yesterday's date automatically")
                        
                except Exception as e:
                    print(f"Error in date selection: {e}")
                    print("Falling back to manual date selection")
                    input(f"\nPlease change the date to {report_date_label} manually on dashboard, then press Enter...\n")
            else:
                print(f"🔁 Deselecting previously selected outlet ID: {outlet_ids[idx - 1]}")
                try:
                    dropdown_toggle = page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span")
                    dropdown_toggle.click()
                    page.wait_for_timeout(1000)

                    prev_id_locator = page.locator(f"text={outlet_ids[idx - 1]}").first
                    if prev_id_locator.is_visible():
                        prev_id_locator.click()
                        print("✅ Deselected previous ID.")
                    else:
                        print("⚠️ Previous ID not visible.")
                    page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"⚠️ Error deselecting previous ID: {e}")

            # Open dropdown again to select current ID
            page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span").click()
            page.wait_for_timeout(1000)

            # Search and select current ID
            search_box = page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[2]/div[1]/div/input")
            search_box.fill("")
            page.wait_for_timeout(500)
            print(f"🔍 Searching for outlet ID: {outlet_id}")
            search_box.fill(str(outlet_id))
            page.wait_for_timeout(2000)

            try:
                match_locator = page.locator(f"text={outlet_id}").first
                if match_locator.is_visible():
                    match_locator.click()
                    page.wait_for_timeout(1000)
                    print("✅ Selected outlet.")
                else:
                    print("❌ No match found for this ID.")
            except Exception as e:
                print(f"❌ Could not select outlet for ID {outlet_id}: {e}")

            print("📌 Applying outlet filter...")
            page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[3]/div[2]").click()
            page.wait_for_timeout(3000)

            print("🔽 Expanding dropdowns...")
            click_dropdowns_in_frames(page, DROPDOWNS_TO_CLICK)

            print("📄 Extracting data...")
            text_content = ""
            for frame in page.frames:
                try:
                    text = frame.locator("body").inner_text()
                    if text:
                        text_content += text + "\n\n"
                except:
                    continue

            parsed_data = extract_third_last_values(text_content, METRICS)

            print(f"\n📄 Summary for {outlet_id}:\n")
            for k, v in parsed_data.items():
                print(f"{k}: {v}")
                try:
                    # Clean and convert RID and metric values
                    outlet_id_int = int(outlet_id)
                    if isinstance(v, str):
                        if '₹' in v:
                            cleaned_value = float(v.replace('₹', '').replace(',', ''))
                        elif '%' in v:
                            cleaned_value = float(v.replace('%', '').replace(',', ''))
                        else:
                            cleaned_value = float(v.replace(',', ''))
                    else:
                        cleaned_value = v

                    # Append row as values
                    sheet.append_row(
                        [report_date_label, outlet_id_int, k, cleaned_value, "Zomato"],
                        value_input_option='USER_ENTERED'
                    )
                except Exception as e:
                    print(f"⚠️ Google Sheet error for {k}: {e}")

        input("\n✅ Done. Press Enter to exit...")
        browser.close()

# ========== Run Script ==========
if __name__ == "__main__":
    # Automatically set report date to yesterday
    report_date = datetime.now() - timedelta(days=1)
    report_date_label = report_date.strftime("%Y-%m-%d")

    outlet_ids = [
        19418061, 19595967, 57750, 19501520,
        19501574, 20547934, 21134281, 20183353,
        19595894, 18422924, 20647827
    ]

    scrape_multiple_outlets(outlet_ids, report_date_label)
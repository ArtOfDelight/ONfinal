from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json

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

# ========== Authentication Helper ==========
def get_login_state():
    """Get login state for Zomato authentication"""
    login_file = "zomato_login.json"
    
    # Check if login file exists
    if os.path.exists(login_file):
        try:
            with open(login_file, 'r') as f:
                login_data = json.load(f)
                print("✅ Found existing zomato_login.json file")
                return login_data
        except Exception as e:
            print(f"⚠️ Error reading zomato_login.json: {e}")
    
    # Check for environment variables as fallback
    zomato_cookies = os.getenv('ZOMATO_COOKIES')
    if zomato_cookies:
        try:
            login_data = json.loads(zomato_cookies)
            print("✅ Using ZOMATO_COOKIES environment variable")
            return login_data
        except Exception as e:
            print(f"⚠️ Error parsing ZOMATO_COOKIES: {e}")
    
    print("⚠️ No authentication found - will need manual login")
    return None

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
        page.wait_for_timeout(3000)
        
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
    login_state = get_login_state()
    
    print(f"🚀 Starting scraper for {len(outlet_ids)} outlets on {report_date_label}")
    print(f"📍 Environment: {'Render' if os.getenv('RENDER') else 'Local'}")

    with sync_playwright() as p:
        browser = None
        context = None
        page = None
        
        # Render-optimized browser configuration
        try:
            print("🌐 Launching browser optimized for Render environment...")
            
            # Render-specific browser args
            browser_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox", 
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--single-process",  # Important for Render
                "--disable-gpu",
                "--disable-http2",
                "--disable-features=VizDisplayCompositor,TranslateUI,BlinkGenPropertyTrees",
                "--disable-web-security",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-extensions",
                "--disable-plugins",
                "--disable-images",  # Speed up loading
                "--disable-javascript",  # Will enable later if needed
                "--force-http1"
            ]
            
            browser = p.chromium.launch(
                headless=True,
                args=browser_args
            )
            
            # Enhanced context for Render
            context_options = {
                "storage_state": login_state,
                "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "ignore_https_errors": True,
                "java_script_enabled": True,
                "accept_downloads": False,
                "bypass_csp": True,  # Bypass content security policy
                "extra_http_headers": {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate",  # Removed br for compatibility
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "no-cache"
                }
            }
            
            context = browser.new_context(**context_options)
            page = context.new_page()
            
            # Longer timeouts for Render's slower environment
            page.set_default_navigation_timeout(180000)  # 3 minutes
            page.set_default_timeout(90000)  # 1.5 minutes for elements
            
            print("✅ Browser successfully launched")
                
        except Exception as e:
            print(f"❌ Browser launch failed: {e}")
            raise Exception(f"Cannot initialize browser: {e}")

        # Navigate with multiple strategies
        print("🔗 Navigating to Zomato Partner Reporting Page...")
        page_loaded = False
        
        urls_to_try = [
            "https://www.zomato.com/partners/onlineordering/reporting/",
            "https://www.zomato.com/partners/onlineordering/",
            "https://www.zomato.com/partners/",
        ]
        
        for url in urls_to_try:
            print(f"🔄 Trying URL: {url}")
            
            for attempt in range(3):  # 3 attempts per URL
                try:
                    print(f"   Attempt {attempt + 1}/3...")
                    
                    # Try basic navigation first
                    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    
                    if response and response.ok:
                        print(f"✅ Successfully loaded: {url}")
                        page.wait_for_timeout(3000)  # Additional wait
                        page_loaded = True
                        break
                    else:
                        print(f"⚠️ Response not OK: {response.status if response else 'No response'}")
                        
                except Exception as e:
                    print(f"   ❌ Attempt {attempt + 1} failed: {e}")
                    if attempt < 2:  # Not the last attempt
                        page.wait_for_timeout(5000)  # Wait before retry
                        
            if page_loaded:
                break
        
        if not page_loaded:
            # Last resort: try to load any page and check if we're logged in
            try:
                print("🔄 Last resort: trying basic Zomato partners page...")
                page.goto("https://www.zomato.com/partners/", timeout=60000)
                page.wait_for_timeout(5000)
                page_loaded = True
                print("✅ Basic page loaded - will attempt to navigate to reports")
            except Exception as e:
                print(f"❌ All navigation attempts failed: {e}")
                raise Exception("Cannot access Zomato partner pages - check authentication")

        print("🔍 Checking authentication status...")
        page.wait_for_timeout(5000)

        # Check if we need to login
        current_url = page.url
        print(f"Current URL: {current_url}")
        
        if "login" in current_url or "signin" in current_url:
            print("❌ Not authenticated - need to update login credentials")
            if os.getenv('RENDER'):
                print("🏗️ Running on Render - authentication must be handled via environment variables")
                print("Please set ZOMATO_COOKIES environment variable with valid session data")
                raise Exception("Authentication required - set ZOMATO_COOKIES environment variable")
            else:
                print("💻 Running locally - manual intervention required")
                input("Please login manually in the browser, then press Enter to continue...")

        # Try to dismiss any popups
        try:
            okay_btn = page.locator("text=Okay")
            if okay_btn.is_visible(timeout=5000):
                okay_btn.click()
                page.wait_for_timeout(1000)
                print("✅ Dismissed popup")
        except:
            pass

        # Navigate to reports if not already there
        if "reporting" not in page.url:
            try:
                print("🖱️ Clicking on 'View Business Reports'...")
                report_selectors = [
                    "text=View Business Reports",
                    "text=Business Reports", 
                    "text=Reports",
                    "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[1]/div[2]"
                ]
                
                clicked = False
                for selector in report_selectors:
                    try:
                        element = page.locator(selector)
                        if element.is_visible(timeout=10000):
                            element.click()
                            page.wait_for_timeout(3000)
                            print(f"✅ Clicked report button using: {selector}")
                            clicked = True
                            break
                    except:
                        continue
                
                if not clicked:
                    print("⚠️ Could not find report button - manual navigation may be needed")
                    if not os.getenv('RENDER'):
                        input("Please navigate to the reports page manually, then press Enter...")
                        
            except Exception as e:
                print(f"❌ Error navigating to reports: {e}")

        # Process outlets
        for idx, outlet_id in enumerate(outlet_ids):
            print(f"\n🔁 Processing outlet {idx + 1}/{len(outlet_ids)}: {outlet_id}")

            try:
                # Open All Outlets dropdown
                dropdown_selector = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[2]/div/div/div/span/span[2]"
                page.locator(dropdown_selector).click(timeout=30000)
                page.wait_for_timeout(2000)

                if idx == 0:
                    # Date selection logic (only on first iteration)
                    try:
                        print("📅 Setting up date selection...")
                        
                        # Switch to Daily view
                        daily_view_selector = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[2]/div/div/div[1]/div/div[1]/div[2]/span/span"
                        page.locator(daily_view_selector).click(timeout=20000)
                        page.wait_for_timeout(3000)
                        
                        # Open calendar
                        calendar_selectors = [
                            "xpath=//*[@id='modal']/div/div/div[2]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div[1]/div/span/span",
                            "text=Select date range",
                            "span:has-text('Select date range')"
                        ]
                        
                        calendar_opened = False
                        for selector in calendar_selectors:
                            try:
                                element = page.locator(selector)
                                if element.is_visible(timeout=10000):
                                    element.click()
                                    page.wait_for_timeout(2000)
                                    print(f"✅ Calendar opened using: {selector}")
                                    calendar_opened = True
                                    break
                            except:
                                continue
                        
                        if calendar_opened:
                            if not select_yesterday_date_zomato(page):
                                print("⚠️ Automatic date selection failed")
                        else:
                            print("⚠️ Could not open calendar automatically")
                            
                    except Exception as e:
                        print(f"⚠️ Date selection error: {e}")

                else:
                    # Deselect previous outlet
                    print(f"🔄 Deselecting previous outlet: {outlet_ids[idx - 1]}")
                    try:
                        prev_dropdown = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span"
                        page.locator(prev_dropdown).click(timeout=20000)
                        page.wait_for_timeout(2000)

                        prev_id_element = page.locator(f"text={outlet_ids[idx - 1]}").first
                        if prev_id_element.is_visible(timeout=10000):
                            prev_id_element.click()
                            page.wait_for_timeout(1000)
                            print("✅ Previous outlet deselected")
                    except Exception as e:
                        print(f"⚠️ Error deselecting previous outlet: {e}")

                # Select current outlet
                print(f"🔍 Searching for outlet: {outlet_id}")
                
                # Open dropdown for current selection
                current_dropdown = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span"
                page.locator(current_dropdown).click(timeout=20000)
                page.wait_for_timeout(2000)

                # Search for outlet
                search_selectors = [
                    "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[2]/div[1]/div/input",
                    "input[placeholder*='Search']",
                    "input[type='text']"
                ]
                
                search_found = False
                for selector in search_selectors:
                    try:
                        search_box = page.locator(selector)
                        if search_box.is_visible(timeout=10000):
                            search_box.fill("")
                            page.wait_for_timeout(500)
                            search_box.fill(str(outlet_id))
                            page.wait_for_timeout(3000)
                            print(f"✅ Searched using: {selector}")
                            search_found = True
                            break
                    except:
                        continue

                if not search_found:
                    print("⚠️ Could not find search box")
                    continue

                # Select the outlet
                try:
                    outlet_element = page.locator(f"text={outlet_id}").first
                    if outlet_element.is_visible(timeout=15000):
                        outlet_element.click()
                        page.wait_for_timeout(2000)
                        print("✅ Outlet selected")
                    else:
                        print(f"❌ Outlet {outlet_id} not found in dropdown")
                        continue
                except Exception as e:
                    print(f"❌ Error selecting outlet: {e}")
                    continue

                # Apply filter
                print("📌 Applying outlet filter...")
                apply_filter_selector = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[3]/div[2]"
                page.locator(apply_filter_selector).click(timeout=20000)
                page.wait_for_timeout(5000)  # Longer wait for data to load

                # Expand dropdowns
                print("🔽 Expanding dropdowns...")
                click_dropdowns_in_frames(page, DROPDOWNS_TO_CLICK)

                # Extract data
                print("📊 Extracting metrics data...")
                text_content = ""
                for frame in page.frames:
                    try:
                        text = frame.locator("body").inner_text()
                        if text and len(text) > 100:  # Only consider substantial content
                            text_content += text + "\n\n"
                    except:
                        continue

                if not text_content:
                    # Try main page if frames don't work
                    try:
                        text_content = page.locator("body").inner_text()
                    except:
                        print("❌ Could not extract any text content")
                        continue

                parsed_data = extract_third_last_values(text_content, METRICS)

                # Log and save data
                print(f"\n📊 Data for outlet {outlet_id}:")
                successful_saves = 0
                
                for metric, value in parsed_data.items():
                    print(f"  {metric}: {value}")
                    
                    try:
                        # Clean and convert values
                        outlet_id_int = int(outlet_id)
                        if isinstance(value, str) and value not in ["N/A", "Not found"]:
                            if '₹' in value:
                                cleaned_value = float(value.replace('₹', '').replace(',', ''))
                            elif '%' in value:
                                cleaned_value = float(value.replace('%', '').replace(',', ''))
                            else:
                                cleaned_value = float(value.replace(',', ''))
                        else:
                            cleaned_value = value

                        # Append to Google Sheet
                        sheet.append_row(
                            [report_date_label, outlet_id_int, metric, cleaned_value, "Zomato"],
                            value_input_option='USER_ENTERED'
                        )
                        successful_saves += 1
                        
                    except Exception as e:
                        print(f"  ⚠️ Sheet error for {metric}: {e}")

                print(f"✅ Successfully saved {successful_saves}/{len(parsed_data)} metrics for outlet {outlet_id}")

            except Exception as e:
                print(f"❌ Error processing outlet {outlet_id}: {e}")
                continue

        print(f"\n🎉 Scraping completed for {len(outlet_ids)} outlets")
        
        # Don't wait for input on Render
        if not os.getenv('RENDER'):
            input("\n✅ All outlets processed. Press Enter to exit...")
            
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
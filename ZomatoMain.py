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
def check_auth_file():
    """Check if authentication file exists and get path"""
    auth_file = "zomato_login.json"
    if os.path.exists(auth_file):
        print(f"✅ Authentication file found: {auth_file}")
        try:
            with open(auth_file, 'r') as f:
                data = json.load(f)
                cookie_count = len(data.get('cookies', []))
                print(f"📝 Contains {cookie_count} cookies")
                return auth_file
        except Exception as e:
            print(f"⚠️ Error reading auth file: {e}")
            return None
    else:
        print(f"❌ Authentication file not found: {auth_file}")
        return None

def validate_page_login(page):
    """Quick check if we're logged in"""
    try:
        current_url = page.url
        print(f"Current URL: {current_url}")
        
        # Check if on login page
        if any(keyword in current_url.lower() for keyword in ['login', 'signin', 'auth']):
            print("❌ On login page - not authenticated")
            return False
        
        # Look for partner indicators
        try:
            # Quick check for partner elements
            if page.locator("text=Partner").first.is_visible(timeout=5000):
                print("✅ Partner element found - likely logged in")
                return True
        except:
            pass
            
        print("⚠️ Login status unclear")
        return True  # Assume logged in if not clearly on login page
        
    except Exception as e:
        print(f"Error checking login: {e}")
        return True

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
    
    print(f"🚀 Starting Zomato scraper")
    print(f"📍 Environment: {'Render' if os.getenv('RENDER') else 'Local'}")
    print(f"📅 Date: {report_date_label}")

    # Check authentication
    auth_file = check_auth_file()

    with sync_playwright() as p:
        browser = None
        context = None
        page = None
        page_loaded = False
        
        # Use the exact browser configuration that works from your original code
        browser_configs = [
            # Config 1: Your working Chromium config
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
                    "--force-http1"
                ]
            }
        ]
        
        for config in browser_configs:
            try:
                print(f"🌐 Launching {config['browser_type']} browser...")
                
                if config['browser_type'] == 'chromium':
                    browser = p.chromium.launch(headless=True, args=config['args'])
                
                # Create context with enhanced error handling
                print("🔐 Creating browser context...")
                try:
                    context_options = {
                        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "ignore_https_errors": True,
                        "java_script_enabled": True,
                        "accept_downloads": False,
                        "extra_http_headers": {
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
                    }
                    
                    # Try to add authentication if file exists
                    if auth_file:
                        try:
                            print("🔑 Applying authentication...")
                            context_options["storage_state"] = auth_file
                        except Exception as auth_error:
                            print(f"⚠️ Authentication failed, continuing without: {auth_error}")
                    
                    context = browser.new_context(**context_options)
                    print("✅ Browser context created successfully")
                    
                except Exception as context_error:
                    print(f"❌ Context creation failed: {context_error}")
                    # Try without authentication
                    try:
                        print("🔄 Retrying without authentication...")
                        context_options_basic = {
                            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "ignore_https_errors": True
                        }
                        context = browser.new_context(**context_options_basic)
                        print("✅ Basic context created successfully")
                    except Exception as basic_error:
                        print(f"❌ Basic context also failed: {basic_error}")
                        if browser:
                            browser.close()
                        continue
                
                page = context.new_page()
                
                # Set timeouts
                page.set_default_navigation_timeout(120000)  # 2 minutes timeout
                page.set_default_timeout(60000)  # 1 minute for elements
                
                print("🔗 Navigating to Zomato Partner Page...")
                
                # Multiple URL attempts with your working strategies
                urls_to_try = [
                    "https://www.zomato.com/partners/onlineordering/reporting/",
                    "https://www.zomato.com/partners/onlineordering/", 
                    "https://www.zomato.com/partners/",
                    "https://partners.zomato.com/onlineordering/reporting/",
                    "https://partners.zomato.com/"
                ]
                
                for url_idx, url in enumerate(urls_to_try):
                    print(f"🔄 Trying URL {url_idx + 1}/{len(urls_to_try)}: {url}")
                    
                    try:
                        # Strategy 1: Load with commit wait (your working method)
                        page.goto(url, wait_until='commit', timeout=30000)
                        page.wait_for_timeout(2000)
                        page.wait_for_load_state('domcontentloaded', timeout=30000) 
                        print(f"✅ Successfully loaded with commit strategy: {url}")
                        
                        # Quick login validation
                        if validate_page_login(page):
                            page_loaded = True
                            break
                        else:
                            print("❌ Not logged in, trying next URL...")
                            continue
                        
                    except Exception as e1:
                        print(f"Commit strategy failed: {e1}")
                        try:
                            # Strategy 2: Load with domcontentloaded
                            page.goto(url, wait_until='domcontentloaded', timeout=45000)
                            print(f"✅ Successfully loaded with domcontentloaded: {url}")
                            
                            if validate_page_login(page):
                                page_loaded = True
                                break
                            
                        except Exception as e2:
                            print(f"Domcontentloaded strategy failed: {e2}")
                            continue
                
                if page_loaded:
                    break  # Success with this browser config
                else:
                    # Clean up failed attempt
                    if browser:
                        browser.close()
                        browser = None
                        
            except Exception as browser_error:
                print(f"❌ {config['browser_type']} browser failed completely: {browser_error}")
                if browser:
                    try:
                        browser.close()
                    except:
                        pass
                    browser = None
                continue
        
        if not page_loaded:
            raise Exception("Could not load Zomato partner page. Check authentication.")
        
        print(f"✅ Successfully connected using {config['browser_type']} browser")

        # Rest of your working code
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
            # Use the corrected XPath with id="root"
            report_btn = page.locator("xpath=//*[@id='root']/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[1]/div[2]")
            report_btn.click()
            page.wait_for_timeout(2000)
            print("✅ Successfully clicked View Business Reports")
        except Exception as e:
            print(f"❌ Error clicking View Business Reports with corrected XPath: {e}")
            # Try alternative approaches
            print("🔍 Looking for alternative report buttons...")
            try:
                alt_selectors = [
                    "text=View Business Reports",
                    "text=Business Reports",
                    "text=Reports",
                    # Also try the old XPath as fallback
                    "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[1]/div[2]"
                ]
                
                clicked = False
                for selector in alt_selectors:
                    try:
                        element = page.locator(selector)
                        if element.is_visible(timeout=5000):
                            element.click()
                            print(f"✅ Clicked reports using: {selector}")
                            page.wait_for_timeout(2000)
                            clicked = True
                            break
                    except:
                        continue
                
                if not clicked:
                    print("⚠️ Could not find reports button with any method")
            except:
                pass

        # Process outlets using your working logic
        for idx, outlet_id in enumerate(outlet_ids):
            print(f"\n🔁 Processing outlet {idx + 1}/{len(outlet_ids)}: {outlet_id}")

            try:
                # Open All Outlets dropdown
                page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[2]/div/div/div/span/span[2]").click()
                page.wait_for_timeout(1000)

                if idx == 0:
                    # Date selection logic (your working code)
                    try:
                        print("📅 Switching to Daily view...")
                        page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[2]/div/div/div[1]/div/div[1]/div[2]/span/span").click()
                        page.wait_for_timeout(2000)
                        
                        print("Opening calendar by clicking 'Select date range'...")
                        calendar_opener_clicked = False
                        
                        try:
                            calendar_opener = page.locator("xpath=//*[@id='modal']/div/div/div[2]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div[1]/div/span/span")
                            if calendar_opener.is_visible():
                                calendar_opener.click()
                                print("Calendar opened using specific XPath.")
                                calendar_opener_clicked = True
                                page.wait_for_timeout(2000)
                        except Exception as e:
                            print(f"Calendar opener XPath failed: {e}")
                        
                        if not calendar_opener_clicked:
                            alternative_selectors = [
                                "text=Select date range",
                                "span:has-text('Select date range')"
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
                        
                        print("🗓️ Automatically selecting yesterday's date...")
                        if not select_yesterday_date_zomato(page):
                            print("⚠️ Automatic date selection failed")
                            if not os.getenv('RENDER'):
                                input(f"Please change the date to {report_date_label} manually, then press Enter...")
                            
                    except Exception as e:
                        print(f"⚠️ Error in date selection: {e}")

                else:
                    # Deselect previous outlet
                    print(f"🔄 Deselecting previous outlet: {outlet_ids[idx - 1]}")
                    try:
                        dropdown_toggle = page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span")
                        dropdown_toggle.click()
                        page.wait_for_timeout(1000)

                        prev_id_locator = page.locator(f"text={outlet_ids[idx - 1]}").first
                        if prev_id_locator.is_visible():
                            prev_id_locator.click()
                            print("✅ Deselected previous ID.")
                        page.wait_for_timeout(1000)
                    except Exception as e:
                        print(f"⚠️ Error deselecting previous ID: {e}")

                # Select current outlet
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
                        continue
                except Exception as e:
                    print(f"❌ Could not select outlet for ID {outlet_id}: {e}")
                    continue

                print("📌 Applying outlet filter...")
                page.locator("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[3]/div[2]").click()
                page.wait_for_timeout(3000)

                print("🔽 Expanding dropdowns...")
                click_dropdowns_in_frames(page, DROPDOWNS_TO_CLICK)

                print("📊 Extracting data...")
                text_content = ""
                for frame in page.frames:
                    try:
                        text = frame.locator("body").inner_text()
                        if text:
                            text_content += text + "\n\n"
                    except:
                        continue

                parsed_data = extract_third_last_values(text_content, METRICS)

                print(f"\n📊 Data for outlet {outlet_id}:")
                successful_saves = 0
                
                for k, v in parsed_data.items():
                    print(f"  {k}: {v}")
                    try:
                        # Clean and convert values
                        outlet_id_int = int(outlet_id)
                        if isinstance(v, str) and v not in ["N/A", "Not found"]:
                            if '₹' in v:
                                cleaned_value = float(v.replace('₹', '').replace(',', ''))
                            elif '%' in v:
                                cleaned_value = float(v.replace('%', '').replace(',', ''))
                            else:
                                cleaned_value = float(v.replace(',', ''))
                        else:
                            cleaned_value = v

                        # Append to Google Sheet
                        sheet.append_row(
                            [report_date_label, outlet_id_int, k, cleaned_value, "Zomato"],
                            value_input_option='USER_ENTERED'
                        )
                        successful_saves += 1
                        
                    except Exception as e:
                        print(f"  ⚠️ Sheet error for {k}: {e}")

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
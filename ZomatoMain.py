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

# ========== Authentication Debug Helper ==========
def debug_auth_file():
    """Debug authentication file loading with detailed logging"""
    print("🔍 Debugging authentication file...")
    
    # Check current working directory
    print(f"Current working directory: {os.getcwd()}")
    
    # List all files in current directory
    try:
        files = os.listdir('.')
        print(f"Files in current directory: {files}")
    except Exception as e:
        print(f"Error listing files: {e}")
    
    # Check if zomato_login.json exists
    auth_file = "zomato_login.json"
    if os.path.exists(auth_file):
        print(f"✅ {auth_file} exists")
        
        # Check file size
        try:
            file_size = os.path.getsize(auth_file)
            print(f"File size: {file_size} bytes")
        except Exception as e:
            print(f"Error getting file size: {e}")
        
        # Try to read and validate JSON
        try:
            with open(auth_file, 'r') as f:
                auth_data = json.load(f)
                print(f"✅ JSON is valid")
                print(f"JSON keys: {list(auth_data.keys())}")
                
                # Check if it has cookies (basic validation)
                if 'cookies' in auth_data:
                    print(f"✅ Contains cookies: {len(auth_data['cookies'])} cookies found")
                    
                    # Check for essential Zomato cookies
                    cookie_names = [cookie.get('name', '') for cookie in auth_data['cookies']]
                    essential_cookies = ['session_id', 'auth_token', 'user_id']
                    found_essential = [name for name in essential_cookies if any(name in cookie_name for cookie_name in cookie_names)]
                    print(f"Essential cookies found: {found_essential}")
                    
                else:
                    print("⚠️ No 'cookies' key found in JSON")
                
                if 'origins' in auth_data:
                    print(f"✅ Contains origins: {len(auth_data['origins'])} origins")
                else:
                    print("⚠️ No 'origins' key found in JSON")
                    
                return auth_data
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            return None
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            return None
    else:
        print(f"❌ {auth_file} does not exist")
        return None

def validate_login_state(page):
    """Check if we're actually logged in after loading auth"""
    print("🔐 Validating login state...")
    
    current_url = page.url
    print(f"Current URL: {current_url}")
    
    # Check if we're on a login page
    login_indicators = ['login', 'signin', 'auth', 'verify']
    if any(indicator in current_url.lower() for indicator in login_indicators):
        print("❌ Appears to be on login page - authentication failed")
        return False
    
    # Check page title for login indicators
    try:
        title = page.title()
        print(f"Page title: {title}")
        if any(indicator in title.lower() for indicator in ['login', 'sign in', 'authentication']):
            print("❌ Page title indicates login required")
            return False
    except Exception as e:
        print(f"Could not get page title: {e}")
    
    # Look for common logged-in indicators
    try:
        # Check for partner dashboard elements
        partner_indicators = [
            "text=Dashboard",
            "text=Business Reports", 
            "text=Partner",
            "text=Logout",
            "[data-testid*='partner']",
            "[class*='partner']"
        ]
        
        found_indicators = []
        for indicator in partner_indicators:
            try:
                element = page.locator(indicator).first
                if element.is_visible(timeout=3000):
                    found_indicators.append(indicator)
            except:
                continue
        
        if found_indicators:
            print(f"✅ Found login indicators: {found_indicators}")
            return True
        else:
            print("⚠️ No clear login indicators found")
            return False
            
    except Exception as e:
        print(f"Error checking login indicators: {e}")
        return False

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
    print(f"🏪 Outlets: {len(outlet_ids)} outlets to process")

    # Debug authentication file before starting browser
    auth_data = debug_auth_file()
    if not auth_data:
        print("❌ Cannot proceed without valid authentication")
        if os.getenv('RENDER'):
            raise Exception("Authentication file not found or invalid on Render")
        else:
            input("Press Enter after fixing authentication file...")
            auth_data = debug_auth_file()

    with sync_playwright() as p:
        browser = None
        
        try:
            print("🌐 Launching Chromium browser...")
            
            # Render-optimized browser args
            browser_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas", 
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-extensions"
            ]
            
            if os.getenv('RENDER'):
                browser_args.extend([
                    "--single-process",  # Important for Render
                    "--disable-http2",
                    "--force-http1"
                ])
            
            browser = p.chromium.launch(
                headless=True,
                args=browser_args
            )
            
            # Create context with authentication
            print("🔐 Creating browser context with authentication...")
            context = browser.new_context(
                storage_state=auth_data,  # Use the loaded auth data directly
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ignore_https_errors=True,
                java_script_enabled=True,
                viewport={"width": 1920, "height": 1080}
            )
            
            page = context.new_page()
            
            # Set longer timeouts for Render
            page.set_default_navigation_timeout(120000)  # 2 minutes
            page.set_default_timeout(60000)  # 1 minute for elements
            
            print("🔗 Navigating to Zomato Partner Reporting Page...")
            
            # Navigate with retries
            success = False
            urls_to_try = [
                "https://www.zomato.com/partners/onlineordering/reporting/",
                "https://www.zomato.com/partners/onlineordering/",
                "https://www.zomato.com/partners/"
            ]
            
            for attempt in range(3):  # 3 attempts total
                for url in urls_to_try:
                    try:
                        print(f"🔄 Attempt {attempt + 1}: Trying {url}")
                        response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
                        
                        if response and response.ok:
                            print(f"✅ Successfully loaded: {url}")
                            page.wait_for_timeout(3000)
                            
                            # Validate login immediately after page load
                            if validate_login_state(page):
                                print("✅ Authentication confirmed - logged in successfully")
                                success = True
                                break
                            else:
                                print("❌ Authentication failed - not logged in")
                                if attempt < 2:  # Try again unless it's the last attempt
                                    print("Retrying...")
                                    continue
                                else:
                                    raise Exception("Authentication failed after all attempts")
                        
                    except Exception as e:
                        print(f"❌ Failed to load {url}: {e}")
                        continue
                
                if success:
                    break
                    
                if attempt < 2:  # Wait before retry unless it's the last attempt
                    print("⏳ Waiting 5 seconds before retry...")
                    page.wait_for_timeout(5000)
            
            if not success:
                raise Exception("Failed to load any Zomato partner page after all attempts")

            # Try to dismiss any popups
            try:
                okay_selectors = ["text=Okay", "text=OK", "button:has-text('Okay')", "button:has-text('OK')"]
                for selector in okay_selectors:
                    try:
                        okay_btn = page.locator(selector).first
                        if okay_btn.is_visible(timeout=3000):
                            okay_btn.click()
                            page.wait_for_timeout(1000)
                            print("✅ Dismissed popup")
                            break
                    except:
                        continue
            except:
                pass

            # Navigate to reports if not already there
            if "reporting" not in page.url:
                print("🖱️ Looking for 'View Business Reports'...")
                
                # Try multiple selectors for the reports button
                report_selectors = [
                    "text=View Business Reports",
                    "text=Business Reports", 
                    "text=Reports",
                    "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[1]/div[2]",
                    "[data-testid*='report']",
                    "[class*='report']"
                ]
                
                reports_clicked = False
                for selector in report_selectors:
                    try:
                        element = page.locator(selector)
                        if element.is_visible(timeout=10000):
                            element.click()
                            page.wait_for_timeout(3000)
                            print(f"✅ Clicked reports using: {selector}")
                            reports_clicked = True
                            break
                    except Exception as e:
                        print(f"Failed to click with {selector}: {e}")
                        continue
                
                if not reports_clicked:
                    print("❌ Could not find 'View Business Reports' button")
                    print("This usually means:")
                    print("1. Authentication session expired")
                    print("2. Page structure changed")
                    print("3. Still loading")
                    
                    # Debug: show what's actually on the page
                    try:
                        page_text = page.locator('body').inner_text()
                        print(f"Page contains 'report': {'report' in page_text.lower()}")
                        print(f"Page contains 'business': {'business' in page_text.lower()}")
                        print(f"Page sample: {page_text[:500]}...")
                    except:
                        pass
                    
                    if not os.getenv('RENDER'):
                        input("Debug: Press Enter after manually navigating to reports page...")

            # Process each outlet
            for idx, outlet_id in enumerate(outlet_ids):
                print(f"\n🔁 Processing outlet {idx + 1}/{len(outlet_ids)}: {outlet_id}")

                try:
                    # Open All Outlets dropdown
                    dropdown_opened = False
                    dropdown_selectors = [
                        "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[1]/div[2]/div/div/div/span/span[2]",
                        "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span",
                        "[class*='dropdown']",
                        "[class*='select']",
                        "text=All Outlets"
                    ]
                    
                    for selector in dropdown_selectors:
                        try:
                            dropdown = page.locator(selector)
                            if dropdown.is_visible(timeout=15000):
                                dropdown.click()
                                page.wait_for_timeout(2000)
                                print(f"✅ Opened dropdown using: {selector}")
                                dropdown_opened = True
                                break
                        except:
                            continue
                    
                    if not dropdown_opened:
                        print(f"❌ Could not open dropdown for outlet {outlet_id}")
                        continue

                    # Date selection (only for first outlet)
                    if idx == 0:
                        try:
                            print("📅 Setting up date selection...")
                            
                            # Switch to Daily view
                            daily_selectors = [
                                "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[2]/div/div/div[1]/div/div[1]/div[2]/span/span",
                                "text=Daily",
                                "[data-testid*='daily']"
                            ]
                            
                            for selector in daily_selectors:
                                try:
                                    daily_btn = page.locator(selector)
                                    if daily_btn.is_visible(timeout=10000):
                                        daily_btn.click()
                                        page.wait_for_timeout(3000)
                                        print(f"✅ Switched to daily view using: {selector}")
                                        break
                                except:
                                    continue
                            
                            # Open calendar
                            calendar_selectors = [
                                "xpath=//*[@id='modal']/div/div/div[2]/div[2]/div/div/div[1]/div/div[2]/div/div/div/div[1]/div/span/span",
                                "text=Select date range",
                                "span:has-text('Select date range')"
                            ]
                            
                            for selector in calendar_selectors:
                                try:
                                    calendar_btn = page.locator(selector)
                                    if calendar_btn.is_visible(timeout=10000):
                                        calendar_btn.click()
                                        page.wait_for_timeout(2000)
                                        print(f"✅ Opened calendar using: {selector}")
                                        break
                                except:
                                    continue
                            
                            # Select yesterday's date
                            select_yesterday_date_zomato(page)
                            
                        except Exception as e:
                            print(f"⚠️ Date selection error: {e}")

                    else:
                        # Deselect previous outlet
                        print(f"🔄 Deselecting previous outlet: {outlet_ids[idx - 1]}")
                        try:
                            prev_outlet_element = page.locator(f"text={outlet_ids[idx - 1]}").first
                            if prev_outlet_element.is_visible(timeout=5000):
                                prev_outlet_element.click()
                                page.wait_for_timeout(1000)
                                print("✅ Previous outlet deselected")
                        except Exception as e:
                            print(f"⚠️ Error deselecting previous outlet: {e}")

                    # Search and select current outlet
                    print(f"🔍 Searching for outlet: {outlet_id}")
                    
                    # Open dropdown for current selection
                    current_dropdown_selectors = [
                        "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[2]/div[1]/div[2]/span/span",
                        "[class*='dropdown']",
                        "[class*='select']"
                    ]
                    
                    for selector in current_dropdown_selectors:
                        try:
                            dropdown = page.locator(selector)
                            if dropdown.is_visible(timeout=10000):
                                dropdown.click()
                                page.wait_for_timeout(2000)
                                print(f"✅ Opened current dropdown using: {selector}")
                                break
                        except:
                            continue

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
                    apply_selectors = [
                        "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[3]/div[2]",
                        "button:has-text('Apply')",
                        "text=Apply"
                    ]
                    
                    for selector in apply_selectors:
                        try:
                            apply_btn = page.locator(selector)
                            if apply_btn.is_visible(timeout=10000):
                                apply_btn.click()
                                page.wait_for_timeout(5000)  # Longer wait for data to load
                                print(f"✅ Applied filter using: {selector}")
                                break
                        except:
                            continue

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
                
        except Exception as e:
            print(f"❌ Fatal error: {e}")
            raise e
        finally:
            if browser:
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
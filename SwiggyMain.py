from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import gspread
from google.oauth2.service_account import Credentials
import os
import google.generativeai as genai
import json
from dotenv import load_dotenv
import time
import logging
from datetime import datetime, timedelta

# Load environment variables from .env file
load_dotenv()

# Setup logging for better debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Environment Setup ===
# Load Gemini API key from environment
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("Gemini AI configured successfully")
else:
    print("GOOGLE_API_KEY not found in environment variables")
    model = None

# === Google Sheets Auth with Error Handling ===
def setup_google_sheets():
    try:
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('service_account.json', scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open("Swiggy Zomato Dashboard").worksheet("Swiggy Live")
        logger.info("Google Sheets connected successfully")
        return sheet
    except Exception as e:
        logger.error(f"Google Sheets connection failed: {e}")
        return None

# === RIDs to Process ===
RID_LIST = [
    "106018", "199634", "121907", "123889", "153827", "170057", "200210", 
    "248665", "310981", "2811", "20663", "66107", "76879", "121120", 
    "248316", "311831", "474649", "671434", "699228", "860008"
]

# === Gemini-Based Metric Extraction - ALL METRICS ===
def extract_all_metrics_with_gemini(text):
    if not model:
        print("Gemini not available, falling back to regex")
        return extract_all_metrics_regex(text)
    
    prompt = """
    Extract ALL these specific metrics from this Swiggy dashboard text. Return ONLY a JSON object with these exact keys:

    {
        "Delivered Orders": "number or N/A",
        "Cancelled Orders": "number or N/A",
        "Rated Orders": "number or N/A",
        "Poor Rated Orders": "number or N/A",
        "% of Bolt Orders": "number only (remove % symbol) or N/A",
        "Impressions": "number or N/A",
        "Menu Opens": "number or N/A", 
        "Cart Builds": "number or N/A",
        "Orders Placed": "number or N/A",
        "New Customers": "number or N/A",
        "Repeat Customers": "number or N/A",
        "Dormant Customers": "number or N/A",
        "New Customer Order %": "number only (remove % symbol) or N/A",
        "Dormant Customer Order %": "number only (remove % symbol) or N/A",
        "Ad Orders": "number or N/A",
        "CPC Menu Visits": "number or N/A",
        "Total Spends": "number without currency symbol or N/A",
        "CBA Impressions": "number or N/A",
        "CBA Menu Visits": "number or N/A",
        "Online %": "number only (remove % symbol) or N/A",
        "Kitchen Prep Time": "number only (remove 'min') or N/A",
        "Food Ready Accuracy (MFR)": "number only (remove % symbol) or N/A",
        "Delayed Orders (> 10 mins)": "number only (remove % symbol) or N/A"
    }

    Extraction Guidelines:
    - For monetary values like "₹9,600", extract only the number "9600" without currency or commas
    - For percentages like "85.0%", extract only the number "85.0" without % symbol
    - For time values like "12.5 min", extract only the number "12.5" without "min"
    - All values should be pure numbers, no symbols or units
    - Look for variations like "Total Spends", "CPC Spends", "Ad Spends" for Total Spends
    - Look for "Ad Impressions" or "CBA Impressions" for CBA Impressions
    - Look for "CPC ADS Orders" or "Ad Orders" for Ad Orders
    - If a metric is not found, use "N/A"

    Text to analyze:
    """ + text[:6000]  # Increased limit for more metrics

    try:
        response = model.generate_content(prompt)
        result_text = response.text.strip()
        
        # Clean up the response to extract JSON
        if result_text.startswith('```json'):
            result_text = result_text[7:-3]
        elif result_text.startswith('```'):
            result_text = result_text[3:-3]
        
        metrics = json.loads(result_text)
        print("Gemini successfully extracted ALL metrics")
        return metrics
        
    except Exception as e:
        print(f"Gemini extraction failed: {e}")
        print("Falling back to regex extraction")
        return extract_all_metrics_regex(text)

# === Fallback Regex-Based Metric Extraction - ALL METRICS ===
def extract_all_metrics_regex(text):
    # Debug: Print sample text to see what we're working with
    logger.info(f"DEBUG - Text sample for regex: {text[:500]}...")
    
    patterns = {
        # Order Metrics
        "Delivered Orders": [
            r"Delivered Orders[:\s]*(\d+)",
            r"Orders Delivered[:\s]*(\d+)",
            r"Delivered[:\s]*(\d+)"
        ],
        "Cancelled Orders": [
            r"Cancelled Orders[:\s]*(\d+)",
            r"Orders Cancelled[:\s]*(\d+)",
            r"Cancelled[:\s]*(\d+)"
        ],
        "Rated Orders": [
            r"Rated Orders[:\s]*(\d+)",
            r"Orders Rated[:\s]*(\d+)"
        ],
        "Poor Rated Orders": [
            r"Poor Rated Orders[:\s]*(\d+)",
            r"Poor Rating Orders[:\s]*(\d+)"
        ],
        "% of Bolt Orders": [
            r"% of Bolt Orders[:\s]*([\d.]+%?)",
            r"Bolt Orders %[:\s]*([\d.]+%?)",
            r"Bolt[:\s]*([\d.]+%)"
        ],
        
        # Marketing Metrics
        "Impressions": [
            r"IMPRESSIONS[:\s]+(\d+)",
            r"Impressions[:\s]+(\d+)",
            r"Total Impressions[:\s]+(\d+)"
        ],
        "Menu Opens": [
            r"MENU OPENS[:\s]+(\d+)",
            r"Menu Opens[:\s]+(\d+)"
        ],
        "Cart Builds": [
            r"CART BUILDS[:\s]+(\d+)",
            r"Cart Builds[:\s]+(\d+)"
        ],
        "Orders Placed": [
            r"ORDERS PLACED[:\s]+(\d+)",
            r"Orders Placed[:\s]+(\d+)"
        ],
        
        # Customer Metrics
        "New Customers": [
            r"New Customers[:\s]+(\d+)",
            r"New Customer[:\s]+(\d+)"
        ],
        "Repeat Customers": [
            r"Repeat Customers[:\s]+(\d+)",
            r"Returning Customers[:\s]+(\d+)"
        ],
        "Dormant Customers": [
            r"Dormant Customers[:\s]+(\d+)",
            r"Inactive Customers[:\s]+(\d+)"
        ],
        "New Customer Order %": [
            r"New Customer Order %[:\s]+([\d.]+%?)",
            r"New Customer %[:\s]+([\d.]+%?)"
        ],
        "Dormant Customer Order %": [
            r"Dormant Customer Order %[:\s]+([\d.]+%?)",
            r"Dormant Customer %[:\s]+([\d.]+%?)"
        ],
        
        # Ad Metrics
        "Ad Orders": [
            r"(?:CPC ADS.*?Orders|Ad Orders)[:\s]*(\d+)",
            r"CPC Orders[:\s]*(\d+)",
            r"Advertisement Orders[:\s]*(\d+)"
        ],
        "CPC Menu Visits": [
            r"CPC Menu Visits[:\s]+(\d+)",
            r"CPC Visits[:\s]+(\d+)"
        ],
        "Total Spends": [
            r"Total CPC Spends\s*\u20B9\s*([\d,]+)",
            r"Total Spends\s*\u20B9\s*([\d,]+)", 
            r"CPC Spends\s*\u20B9\s*([\d,]+)",
            r"Ad Spends\s*\u20B9\s*([\d,]+)",
            r"Total CPC Spends\s*₹\s*([\d,]+)",
            r"Total Spends\s*₹\s*([\d,]+)", 
            r"CPC Spends\s*₹\s*([\d,]+)",
            r"Ad Spends\s*₹\s*([\d,]+)",
            r"CPC\s*\u20B9\s*([\d,]+)",
            r"CPC\s*₹\s*([\d,]+)",
            r"\u20B9\s*([\d,]+)",
            r"₹\s*([\d,]+)"
        ],
        "CBA Impressions": [
            r"(?:Ad Impressions|CBA Impressions)[:\s]+(\d+)",
            r"CBA Impression[:\s]+(\d+)"
        ],
        "CBA Menu Visits": [
            r"CBA Menu Visits[:\s]+(\d+)",
            r"CBA Visits[:\s]+(\d+)"
        ],
        
        # Performance Metrics
        "Online %": [
            r"Online Availability\s*%?\s*([\d.]+)%?",
            r"Online\s*%\s*([\d.]+)%?",
            r"Availability\s*%?\s*([\d.]+)%?",
            r"Online\s+([\d.]+)%",
            r"([\d.]+)%?\s*Online",
            r"Online.*?([\d.]+)%",
            r"Availability.*?([\d.]+)%"
        ],
        "Kitchen Prep Time": [
            r"Kitchen Prep Time[:\s]+([\d.]+)\s*min",
            r"Prep Time[:\s]+([\d.]+)\s*min",
            r"Kitchen Time[:\s]+([\d.]+)\s*min"
        ],
        "Food Ready Accuracy (MFR)": [
            r"Food Ready Accuracy[:\s]*\(MFR\)[:\s]*([\d.]+%?)",
            r"MFR[:\s]*([\d.]+%?)",
            r"Food Ready[:\s]*([\d.]+%?)"
        ],
        "Delayed Orders (> 10 mins)": [
            r"Delayed Orders[:\s]*\([>\s]*10\s*mins?\)[:\s]*([\d.]+%?)",
            r"Delayed Orders[:\s]*([\d.]+%?)",
            r"Late Orders[:\s]*([\d.]+%?)"
        ]
    }
    
    extracted = {}
    
    for label, pattern_list in patterns.items():
        found = False
        for i, pattern in enumerate(pattern_list):
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                # Clean up values - extract numbers only
                value = match.group(1).strip().replace(',', '')
                
                # Remove all symbols and units to get pure numbers
                value = re.sub(r'[₹\u20B9%min\s]', '', value)
                
                extracted[label] = value
                logger.info(f"DEBUG - Found {label} using pattern {i+1}: '{value}'")
                found = True
                break
            
        if not found:
            extracted[label] = "N/A"
            logger.warning(f"DEBUG - Could not find {label} in text")
    
    return extracted

# === Value Conversion - Convert everything to numbers ===
def convert_value(val):
    if val == "N/A" or not val:
        return "N/A"
    try:
        # Remove all non-numeric characters except decimal point
        cleaned = re.sub(r'[^\d.]', '', str(val))
        
        # Convert to float if it contains a decimal, otherwise int
        if '.' in cleaned:
            return float(cleaned)
        else:
            return int(cleaned) if cleaned else "N/A"
            
    except (ValueError, TypeError):
        logger.warning(f"Could not convert value to number: {val}")
        return "N/A"

# === ENHANCED Function to select Custom date option and pick specific date ===
def select_custom_date_option(page, target_date):
    """Enhanced date selection optimized for server environments like Render."""
    logger.info(f"Selecting Custom date option and picking date: {target_date.strftime('%d-%m-%Y')}...")
    
    # Enhanced waiting function with retries
    def wait_with_retries(locator, timeout=20000, retries=3):
        for attempt in range(retries):
            try:
                locator.wait_for(state='visible', timeout=timeout)
                return True
            except Exception as e:
                logger.info(f"Wait attempt {attempt + 1} failed: {e}")
                page.wait_for_timeout(3000)  # Longer wait between retries
        return False
    
    # === STEP 1: Click Custom Button ===
    custom_xpath = "xpath=/html/body/div[2]/div/div/div/div[2]/div[2]/div/div/div[7]/div[2]/div"
    custom_clicked = False
    
    # Method 1: Enhanced XPath clicking
    try:
        custom_button = page.locator(custom_xpath)
        if wait_with_retries(custom_button, timeout=25000):
            # Scroll into view and wait
            custom_button.scroll_into_view_if_needed()
            page.wait_for_timeout(3000)  # Longer wait for server
            
            # Try force click first (better for server environments)
            try:
                custom_button.click(force=True, timeout=15000)
                logger.info("Custom button clicked with force using XPath")
                custom_clicked = True
            except:
                # Fallback to regular click
                custom_button.click(timeout=15000)
                logger.info("Custom button clicked using XPath")
                custom_clicked = True
                
            page.wait_for_timeout(5000)  # Much longer wait for UI update
    except Exception as e:
        logger.info(f"XPath method failed: {e}")
    
    # Method 2: Try in frames with enhanced reliability
    if not custom_clicked:
        logger.info("Trying Custom button in frames...")
        frames = page.frames
        logger.info(f"Found {len(frames)} frames to check")
        
        for frame_idx, frame in enumerate(frames):
            try:
                logger.info(f"Checking frame {frame_idx + 1}/{len(frames)}")
                custom_button_frame = frame.locator(custom_xpath)
                if wait_with_retries(custom_button_frame, timeout=15000):
                    try:
                        custom_button_frame.scroll_into_view_if_needed()
                        page.wait_for_timeout(2000)
                        custom_button_frame.click(force=True, timeout=15000)
                        logger.info(f"Custom button clicked in frame {frame_idx + 1} with force")
                        custom_clicked = True
                        page.wait_for_timeout(5000)
                        break
                    except:
                        custom_button_frame.click(timeout=15000)
                        logger.info(f"Custom button clicked in frame {frame_idx + 1} (regular)")
                        custom_clicked = True
                        page.wait_for_timeout(5000)
                        break
            except Exception as e:
                logger.info(f"Frame {frame_idx + 1} failed: {e}")
                continue
    
    # Method 3: Alternative selectors with enhanced search
    if not custom_clicked:
        logger.info("Trying alternative selectors for Custom...")
        
        selectors = [
            "text=Custom",
            "button:has-text('Custom')",
            "div:has-text('Custom')",
            "span:has-text('Custom')",
            "[data-testid*='custom' i]",
            "[class*='custom' i]",
            "[id*='custom' i]",
            "*:has-text('Custom'):visible"
        ]
        
        # Try on main page first
        for selector in selectors:
            try:
                element = page.locator(selector).first
                if wait_with_retries(element, timeout=12000):
                    element.scroll_into_view_if_needed()
                    page.wait_for_timeout(2000)
                    try:
                        element.click(force=True, timeout=15000)
                        logger.info(f"Custom clicked with force using: {selector}")
                        custom_clicked = True
                        break
                    except:
                        element.click(timeout=15000)
                        logger.info(f"Custom clicked using: {selector}")
                        custom_clicked = True
                        break
            except:
                continue
        
        # Try in frames
        if not custom_clicked:
            for frame in page.frames:
                for selector in selectors:
                    try:
                        element = frame.locator(selector).first
                        if wait_with_retries(element, timeout=8000):
                            element.click(force=True, timeout=15000)
                            logger.info(f"Custom clicked in frame using: {selector}")
                            custom_clicked = True
                            break
                    except:
                        continue
                if custom_clicked:
                    break
    
    if not custom_clicked:
        logger.error("Could not find or click Custom option")
        return False
    
    # Longer wait for calendar to load in server environment
    logger.info("Waiting for calendar to load...")
    page.wait_for_timeout(8000)  # Increased from 2000 to 8000
    
    # === STEP 2: Select the specific day ===
    logger.info(f"Looking for day: {target_date.day}")
    target_day_str = str(target_date.day)
    day_clicked = False
    
    base_xpath = "/html/body/div[1]/div/div/div/div[2]/div[2]/div[2]/div/div[3]/div/div/div[3]/div/div[2]/div/div/div/div[2]"
    
    # Enhanced day selection with more comprehensive search
    for i in range(1, 50):  # Increased range for full calendar view
        button_xpath = f"xpath={base_xpath}/button[{i}]/abbr"
        
        # Try on main page
        try:
            day_button = page.locator(button_xpath)
            if wait_with_retries(day_button, timeout=8000):
                try:
                    day_text = day_button.inner_text(timeout=5000).strip()
                    logger.info(f"Found button {i} with text: '{day_text}'")
                    
                    if day_text == target_day_str:
                        # Enhanced double-click with better timing and force
                        day_button.scroll_into_view_if_needed()
                        page.wait_for_timeout(1000)
                        
                        # First click with force
                        day_button.click(force=True, timeout=15000)
                        logger.info(f"First click on day {target_date.day} successful (force)")
                        page.wait_for_timeout(1500)  # Longer pause between clicks
                        
                        # Second click with force
                        day_button.click(force=True, timeout=15000)
                        logger.info(f"Second click on day {target_date.day} successful (force)")
                        day_clicked = True
                        page.wait_for_timeout(3000)  # Longer wait after double-click
                        break
                except Exception as day_e:
                    logger.info(f"Day text extraction/click failed: {day_e}")
        except:
            pass
        
        # Try in frames if main page didn't work
        if not day_clicked:
            for frame in page.frames:
                try:
                    day_button_frame = frame.locator(button_xpath)
                    if wait_with_retries(day_button_frame, timeout=5000):
                        day_text = day_button_frame.inner_text(timeout=3000).strip()
                        if day_text == target_day_str:
                            # Double click in frame with force
                            day_button_frame.click(force=True, timeout=15000)
                            page.wait_for_timeout(1500)
                            day_button_frame.click(force=True, timeout=15000)
                            logger.info(f"Day {target_date.day} clicked in frame with force")
                            day_clicked = True
                            page.wait_for_timeout(3000)
                            break
                except:
                    continue
            if day_clicked:
                break
    
    if not day_clicked:
        logger.error(f"Could not find or click day {target_date.day}")
        return False
    
    # === STEP 3: Click Confirm Button ===
    logger.info("Looking for Confirm button...")
    confirm_xpath = "xpath=//*[@id=\"mfe-root\"]/div/div[2]/div[2]/div[2]/div/div[3]/div/div/div[4]/div"
    confirm_clicked = False
    
    # Wait longer for UI to update after day selection
    page.wait_for_timeout(4000)  # Increased wait time
    
    # Enhanced confirm button selection with multiple methods
    confirm_selectors = [
        confirm_xpath,
        "button:has-text('Confirm')",
        "div:has-text('Confirm')", 
        "button:has-text('OK')",
        "button:has-text('Apply')",
        "button:has-text('Done')",
        "[data-testid*='confirm' i]",
        "[class*='confirm' i]",
        "*:has-text('Confirm'):visible",
        "*:has-text('OK'):visible"
    ]
    
    for selector in confirm_selectors:
        # Try on main page
        try:
            if selector.startswith("xpath="):
                element = page.locator(selector)
            else:
                element = page.locator(selector).first
                
            if wait_with_retries(element, timeout=12000):
                try:
                    button_text = element.inner_text(timeout=3000)
                    logger.info(f"Found confirm element with text: '{button_text}'")
                except:
                    logger.info(f"Found confirm element with selector: {selector}")
                
                # Try clicking with enhanced method
                try:
                    element.scroll_into_view_if_needed()
                    page.wait_for_timeout(2000)
                    element.click(force=True, timeout=15000)
                    logger.info(f"Confirm clicked with force using: {selector}")
                    confirm_clicked = True
                    break
                except:
                    try:
                        element.click(timeout=15000)
                        logger.info(f"Confirm clicked using: {selector}")
                        confirm_clicked = True
                        break
                    except Exception as click_e:
                        logger.info(f"Confirm click failed with {selector}: {click_e}")
        except Exception as sel_e:
            logger.info(f"Confirm selector {selector} failed: {sel_e}")
            continue
    
    # Try in frames if main page failed
    if not confirm_clicked:
        logger.info("Trying Confirm button in frames...")
        for frame in page.frames:
            for selector in confirm_selectors:
                try:
                    if selector.startswith("xpath="):
                        element = frame.locator(selector)
                    else:
                        element = frame.locator(selector).first
                        
                    if wait_with_retries(element, timeout=8000):
                        try:
                            element.click(force=True, timeout=15000)
                            logger.info(f"Confirm clicked in frame with force using: {selector}")
                            confirm_clicked = True
                            break
                        except:
                            try:
                                element.click(timeout=15000)
                                logger.info(f"Confirm clicked in frame using: {selector}")
                                confirm_clicked = True
                                break
                            except:
                                continue
                except:
                    continue
            if confirm_clicked:
                break
    
    if confirm_clicked:
        page.wait_for_timeout(5000)  # Longer wait for UI to update
        logger.info(f"Successfully selected custom date: {target_date.strftime('%d-%m-%Y')}")
        return True
    else:
        logger.error("Could not find or click Confirm button")
        return False

# === Main Function ===
def open_and_cycle_outlets():
    # Setup Google Sheets with error handling
    sheet = setup_google_sheets()
    if not sheet:
        logger.error("Cannot proceed without Google Sheets connection")
        return
    
    # Calculate target date (2 days before today)
    target_date = datetime.now() - timedelta(days=2)
    formatted_date = target_date.strftime("%Y-%m-%d")  # Format as YYYY-MM-DD
    
    print(f"Using target date (2 days before today): {formatted_date}")

    with sync_playwright() as p:
        try:
            # Enhanced browser launch for server environment
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--window-size=1920,1080',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            context = browser.new_context(
                storage_state="swiggy_login.json",
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
            page.set_default_timeout(45000)  # Increased timeout for server

            logger.info("Opening Swiggy Partner Dashboard...")
            page.goto("https://partner.swiggy.com/business-metrics/overview/restaurant/121907", timeout=90000)
            page.wait_for_load_state("networkidle", timeout=60000)

            # Enhanced popup handling
            popup_selectors = [
                "xpath=/html/body/div[2]/div[2]/div[3]/button[1]",
                "text=No! Not needed",
                "button:has-text('Close')",
                "button:has-text('Dismiss')"
            ]
            
            for selector in popup_selectors:
                try:
                    popup = page.locator(selector).first
                    if popup.is_visible(timeout=5000):
                        popup.click(timeout=10000)
                        logger.info(f"Closed popup using: {selector}")
                        page.wait_for_timeout(2000)
                        break
                except:
                    continue

            # === Date Selection ===
            logger.info("Opening Filter and selecting Custom date...")

            # Open Filter with enhanced method
            filter_opened = False
            for frame in page.frames:
                try:
                    filter_btn = frame.locator("span:has-text('Filter')")
                    if filter_btn.is_visible(timeout=10000):
                        filter_btn.click(force=True, timeout=15000)
                        page.wait_for_timeout(2000)
                        logger.info("Filter opened successfully")
                        filter_opened = True
                        break
                except: continue
            
            if not filter_opened:
                # Try on main page if frames failed
                try:
                    filter_btn = page.locator("span:has-text('Filter')").first
                    if filter_btn.is_visible(timeout=10000):
                        filter_btn.click(force=True, timeout=15000)
                        page.wait_for_timeout(2000)
                        logger.info("Filter opened on main page")
                        filter_opened = True
                except:
                    logger.warning("Could not open Filter")

            # Select Custom date option and pick specific date (ENHANCED VERSION)
            if not select_custom_date_option(page, target_date):
                logger.warning("Custom date selection failed, but continuing...")

            # Go directly to "Filter by outlets" after selecting custom date
            logger.info("Looking for 'Filter by outlets' element...")
            filter_outlets_clicked = False
            
            # Add extra wait time for UI to update after date selection
            logger.info("Waiting for UI to update after custom date selection...")
            page.wait_for_timeout(3000)  # Increased wait time
            
            # Enhanced Filter by outlets selection
            filter_outlets_selectors = [
                "xpath=/html/body/div[2]/div/div/div/div[2]/div[1]/div[4]/div",
                "text=Filter by outlets",
                "div:has-text('Filter by outlets')",
                "button:has-text('Filter by outlets')",
                "*:has-text('outlets'):visible"
            ]
            
            for selector in filter_outlets_selectors:
                if filter_outlets_clicked:
                    break
                    
                # Try on main page
                try:
                    if selector.startswith("xpath="):
                        element = page.locator(selector)
                    else:
                        element = page.locator(selector).first
                        
                    if element.is_visible(timeout=8000):
                        element.click(force=True, timeout=15000)
                        logger.info(f"Filter by outlets clicked using: {selector}")
                        filter_outlets_clicked = True
                        page.wait_for_timeout(2000)
                        break
                except:
                    pass
                
                # Try in frames
                if not filter_outlets_clicked:
                    for frame in page.frames:
                        try:
                            if selector.startswith("xpath="):
                                element = frame.locator(selector)
                            else:
                                element = frame.locator(selector).first
                                
                            if element.is_visible(timeout=5000):
                                element.click(force=True, timeout=15000)
                                logger.info(f"Filter by outlets clicked in frame using: {selector}")
                                filter_outlets_clicked = True
                                page.wait_for_timeout(2000)
                                break
                        except:
                            continue
                    if filter_outlets_clicked:
                        break
            
            if not filter_outlets_clicked:
                logger.warning("Could not find or click 'Filter by outlets'")

            # Click Select All after custom date selection and Filter by outlets
            for frame in page.frames:
                try:
                    select_all_initial = frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[2]/div[2]/div/div[2]/div[2]/div")
                    if select_all_initial.is_visible(timeout=8000):
                        select_all_initial.click(force=True, timeout=15000)
                        logger.info("Select All clicked after custom date selection")
                        page.wait_for_timeout(2000)
                        break
                except: continue

            # === Loop through all RIDs with progress tracking ===
            successful_scrapes = 0
            for index, rid in enumerate(RID_LIST):
                logger.info(f"\nProcessing RID {index + 1}/{len(RID_LIST)}: {rid}")

                try:
                    if index > 0:
                        # Reopen Filter for subsequent RIDs
                        logger.info("Reopening main Filter for next RID...")
                        for frame in page.frames:
                            try:
                                filter_btn = frame.locator("span:has-text('Filter')")
                                if filter_btn.is_visible(timeout=8000):
                                    filter_btn.click(force=True, timeout=15000)
                                    page.wait_for_timeout(2000)
                                    logger.info("Main Filter reopened")
                                    break
                            except: continue
                        
                        # Select Custom date again for subsequent RIDs
                        if not select_custom_date_option(page, target_date):
                            logger.warning("Custom date selection failed for subsequent RID, but continuing...")
                        
                        # Click "Filter by outlets" again for subsequent RIDs with enhanced method
                        logger.info("Clicking 'Filter by outlets' for RID selection...")
                        filter_outlets_clicked = False
                        
                        for selector in filter_outlets_selectors:
                            if filter_outlets_clicked:
                                break
                            try:
                                if selector.startswith("xpath="):
                                    element = page.locator(selector)
                                else:
                                    element = page.locator(selector).first
                                    
                                if element.is_visible(timeout=8000):
                                    element.click(force=True, timeout=15000)
                                    logger.info(f"Filter by outlets clicked using: {selector}")
                                    filter_outlets_clicked = True
                                    break
                            except:
                                pass
                            
                            # Try in frames
                            for frame in page.frames:
                                try:
                                    if selector.startswith("xpath="):
                                        element = frame.locator(selector)
                                    else:
                                        element = frame.locator(selector).first
                                        
                                    if element.is_visible(timeout=5000):
                                        element.click(force=True, timeout=15000)
                                        logger.info(f"Filter by outlets clicked in frame using: {selector}")
                                        filter_outlets_clicked = True
                                        break
                                except:
                                    continue
                            if filter_outlets_clicked:
                                break
                        
                        if filter_outlets_clicked:
                            page.wait_for_timeout(2000)
                        
                        # Reset outlet selection by clicking Select All twice
                        logger.info("Resetting outlet selection...")
                        for frame in page.frames:
                            try:
                                select_all_reset = frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[2]/div[2]/div/div[2]/div[2]/div")
                                if select_all_reset.is_visible(timeout=8000):
                                    select_all_reset.click(force=True, timeout=15000)
                                    page.wait_for_timeout(1000)
                                    select_all_reset.click(force=True, timeout=15000)
                                    logger.info("Select All clicked twice to reset outlet selection")
                                    page.wait_for_timeout(1500)
                                    break
                            except: continue

                    # Select specific RID
                    logger.info(f"Selecting specific RID: {rid}")
                    found = False
                    for frame in page.frames:
                        try:
                            rid_locator = frame.locator(f"text={rid}").first
                            if rid_locator.is_visible(timeout=10000):
                                rid_locator.click(force=True, timeout=15000)
                                logger.info(f"Selected RID: {rid}")
                                page.wait_for_timeout(1500)
                                found = True
                                break
                        except: continue
                    
                    if not found:
                        logger.warning(f"RID {rid} not found.")
                        continue

                    # Click Apply
                    for frame in page.frames:
                        try:
                            apply_btn = frame.locator("button:has-text('Apply')")
                            if apply_btn.is_visible(timeout=8000):
                                apply_btn.click(force=True, timeout=15000)
                                logger.info("Applied.")
                                page.wait_for_timeout(4000)  # Longer wait for data to load
                                break
                        except: continue

                    # Scrape Metrics
                    logger.info("Scraping ALL metrics...")
                    full_text = ""
                    
                    # Try multiple scraping strategies for better coverage
                    try:
                        # Strategy 1: Look for rupee symbol
                        metric = page.locator("div:has-text('₹')").first
                        metric.wait_for(timeout=15000)
                        full_text = metric.inner_text()
                        logger.info("Found content using rupee symbol locator")
                    except PlaywrightTimeoutError:
                        try:
                            # Strategy 2: Look in frames for rupee symbol
                            for frame in page.frames:
                                try:
                                    metric = frame.locator("div:has-text('₹')").first
                                    metric.wait_for(timeout=8000)
                                    full_text = metric.inner_text()
                                    if full_text: 
                                        logger.info("Found content in frame using rupee symbol")
                                        break
                                except: continue
                        except: pass
                    
                    # Strategy 3: Try broader selectors if rupee search failed
                    if not full_text:
                        try:
                            # Look for common dashboard containers
                            containers = [
                                "[class*='metric']",
                                "[class*='dashboard']", 
                                "[class*='overview']",
                                "[class*='stats']",
                                "main",
                                ".content"
                            ]
                            
                            for container in containers:
                                try:
                                    content = page.locator(container).first
                                    if content.is_visible(timeout=5000):
                                        full_text = content.inner_text()
                                        if "₹" in full_text or "%" in full_text:
                                            logger.info(f"Found content using {container} selector")
                                            break
                                except: continue
                                
                            # Last resort: get all visible text
                            if not full_text:
                                full_text = page.locator('body').inner_text()
                                logger.info("Using full page text as fallback")
                                
                        except Exception as e:
                            logger.error(f"Error in broader scraping: {e}")

                    # Save to Sheet with ALL metrics
                    if full_text:
                        metrics = extract_all_metrics_with_gemini(full_text)
                        metrics_written = 0
                        
                        for label, raw_value in metrics.items():
                            if raw_value != "N/A":  # Only write non-N/A values
                                cleaned_value = convert_value(raw_value)
                                try:
                                    sheet.append_row([
                                        formatted_date,
                                        int(rid),  # Convert RID to integer
                                        label,
                                        cleaned_value,
                                        "Swiggy"
                                    ], value_input_option='USER_ENTERED')
                                    metrics_written += 1
                                    logger.info(f"Saved: {label} = {cleaned_value}")
                                except Exception as e:
                                    logger.error(f"Error writing {label} to sheet: {e}")
                        
                        logger.info(f"Written {metrics_written} metrics for RID {rid}")
                        successful_scrapes += 1
                    else:
                        logger.warning(f"No data found for RID {rid}")

                except Exception as e:
                    logger.error(f"Error processing RID {rid}: {e}")
                    continue

                # Small delay between RIDs
                time.sleep(3)

            logger.info(f"\nScraping completed! Successfully processed {successful_scrapes}/{len(RID_LIST)} RIDs")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            try:
                browser.close()
            except:
                pass

# === Run Script ===
if __name__ == "__main__":
    print("Starting Complete Swiggy Scraper with Enhanced Date Selection for Render")
    print("Extracting ALL metrics: Orders, Customers, Ads, Performance")
    print(f"Gemini Status: {'Available' if model else 'Not Available (using regex fallback)'}")
    open_and_cycle_outlets()
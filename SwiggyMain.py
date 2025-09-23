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

# === Function to select Custom date option and pick specific date ===
def select_custom_date_option(page, target_date):
    """Selects the Custom option and picks the target date from calendar."""
    logger.info(f"Selecting Custom date option and picking date: {target_date.strftime('%d-%m-%Y')}...")
    
    # XPath for Custom button as provided by user
    custom_xpath = "xpath=/html/body/div[2]/div/div/div/div[2]/div[2]/div/div/div[7]/div[2]/div"
    custom_clicked = False
    
    # Try on main page first
    try:
        custom_button = page.locator(custom_xpath)
        if custom_button.is_visible():
            # Get button text to verify
            try:
                button_text = custom_button.inner_text()
                logger.info(f"Found Custom button with text: '{button_text}'")
            except:
                logger.info("Could not retrieve Custom button text")
            
            custom_button.click()
            logger.info("Custom option selected using XPath on main page.")
            custom_clicked = True
            # Wait for calendar to open
            page.wait_for_timeout(2000)
        else:
            logger.info("Custom button not visible on main page")
    except Exception as e:
        logger.info(f"Main page Custom XPath failed: {e}")
    
    # Try in frames if main page didn't work
    if not custom_clicked:
        logger.info("Trying Custom button in frames...")
        for frame in page.frames:
            try:
                custom_button_frame = frame.locator(custom_xpath)
                if custom_button_frame.is_visible():
                    # Get button text to verify
                    try:
                        button_text = custom_button_frame.inner_text()
                        logger.info(f"Found Custom button in frame with text: '{button_text}'")
                    except:
                        logger.info("Could not retrieve Custom button text from frame")
                    
                    custom_button_frame.click()
                    logger.info("Custom option selected using XPath in frame.")
                    custom_clicked = True
                    # Wait for calendar to open
                    page.wait_for_timeout(2000)
                    break
            except Exception as e:
                logger.info(f"Frame Custom XPath failed: {e}")
                continue
    
    # Try alternative selectors if XPath fails
    if not custom_clicked:
        logger.info("Trying alternative selectors for Custom...")
        alternative_selectors = [
            "text=Custom",
            "button:has-text('Custom')",
            "div:has-text('Custom')",
            "[data-testid*='custom']",
            "[class*='custom']"
        ]
        
        # Try on main page
        for selector in alternative_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible():
                    # Get button text to verify
                    try:
                        button_text = element.inner_text()
                        logger.info(f"Found Custom button with alternative selector with text: '{button_text}'")
                    except:
                        logger.info("Could not retrieve button text with alternative selector")
                    
                    element.click()
                    logger.info(f"Custom option selected using selector: {selector}")
                    custom_clicked = True
                    # Wait for calendar to open
                    page.wait_for_timeout(2000)
                    break
            except:
                continue
        
        # Try in frames
        if not custom_clicked:
            for frame in page.frames:
                for selector in alternative_selectors:
                    try:
                        element = frame.locator(selector).first
                        if element.is_visible():
                            # Get button text to verify
                            try:
                                button_text = element.inner_text()
                                logger.info(f"Found Custom button in frame with alternative selector with text: '{button_text}'")
                            except:
                                logger.info("Could not retrieve button text from frame with alternative selector")
                            
                            element.click()
                            logger.info(f"Custom option selected in frame using selector: {selector}")
                            custom_clicked = True
                            # Wait for calendar to open
                            page.wait_for_timeout(2000)
                            break
                    except:
                        continue
                if custom_clicked:
                    break
    
    if not custom_clicked:
        logger.warning("Could not find or click Custom option using any method.")
        return False
    
    # Now select the specific date from calendar
    logger.info(f"Calendar opened, now selecting date: {target_date.day}")
    target_day = target_date.day
    
    # Base XPath pattern for day buttons (user provided pattern)
    base_xpath = "/html/body/div[1]/div/div/div/div[2]/div[2]/div[2]/div/div[3]/div/div/div[3]/div/div[2]/div/div/div/div[2]"
    
    # First, inspect the first few buttons to understand calendar layout
    logger.info("Inspecting calendar layout...")
    calendar_days = []
    
    try:
        # Check first 10 buttons to understand the calendar structure
        for i in range(1, 11):
            button_xpath = f"xpath={base_xpath}/button[{i}]/abbr"
            try:
                day_button = page.locator(button_xpath)
                if day_button.is_visible():
                    day_text = day_button.inner_text().strip()
                    calendar_days.append((i, day_text))
                    logger.info(f"Button {i}: '{day_text}'")
            except:
                continue
        
        # Also try in frames
        if not calendar_days:
            for frame in page.frames:
                try:
                    for i in range(1, 11):
                        button_xpath = f"xpath={base_xpath}/button[{i}]/abbr"
                        day_button = frame.locator(button_xpath)
                        if day_button.is_visible():
                            day_text = day_button.inner_text().strip()
                            calendar_days.append((i, day_text))
                            logger.info(f"Frame Button {i}: '{day_text}'")
                except:
                    continue
                if calendar_days:
                    break
                    
    except Exception as e:
        logger.warning(f"Error inspecting calendar: {e}")
    
    # Find and click the target day TWICE
    day_clicked = False
    target_day_str = str(target_day)
    
    # Search through all calendar buttons (up to 42 for a full month view)
    for i in range(1, 43):
        button_xpath = f"xpath={base_xpath}/button[{i}]/abbr"
        
        try:
            # Try on main page first
            day_button = page.locator(button_xpath)
            if day_button.is_visible():
                day_text = day_button.inner_text().strip()
                if day_text == target_day_str:
                    # Click the day TWICE as requested
                    day_button.click()
                    logger.info(f"First click on day {target_day} using button {i} on main page")
                    page.wait_for_timeout(500)
                    day_button.click()
                    logger.info(f"Second click on day {target_day} using button {i} on main page")
                    day_clicked = True
                    page.wait_for_timeout(1000)
                    break
        except:
            pass
        
        # Try in frames if main page didn't work
        if not day_clicked:
            for frame in page.frames:
                try:
                    day_button_frame = frame.locator(button_xpath)
                    if day_button_frame.is_visible():
                        day_text = day_button_frame.inner_text().strip()
                        if day_text == target_day_str:
                            # Click the day TWICE as requested
                            day_button_frame.click()
                            logger.info(f"First click on day {target_day} using button {i} in frame")
                            page.wait_for_timeout(500)
                            day_button_frame.click()
                            logger.info(f"Second click on day {target_day} using button {i} in frame")
                            day_clicked = True
                            page.wait_for_timeout(1000)
                            break
                except:
                    continue
            if day_clicked:
                break
    
    if day_clicked:
        logger.info(f"Successfully clicked day {target_day} twice")
        
        # Wait for UI to update after double-clicking the day
        page.wait_for_timeout(2000)
        
        # Now click the Confirm button using the provided XPath
        confirm_xpath = "xpath=//*[@id=\"mfe-root\"]/div/div[2]/div[2]/div[2]/div/div[3]/div/div/div[4]/div"
        confirm_clicked = False
        
        # Try on main page first
        try:
            confirm_button = page.locator(confirm_xpath)
            if confirm_button.is_visible():
                # Get button text to verify
                try:
                    button_text = confirm_button.inner_text()
                    logger.info(f"Found Confirm button with text: '{button_text}'")
                except:
                    logger.info("Could not retrieve Confirm button text")
                
                confirm_button.click()
                logger.info("Confirm button clicked on main page")
                confirm_clicked = True
                page.wait_for_timeout(2000)
            else:
                logger.info("Confirm button not visible on main page")
        except Exception as e:
            logger.info(f"Main page Confirm button failed: {e}")
        
        # Try in frames if main page didn't work
        if not confirm_clicked:
            logger.info("Trying Confirm button in frames...")
            for frame in page.frames:
                try:
                    confirm_button_frame = frame.locator(confirm_xpath)
                    if confirm_button_frame.is_visible():
                        # Get button text to verify
                        try:
                            button_text = confirm_button_frame.inner_text()
                            logger.info(f"Found Confirm button in frame with text: '{button_text}'")
                        except:
                            logger.info("Could not retrieve Confirm button text from frame")
                        
                        confirm_button_frame.click()
                        logger.info("Confirm button clicked in frame")
                        confirm_clicked = True
                        page.wait_for_timeout(2000)
                        break
                except Exception as e:
                    logger.info(f"Frame Confirm button failed: {e}")
                    continue
        
        # Try alternative selectors for Confirm button if XPath fails
        if not confirm_clicked:
            logger.info("Trying alternative selectors for Confirm button...")
            alternative_selectors = [
                "button:has-text('Confirm')",
                "div:has-text('Confirm')",
                "button:has-text('OK')",
                "button:has-text('Apply')",
                "button:has-text('Done')",
                "[data-testid*='confirm']",
                "[class*='confirm']"
            ]
            
            # Try on main page
            for selector in alternative_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible():
                        # Get button text to verify
                        try:
                            button_text = element.inner_text()
                            logger.info(f"Found Confirm button with alternative selector with text: '{button_text}'")
                        except:
                            logger.info("Could not retrieve button text with alternative selector")
                        
                        element.click()
                        logger.info(f"Confirm button clicked using selector: {selector}")
                        confirm_clicked = True
                        page.wait_for_timeout(2000)
                        break
                except:
                    continue
            
            # Try in frames
            if not confirm_clicked:
                for frame in page.frames:
                    for selector in alternative_selectors:
                        try:
                            element = frame.locator(selector).first
                            if element.is_visible():
                                # Get button text to verify
                                try:
                                    button_text = element.inner_text()
                                    logger.info(f"Found Confirm button in frame with alternative selector with text: '{button_text}'")
                                except:
                                    logger.info("Could not retrieve button text from frame with alternative selector")
                                
                                element.click()
                                logger.info(f"Confirm button clicked in frame using selector: {selector}")
                                confirm_clicked = True
                                page.wait_for_timeout(2000)
                                break
                        except:
                            continue
                    if confirm_clicked:
                        break
        
        if confirm_clicked:
            logger.info(f"Successfully selected custom date: {target_date.strftime('%d-%m-%Y')} and confirmed")
            return True
        else:
            logger.warning("Could not find or click Confirm button")
            return False
    else:
        logger.warning(f"Could not find day {target_day} in calendar")
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
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state="swiggy_login.json")
            page = context.new_page()
            page.set_default_timeout(30000)  # Better timeout

            logger.info("Opening Swiggy Partner Dashboard...")
            page.goto("https://partner.swiggy.com/business-metrics/overview/restaurant/121907", timeout=60000)
            page.wait_for_load_state("networkidle")

            # Close popup if present
            try:
                popup = page.locator("xpath=/html/body/div[2]/div[2]/div[3]/button[1]")
                if popup.is_visible():
                    popup.click()
                    logger.info("Popup closed.")
                    page.wait_for_timeout(1000)
            except:
                logger.info("No popup found or already closed.")

            # Try to close the "No! Not needed" popup if it appears
            try:
                no_needed_popup = page.locator("text=No! Not needed").first
                if no_needed_popup.is_visible():
                    no_needed_popup.click()
                    logger.info("Closed 'No! Not needed' popup.")
                    page.wait_for_timeout(1000)
            except Exception:
                logger.info("No 'No! Not needed' popup found or already closed.")

            # === Date Selection ===
            logger.info("Opening Filter and selecting Custom date...")

            # Open Filter
            for frame in page.frames:
                try:
                    if frame.locator("span:has-text('Filter')").is_visible():
                        frame.locator("span:has-text('Filter')").click()
                        page.wait_for_timeout(1500)
                        logger.info("Filter opened successfully")
                        break
                except: continue

            # Select Custom date option and pick specific date
            if not select_custom_date_option(page, target_date):
                logger.warning("Custom date selection failed, but continuing...")

            # Go directly to "Filter by outlets" after selecting custom date
            logger.info("Looking for 'Filter by outlets' element...")
            filter_outlets_clicked = False
            
            # Add extra wait time for UI to update after date selection
            logger.info("Waiting for UI to update after custom date selection...")
            page.wait_for_timeout(2000)
            
            # Method 1: Use the specific XPath provided by user
            try:
                filter_outlets_xpath = page.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[1]/div[4]/div")
                if filter_outlets_xpath.is_visible():
                    # Get button text to verify
                    try:
                        button_text = filter_outlets_xpath.inner_text()
                        logger.info(f"Found Filter by outlets button with text: '{button_text}'")
                    except:
                        logger.info("Could not retrieve Filter by outlets button text")
                    
                    filter_outlets_xpath.click()
                    logger.info("Filter by outlets clicked using specific XPath on main page.")
                    filter_outlets_clicked = True
                else:
                    logger.info("Filter by outlets XPath not visible on main page")
            except Exception as e:
                logger.info(f"Main page Filter by outlets XPath failed: {e}")
            
            # Method 2: Try the XPath in frames if main page didn't work
            if not filter_outlets_clicked:
                logger.info("Trying Filter by outlets XPath in frames...")
                for frame in page.frames:
                    try:
                        filter_outlets_xpath_frame = frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[1]/div[4]/div")
                        if filter_outlets_xpath_frame.is_visible():
                            # Get button text to verify
                            try:
                                button_text = filter_outlets_xpath_frame.inner_text()
                                logger.info(f"Found Filter by outlets button in frame with text: '{button_text}'")
                            except:
                                logger.info("Could not retrieve Filter by outlets button text from frame")
                            
                            filter_outlets_xpath_frame.click()
                            logger.info("Filter by outlets clicked using specific XPath in frame.")
                            filter_outlets_clicked = True
                            break
                    except Exception as e:
                        logger.info(f"Frame Filter by outlets XPath failed: {e}")
                        continue
            
            # Method 3: Try by text content if XPath fails
            if not filter_outlets_clicked:
                logger.info("Trying Filter by outlets using text content...")
                try:
                    filter_outlets_text = page.locator("text=Filter by outlets")
                    if filter_outlets_text.is_visible():
                        filter_outlets_text.click()
                        logger.info("Filter by outlets clicked using text locator on main page.")
                        filter_outlets_clicked = True
                    else:
                        # Try in frames
                        for frame in page.frames:
                            try:
                                if frame.locator("text=Filter by outlets").is_visible():
                                    frame.locator("text=Filter by outlets").click()
                                    logger.info("Filter by outlets clicked using text locator in frame.")
                                    filter_outlets_clicked = True
                                    break
                            except:
                                continue
                except Exception as e:
                    logger.info(f"Text locator failed: {e}")
            
            # Method 4: Try alternative selectors as last resort
            if not filter_outlets_clicked:
                logger.info("Trying alternative selectors for 'Filter by outlets'...")
                alternative_selectors = [
                    "div:has-text('Filter by outlets')",
                    "button:has-text('Filter by outlets')",
                    "span:has-text('Filter by outlets')",
                    "text*=outlets",
                    "[data-testid*='outlet']",
                    "[class*='outlet']",
                    "div:has-text('outlets')"
                ]
                
                for selector in alternative_selectors:
                    try:
                        element = page.locator(selector).first
                        if element.is_visible():
                            element.click()
                            logger.info(f"Filter by outlets clicked using selector: {selector}")
                            filter_outlets_clicked = True
                            break
                    except:
                        continue
                
                # Try alternative selectors in frames too
                if not filter_outlets_clicked:
                    for frame in page.frames:
                        for selector in alternative_selectors:
                            try:
                                element = frame.locator(selector).first
                                if element.is_visible():
                                    element.click()
                                    logger.info(f"Filter by outlets clicked in frame using selector: {selector}")
                                    filter_outlets_clicked = True
                                    break
                            except:
                                continue
                        if filter_outlets_clicked:
                            break
            
            if filter_outlets_clicked:
                page.wait_for_timeout(1500)
                logger.info("Successfully clicked Filter by outlets - proceeding with outlet selection logic.")
            else:
                logger.warning("Could not find or click 'Filter by outlets' using any method.")
                logger.info("Debug: Checking what elements are visible on page...")
                try:
                    # Debug: Show all visible text on page
                    page_text = page.locator('body').inner_text()
                    logger.info(f"DEBUG - Page text contains 'outlets': {'outlets' in page_text.lower()}")
                    logger.info(f"DEBUG - Page text contains 'filter': {'filter' in page_text.lower()}")
                    logger.info(f"DEBUG - Full page text sample (first 1000 chars): {page_text[:1000]}...")
                    
                    # Debug: Check if there are any clickable elements with "outlet" in text
                    outlet_elements = page.locator("*:has-text('outlet')").all()
                    logger.info(f"DEBUG - Found {len(outlet_elements)} elements containing 'outlet'")
                    for i, elem in enumerate(outlet_elements[:5]):  # Show first 5
                        try:
                            elem_text = elem.inner_text()
                            logger.info(f"DEBUG - Element {i+1}: '{elem_text}'")
                        except:
                            pass
                            
                except Exception as debug_e:
                    logger.info(f"DEBUG failed: {debug_e}")

            # Click Select All after custom date selection and Filter by outlets
            for frame in page.frames:
                try:
                    select_all_initial = frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[2]/div[2]/div/div[2]/div[2]/div")
                    if select_all_initial.is_visible():
                        select_all_initial.click()
                        logger.info("Select All clicked after custom date selection")
                        page.wait_for_timeout(1500)
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
                                if filter_btn.is_visible():
                                    filter_btn.click()
                                    page.wait_for_timeout(1500)
                                    logger.info("Main Filter reopened")
                                    break
                            except: continue
                        
                        # Select Custom date again for subsequent RIDs
                        if not select_custom_date_option(page, target_date):
                            logger.warning("Custom date selection failed for subsequent RID, but continuing...")
                        
                        # Click "Filter by outlets" again for subsequent RIDs
                        logger.info("Clicking 'Filter by outlets' for RID selection...")
                        filter_outlets_clicked = False
                        
                        # Try in main page first
                        try:
                            filter_outlets_text = page.locator("text=Filter by outlets")
                            if filter_outlets_text.is_visible():
                                filter_outlets_text.click()
                                logger.info("Filter by outlets clicked using main page text locator.")
                                filter_outlets_clicked = True
                            else:
                                filter_outlets_xpath = page.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[1]/div[4]/div")
                                if filter_outlets_xpath.is_visible():
                                    filter_outlets_xpath.click()
                                    logger.info("Filter by outlets clicked using main page XPath.")
                                    filter_outlets_clicked = True
                        except Exception as e:
                            logger.info(f"Main page search failed: {e}")
                        
                        # Try in frames if main page didn't work
                        if not filter_outlets_clicked:
                            logger.info("Searching for 'Filter by outlets' in frames...")
                            for frame in page.frames:
                                try:
                                    if frame.locator("text=Filter by outlets").is_visible():
                                        frame.locator("text=Filter by outlets").click()
                                        logger.info("Filter by outlets clicked using frame text locator.")
                                        filter_outlets_clicked = True
                                        break
                                    elif frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[1]/div[4]/div").is_visible():
                                        frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[1]/div[4]/div").click()
                                        logger.info("Filter by outlets clicked using frame XPath.")
                                        filter_outlets_clicked = True
                                        break
                                    elif frame.locator("text*=outlets").is_visible():
                                        frame.locator("text*=outlets").click()
                                        logger.info("Filter by outlets clicked using frame partial text.")
                                        filter_outlets_clicked = True
                                        break
                                except:
                                    continue
                        
                        if filter_outlets_clicked:
                            page.wait_for_timeout(1500)
                        else:
                            logger.warning("Could not find 'Filter by outlets' for RID selection.")
                        
                        # After reopening filter and clicking Filter by outlets, reset outlet selection
                        logger.info("Resetting outlet selection by clicking Select All twice...")
                        for frame in page.frames:
                            try:
                                select_all_reset = frame.locator("xpath=/html/body/div[2]/div/div/div/div[2]/div[2]/div[2]/div/div[2]/div[2]/div")
                                if select_all_reset.is_visible():
                                    select_all_reset.click()
                                    page.wait_for_timeout(500)
                                    select_all_reset.click()
                                    logger.info("Select All clicked twice to reset outlet selection")
                                    page.wait_for_timeout(1000)
                                    break
                            except: continue

                    # Select All clicking logic: First time = once, subsequent times = twice (already done above)
                    if index == 0:
                        # For first RID, just click Select All once (this happens in the initial setup above)
                        logger.info("First RID - Select All was already clicked once in initial setup")
                    else:
                        # For subsequent RIDs, Select All was already clicked twice in reset logic above
                        logger.info("Subsequent RID - Select All was already clicked twice in reset logic")

                    # Select specific RID
                    logger.info(f"Selecting specific RID: {rid}")
                    found = False
                    for frame in page.frames:
                        try:
                            rid_locator = frame.locator(f"text={rid}").first
                            if rid_locator.is_visible():
                                rid_locator.click()
                                logger.info(f"Selected RID: {rid}")
                                page.wait_for_timeout(1000)
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
                            if apply_btn.is_visible():
                                apply_btn.click()
                                logger.info("Applied.")
                                page.wait_for_timeout(3000)
                                break
                        except: continue

                    # Scrape Metrics
                    logger.info("Scraping ALL metrics...")
                    full_text = ""
                    
                    # Try multiple scraping strategies for better coverage
                    try:
                        # Strategy 1: Look for rupee symbol
                        metric = page.locator("div:has-text('₹')").first
                        metric.wait_for(timeout=10000)
                        full_text = metric.inner_text()
                        logger.info("Found content using rupee symbol locator")
                    except PlaywrightTimeoutError:
                        try:
                            # Strategy 2: Look in frames for rupee symbol
                            for frame in page.frames:
                                try:
                                    metric = frame.locator("div:has-text('₹')").first
                                    metric.wait_for(timeout=5000)
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
                                    if content.is_visible():
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

                    # Debug: Show more of the scraped text
                    if full_text:
                        logger.info(f"DEBUG - Full text length: {len(full_text)} characters")
                        logger.info(f"DEBUG - First 300 chars: {full_text[:300]}...")
                        
                        # Look specifically for rupee amounts in the text
                        rupee_matches = re.findall(r'₹\s*[\d,]+|₹[\d,]+|\u20B9\s*[\d,]+|\u20B9[\d,]+', full_text)
                        logger.info(f"DEBUG - Found rupee amounts: {rupee_matches}")
                        
                        # Look for percentage values
                        percent_matches = re.findall(r'[\d.]+%', full_text)
                        logger.info(f"DEBUG - Found percentages: {percent_matches}")
                    else:
                        logger.warning("No text content found at all")

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
                time.sleep(2)

            logger.info(f"\nScraping completed! Successfully processed {successful_scrapes}/{len(RID_LIST)} RIDs")
            input("Press Enter to close the browser...")

        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            try:
                browser.close()
            except:
                pass

# === Run Script ===
if __name__ == "__main__":
    print("Starting Complete Swiggy Scraper with Custom Date Selection")
    print("Extracting ALL metrics: Orders, Customers, Ads, Performance")
    print(f"Gemini Status: {'Available' if model else 'Not Available (using regex fallback)'}")
    open_and_cycle_outlets()
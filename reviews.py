# reviews.py

from playwright.sync_api import sync_playwright
import google.generativeai as genai
import os
import time
import json
import gspread
import hashlib
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
import requests # Add this import
from datetime import datetime, timedelta
import re

# === Load environment variables and API keys ===
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# === Setup Google Sheet ===
# Ensure your service_account.json is in the same directory as your script
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
client = gspread.authorize(creds)
# The worksheet name is specific to reviews
sheet = client.open("Swiggy Zomato Dashboard").worksheet("Copy of swiggy_review")

# === RID to Brand Mapping ===
RID_BRAND_MAPPING = {
    # First 11 RIDs - Art Of Delight - Crafted Ice Creams And Desserts
    "121120": "Art Of Delight - Crafted Ice Creams And Desserts",
    "20663": "Art Of Delight - Crafted Ice Creams And Desserts",
    "248316": "Art Of Delight - Crafted Ice Creams And Desserts",
    "2811": "Art Of Delight - Crafted Ice Creams And Desserts",
    "311831": "Art Of Delight - Crafted Ice Creams And Desserts",
    "474649": "Art Of Delight - Crafted Ice Creams And Desserts",
    "66107": "Art Of Delight - Crafted Ice Creams And Desserts",
    "671434": "Art Of Delight - Crafted Ice Creams And Desserts",
    "699228": "Art Of Delight - Crafted Ice Creams And Desserts",
    "76879": "Art Of Delight - Crafted Ice Creams And Desserts",
    "860008": "Art Of Delight - Crafted Ice Creams And Desserts",
    
    # Rest of RIDs - Art of Delight Express
    "106018": "Art of Delight Express",
    "121907": "Art of Delight Express",
    "123889": "Art of Delight Express",
    "153827": "Art of Delight Express",
    "170057": "Art of Delight Express",
    "199634": "Art of Delight Express",
    "200210": "Art of Delight Express",
    "248665": "Art of Delight Express",
    "310981": "Art of Delight Express"
}

# Get unique brands from the mapping
BRAND_NAMES = list(set(RID_BRAND_MAPPING.values()))

# Apps Script Web App URL for Swiggy review matching
SWIGGY_MATCH_GAS_WEB_APP_URL = os.getenv("SWIGGY_MATCH_GAS_WEB_APP_URL", "")

# === Utility Functions ===
def adjust_timestamp_for_timezone(timestamp_str):
    """
    Adjusts timestamp by adding 5 hours 30 minutes to account for Render's GMT conversion.
    Input: 'Jul 19, 10:59 PM' or similar format
    Output: Adjusted timestamp string in same format
    """
    if not timestamp_str or timestamp_str.strip() == "":
        return timestamp_str
    
    try:
        # Parse various timestamp formats that might appear
        timestamp_patterns = [
            "%b %d, %I:%M %p",      # Jul 19, 10:59 PM
            "%b %d, %H:%M",         # Jul 19, 22:59
            "%B %d, %I:%M %p",      # July 19, 10:59 PM
            "%B %d, %H:%M",         # July 19, 22:59
            "%d %b, %I:%M %p",      # 19 Jul, 10:59 PM
            "%d %b, %H:%M",         # 19 Jul, 22:59
        ]
        
        parsed_time = None
        matched_pattern = None
        
        # Try to parse with different patterns
        for pattern in timestamp_patterns:
            try:
                # Add current year if not present
                test_timestamp = timestamp_str.strip()
                if not re.search(r'\d{4}', test_timestamp):  # No year found
                    current_year = datetime.now().year
                    test_timestamp = f"{test_timestamp}, {current_year}"
                    pattern = f"{pattern}, %Y"
                
                parsed_time = datetime.strptime(test_timestamp, pattern)
                matched_pattern = pattern
                break
            except ValueError:
                continue
        
        if parsed_time is None:
            print(f"Could not parse timestamp: {timestamp_str}. Returning original.")
            return timestamp_str
        
        # Add 5 hours 30 minutes (GMT to IST adjustment)
        adjusted_time = parsed_time + timedelta(hours=5, minutes=30)
        
        # Format back to original style (without year if it wasn't in original)
        if ', %Y' in matched_pattern:
            # Remove year from pattern for output formatting
            output_pattern = matched_pattern.replace(', %Y', '')
            formatted_time = adjusted_time.strftime(output_pattern)
        else:
            formatted_time = adjusted_time.strftime(matched_pattern)
        
        print(f"Timezone adjusted: {timestamp_str} → {formatted_time} (+5:30)")
        return formatted_time
        
    except Exception as e:
        print(f"Error adjusting timestamp '{timestamp_str}': {e}")
        return timestamp_str  # Return original if adjustment fails

def generate_review_hash(parsed_review: dict) -> str:
    """Generates a unique hash for a review to help with deduplication."""
    # Use Order ID as the primary key for deduplication, fallback to empty if missing
    order_id = parsed_review.get("Order ID", "").strip()
    timestamp = parsed_review.get("Timestamp", "").strip()
    unique_str = order_id if order_id else timestamp  # Prioritize Order ID, use Timestamp as fallback
    return hashlib.sha256(unique_str.encode('utf-8')).hexdigest()

def scroll_reviews(frame, max_scrolls=100):
    """Scrolls the review container to load more reviews."""
    print("Scrolling to load all review cards...")
    for _ in range(max_scrolls):
        try:
            # Adjust the selector if the class name changes or is too dynamic
            frame.evaluate("""
                const container = document.querySelector('[class*="sc-khLCKb"]');
                if (container) container.scrollBy(0, 500);
            """)
            time.sleep(0.4) # Small delay for content to load
        except Exception as e:
            print(f"Scrolling error: {e}") # Log error but don't stop scrolling loop
            break # Exit if scroll fails (e.g., container not found)

def extract_entire_visible_text(frame):
    """Extracts all visible text from the specified frame."""
    try:
        return frame.locator("body").inner_text().strip()
    except Exception as e:
        print(f"Failed to extract text from frame: {e}")
        return ""

def parse_review_with_gemini(raw_text):
    """Parses raw review text using the Gemini API."""
    prompt = f"""
You are an expert at parsing customer review text from Swiggy's partner portal. Parse the text by starting from the bottom and working upward, stopping at the first occurrence of an Order ID (a string starting with '#'). Extract the following fields based solely on the text within this range (from the bottom up to and including the first Order ID), ignoring all data from reviews above this Order ID:

Required Fields (must always be present):
- Order ID: The first string starting with '#' found from the bottom upward.
- Timestamp: The date and time (e.g., 'Jul 19, 10:59 PM') closest to and below the Order ID within the same review range.
- Outlet: The location name immediately following "Orders & Complaints are based on the last 90 days" within the same review range.
- Item Ordered: The item name(s) (e.g., 'Nostalgia Ice Cream Sandwiches - Pack Of 4') listed closest to and below the Order ID within the same review.

Optional Fields (include only if found within the same bottom-to-top range for the identified Order ID):
- Rating: A single digit (e.g., '4') indicating the customer rating within the same review.
- Status: Either 'UNRESOLVED' or 'EXPIRED' if present within the same review.
- Customer Name: The first name appearing immediately below the Order ID within the defined range, ignoring any names from reviews above the Order ID (e.g., ignore 'Abhishek Eswarappa' if it appears above). If no name is found below the Order ID in this range, leave it empty.
- Customer Info: Text including 'New Customer' or 'Repeat Customer' with a date (e.g., 'New Customer | Sunday, Jul 20, 2025') within the same review.
- Total Orders (90d): The number next to 'Orders 🍛' within the same review.
- Order Value (90d): The amount Below Bill Total.
- Complaints (90d): The number next to 'Complaints ⚠️' within the same review.
- Delivery Remark: Text indicating delivery status (e.g., 'This order was delivered on time') within the same review.

Instructions:
- Begin parsing from the bottom of the text and stop at the first Order ID encountered (e.g., '#21191574063-9546'). Include only the text below and up to this Order ID in the parsing range, completely disregarding any text or names (e.g., 'Abhishek Eswarappa') from reviews above this Order ID.
- For Customer Name, select only the first name that appears directly below the Order ID within this range. Do not consider names from prior reviews or text above the Order ID. If no name is found below the Order ID, set Customer Name to an empty string.
- Return the result as a compact JSON object. Do NOT use markdown or code block wrappers.
- If a required field is missing, use an empty string ("").
- For debugging, include a string field named "debug_context" with the 5 lines of text immediately surrounding the Order ID to verify the parsing range and name selection.

Review Text:
{raw_text}
"""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash') # Using the recommended model
        response = model.generate_content(
            [{"role": "user", "parts": [prompt]}],
            generation_config={"temperature": 0}
        )

        raw_content = response.text.strip()
        cleaned = raw_content.replace("```json", "").replace("```", "").strip()
        parsed_data = json.loads(cleaned)
        
        # Apply timezone adjustment to the timestamp
        if "Timestamp" in parsed_data and parsed_data["Timestamp"]:
            parsed_data["Timestamp"] = adjust_timestamp_for_timezone(parsed_data["Timestamp"])
        
        return parsed_data

    except json.JSONDecodeError as e:
        print(f"Failed to parse Gemini response as JSON: {e}")
        print("Raw Gemini Response:", raw_content)
        return None
    except Exception as e:
        print(f"Gemini API error: {e}")
        return None

def append_to_sheet(parsed_review, seen_hashes):
    """Appends a parsed review to the Google Sheet if it's not a duplicate."""
    try:
        item_ordered = parsed_review.get("Item Ordered", "")
        if isinstance(item_ordered, list):
            item_ordered = ", ".join(item_ordered)

        order_id = parsed_review.get("Order ID", "").strip()
        if not order_id:
            print("Skipping append: No valid Order ID found in parsed review.")
            return

        review_hash = generate_review_hash(parsed_review)
        if review_hash in seen_hashes:
            print(f"Duplicate review detected for Order ID: {order_id}. Hash: {review_hash}")
            return # Skip appending if duplicate

        row = [
            parsed_review.get("Order ID", ""),
            parsed_review.get("Timestamp", ""),  # This now contains the adjusted timestamp
            parsed_review.get("Outlet", ""),
            item_ordered,
            parsed_review.get("Rating", ""),
            parsed_review.get("Status", ""),
            parsed_review.get("Customer Name", ""),
            parsed_review.get("Customer Info", ""),
            parsed_review.get("Total Orders (90d)", ""),
            parsed_review.get("Order Value (90d)", ""),
            parsed_review.get("Complaints (90d)", ""),
            parsed_review.get("Delivery Remark", ""),
            parsed_review.get("RID", ""),  # Add RID column
            parsed_review.get("Brand", "")  # Add Brand column
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        seen_hashes.add(review_hash) # Add hash only after successful append

        print("Structured row appended to sheet:")
        print(row)
    except Exception as e:
        print(f"Failed to write structured row to Google Sheet: {e}")

def select_yesterday_date(page):
    """Selects yesterday's date (18th) in the calendar widget."""
    print("Selecting yesterday's date (18th)...")
    try:
        # Step 1: Click on the date button to open calendar
        print("Opening calendar...")
        date_button_clicked = False
        
        # Method 1: Try main page first
        try:
            date_button = page.locator("xpath=//*[@id='mfe-root']/div/div[3]/div[2]/div[1]/div/div[1]")
            if date_button.is_visible():
                date_button.click()
                print("Clicked date button using updated XPath on main page.")
                date_button_clicked = True
                time.sleep(2)
        except Exception as e:
            print(f"Main page XPath failed: {e}")
        
        # Method 2: Try in frames if main page didn't work
        if not date_button_clicked:
            print("Searching for date button in frames...")
            for frame in page.frames:
                try:
                    # Try XPath in frame
                    date_button_frame = frame.locator("xpath=//*[@id='mfe-root']/div/div[3]/div[2]/div[1]/div/div[1]")
                    if date_button_frame.is_visible():
                        date_button_frame.click()
                        print("Clicked date button using XPath in frame.")
                        date_button_clicked = True
                        time.sleep(2)
                        break
                except:
                    continue
        
        # Method 3: Try alternative selectors on main page
        if not date_button_clicked:
            print("Trying alternative selectors on main page...")
            alt_selectors = [
                "[class*='date-picker']",
                "[class*='calendar']",
                "button[class*='date']",
                "div[class*='date-select']",
                "[class*='date-input']",
                "[class*='date-field']"
            ]
            
            for selector in alt_selectors:
                try:
                    button = page.locator(selector).first
                    if button.is_visible():
                        button.click()
                        print(f"Clicked date button using selector: {selector}")
                        date_button_clicked = True
                        time.sleep(2)
                        break
                except:
                    continue
        
        # Method 4: Try alternative selectors in frames
        if not date_button_clicked:
            print("Trying alternative selectors in frames...")
            alt_selectors = [
                "[class*='date-picker']",
                "[class*='calendar']",
                "button[class*='date']",
                "div[class*='date-select']",
                "[class*='date-input']",
                "[class*='date-field']"
            ]
            
            for frame in page.frames:
                for selector in alt_selectors:
                    try:
                        button = frame.locator(selector).first
                        if button.is_visible():
                            button.click()
                            print(f"Clicked date button using selector {selector} in frame.")
                            date_button_clicked = True
                            time.sleep(2)
                            break
                    except:
                        continue
                if date_button_clicked:
                    break
        
        if not date_button_clicked:
            print("Could not find date button. Calendar may already be open or element not found.")
        
        # Wait for calendar modal to appear
        time.sleep(2)
        
        # Step 2: Check if we need to navigate to the correct month (September 2025)
        print("Checking calendar month...")
        try:
            # Try to find September 2025 in main page first
            month_text = page.locator("text=September 2025")
            month_found = month_text.is_visible()
            
            # If not found on main page, try in frames
            if not month_found:
                for frame in page.frames:
                    try:
                        month_text_frame = frame.locator("text=September 2025")
                        if month_text_frame.is_visible():
                            month_found = True
                            print("Found September 2025 in frame.")
                            break
                    except:
                        continue
            
            if not month_found:
                print("Navigating to September 2025...")
                # Try to find and click next button in main page
                next_clicked = False
                next_selectors = [
                    "button[aria-label*='next']",
                    ".react-calendar__navigation__next-button",
                    "[class*='navigation__next']",
                    "[class*='next-button']",
                    "button[class*='next']"
                ]
                
                for selector in next_selectors:
                    try:
                        next_button = page.locator(selector).first
                        if next_button.is_visible():
                            next_button.click()
                            print(f"Clicked next month button using selector: {selector}")
                            next_clicked = True
                            time.sleep(1)
                            break
                    except:
                        continue
                
                # If not found on main page, try in frames
                if not next_clicked:
                    for frame in page.frames:
                        for selector in next_selectors:
                            try:
                                next_button = frame.locator(selector).first
                                if next_button.is_visible():
                                    next_button.click()
                                    print(f"Clicked next month button using selector {selector} in frame.")
                                    next_clicked = True
                                    time.sleep(1)
                                    break
                            except:
                                continue
                        if next_clicked:
                            break
                            
        except Exception as e:
            print(f"Month navigation not needed or failed: {e}")
        
        # Step 3: Select the 18th date using dynamic XPath
        print("Selecting the 18th date...")
        date_selected = False
        
        # Primary method: Use dynamic XPath where button number matches date
        dynamic_xpath_selectors = [
            "//*[@id='mfe-root']/div/div[5]/div/div[3]/div/div[2]/div/div/div/div[2]/button[18]/abbr",
            "//*[@id='mfe-root']/div/div[5]/div/div[3]/div/div[2]/div/div/div/div[2]/button[18]",
            "xpath=//*[@id='mfe-root']/div/div[5]/div/div[3]/div/div[2]/div/div/div/div[2]/button[18]/abbr",
            "xpath=//*[@id='mfe-root']/div/div[5]/div/div[3]/div/div[2]/div/div/div/div[2]/button[18]"
        ]
        
        # Try dynamic XPath selectors in main page first
        for selector in dynamic_xpath_selectors:
            try:
                date_element = page.locator(selector).first
                if date_element.is_visible():
                    # Click twice as suggested
                    date_element.click()
                    time.sleep(0.5)
                    date_element.click()
                    print(f"Selected date 18 using dynamic XPath: {selector} (clicked twice)")
                    date_selected = True
                    time.sleep(1)
                    break
            except:
                continue
        
        # Try dynamic XPath selectors in frames
        if not date_selected:
            for frame in page.frames:
                for selector in dynamic_xpath_selectors:
                    try:
                        date_element = frame.locator(selector).first
                        if date_element.is_visible():
                            # Click twice as suggested
                            date_element.click()
                            time.sleep(0.5)
                            date_element.click()
                            print(f"Selected date 18 using dynamic XPath {selector} in frame (clicked twice)")
                            date_selected = True
                            time.sleep(1)
                            break
                    except:
                        continue
                if date_selected:
                    break
        
        # Fallback method: More generic button[18] selectors
        if not date_selected:
            print("Dynamic XPath failed, trying generic button[18] selectors...")
            generic_button_selectors = [
                "button[18] abbr",
                "button[18]",
                "[role='gridcell']:nth-child(18)",
                "div[role='grid'] button:nth-child(18)"
            ]
            
            # Try in main page
            for selector in generic_button_selectors:
                try:
                    date_element = page.locator(selector).first
                    if date_element.is_visible():
                        date_element.click()
                        time.sleep(0.5)
                        date_element.click()
                        print(f"Selected date 18 using generic selector: {selector} (clicked twice)")
                        date_selected = True
                        time.sleep(1)
                        break
                except:
                    continue
            
            # Try in frames
            if not date_selected:
                for frame in page.frames:
                    for selector in generic_button_selectors:
                        try:
                            date_element = frame.locator(selector).first
                            if date_element.is_visible():
                                date_element.click()
                                time.sleep(0.5)
                                date_element.click()
                                print(f"Selected date 18 using generic selector {selector} in frame (clicked twice)")
                                date_selected = True
                                time.sleep(1)
                                break
                        except:
                            continue
                    if date_selected:
                        break
        
        # Last resort: Precise aria-label selectors (keeping original backup)
        if not date_selected:
            print("Generic button selectors failed, trying precise aria-label selectors...")
            precise_aria_selectors = [
                '[aria-label="18 September 2025"]',
                '[aria-label="September 18, 2025"]',
                '[aria-label*="18 September 2025"]',
                '[aria-label*="September 18, 2025"]'
            ]
            
            # Try in main page
            for selector in precise_aria_selectors:
                try:
                    date_element = page.locator(selector).first
                    if date_element.is_visible():
                        date_element.click()
                        time.sleep(0.5)
                        date_element.click()
                        print(f"Selected date 18 using aria-label: {selector} (clicked twice)")
                        date_selected = True
                        time.sleep(1)
                        break
                except:
                    continue
            
            # Try in frames
            if not date_selected:
                for frame in page.frames:
                    for selector in precise_aria_selectors:
                        try:
                            date_element = frame.locator(selector).first
                            if date_element.is_visible():
                                date_element.click()
                                time.sleep(0.5)
                                date_element.click()
                                print(f"Selected date 18 using aria-label {selector} in frame (clicked twice)")
                                date_selected = True
                                time.sleep(1)
                                break
                        except:
                            continue
                    if date_selected:
                        break
        
        if not date_selected:
            print("Could not find or click on date 18. All methods failed.")
        
        # Step 4: Click the Confirm button
        print("Clicking Confirm button...")
        confirm_clicked = False
        confirm_selectors = [
            "button:has-text('Confirm')",
            "text=Confirm",
            "[class*='confirm']",
            "button[type='submit']"
        ]
        
        # Try main page first
        for selector in confirm_selectors:
            try:
                confirm_button = page.locator(selector).first
                if confirm_button.is_visible():
                    confirm_button.click()
                    print(f"Clicked Confirm button using selector: {selector}")
                    confirm_clicked = True
                    time.sleep(2)
                    break
            except:
                continue
        
        # Try in frames if not found on main page
        if not confirm_clicked:
            for frame in page.frames:
                for selector in confirm_selectors:
                    try:
                        confirm_button = frame.locator(selector).first
                        if confirm_button.is_visible():
                            confirm_button.click()
                            print(f"Clicked Confirm button using selector {selector} in frame.")
                            confirm_clicked = True
                            time.sleep(2)
                            break
                    except:
                        continue
                if confirm_clicked:
                    break
        
        if not confirm_clicked:
            print("Could not find or click Confirm button.")
            return False
        
        print("Successfully selected yesterday's date (18th) and confirmed.")
        return True
        
    except Exception as e:
        print(f"Error in date selection process: {e}")
        return False

def click_and_extract_reviews(page, rid):
    """Clicks on review labels, extracts text, parses, and appends to sheet for a specific RID."""
    frame = page.frames[1] # Assuming the reviews are always in the second frame
    scroll_reviews(frame)

    print("Loading existing reviews from sheet for deduplication...")
    existing_rows = sheet.get_all_values()[1:]  # Skip header
    seen_hashes = set()
    for row in existing_rows:
        # Ensure row has enough columns before accessing
        oid = row[0].strip() if len(row) > 0 else ""
        ts = row[1].strip() if len(row) > 1 else ""
        if oid:
            review_hash = generate_review_hash({"Order ID": oid, "Timestamp": ts})
            seen_hashes.add(review_hash)
    print(f"Loaded {len(seen_hashes)} existing review hashes from sheet.")

    expired = frame.locator("text=EXPIRED").all()
    unresolved = frame.locator("text=UNRESOLVED").all()
    all_labels = expired + unresolved
    print(f"Found {len(all_labels)} review labels to process for RID {rid}.")

    for idx, label in enumerate(all_labels):
        try:
            print(f"Clicking review label {idx + 1} for RID {rid}...")
            label.click()
            time.sleep(2.5) # Give time for content to load after click

            full_text = extract_entire_visible_text(frame)
            if not full_text:
                print("No text extracted from review card. Skipping.")
                continue

            print("Raw Review Text Extracted (last 1500 chars):")

            parsed = parse_review_with_gemini(full_text)
            if parsed:
                if not parsed.get("Order ID", "").strip():
                    print("Skipping review: Gemini did not return a valid Order ID.")
                    continue

                # Add RID information to parsed review
                parsed["RID"] = rid
                parsed["Brand"] = RID_BRAND_MAPPING.get(rid, "Unknown Brand")

                # Remap keys from Gemini's output to match sheet headers
                key_map = {
                    "OrderID": "Order ID",
                    "Timestamp": "Timestamp",
                    "Outlet": "Outlet",
                    "ItemOrdered": "Item Ordered",
                    "Rating": "Rating",
                    "Status": "Status",
                    "CustomerName": "Customer Name",
                    "CustomerInfo": "Customer Info",
                    "TotalOrders90d": "Total Orders (90d)",
                    "OrderValue90d": "Order Value (90d)",
                    "Complaints90d": "Complaints (90d)",
                    "DeliveryRemark": "Delivery Remark"
                }
                # Create a new dictionary with remapped keys, keeping original keys if not in key_map
                parsed_remapped = {key_map.get(k, k): v for k, v in parsed.items()}
                
                print("Parsed Review (remapped keys with adjusted timestamp):")
                print(json.dumps(parsed_remapped, indent=2))
                
                append_to_sheet(parsed_remapped, seen_hashes)
            else:
                print("Skipped review due to Gemini parsing error (returned None).")
        except Exception as e:
            print(f"Error processing review label {idx + 1}: {e}")
        time.sleep(1) # Small delay between clicks

def click_back_button(page):
    """Clicks the back button to return to brand selection."""
    print("Clicking back button to return to brand selection...")
    try:
        # Method 1: Try by XPath
        try:
            back_button = page.locator("xpath=/html/body/div[1]/div/div/div/div[1]/div[1]/button/div/img")
            if back_button.is_visible():
                back_button.click()
                print("Clicked back button using XPath.")
                time.sleep(2)
                return True
        except:
            pass
        
        # Method 2: Try alternative selectors
        back_selectors = [
            "button[class*='back']",
            "button img",
            "div[role='button'] img",
            "[class*='back-button']"
        ]
        
        for selector in back_selectors:
            try:
                button = page.locator(selector).first
                if button.is_visible():
                    button.click()
                    print(f"Clicked back button using selector: {selector}")
                    time.sleep(2)
                    return True
            except:
                continue
        
        # Method 3: Try in frames
        for frame in page.frames:
            try:
                back_button = frame.locator("xpath=/html/body/div[1]/div/div/div/div[1]/div[1]/button/div/img")
                if back_button.is_visible():
                    back_button.click()
                    print("Clicked back button in frame.")
                    time.sleep(2)
                    return True
            except:
                continue
        
        print("Could not find back button using any method.")
        return False
        
    except Exception as e:
        print(f"Error clicking back button: {e}")
        return False

def click_see_outlet_level_ratings(page, include_date_selection=False):
    """Clicks on 'See Outlet Level Ratings' button, optionally with date selection."""
    
    # If date selection is needed, do it first
    if include_date_selection:
        if not select_yesterday_date(page):
            print("Date selection failed, but continuing with outlet ratings...")
    
    print("Looking for 'See Outlet Level Ratings' button...")
    try:
        # Method 1: Try by XPath
        try:
            outlet_ratings_button = page.locator("xpath=/html/body/div[1]/div/div/div/div[1]/div[2]/button[2]/span")
            if outlet_ratings_button.is_visible():
                outlet_ratings_button.click()
                print("Clicked 'See Outlet Level Ratings' using XPath.")
                time.sleep(2)
                return True
        except:
            pass
        
        # Method 2: Try by text content
        try:
            outlet_ratings_button = page.locator("text=See Outlet Level Ratings")
            if outlet_ratings_button.is_visible():
                outlet_ratings_button.click()
                print("Clicked 'See Outlet Level Ratings' using text locator.")
                time.sleep(2)
                return True
        except:
            pass
        
        # Method 3: Try in frames
        for frame in page.frames:
            try:
                button_in_frame = frame.locator("text=See Outlet Level Ratings")
                if button_in_frame.is_visible():
                    button_in_frame.click()
                    print("Clicked 'See Outlet Level Ratings' in frame.")
                    time.sleep(2)
                    return True
            except:
                continue
        
        print("Could not find 'See Outlet Level Ratings' button")
        return False
        
    except Exception as e:
        print(f"Error clicking 'See Outlet Level Ratings' button: {e}")
        return False

def search_and_select_rid(page, rid):
    """Searches for and selects a specific RID."""
    print(f"Searching for RID: {rid}")
    try:
        # Method 1: Try by XPath
        search_input = None
        try:
            search_input = page.locator("xpath=/html/body/div[1]/div/div/div[2]/div/div/div[2]/div[1]/div[1]/input")
            if search_input.is_visible():
                search_input.clear()  # Clear any existing text
                search_input.fill(rid)
                print(f"Entered RID '{rid}' in search input using XPath.")
            else:
                raise Exception("XPath search input not visible")
        except:
            # Method 2: Try by placeholder text
            try:
                search_input = page.locator("input[placeholder*='Search item']")
                if search_input.is_visible():
                    search_input.clear()
                    search_input.fill(rid)
                    print(f"Entered RID '{rid}' in search input using placeholder.")
                else:
                    # Method 3: Try generic input search
                    search_inputs = page.locator("input").all()
                    for inp in search_inputs:
                        try:
                            if inp.is_visible():
                                inp.clear()
                                inp.fill(rid)
                                print(f"Entered RID '{rid}' in search input (generic method).")
                                break
                        except:
                            continue
            except:
                pass
        
        time.sleep(2)
        
        # Click on the search result (RID should appear as clickable result)
        print(f"Looking for RID '{rid}' in search results...")
        try:
            rid_result = page.locator(f"text={rid}").first
            if rid_result.is_visible():
                rid_result.click()
                print(f"Clicked on RID '{rid}' from search results.")
                time.sleep(3)
                return True
            else:
                # Try in frames
                for frame in page.frames:
                    try:
                        rid_in_frame = frame.locator(f"text={rid}").first
                        if rid_in_frame.is_visible():
                            rid_in_frame.click()
                            print(f"Clicked on RID '{rid}' from search results in frame.")
                            time.sleep(3)
                            return True
                    except:
                        continue
                
                print(f"Could not find RID '{rid}' in search results.")
                return False
        except Exception as e:
            print(f"Error clicking RID search result: {e}")
            return False
            
    except Exception as e:
        print(f"Error during RID search: {e}")
        return False

def scrape_and_push_reviews():
    """Main function to orchestrate Swiggy review scraping and pushing to sheet."""
    print("Starting Swiggy review scraping process with outlet-level RID functionality...")
    
    with sync_playwright() as p:
        # Use existing context if login state is saved, otherwise headless=False for manual login
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        
        # Check if swiggy_login.json exists for persistent login
        if os.path.exists("swiggy_login.json"):
            context = browser.new_context(storage_state="swiggy_login.json")
            print("Using saved login state (swiggy_login.json).")
        else:
            print("swiggy_login.json not found. You might need to log in manually first and save state.")
            context = browser.new_context()

        page = context.new_page()

        # Group RIDs by brand to minimize brand switching
        rids_by_brand = {}
        for rid, brand in RID_BRAND_MAPPING.items():
            if brand not in rids_by_brand:
                rids_by_brand[brand] = []
            rids_by_brand[brand].append(rid)

        # Process each brand and its RIDs
        for brand_idx, (brand, rids) in enumerate(rids_by_brand.items()):
            print(f"Processing brand: {brand} with {len(rids)} outlets")
            
            for rid_idx, rid in enumerate(rids):
                print(f"Processing RID {rid} ({rid_idx + 1}/{len(rids)}) for brand: {brand}")
                
                try:
                    # For first RID of first brand, do full setup
                    if brand_idx == 0 and rid_idx == 0:
                        # Go to customer ratings page
                        page.goto("https://partner.swiggy.com/business-metrics/customer-ratings", timeout=60000)
                        page.wait_for_load_state("networkidle")

                        # Try to close the popup if it appears
                        try:
                            popup = page.locator("text=No! Not needed").first
                            if popup.is_visible():
                                popup.click()
                                print("Closed 'No! Not needed' popup.")
                        except Exception:
                            pass

                        # Locate the iframe and interact within it
                        iframe = page.frame_locator("iframe").first
                        if not iframe:
                            raise Exception("Could not find the main iframe.")
                        
                        # Input brand name and select it
                        iframe.locator("input").first.fill(brand)
                        time.sleep(2)
                        
                        # Check if the brand name is clickable or if we need to select from a list
                        brand_option = iframe.locator(f"text={brand}").first
                        if brand_option.is_visible():
                            brand_option.click()
                            print(f"Selected brand: {brand}")
                        else:
                            print(f"Brand option '{brand}' not found in dropdown. Trying to continue anyway...")
                        
                        iframe.locator("text=Continue").first.click()
                        print("Clicked 'Continue'.")
                        time.sleep(3)
                    
                    # For first RID of subsequent brands, need to go back and select new brand
                    elif rid_idx == 0:
                        # Click back button to return to brand selection
                        if not click_back_button(page):
                            print("Failed to click back button, trying to navigate directly...")
                            page.goto("https://partner.swiggy.com/business-metrics/customer-ratings", timeout=60000)
                            page.wait_for_load_state("networkidle")
                        
                        time.sleep(2)
                        
                        # Select new brand
                        iframe = page.frame_locator("iframe").first
                        if iframe:
                            iframe.locator("input").first.fill(brand)
                            time.sleep(2)
                            
                            brand_option = iframe.locator(f"text={brand}").first
                            if brand_option.is_visible():
                                brand_option.click()
                                print(f"Selected brand: {brand}")
                            
                            iframe.locator("text=Continue").first.click()
                            print("Clicked 'Continue'.")
                            time.sleep(3)
                    
                    # For subsequent RIDs of same brand, just go back from outlet level
                    else:
                        # Click back button to return to brand overview
                        if not click_back_button(page):
                            print("Failed to click back button, continuing with current page...")
                        time.sleep(1)

                    # Click "See Outlet Level Ratings" button (with date selection only for first RID)
                    if not click_see_outlet_level_ratings(page, include_date_selection=(brand_idx == 0 and rid_idx == 0)):
                        print(f"Failed to access outlet level ratings for RID {rid}. Skipping...")
                        continue

                    # Search for and select specific RID
                    if not search_and_select_rid(page, rid):
                        print(f"Failed to search/select RID {rid}. Skipping...")
                        continue

                    # Now scrape reviews for this specific outlet/RID
                    print(f"Starting review extraction for RID {rid}...")
                    click_and_extract_reviews(page, rid)

                except Exception as e:
                    print(f"Error processing RID '{rid}': {e}")
                
                print(f"Completed processing RID {rid}")
                time.sleep(2)

        browser.close()
        print("Swiggy scraping complete.")

        # --- Call the Google Apps Script Web App after scraping ---
        print("Triggering Swiggy review matching via Google Apps Script...")
        if not SWIGGY_MATCH_GAS_WEB_APP_URL:
            print("WARNING: SWIGGY_MATCH_GAS_WEB_APP_URL is not set in .env. Cannot trigger Apps Script.")
            print("Please deploy your Apps Script as a Web App and paste its URL into your .env file as SWIGGY_MATCH_GAS_WEB_APP_URL.")
        else:
            try:
                # Make a GET request to the deployed Apps Script URL
                print(f"Calling Apps Script URL: {SWIGGY_MATCH_GAS_WEB_APP_URL}")
                response = requests.get(SWIGGY_MATCH_GAS_WEB_APP_URL)
                response.raise_for_status()
                
                # Apps Script is expected to return JSON
                gas_response = response.json() 
                if gas_response.get('success'):
                    print(f"Apps Script triggered successfully. Message: {gas_response.get('message')}")
                else:
                    print(f"Apps Script reported an error. Error: {gas_response.get('error')}")
                    print(f"Raw Apps Script response: {response.text}")
            except requests.exceptions.RequestException as e:
                print(f"Error triggering Apps Script: {e}")
                if 'response' in locals() and response.text:
                    print(f"Raw Apps Script response (on error): {response.text}")
            except json.JSONDecodeError:
                print(f"Could not decode JSON from Apps Script response. Raw: {response.text if 'response' in locals() else 'No response text'}")

    print("All review scraping processes completed.")

# This allows you to test reviews.py directly if needed, but main.py will call it.
if __name__ == "__main__":
    scrape_and_push_reviews()
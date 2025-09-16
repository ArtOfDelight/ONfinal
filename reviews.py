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
sheet = client.open("Swiggy Zomato Dashboard").worksheet("swiggy_review")

# === Brand List ===
BRAND_NAMES = [
    "Frosty Crumble",
    "Frosty Crumble By Art Of Delight",
    "Art Of Delight - Crafted Ice Creams And Desserts"
]

# Apps Script Web App URL for Swiggy review matching
# IMPORTANT: Replace with your deployed Google Apps Script Web App URL for Swiggy matching.
SWIGGY_MATCH_GAS_WEB_APP_URL = os.getenv("SWIGGY_MATCH_GAS_WEB_APP_URL", "") # Get from .env or default to empty string


# === Utils ===
def adjust_timestamp_for_timezone(timestamp_str):
    """
    Adjusts timestamp by subtracting 5 hours 30 minutes to account for Render's GMT conversion.
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
            print(f"⚠️ Could not parse timestamp: {timestamp_str}. Returning original.")
            return timestamp_str
        
        # Subtract 5 hours 30 minutes (IST to GMT adjustment)
        adjusted_time = parsed_time - timedelta(hours=5, minutes=30)
        
        # Format back to original style (without year if it wasn't in original)
        if ', %Y' in matched_pattern:
            # Remove year from pattern for output formatting
            output_pattern = matched_pattern.replace(', %Y', '')
            formatted_time = adjusted_time.strftime(output_pattern)
        else:
            formatted_time = adjusted_time.strftime(matched_pattern)
        
        print(f"🕐 Timezone adjusted: {timestamp_str} → {formatted_time}")
        return formatted_time
        
    except Exception as e:
        print(f"⚠️ Error adjusting timestamp '{timestamp_str}': {e}")
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
    print("🔽 Scrolling to load all review cards...")
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
        print(f"⚠️ Failed to extract text from frame: {e}")
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
        print(f"⚠️ Failed to parse Gemini response as JSON: {e}")
        print("Raw Gemini Response:", raw_content)
        return None
    except Exception as e:
        print(f"⚠️ Gemini API error: {e}")
        return None

def append_to_sheet(parsed_review, seen_hashes):
    """Appends a parsed review to the Google Sheet if it's not a duplicate."""
    try:
        item_ordered = parsed_review.get("Item Ordered", "")
        if isinstance(item_ordered, list):
            item_ordered = ", ".join(item_ordered)

        order_id = parsed_review.get("Order ID", "").strip()
        if not order_id:
            print("⚠️ Skipping append: No valid Order ID found in parsed review.")
            return

        review_hash = generate_review_hash(parsed_review)
        if review_hash in seen_hashes:
            print(f"⏭️ Duplicate review detected for Order ID: {order_id}. Hash: {review_hash}")
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
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        seen_hashes.add(review_hash) # Add hash only after successful append

        print("📤 Structured row appended to sheet:")
        print(row)
    except Exception as e:
        print(f"⚠️ Failed to write structured row to Google Sheet: {e}")

def click_and_extract_reviews(page):
    """Clicks on review labels, extracts text, parses, and appends to sheet."""
    frame = page.frames[1] # Assuming the reviews are always in the second frame
    scroll_reviews(frame)

    print("📊 Loading existing reviews from sheet for deduplication...")
    existing_rows = sheet.get_all_values()[1:]  # Skip header
    seen_hashes = set()
    for row in existing_rows:
        # Ensure row has enough columns before accessing
        oid = row[0].strip() if len(row) > 0 else ""
        ts = row[1].strip() if len(row) > 1 else ""
        if oid:
            review_hash = generate_review_hash({"Order ID": oid, "Timestamp": ts})
            seen_hashes.add(review_hash)
    print(f"📊 Loaded {len(seen_hashes)} existing review hashes from sheet.")

    expired = frame.locator("text=EXPIRED").all()
    unresolved = frame.locator("text=UNRESOLVED").all()
    all_labels = expired + unresolved
    print(f"🧾 Found {len(all_labels)} review labels to process.")

    for idx, label in enumerate(all_labels):
        try:
            print(f"\n➡️ Clicking review label {idx + 1}...")
            label.click()
            time.sleep(2.5) # Give time for content to load after click

            full_text = extract_entire_visible_text(frame)
            if not full_text:
                print("⚠️ No text extracted from review card. Skipping.")
                continue

            print("📋 Raw Review Text Extracted (last 1500 chars):")
          

            parsed = parse_review_with_gemini(full_text)
            if parsed:
                if not parsed.get("Order ID", "").strip():
                    print("⚠️ Skipping review: Gemini did not return a valid Order ID.")
                    continue

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
                
                print("✅ Parsed Review (remapped keys with adjusted timestamp):")
                print(json.dumps(parsed_remapped, indent=2))
                
                append_to_sheet(parsed_remapped, seen_hashes)
            else:
                print("❌ Skipped review due to Gemini parsing error (returned None).")
        except Exception as e:
            print(f"⚠️ Error processing review label {idx + 1}: {e}")
        time.sleep(1) # Small delay between clicks

def scrape_and_push_reviews():
    """Main function to orchestrate Swiggy review scraping and pushing to sheet."""
    print("🚀 Starting Swiggy review scraping process...")
    
    with sync_playwright() as p:
        # Use existing context if login state is saved, otherwise headless=False for manual login
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        
        # Check if swiggy_login.json exists for persistent login
        if os.path.exists("swiggy_login.json"):
            context = browser.new_context(storage_state="swiggy_login.json")
            print("💾 Using saved login state (swiggy_login.json).")
        else:
            print("🚫 swiggy_login.json not found. You might need to log in manually first and save state.")
            # If headless=True, this might fail unless you manually save login state before
            context = browser.new_context()

        page = context.new_page()

        for brand in BRAND_NAMES:
            print(f"\n🌐 Opening Swiggy Ratings for: {brand}")
            try:
                page.goto("https://partner.swiggy.com/business-metrics/customer-ratings", timeout=60000)
                page.wait_for_load_state("networkidle")

                # Try to close the popup if it appears
                try:
                    popup = page.locator("text=No! Not needed").first
                    if popup.is_visible():
                        popup.click()
                        print("✅ Closed 'No! Not needed' popup.")
                except Exception:
                    pass # Popup not found or other issue, just continue

                # Locate the iframe and interact within it
                iframe = page.frame_locator("iframe").first
                if not iframe:
                    raise Exception("Could not find the main iframe.")
                
                # Input brand name and select it
                iframe.locator("input").first.fill(brand)
                time.sleep(2) # Wait for dropdown to appear
                
                # Check if the brand name is clickable or if we need to select from a list
                brand_option = iframe.locator(f"text={brand}").first
                if brand_option.is_visible():
                    brand_option.click()
                    print(f"✅ Selected brand: {brand}")
                else:
                    print(f"⚠️ Brand option '{brand}' not found in dropdown. Ensure accurate brand name.")
                    # Fallback: just try to click continue, might work if input was sufficient
                
                iframe.locator("text=Continue").first.click()
                print("✅ Clicked 'Continue'.")
                time.sleep(5) # Give time for content to load after brand selection

                click_and_extract_reviews(page)

            except Exception as e:
                print(f"❌ Error processing brand '{brand}': {e}")
            print("🔁 Moving to next brand...\n")
            time.sleep(2)

        browser.close()
        print("✅ Swiggy scraping complete.")

        # --- Call the Google Apps Script Web App after scraping ---
        print("\n📞 Triggering Swiggy review matching via Google Apps Script...")
        if not SWIGGY_MATCH_GAS_WEB_APP_URL:
            print("⚠️ WARNING: SWIGGY_MATCH_GAS_WEB_APP_URL is not set in .env. Cannot trigger Apps Script.")
            print("Please deploy your Apps Script as a Web App and paste its URL into your .env file as SWIGGY_MATCH_GAS_WEB_APP_URL.")
        else:
            try:
                # Make a GET request to the deployed Apps Script URL
                print(f"Calling Apps Script URL: {SWIGGY_MATCH_GAS_WEB_APP_URL}")
                response = requests.get(SWIGGY_MATCH_GAS_WEB_APP_URL)
                response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                
                # Apps Script is expected to return JSON
                gas_response = response.json() 
                if gas_response.get('success'):
                    print(f"✅ Apps Script triggered successfully. Message: {gas_response.get('message')}")
                else:
                    print(f"❌ Apps Script reported an error. Error: {gas_response.get('error')}")
                    print(f"Raw Apps Script response: {response.text}") # For debugging
            except requests.exceptions.RequestException as e:
                print(f"❌ Error triggering Apps Script: {e}")
                if response is not None and response.text: # Check if response object exists and has text
                    print(f"Raw Apps Script response (on error): {response.text}")
            except json.JSONDecodeError:
                print(f"❌ Could not decode JSON from Apps Script response. Raw: {response.text if response is not None else 'No response text'}")

    print("✅ All review scraping processes completed.")

# This allows you to test reviews.py directly if needed, but main.py will call it.
if __name__ == "__main__":
    scrape_and_push_reviews()
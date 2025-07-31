# reviewsz.py

from playwright.sync_api import sync_playwright
import gspread
import re
from oauth2client.service_account import ServiceAccountCredentials
import requests
import hashlib # Added for hashing
import os # Added for environment variables
from dotenv import load_dotenv # Added for loading .env

# === Load environment variables if needed (though not directly used here, good practice) ===
load_dotenv()

SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Zomato Order Data"
CREDENTIALS_FILE = "service_account.json"
LOGIN_STORAGE_FILE = "zomato_login.json"

def init_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME)
    try:
        worksheet = sheet.worksheet(WORKSHEET_NAME)
        print(f"✅ Successfully connected to Google Sheet: '{SHEET_NAME}' -> '{WORKSHEET_NAME}'")
    except gspread.exceptions.WorksheetNotFound: # Catch specific exception for clarity
        print(f"⚠️ Worksheet '{WORKSHEET_NAME}' not found. Creating new worksheet...")
        worksheet = sheet.add_worksheet(title=WORKSHEET_NAME, rows="1000", cols="20")
        worksheet.append_row([
            "Outlet ID", "Order History", "Customer Rating", "Comment", "Order ID", "Date & Time",
            "Delivery Duration", "Placed", "Accepted", "Ready", "Delivery partner arrived",
            "Picked up", "Delivered", "Items Ordered", "Customer Distance"
        ])
        print(f"✅ Worksheet '{WORKSHEET_NAME}' created with headers.")
    return worksheet

def generate_order_hash(order_id: str) -> str:
    """Generates a hash for an order ID for deduplication."""
    return hashlib.sha256(order_id.encode('utf-8')).hexdigest()

def get_existing_order_hashes(worksheet):
    """Fetches existing Order IDs and returns their hashes for deduplication."""
    try:
        # Assuming Order ID is in the 5th column (index 4)
        order_ids = worksheet.col_values(5)
        # Skip header row, generate hashes for unique IDs
        return {generate_order_hash(order_id) for order_id in order_ids[1:] if order_id.strip()}
    except Exception as e:
        print(f"❌ Error fetching existing Order IDs for hashing: {e}")
        return set() # Return an empty set to avoid stopping the script

def push_to_sheet(ws, outlet_id, data):
    formatted_items = []
    for item in data['items']:
        formatted = re.sub(r'(\b\d+ x)', r'\n\1', item).strip()
        formatted_items.append(formatted)

    row = [
        outlet_id,
        data['history'],
        data['rating'],
        data['comment'],
        data['order_id'],
        data['datetime'],
        data['timeline'].get("Delivery Duration", ""),
        data['timeline'].get("Placed", ""),
        data['timeline'].get("Accepted", ""),
        data['timeline'].get("Ready", ""),
        data['timeline'].get("Delivery partner arrived", ""),
        data['timeline'].get("Picked up", ""),
        data['timeline'].get("Delivered", ""),
        " | ".join(formatted_items),
        data['distance']
    ]
    print("\n\n📤 Pushing row to sheet:", row)
    ws.append_row(row)

def extract_fields(text: str) -> dict:
    lines = text.strip().splitlines()
    output = {
        "history": "",
        "rating": "",
        "comment": "",
        "order_id": "",
        "datetime": "",
        "timeline": {},
        "items": [],
        "distance": ""
    }

    i = 0
    inside_items_section = False
    item_lines = []

    while i < len(lines):
        line = lines[i].strip()

        if not output["history"] and "order with you" in line:
            output["history"] = line

        if not output["rating"] and line.lower() == "customer rating" and i + 1 < len(lines):
            output["rating"] = lines[i + 1].strip()

        if not output["comment"]:
            quote_match = re.search(r'"([^"]+)"', line)
            if quote_match:
                output["comment"] = quote_match.group(1)

        if line == "ID:":
            if i + 1 < len(lines):
                output["order_id"] = lines[i + 1].strip()
            if i + 2 < len(lines):
                output["datetime"] = lines[i + 2].strip()

        if "Delivered in" in line:
            output["timeline"]["Delivery Duration"] = line

        timeline_keys = ["Placed", "Accepted", "Ready", "Delivery partner arrived", "Picked up", "Delivered"]
        if line in timeline_keys and i + 1 < len(lines):
            output["timeline"][line] = lines[i + 1].strip()

        if line in ["ORDER", "Order Details"]: # Added "Order Details" as an alternative trigger
            inside_items_section = True
            item_lines = []
            i += 1
            continue

        if inside_items_section and "Restaurant Packaging Charges" in line:
            inside_items_section = False
            # Before breaking, capture any remaining item lines that might not have been appended
            if item_lines:
                output["items"].append(" | ".join(item_lines))
                item_lines = [] # Reset for next item if any

        if inside_items_section:
            if line.strip() and not line.startswith("Total"): # Avoid total lines within items
                item_lines.append(line.strip())

        if not output["distance"] and "away" in line:
            output["distance"] = line

        i += 1
    
    # After the loop, if still inside items section (e.g., no "Restaurant Packaging Charges" found),
    # append any remaining items
    if inside_items_section and item_lines:
        output["items"].append(" | ".join(item_lines))

    return output

# Renamed run() to scrape_and_push_reviews() for consistency with main.py calls
def scrape_and_push_reviews():
    IDs = ["20647827","19501520", "20996205", "19418061", "19595967", "57750", "19501520", "20547934", "2113481", "20183353", "19595894", "18422924"]
    URL = "https://www.zomato.com/partners/onlineordering/reviews/"
    worksheet = init_sheet()
    existing_hashes = get_existing_order_hashes(worksheet) # Use hashes for deduplication

    with sync_playwright() as p:
        browser = browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--single-process",
            "--disable-accelerated-2d-canvas",
            "--no-zygote",
            "--disable-features=VizDisplayCompositor"])
        context = browser.new_context(storage_state=LOGIN_STORAGE_FILE)
        page = context.new_page()
        page.goto(URL)

        for index, outlet_id in enumerate(IDs):
            print(f"\n🔁 Processing Outlet ID: {outlet_id}")
            try:
                if index == 0:
                    search_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[1]/div[3]/div/div/div/div/div/div/div/input"
                    page.wait_for_selector(f"xpath={search_xpath}", timeout=10000)
                    page.locator(f"xpath={search_xpath}").fill(outlet_id)
                    print(f"✅ ID {outlet_id} entered successfully.")

                    page.wait_for_timeout(3000)
                    # Use a more generic selector if "Art Of Delight" is not always the first outlet name
                    try:
                        page.wait_for_selector("div.css-1dbjc4n[role='button']:has-text('ID:')", timeout=10000).click()
                        print("✅ Clicked on outlet from search results (generic).")
                    except:
                        # Fallback to specific name if generic fails (or if Art of Delight is always first)
                        page.wait_for_selector("text=Art Of Delight", timeout=10000)
                        page.locator("text=Art Of Delight").first.click()
                        print("✅ Clicked on 'Art Of Delight' (fallback).")
                else:
                    # Logic for switching outlets
                    outlet_switch_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div[2]/div[3]/div/div/div[3]/img"
                    # Ensure the switch button is visible and clickable
                    page.wait_for_selector(f"xpath={outlet_switch_xpath}", timeout=10000)
                    page.locator(f"xpath={outlet_switch_xpath}").click(force=True)
                    
                    input_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div[2]/div[3]/div[2]/div[1]/div/div/div/div/div/div/div/input"
                    page.wait_for_selector(f"xpath={input_xpath}", timeout=10000)
                    page.locator(f"xpath={input_xpath}").fill(outlet_id)
                    page.wait_for_timeout(3000) # Give time for results to appear
                    page.locator(f"text=ID: {outlet_id}").first.click()
                    print(f"✅ Switched to ID {outlet_id}")

                page.wait_for_timeout(3000)
                review_buttons = page.locator("text=View Review Details")
                count = min(review_buttons.count(), 10) # Limit to 10 reviews
                print(f"🔍 Found {review_buttons.count()} total review(s), processing {count}.")


                for i in range(count):
                    print(f"\n🔄 Opening review #{i + 1} for outlet {outlet_id}...")
                    
                    # Re-locate buttons each time as DOM might change
                    current_review_buttons = page.locator("text=View Review Details")
                    if current_review_buttons.count() <= i:
                        print(f"⚠️ Not enough review buttons found. Expected {i+1}, found {current_review_buttons.count()}. Breaking.")
                        break

                    current_review_buttons.nth(i).click()
                    page.wait_for_timeout(1000)

                    try:
                        # Click 'Order Details' if available to expand for full info
                        order_details_button = page.locator("text=Order Details").first
                        if order_details_button.is_visible():
                            order_details_button.click()
                            print("📄 Clicked 'Order Details'.")
                            page.wait_for_timeout(1500)
                        else:
                            print("ℹ️ 'Order Details' button not visible or already expanded.")
                    except Exception as e:
                        print(f"⚠️ Could not click 'Order Details': {e}")


                    try:
                        modal_section_locator = page.locator("div:has-text('ORDER TIMELINE')").first
                        modal_section_locator.wait_for(state='visible', timeout=5000)
                        full_modal_text = modal_section_locator.inner_text()
                        
                        extracted_data = extract_fields(full_modal_text) # Use the original extract_fields

                        order_id = extracted_data['order_id'].strip()
                        print(f"\n📋 Extracted Preview for Order ID: {order_id}")
                        for k, v in extracted_data.items():
                            if isinstance(v, dict):
                                print(f"{k}:\n" + "\n".join([f"   {ik}: {iv}" for ik, iv in v.items()]))
                            elif isinstance(v, list):
                                print(f"{k}:\n   " + "\n   ".join(v))
                            else:
                                print(f"{k}: {v}")

                        if not order_id:
                            print(f"⚠️ Skipping: No valid Order ID extracted for review #{i+1}.")
                        elif generate_order_hash(order_id) in existing_hashes:
                            print(f"⏭️ Skipping duplicate Order ID: {order_id}")
                        else:
                            push_to_sheet(worksheet, outlet_id, extracted_data)
                            existing_hashes.add(generate_order_hash(order_id))
                            print(f"✅ Added Order ID: {order_id}")

                    except Exception as e:
                        print(f"❌ Could not extract modal section or process review #{i+1}: {e}")

                    try:
                        close_button = page.locator("text=Close").first
                        if close_button.is_visible():
                            close_button.click(timeout=3000)
                        else:
                            page.keyboard.press("Escape") # Fallback if button not found/visible
                        print("✅ Closed review modal.")
                    except Exception as e:
                        print(f"⚠️ Could not close review modal: {e}")
                        page.keyboard.press("Escape") # Always try escape as a last resort
                    page.wait_for_timeout(1000) # Give time for modal to close

            except Exception as e:
                print(f"❌ Script failed for ID {outlet_id}: {e}")
            
            page.wait_for_timeout(2000) # Pause between outlets for stability


        # ✅ Trigger Apps Script Web App at the end
        try:
            APPS_SCRIPT_WEB_URL = "https://script.google.com/macros/s/AKfycbyHt37GPrtXQ64aYwNCz5huxX0wKHCysB4T1xf5M6Jfdl8DqEXQU3CvcAtVgJMqNwWtmQ/exec"
            print(f"\n🌐 Triggering Apps Script at: {APPS_SCRIPT_WEB_URL}")
            r = requests.get(APPS_SCRIPT_WEB_URL)
            if r.status_code == 200:
                print("✅ Apps Script triggered successfully.")
            else:
                print(f"⚠️ Apps Script returned HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print("❌ Failed to trigger Apps Script:", e)

        input("Press ENTER to close browser...")
        browser.close()

if __name__ == "__main__":
    scrape_and_push_reviews()
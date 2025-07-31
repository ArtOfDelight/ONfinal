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
WORKSHEET_NAME = "Zomato Complaints" # Ensure this matches your sheet tab name

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
        raise # Re-raise to stop execution if sheet connection fails

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
            return # Skip appending if duplicate

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

def scrape_and_push_complaints():
    """Main function to orchestrate Zomato complaint scraping and pushing to sheet."""
    print("🚀 Starting Zomato complaint scraping process...")
    sheet = init_gsheet()

    print("📊 Loading existing complaints from sheet for deduplication...")
    existing_rows = sheet.get_all_values()[1:] # Skip header row
    seen_hashes = set()
    for row in existing_rows:
        if len(row) > 4:
            complaint_id_from_sheet = row[4].strip()
            timestamp_from_sheet = row[5].strip() if len(row) > 5 else ""
            if complaint_id_from_sheet:
                complaint_hash = generate_complaint_hash({"Complaint ID": complaint_id_from_sheet, "Timestamp": timestamp_from_sheet})
                seen_hashes.add(complaint_hash)
    print(f"📊 Loaded {len(seen_hashes)} existing complaint hashes from sheet.")

    with sync_playwright() as p:
        browser = browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--single-process",
            "--disable-accelerated-2d-canvas",
            "--no-zygote",
            "--disable-features=VizDisplayCompositor"
])

        context = browser.new_context(storage_state="zomato_login.json")
        page = context.new_page()
        page.goto("https://www.zomato.com/partners/onlineordering/customerIssues/")
        page.wait_for_timeout(5000)

        for y in [200, 300, 400]:
            try:
                page.mouse.click(1100, y)
                page.wait_for_timeout(500)
            except:
                pass

        for idx, outlet_id in enumerate(OUTLET_IDS):
            print(f"\n🔁 Scraping Outlet ID: {outlet_id}")

            try:
                # Select outlet
                page.click("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[1]/div/div[2]/span")
                page.wait_for_timeout(1000)

                if idx > 0:
                    prev_id = OUTLET_IDS[idx - 1]
                    try:
                        page.locator(f"text=ID: {prev_id}").first.click()
                        page.wait_for_timeout(500)
                    except:
                        pass

                page.fill("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[2]/div[1]/div/div/div/div/div/div/div/input", outlet_id)
                page.wait_for_timeout(1500)
                page.locator(f"text=ID: {outlet_id}").first.click()
                page.wait_for_timeout(800)

                page.click("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[2]/div[4]/div[2]")
                page.wait_for_timeout(3000)

                view_buttons = page.locator(".css-1ttmdgu > .css-c4te0e > .css-19i1v5i").filter(has_text="View details")
                total = view_buttons.count()
                print(f"🔍 Found {total} complaints.")

                for i in range(total):
                    try:
                        print(f"\n🕵️ Checking complaint {i+1}/{total}")
                        # Re-locate the view buttons to avoid stale references
                        view_buttons = page.locator(".css-1ttmdgu > .css-c4te0e > .css-19i1v5i").filter(has_text="View details")
                        if view_buttons.count() <= i:
                            print(f"⚠️ Not enough 'View details' buttons found for complaint {i+1}/{total}. Skipping.")
                            continue

                        # Scroll to the button to ensure it's in view
                        view_buttons.nth(i).scroll_into_view_if_needed()
                        page.wait_for_timeout(500)
                        view_buttons.nth(i).click()
                        page.wait_for_timeout(3000)

                        # Attempt to click "Order details"
                        try:
                            order_details_xpath = "xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[2]/div[2]/div/div[1]/div[3]/div[1]/div/div[2]/div/div[2]"
                            order_details_locator = page.locator(order_details_xpath).first
                            if order_details_locator.is_visible():
                                print("    Attempting to click 'Order details' using provided XPath...")
                                order_details_locator.click()
                                page.wait_for_timeout(1500)
                            else:
                                print("    'Order details' element not visible at provided XPath. Skipping click.")
                        except Exception as click_e:
                            print(f"    Could not click 'Order details' at XPath: {click_e}")

                        raw_text = page.locator("body").inner_text(timeout=5000)

                        parsed_complaint = parse_complaint_with_gemini(raw_text, outlet_id)

                        if parsed_complaint:
                            status = parsed_complaint.get("Status", "").upper()
                            complaint_id = parsed_complaint.get("Complaint ID", "").strip()

                            if not complaint_id:
                                print(f"⚠️ Skipped complaint: Gemini did not return a valid Complaint ID for outlet {outlet_id}, complaint {i+1}.")
                            else:
                                print(f"✅ Complaint {complaint_id} (Status: {status}). Extracting and appending...")
                                append_complaint_to_sheet(sheet, parsed_complaint, seen_hashes)
                        else:
                            print(f"❌ Skipped complaint {i+1} for outlet {outlet_id} due to Gemini parsing error (returned None).")

                        # Close the complaint details modal
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(1500)

                        # Verify modal is closed by checking for absence of modal (using a generic modal class, adjust if specific class/ID is known)
                        modal_locator = page.locator(".css-1dbjc4n") # Adjust to match modal's class or ID if known
                        if modal_locator.count() > 0 and modal_locator.is_visible(timeout=2000):
                            print("    ⚠️ Modal may not have closed properly. Attempting to click outside to close...")
                            page.mouse.click(100, 100)
                            page.wait_for_timeout(1000)

                        # Refresh the page and repeat setup steps
                        print("    🔄 Refreshing page to ensure correct complaint loading...")
                        page.reload()
                        page.wait_for_timeout(5000)

                        # Handle pop-ups again after refresh
                        for y in [200, 300, 400]:
                            try:
                                page.mouse.click(1100, y)
                                page.wait_for_timeout(500)
                            except:
                                pass

                        # Re-select outlet after refresh
                        page.click("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[1]/div/div[2]/span")
                        page.wait_for_timeout(1000)
                        page.fill("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[2]/div[1]/div/div/div/div/div/div/div/input", outlet_id)
                        page.wait_for_timeout(1500)
                        page.locator(f"text=ID: {outlet_id}").first.click()
                        page.wait_for_timeout(800)
                        page.click("xpath=/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div[2]/div/div/div[3]/div[2]/div[4]/div[2]")
                        page.wait_for_timeout(3000)

                    except Exception as e:
                        print(f"❌ Failed to process complaint {i+1}/{total} for outlet {outlet_id}: {e}")
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(1000)

            except Exception as e:
                print(f"❌ Error for outlet {outlet_id}: {e}")

            page.wait_for_timeout(2000)

        input("\n✅ Done. Press ENTER to close.")
        browser.close()

if __name__ == "__main__":
    scrape_and_push_complaints()
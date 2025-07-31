from playwright.sync_api import sync_playwright
import time
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import google.generativeai as genai
import os

# === Setup Gemini ===
genai.configure(api_key="AIzaSyAtlVktuD6zjnftoOkewgdJx7EpX9I7sFY")

# === Google Sheet Setup ===
SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Swiggy Complaints"
CREDENTIALS_FILE = "service_account.json"

HEADERS = [
    "Outlet ID", "Complaint ID", "Status", "Expiry Date", "Expiry Time", "Reason",
    "Customer Name", "Customer History", "Description", "Comment",
    "Validation", "Refund Amount", "Image Link"
]

def parse_date_with_gemini(date_text):
    try:
        prompt = f"""Extract and convert the following expiry date into full timestamp in IST (India timezone) format: "{date_text}".
Return it in format: 2025-07-27 14:30 (24-hour).Take the year as 2025 and only give back the date no explainations."""
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(prompt)
        raw_response = response.text.strip()

        # Parse into datetime object
        dt = datetime.strptime(raw_response, "%Y-%m-%d %H:%M") - timedelta(days=3)

        # Format for Google Sheets
        expiry_date = dt.strftime("%d/%m/%Y")   # dd/mm/yyyy
        expiry_time = dt.strftime("%H:%M")
        return expiry_date, expiry_time
    except Exception as e:
        print(f"⚠️ Gemini failed to parse: {date_text} — {e}")
        return "❌ Gemini Date Error", "❌"

def push_to_google_sheet(data_rows):
    if not data_rows:
        print("❌ No data to push to sheet.")
        return

    print("🔐 Connecting to Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        sheet = client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)
        print("📄 Sheet opened successfully.")

        existing_ids = set(row[1] for row in sheet.get_all_values()[1:] if row)
        new_rows = [row for row in data_rows if row[1] not in existing_ids]

        if not new_rows:
            print("⚠️ All complaint IDs already exist. No new data to push.")
            return

        print(f"📤 Pushing {len(new_rows)} new complaints...")
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"✅ Successfully pushed to Google Sheet.")

    except Exception as e:
        print(f"❌ Google Sheet push failed: {e}")

def extract_structured_data(complaint_id, block_2, image_url):
    lines = [line.strip() for line in block_2.strip().splitlines() if line.strip()]
    status = "UNRESOLVED" if "UNRESOLVED" in lines else "❌"

    expiry_line = next((line for line in lines if line.startswith("Expires on")), "❌ Not Found")
    expiry_raw = expiry_line.replace("Expires on", "").strip()

    # Convert using Gemini
    expiry_date, expiry_time = parse_date_with_gemini(expiry_raw)

    expiry_index = lines.index(expiry_line) if expiry_line in lines else -1
    reason = lines[expiry_index + 1] if expiry_index + 1 < len(lines) else ""
    reason_items = []
    i = expiry_index + 2

    while i < len(lines):
        if any(k in lines[i].lower() for k in [' x ', 'gm', 'ml', 'scoop', 'pack', 'addon', 'item', 'pcs', 'qty']):
            reason_items.append(lines[i])
            i += 1
        else:
            break

    reason_block = f"{reason}\n" + "\n".join(reason_items)

    name = "❌ Not Found"
    while i < len(lines):
        if not any(k in lines[i].lower() for k in [' x ', 'gm', 'ml', 'scoop', 'pack', 'addon', 'item', 'pcs', 'qty']) and len(lines[i].split()) <= 4:
            name = lines[i]
            break
        i += 1

    type_keywords = ["HIGH VALUE CUSTOMER", "LOW VALUE CUSTOMER", "NEW CUSTOMER", "REPEAT CUSTOMER"]
    type_line = next((line for line in lines if any(k in line for k in type_keywords)), "❌ Not Found")
    type_index = lines.index(type_line) if type_line in lines else -1
    history = "\n".join(lines[type_index + 1:type_index + 4]) if type_index != -1 else "❌"

    comment_match = re.search(r'“([^”]+)”', "\n".join(lines))
    comment = comment_match.group(1) if comment_match else "❌ Not Found"

    res_idx = lines.index("RESOLUTION") if "RESOLUTION" in lines else -1
    resolution_line = lines[res_idx + 1] if res_idx + 1 < len(lines) else "❌"

    refund_line = next((line for line in lines if "Recommended Refund Amount" in line), "")
    refund_match = re.search(r'₹[\d,]+', refund_line)
    refund_amount = refund_match.group(0) if refund_match else "₹0"

    # Extract outlet ID before last UNRESOLVED
    block2_lines = block_2.splitlines()
    unresolved_indexes = [i for i, line in enumerate(block2_lines) if "UNRESOLVED" in line]
    if unresolved_indexes:
        outlet_line = block2_lines[unresolved_indexes[-1] - 1].strip()
        outlet_id_match = re.search(r'\b\d+\b', outlet_line)
        outlet_id = outlet_id_match.group(0) if outlet_id_match else "❌ Not Found"
    else:
        outlet_id = "❌ Not Found"

    return [
        outlet_id, complaint_id, status, expiry_date, expiry_time, reason_block.strip(), name.strip(),
        history, type_line, comment, resolution_line, refund_amount, image_url
    ]

def scrape_and_push_complaints():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="swiggy_login.json")
        page = context.new_page()

        print("🌐 Opening Swiggy Complaints page...")
        page.goto("https://partner.swiggy.com/complaints/")
        page.wait_for_selector("text=Resolve this complaint", timeout=30000)

        try:
            page.locator("xpath=/html/body/div[1]/div[2]/div[3]/button[1]").click(timeout=5000)
            print("✅ Popup closed.")
        except:
            print("⚠️ No popup to close.")

        print("⏬ Scrolling to load all complaints...")
        resolve_blocks = page.locator("text=Resolve this complaint")
        previous_count = -1
        for _ in range(50):
            current_count = resolve_blocks.count()
            if current_count == previous_count:
                break
            previous_count = current_count
            resolve_blocks.nth(current_count - 1).scroll_into_view_if_needed()
            time.sleep(2)

        total = resolve_blocks.count()
        data_rows = []

        for i in range(total):
            try:
                block = resolve_blocks.nth(i)
                block.scroll_into_view_if_needed()
                block.click(force=True)
                time.sleep(2)

                full_text = page.inner_text("body")
                all_ids = re.findall(r'#\d+', full_text)
                complaint_id = all_ids[i] if i < len(all_ids) else f"❌ ID not found #{i + 1}"

                start_index = full_text.find("UNRESOLVED")
                end_index = full_text.find("Will reflect in your next payout")
                block_2 = full_text[start_index:end_index].strip()

                try:
                    image_url = page.locator("div img").nth(0).get_attribute("src") or ""
                except:
                    image_url = ""

                structured_row = extract_structured_data(complaint_id, block_2, image_url)
                data_rows.append(structured_row)

            except Exception as e:
                print(f"⚠️ Error at complaint #{i + 1}: {e}")
                continue

        print(f"✅ Extracted {len(data_rows)} complaints.")
        push_to_google_sheet(data_rows)
        browser.close()

# === Run it ===
scrape_and_push_complaints()

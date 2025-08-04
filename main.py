# main.py
from complaints import scrape_and_push_complaints as scrape_swiggy_complaints
from reviews import scrape_and_push_reviews as scrape_swiggy_reviews
from complaintsz import scrape_and_push_complaints as scrape_zomato_complaints
from reviewsz import scrape_and_push_reviews as scrape_zomato_reviews
from dotenv import load_dotenv
import os

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    print(f"🚀 Starting Multi-Platform Automation Sequence at {os.getenv('RENDER', 'local')}...")

    # --- Swiggy Complaints ---
    # try:
    #     print("\n📂 Step 1: Fetching Swiggy Complaints...")
    #     scrape_swiggy_complaints()
    #     print("✅ Swiggy Complaints completed")
    # except Exception as e:
    #     print(f"❌ Swiggy Complaints scraper failed: {e}")

    # # --- Swiggy Reviews ---
    # try:
    #     print("\n📂 Step 2: Fetching Swiggy Reviews...")
    #     scrape_swiggy_reviews()
    #     print("✅ Swiggy Reviews completed")
    # except Exception as e:
    #     print(f"❌ Swiggy Reviews scraper failed: {e}")

    # --- Zomato Complaints ---
    try:
        print("\n📂 Step 3: Fetching Zomato Complaints...")
        scrape_zomato_complaints()
        print("✅ Zomato Complaints completed")
    except Exception as e:
        print(f"❌ Zomato Complaints scraper failed: {e}")

    # --- Zomato Reviews ---
    try:
        print("\n📂 Step 4: Fetching Zomato Reviews...")
        scrape_zomato_reviews()
        print("✅ Zomato Reviews completed")
    except Exception as e:
        print(f"❌ Zomato Reviews scraper failed: {e}")

    print("\n✅ All scraping tasks complete.")
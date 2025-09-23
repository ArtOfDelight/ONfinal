# main.py
from complaints import scrape_and_push_complaints as scrape_swiggy_complaints
from reviews import scrape_and_push_reviews as scrape_swiggy_reviews
from complaintsz import scrape_and_push_complaints as scrape_zomato_complaints
from reviewsz import scrape_and_push_reviews as scrape_zomato_reviews

# Import the main scrapers
from SwiggyMain import open_and_cycle_outlets as scrape_swiggy_main
from ZomatoMain import scrape_multiple_outlets as scrape_zomato_main

from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    print(f"Starting Zomato Main Dashboard Scraper at {os.getenv('RENDER', 'local')}...")
    
    # Automatically calculate yesterday's date
    yesterday = datetime.now() - timedelta(days=1)
    
    # Set up date parameters for Zomato
    print("\nSetting up date parameters...")
    zomato_date_label = yesterday.strftime("%Y-%m-%d")   # YYYY-MM-DD format for Zomato
    
    print(f"Using yesterday's date: {zomato_date_label}")
    
    zomato_outlet_ids = [
        19418061, 19595967, 57750, 19501520,
        19501574, 20547934, 21134281, 20183353,
        19595894, 18422924, 20647827
    ]

    # --- Swiggy Complaints ---
    # try:
    #     print("\nStep 1: Fetching Swiggy Complaints...")
    #     scrape_swiggy_complaints()
    #     print("Swiggy Complaints completed")
    # except Exception as e:
    #     print(f"Swiggy Complaints scraper failed: {e}")

    #--- Swiggy Reviews ---
    try:
        print("\nStep 2: Fetching Swiggy Reviews...")
        scrape_swiggy_reviews()
        print("Swiggy Reviews completed")
    except Exception as e:
        print(f"Swiggy Reviews scraper failed: {e}")

    # --- Swiggy Main Dashboard ---
    try:
        print("\nStep 3: Running Swiggy Main Dashboard Scraper...")
        scrape_swiggy_main()
        print("Swiggy Main Dashboard completed")
    except Exception as e:
        print(f"Swiggy Main Dashboard scraper failed: {e}")

    #--- Zomato Complaints ---
    try:
        print("\nStep 4: Fetching Zomato Complaints...")
        scrape_zomato_complaints()
        print("Zomato Complaints completed")
    except Exception as e:
        print(f"Zomato Complaints scraper failed: {e}")

    # --- Zomato Reviews ---
    # try:
    #     print("\nStep 5: Fetching Zomato Reviews...")
    #     scrape_zomato_reviews()
    #     print("Zomato Reviews completed")
    # except Exception as e:
    #     print(f"Zomato Reviews scraper failed: {e}")

    # --- Zomato Main Dashboard ---
    # try:
    #     print("\nRunning Zomato Main Dashboard Scraper...")
    #     scrape_zomato_main(zomato_outlet_ids, zomato_date_label)
    #     print("Zomato Main Dashboard completed")
    # except Exception as e:
    #     print(f"Zomato Main Dashboard scraper failed: {e}")

    # print("\nZomato Main Dashboard scraping task complete.")
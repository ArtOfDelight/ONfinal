# main.py

# Swiggy Modules
from complaints import scrape_and_push_complaints as scrape_swiggy_complaints
from reviews import scrape_and_push_reviews as scrape_swiggy_reviews

# Zomato Modules (imported with aliases to avoid naming conflicts)
from complaintsz import scrape_and_push_complaints as scrape_zomato_complaints
from reviewsz import scrape_and_push_reviews as scrape_zomato_reviews

if __name__ == "__main__":
    print("🚀 Starting Multi-Platform Automation Sequence...")

    #--- Swiggy Complaints ---
    try:
        print("\n📂 Step 1: Fetching Swiggy Complaints...")
        scrape_swiggy_complaints()
    except Exception as e:
        print(f"❌ Swiggy Complaints scraper failed: {e}")

    # --- Swiggy Reviews ---
    try:
        print("\n📂 Step 2: Fetching Swiggy Reviews...")
        scrape_swiggy_reviews()
    except Exception as e:
        print(f"❌ Swiggy Reviews scraper failed: {e}")

    #--- Zomato Complaints ---
    try:
        print("\n📂 Step 3: Fetching Zomato Complaints...")
        scrape_zomato_complaints()
    except Exception as e:
        print(f"❌ Zomato Complaints scraper failed: {e}")

    # --- Zomato Reviews ---
    try:
        print("\n📂 Step 4: Fetching Zomato Reviews...")
        scrape_zomato_reviews()
    except Exception as e:
        print(f"❌ Zomato Reviews scraper failed: {e}")
        
    print("\n✅ All scraping tasks complete.")
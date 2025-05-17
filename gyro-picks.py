# gyro-picks.py

import sys
import os
import json
import hashlib
import logging
import re
import time
from datetime import datetime, timezone, timedelta 
from urllib.parse import urlparse, urljoin, quote 

# --- Path Setup & Project Root ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# Ensure the project root is in sys.path to find the 'src' package
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT) 

from dotenv import load_dotenv

# --- Corrected Imports for Agents and Scrapers ---
try:
    from src.scrapers.news_scraper import get_full_article_content 
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image 
except ImportError as e:
    print(f"FATAL IMPORT ERROR in gyro-picks.py: {e}.")
    print(f"Ensure 'src/scrapers/' and modules exist and are accessible from project root.")
    print(f"Current sys.path: {sys.path}")
    sys.exit(1)

dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO = os.path.join(DATA_DIR, 'raw_web_research')
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Gyro Pick Team') 
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola') 
YOUR_SITE_BASE_URL_FOR_LINKS = os.getenv('YOUR_SITE_BASE_URL', '/').rstrip('/') + '/' 

# --- Logging Setup ---
log_file_path_gyro = os.path.join(PROJECT_ROOT, 'gyro-picks.log') 
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path_gyro, encoding='utf-8')],
    force=True 
)
logger = logging.getLogger('GyroPicksTool') 
logger.setLevel(logging.DEBUG)


# --- Helper Functions ---
def ensure_gyro_directories():
    dirs_to_check = [DATA_DIR, RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO]
    for d_path in dirs_to_check:
        os.makedirs(d_path, exist_ok=True)
    logger.info("Ensured core directories exist for GyroPicks.")

def generate_gyro_article_id(url_for_hash): 
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    url_hash_part = hashlib.sha1(url_for_hash.encode('utf-8')).hexdigest()[:10]
    return f"gyro-{timestamp}-{url_hash_part}"

def get_initial_title_from_content(html_content, url_for_log=""):
    title = "Untitled Gyro Pick"
    if html_content:
        try:
            from bs4 import BeautifulSoup 
            soup = BeautifulSoup(html_content, 'html.parser')
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.find('h1'):
                title = soup.find('h1').get_text(strip=True)
            if title:
                title = re.sub(r'\s+', ' ', title).strip() 
            logger.info(f"Scraped initial title: '{title}' from {url_for_log}")
        except Exception as e:
            logger.warning(f"Could not scrape title from content for {url_for_log}: {e}")
    return title


# --- UI Input Functions ---
def get_quick_add_urls():
    urls = []; print("\n--- Gyro Pick - Quick Add Mode --- \nPaste article URL(s). Press Enter after each. Type 'done'.")
    while True:
        url_input = input(f"Quick Add URL {len(urls) + 1} (or 'done'): ").strip()
        if url_input.lower() == 'done':
            if not urls: print("No URLs. Exiting Quick Add."); return []
            break
        if not (url_input.startswith('http://') or url_input.startswith('https://')): print("Err: URL format."); continue
        try: parsed = urlparse(url_input); assert parsed.scheme and parsed.netloc; urls.append(url_input)
        except Exception: print(f"Err: Invalid URL.")
    return urls

def get_advanced_add_inputs():
    urls = []; print("\n--- Gyro Pick - Advanced Add Mode --- \nPrimary URL then optional other URLs for same story. Type 'done' for URLs.")
    primary_url = ""
    while not primary_url:
        primary_url = input("Primary URL: ").strip()
        if not (primary_url.startswith('http://') or primary_url.startswith('https://')): print("Err: Primary URL format."); primary_url = ""; continue
        try: urlparse(primary_url); urls.append(primary_url)
        except: print("Err: Invalid primary URL."); primary_url = ""
    print("Secondary URLs (optional). Type 'done'.")
    while True:
        url_input = input(f"Secondary URL {len(urls)} (or 'done'): ").strip()
        if url_input.lower() == 'done': break
        if not (url_input.startswith('http://') or url_input.startswith('https://')): print("Err: URL format."); continue
        try: urlparse(url_input); urls.append(url_input)
        except: print("Err: Invalid URL.")
    user_importance = "Interesting" 
    while True:
        choice = input("Mark as (1) Interesting or (2) Breaking [Default: 1]: ").strip()
        if choice == '1' or not choice: user_importance = "Interesting"; break
        elif choice == '2': user_importance = "Breaking"; break
        else: print("Invalid choice.")
    is_trending = input("Mark as 'Trending Pick' (top banner highlight)? (yes/no) [Default: no]: ").strip().lower() == 'yes'
    user_img = None
    if input("Provide direct image URL? (yes/no) [Default: no, will scrape/search]: ").strip().lower() == 'yes':
        img_input = input("Paste direct image URL: ").strip()
        if img_input.startswith('http://') or img_input.startswith('https://'): user_img = img_input
        else: print("Warning: Invalid image URL provided. Will attempt to scrape/search instead.")
    return urls, user_importance, is_trending, user_img


# --- Gyro Pick Specific Data Preparation ---
def save_raw_gyro_pick_for_pipeline(article_id, data):
    filepath = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO, f"{article_id}.json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"SAVED RAW GYRO PICK: {os.path.basename(filepath)} for main pipeline processing.")
        return True
    except Exception as e:
        logger.error(f"Failed to save raw Gyro Pick JSON {os.path.basename(filepath)}: {e}")
        return False

def create_raw_gyro_pick_file(article_urls, mode, user_importance_override=None, user_is_trending_pick=None, user_provided_image_url=None):
    if not article_urls: logger.error("No URLs provided for Gyro Pick. Skipping."); return False
    primary_url = article_urls[0]
    logger.info(f"--- Preparing Gyro Pick ({mode} mode) for URL: {primary_url} ---")

    gyro_pick_id = generate_gyro_article_id(primary_url)
    
    raw_gyro_filepath = os.path.join(RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO, f"{gyro_pick_id}.json")
    if os.path.exists(raw_gyro_filepath):
        logger.warning(f"Raw Gyro Pick file for ID {gyro_pick_id} (from {primary_url}) already exists in queue. Skipping creation.")
        return False

    logger.info(f"Fetching full content for Gyro Pick: {primary_url}")
    full_content = get_full_article_content(primary_url) 
    if not full_content:
        logger.error(f"Could not fetch content for Gyro Pick primary URL {primary_url}. Aborting this pick.")
        return False
    
    initial_title = get_initial_title_from_content(full_content, primary_url)

    logger.info(f"Determining image for Gyro Pick: {initial_title}")
    image_url_to_use = user_provided_image_url 
    if not image_url_to_use:
        scraped_from_source = scrape_source_for_image(primary_url)
        if scraped_from_source:
            image_url_to_use = scraped_from_source
            logger.info(f"Gyro: Used image scraped directly from source: {image_url_to_use}")
        else:
            logger.info(f"Gyro: Could not scrape from source, searching for best image for '{initial_title}'...")
            image_url_to_use = find_best_image(initial_title, article_url_for_scrape=primary_url)
            if image_url_to_use:
                logger.info(f"Gyro: Found best image via search: {image_url_to_use}")
            else:
                logger.warning(f"Gyro: Could not find any image for '{initial_title}'. Using placeholder.")
                image_url_to_use = "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"

    raw_article_data_for_pipeline = {
        'id': gyro_pick_id,
        'original_source_url': primary_url,
        'all_source_links_gyro': article_urls,
        'initial_title_from_web': initial_title,
        'raw_scraped_text': full_content,
        'research_topic': f"Gyro Pick - {mode}", 
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'is_gyro_pick': True,
        'gyro_pick_mode': mode,
        'user_importance_override_gyro': user_importance_override,
        'user_is_trending_pick_gyro': user_is_trending_pick,
        'user_provided_image_url_gyro': user_provided_image_url, 
        'selected_image_url': image_url_to_use, 
        'author': AUTHOR_NAME_DEFAULT, 
        'published_iso': datetime.now(timezone.utc).isoformat() 
    }

    if save_raw_gyro_pick_for_pipeline(gyro_pick_id, raw_article_data_for_pipeline):
        logger.info(f"--- Successfully prepared and queued Gyro Pick: {gyro_pick_id} ('{initial_title}') ---")
        logger.info(f"    Raw JSON saved to: {raw_gyro_filepath}")
        return True
    else:
        logger.error(f"Failed to save raw Gyro Pick data for {gyro_pick_id}.")
        return False

# --- Main Interactive Loop ---
if __name__ == "__main__":
    ensure_gyro_directories()
    logger.info("GyroPicks Tool Started. Prepares raw article data for the main pipeline.")
    logger.info(f"Raw Gyro Pick JSONs will be saved to: {RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO}")
    logger.info("The main pipeline (src/main.py) will then process these files.")

    while True:
        mode_choice = input("\nGyro Pick Tool: (1) Quick Add URL (2) Advanced Add URL(s) (0) Exit: ").strip()
        if mode_choice == '0':
            logger.info("Exiting Gyro Picks tool.")
            break
        elif mode_choice == '1':
            q_urls = get_quick_add_urls()
            if not q_urls: continue
            processed_count_quick = 0
            for i, url in enumerate(q_urls):
                logger.info(f"\nPreparing Quick Add Gyro Pick {i+1}/{len(q_urls)}: {url}")
                if create_raw_gyro_pick_file([url], mode="Quick"):
                    processed_count_quick +=1
                if i < len(q_urls) - 1:
                    logger.info("Brief pause before next Quick Add URL...")
                    time.sleep(1) 
            logger.info(f"Quick Add finished. Prepared {processed_count_quick}/{len(q_urls)} items for the main pipeline.")
        elif mode_choice == '2':
            adv_urls, imp, trend, img_url = get_advanced_add_inputs()
            if not adv_urls: continue
            logger.info(f"\nPreparing Advanced Add Gyro Pick for primary URL: {adv_urls[0]}")
            create_raw_gyro_pick_file(
                adv_urls, 
                mode="Advanced", 
                user_importance_override=imp, 
                user_is_trending_pick=trend, 
                user_provided_image_url=img_url
            )
        else:
            print("Invalid choice. Please enter 0, 1, or 2.")

    logger.info("--- Gyro Picks tool session finished. ---")
    print("\nGyro Picks saved. Run main.py to process them through the full pipeline.")
# gyro-picks.py (Self-contained content fetching)

import sys
import os
import json
import hashlib
import logging
import re
import time
import html # For unescaping titles/summaries if needed, though content is plain text
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Comment # For content extraction & title

try:
    import trafilatura
except ImportError:
    trafilatura = None
    logging.warning("Trafilatura library not found. Full article fetching will rely on basic BeautifulSoup. pip install trafilatura")

# --- Path Setup & Project Root ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT) 

from dotenv import load_dotenv

# --- Image Scraper Import (Still needed) ---
try:
    from src.scrapers.image_scraper import find_best_image, scrape_source_for_image 
except ImportError as e:
    print(f"FATAL IMPORT ERROR in gyro-picks.py (image_scraper): {e}.")
    print(f"Ensure 'src/scrapers/image_scraper.py' exists and is accessible.")
    sys.exit(1)

dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration ---
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO = os.path.join(DATA_DIR, 'raw_web_research')
AUTHOR_NAME_DEFAULT = os.getenv('AUTHOR_NAME', 'Gyro Pick Team') 
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola') 

# Content Fetching Config (moved from news_scraper.py)
ARTICLE_FETCH_TIMEOUT = 20
MIN_FULL_TEXT_LENGTH = 250 

# --- Logging Setup ---
log_file_path_gyro = os.path.join(PROJECT_ROOT, 'gyro-picks.log') 
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file_path_gyro, encoding='utf-8')],
    force=True 
)
logger = logging.getLogger('GyroPicksTool')

# --- START: Content Fetching Logic (Adapted from news_scraper.py) ---
def _fetch_full_article_text_with_trafilatura(article_url, downloaded_html):
    """Extracts main content using Trafilatura."""
    if not trafilatura:
        return None
    try:
        extracted_text = trafilatura.extract(downloaded_html,
                                             include_comments=False,
                                             include_tables=False,
                                             output_format='txt',
                                             deduplicate=True)
        if extracted_text and len(extracted_text.strip()) >= MIN_FULL_TEXT_LENGTH:
            logger.info(f"Trafilatura extracted content from {article_url} (Length: {len(extracted_text)})")
            return extracted_text.strip()
        else:
            logger.debug(f"Trafilatura extracted insufficient text (Length: {len(extracted_text or '')}) from {article_url}.")
            return None
    except Exception as e:
        logger.warning(f"Trafilatura extraction failed for {article_url}: {e}")
        return None

def _fetch_full_article_text_bs_fallback(article_url, downloaded_html):
    """Fallback to BeautifulSoup for main content extraction."""
    try:
        soup = BeautifulSoup(downloaded_html, 'html.parser')
        tags_to_remove = ['script', 'style', 'nav', 'footer', 'aside', 'header', 'form', 'button', 'input',
                          '.related-posts', '.comments', '.sidebar', '.ad', '.banner', '.share-buttons',
                          '.newsletter-signup', '.cookie-banner', '.site-header', '.site-footer',
                          '.navigation', '.menu', '.social-links', '.author-bio', '.pagination',
                          '#comments', '#sidebar', '#header', '#footer', '#navigation', '.print-button',
                          '.breadcrumbs', 'figcaption', 'figure > div']
        for selector in tags_to_remove:
            for element in soup.select(selector):
                element.decompose()
        for comment_tag in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment_tag.extract()

        main_content_selectors = ['article[class*="content"]', 'article[class*="post"]', 'article[class*="article"]',
                                  'main[id*="content"]', 'main[class*="content"]', 'div[class*="article-body"]',
                                  'div[class*="post-body"]', 'div[class*="entry-content"]', 'div[class*="story-content"]',
                                  'div[id*="article"]', 'div#content', 'div#main', '.article-content']
        best_text = ""
        for selector in main_content_selectors:
            element = soup.select_one(selector)
            if element:
                text_parts = []
                for child in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'pre']):
                    if child.name == 'p' and child.find('a') and len(child.find_all(text=True, recursive=False)) == 0 and len(child.find_all('a')) == 1:
                        link_text = child.find('a').get_text(strip=True)
                        if link_text and len(link_text) > 20:
                             text_parts.append(link_text)
                        continue
                    text_parts.append(child.get_text(separator=' ', strip=True))
                current_text = "\n\n".join(filter(None, text_parts)).strip()
                if len(current_text) > len(best_text):
                    best_text = current_text
        
        if best_text and len(best_text) >= MIN_FULL_TEXT_LENGTH:
            logger.info(f"BS (selector) extracted from {article_url} (Length: {len(best_text)})")
            return best_text
        
        body = soup.find('body')
        if body:
            content_text = ""
            paragraphs = body.find_all('p')
            if paragraphs:
                 text_parts = [p.get_text(separator=' ', strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50]
                 content_text = "\n\n".join(filter(None, text_parts)).strip()
            if content_text and len(content_text) >= MIN_FULL_TEXT_LENGTH:
                logger.info(f"BS (aggressive) extracted from {article_url} (Length: {len(content_text)})")
                return content_text
        logger.warning(f"BS fallback failed for {article_url}.")
        return None
    except Exception as e:
        logger.error(f"Error parsing with BS fallback from {article_url}: {e}")
        return None

def get_full_article_content_standalone(article_url):
    """Fetches HTML and tries multiple methods to extract main article text."""
    if not article_url or not article_url.startswith('http'):
        logger.debug(f"Invalid article_url for content fetch: {article_url}")
        return None, None # Return None for both title and text
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DacoolaNewsBot/1.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(article_url, headers=headers, timeout=ARTICLE_FETCH_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"Content type for {article_url} is not HTML ({content_type}).")
            return None, None
            
        downloaded_html = response.text

        # Extract title using BeautifulSoup (done by get_initial_title_from_content now)
        initial_title = get_initial_title_from_content(downloaded_html, article_url) # Uses BS

        # Try Trafilatura first for main text
        content_text = _fetch_full_article_text_with_trafilatura(article_url, downloaded_html)

        # If Trafilatura fails, try BeautifulSoup fallback
        if not content_text:
            logger.info(f"Trafilatura failed/insufficient for {article_url}, trying BS fallback.")
            content_text = _fetch_full_article_text_bs_fallback(article_url, downloaded_html)
        
        return initial_title, content_text # Return both title and text

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch HTML for {article_url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in get_full_article_content_standalone for {article_url}: {e}")
    return None, None # Return None for both on error
# --- END: Content Fetching Logic ---


# --- GyroPicks Helper Functions (Mostly Unchanged) ---
def ensure_gyro_directories():
    dirs_to_check = [DATA_DIR, RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO]
    for d_path in dirs_to_check:
        os.makedirs(d_path, exist_ok=True)
    logger.info(f"Ensured GyroPicks directories. Raw output to: {RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO}")

def generate_gyro_article_id(url_for_hash): 
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    url_hash_part = hashlib.sha1(url_for_hash.encode('utf-8')).hexdigest()[:10]
    return f"gyro-{timestamp}-{url_hash_part}"

def get_initial_title_from_content(html_content_for_title, url_for_log=""): # Now used by get_full_article_content_standalone
    title = "Untitled Gyro Pick"
    if html_content_for_title:
        try:
            soup = BeautifulSoup(html_content_for_title, 'html.parser')
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.find('h1'):
                title = soup.find('h1').get_text(strip=True)
            if title:
                title = html.unescape(re.sub(r'\s+', ' ', title).strip())
            logger.info(f"Scraped initial title: '{title}' from {url_for_log}")
        except Exception as e:
            logger.warning(f"Could not scrape title from content for {url_for_log}: {e}")
    return title

# --- UI Input Functions (Unchanged) ---
def get_quick_add_urls():
    urls = []
    print("\n--- Gyro Pick - Quick Add Mode ---")
    print("Paste article URL(s). Press Enter after each URL. Type 'done' when finished.")
    while True:
        url_input = input(f"Quick Add URL {len(urls) + 1} (or 'done'): ").strip()
        if url_input.lower() == 'done':
            if not urls: 
                print("No URLs entered. Exiting Quick Add.")
                return []
            break
        if not (url_input.startswith('http://') or url_input.startswith('https://')):
            print("Error: URL must start with http:// or https://. Please try again.")
            continue
        try:
            parsed = urlparse(url_input)
            assert parsed.scheme and parsed.netloc 
            urls.append(url_input)
            print(f"Added: {url_input}")
        except Exception:
            print(f"Error: Invalid URL format for '{url_input}'. Please enter a valid URL.")
    return urls

def get_advanced_add_inputs():
    urls = []
    print("\n--- Gyro Pick - Advanced Add Mode ---")
    primary_url = ""
    while not primary_url:
        primary_url_input = input("Enter PRIMARY article URL: ").strip()
        if not (primary_url_input.startswith('http://') or primary_url_input.startswith('https://')):
            print("Error: Primary URL must start with http:// or https://.")
            continue
        try:
            urlparse(primary_url_input) 
            primary_url = primary_url_input
            urls.append(primary_url)
        except Exception:
            print("Error: Invalid primary URL format.")
    print("Enter any SECONDARY URLs for the same story (optional). Type 'done' when finished.")
    while True:
        url_input = input(f"Secondary URL {len(urls)} (or 'done'): ").strip()
        if url_input.lower() == 'done': break
        if not (url_input.startswith('http://') or url_input.startswith('https://')):
            print("Error: URL must start with http:// or https://.")
            continue
        try:
            urlparse(url_input); urls.append(url_input); print(f"Added secondary: {url_input}")
        except Exception: print("Error: Invalid secondary URL format.")
    user_importance = "Interesting" 
    while True:
        choice = input("Mark article as (1) Interesting or (2) Breaking [Default: 1-Interesting]: ").strip()
        if choice == '1' or not choice: user_importance = "Interesting"; break
        elif choice == '2': user_importance = "Breaking"; break
        else: print("Invalid choice. Please enter 1 or 2.")
    is_trending = input("Mark as 'Trending Pick' (highlight in banner)? (yes/no) [Default: no]: ").strip().lower() == 'yes'
    user_img = None
    if input("Provide a direct image URL? (yes/no) [Default: no, will attempt to scrape/search]: ").strip().lower() == 'yes':
        img_input = input("Paste direct image URL: ").strip()
        if img_input.startswith('http://') or img_input.startswith('https://'): user_img = img_input
        else: print("Warning: Invalid image URL provided. Will attempt to scrape/search instead.")
    return urls, user_importance, is_trending, user_img

# --- Gyro Pick Specific Data Preparation (Modified) ---
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
        logger.warning(f"Raw Gyro Pick file for ID {gyro_pick_id} from {primary_url} already exists. Skipping.")
        return False

    logger.info(f"Fetching title and full text content for Gyro Pick: {primary_url}")
    # Call the new self-contained content fetching function
    fetched_title, fetched_full_text = get_full_article_content_standalone(primary_url) 
    
    if not fetched_full_text: # Title might be generic, but text is crucial
        logger.error(f"Could not fetch or parse sufficient text content for Gyro Pick {primary_url}. Aborting.")
        return False
    
    final_title_to_use = fetched_title if fetched_title and fetched_title != "Untitled Gyro Pick" else "Manually Curated Article"

    logger.info(f"Determining image for Gyro Pick: '{final_title_to_use}'")
    image_url_to_use = user_provided_image_url 
    if not image_url_to_use:
        scraped_from_source = scrape_source_for_image(primary_url)
        if scraped_from_source:
            image_url_to_use = scraped_from_source
            logger.info(f"Gyro: Used image scraped directly from source: {image_url_to_use}")
        else:
            logger.info(f"Gyro: Could not scrape from source, searching for best image for '{final_title_to_use}'...")
            image_url_to_use = find_best_image(final_title_to_use, article_url_for_scrape=primary_url)
            if image_url_to_use: logger.info(f"Gyro: Found best image via search: {image_url_to_use}")
            else:
                logger.warning(f"Gyro: Could not find any image for '{final_title_to_use}'. Using placeholder.")
                image_url_to_use = "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"

    raw_article_data_for_pipeline = {
        'id': gyro_pick_id,
        'original_source_url': primary_url,
        'all_source_links_gyro': article_urls,
        'initial_title_from_web': final_title_to_use, # Use title from our standalone fetch
        'raw_scraped_text': fetched_full_text, # Use text from our standalone fetch
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
        logger.info(f"--- Successfully prepared Gyro Pick: {gyro_pick_id} ('{final_title_to_use}') ---")
        return True
    else:
        logger.error(f"Failed to save raw Gyro Pick data for {gyro_pick_id}.")
        return False

# --- Main Interactive Loop (Unchanged) ---
if __name__ == "__main__":
    ensure_gyro_directories()
    logger.info("GyroPicks Tool Started (Self-Contained Content Fetching).")
    logger.info(f"Raw Gyro Pick JSONs will be saved to: {RAW_WEB_RESEARCH_OUTPUT_DIR_GYRO}")
    logger.info("Run main.py to process these files through the full pipeline.")

    while True:
        print("\n======================================")
        print("       Gyro Pick Input Options        ")
        print("======================================")
        print("(1) Quick Add (Process single URLs one by one)")
        print("(2) Advanced Add (Primary URL + optionals, importance, trending, image)")
        print("(0) Exit Gyro Picks Tool")
        print("--------------------------------------")
        mode_choice = input("Choose an option (0-2): ").strip()

        if mode_choice == '0': logger.info("Exiting Gyro Picks tool."); break
        elif mode_choice == '1':
            q_urls = get_quick_add_urls()
            if not q_urls: continue
            processed_count_quick = 0
            for i, url in enumerate(q_urls):
                logger.info(f"\nProcessing Quick Add Gyro Pick {i+1}/{len(q_urls)}: {url}")
                if create_raw_gyro_pick_file([url], mode="Quick"): processed_count_quick +=1
                if i < len(q_urls) - 1: logger.info("Brief pause..."); time.sleep(1) 
            logger.info(f"Quick Add finished. Prepared {processed_count_quick}/{len(q_urls)} items.")
        elif mode_choice == '2':
            adv_urls, imp, trend, img_url = get_advanced_add_inputs()
            if not adv_urls: continue
            logger.info(f"\nProcessing Advanced Add Gyro Pick for primary URL: {adv_urls[0]}")
            create_raw_gyro_pick_file(adv_urls, mode="Advanced", user_importance_override=imp, 
                                      user_is_trending_pick=trend, user_provided_image_url=img_url)
        else: print("Invalid choice. Please enter 0, 1, or 2.")
    logger.info("--- Gyro Picks tool session finished. ---")
    print("\nGyro Picks tool exited. Run main.py to process any queued picks.")
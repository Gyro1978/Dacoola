# src/scrapers/news_scraper.py

import feedparser
import os
import sys
import json
import hashlib
import logging
import html  # <-- Added import
from datetime import datetime, timezone # Use timezone

# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# --- End Path Setup ---

# --- Configuration ---
# List of RSS Feed URLs (User provided list)
NEWS_FEED_URLS = [
    # --- Kept Feeds ---
    "https://techcrunch.com/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://blogs.nvidia.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
    "https://www.microsoft.com/en-us/research/blog/category/artificial-intelligence/feed/",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://www.cnet.com/rss/news/", # General Tech, but usually high quality
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
    "https://news.mit.edu/topic/artificial-intelligence2/feed",
    "https://blog.google/technology/ai/rss/", # Google AI Blog (New URL)
    "https://ai.meta.com/results/?content_types[0]=blog&rss=1", # Meta AI Blog (New URL, check if works)
    "https://research.googleblog.com/feeds/posts/default?alt=rss", # Google Research
    "https://ir.thomsonreuters.com/rss/news-releases.xml?items=15",
    
    ]

# File to store IDs of processed articles
PROCESSED_IDS_FILE = os.path.join(DATA_DIR, 'processed_article_ids.txt')
# Folder to save newly scraped articles as JSON files
OUTPUT_DIR = os.path.join(DATA_DIR, 'scraped_articles')
# Max *total* new articles to save across all feeds per run
MAX_ARTICLES_PER_RUN = 20 # Keep reasonably low (User provided value)
# --- End Configuration ---

# --- Setup Logging ---
logger = logging.getLogger(__name__) # Use module-specific logger
# Basic config for standalone testing if no handlers are present
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def get_article_id(entry, feed_url):
    """Generate a unique ID for an article entry, using feed_url for uniqueness."""
    # Decode title/summary here ONLY IF used for ID generation fallback
    raw_title = entry.get('title', '')
    raw_summary = entry.get('summary', entry.get('description', ''))

    guid = entry.get('id', ''); link = entry.get('link', '')
    if guid and guid != link: identifier_base = guid
    elif link: identifier_base = link
    else:
        # Use raw title/summary for ID generation if needed, decoding happens later for content
        identifier_base = raw_title + raw_summary
        if not identifier_base:
             identifier_base = str(datetime.now(timezone.utc).timestamp());
             logger.warning(f"Using timestamp ID {feed_url}. T: {raw_title}")
        else:
             logger.warning(f"Using title+summary ID {feed_url}. T: {raw_title}")
    identifier = f"{identifier_base}::{feed_url}"
    article_id = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    return article_id

def load_processed_ids():
    """Load the set of already processed article IDs from the file."""
    processed_ids = set()
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(PROCESSED_IDS_FILE):
            with open(PROCESSED_IDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped_line = line.strip();
                    if stripped_line: processed_ids.add(stripped_line)
            logger.debug(f"Loaded {len(processed_ids)} IDs from {PROCESSED_IDS_FILE}")
        else: logger.info(f"{PROCESSED_IDS_FILE} not found. Start fresh.")
    except Exception as e: logger.error(f"Error loading processed IDs: {e}")
    return processed_ids

def save_processed_id(article_id):
    """Append a new processed article ID to the file."""
    if not article_id: return
    try:
        os.makedirs(os.path.dirname(PROCESSED_IDS_FILE), exist_ok=True)
        with open(PROCESSED_IDS_FILE, 'a', encoding='utf-8') as f: f.write(article_id + '\n')
    except Exception as e: logger.error(f"Error saving ID {article_id}: {e}")

def save_article_data(article_id, data):
    """Save the scraped article data as a JSON file."""
    if not article_id or not data: return False
    try: os.makedirs(OUTPUT_DIR, exist_ok=True)
    except OSError as e: logger.error(f"Could not create output dir {OUTPUT_DIR}: {e}"); return False
    file_path = os.path.join(OUTPUT_DIR, f"{article_id}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"SAVED SCRAPED: {os.path.basename(file_path)} (T: {data.get('title', 'N/A')[:50]}...)")
        return True
    except Exception as e: logger.error(f"Error saving article {file_path}: {e}"); return False


def scrape_news(feed_urls, processed_ids):
    """Fetches news feeds, processes new entries, saves them."""
    logger.info(f"--- Starting News Scraper Run ({len(feed_urls)} feeds) ---")
    articles_saved_this_run = 0
    for feed_url in feed_urls:
        if articles_saved_this_run >= MAX_ARTICLES_PER_RUN: logger.warning(f"Hit max articles ({MAX_ARTICLES_PER_RUN}). Stop scrape."); break
        logger.info(f"Checking feed: {feed_url}")
        try:
            headers = {'User-Agent': 'DacoolaNewsBot/1.0 (+https://dacoolaa.netlify.app)'}
            feed_data = feedparser.parse(feed_url, agent=headers['User-Agent'], request_headers=headers)
            http_status = getattr(feed_data, 'status', None)

            # --- START CORRECTED ERROR HANDLING BLOCK ---
            if http_status and (http_status < 200 or http_status >= 400):
                logger.error(f"Failed to fetch feed {feed_url}. HTTP Status: {http_status}")
                continue
            if feed_data.bozo:
                bozo_reason = feed_data.get('bozo_exception', Exception("Unknown feedparser error"))
                bozo_message = str(bozo_reason).lower()
                # Check if the error message indicates a non-XML content type
                if ("content-type" in bozo_message and
                    ("xml" not in bozo_message and "rss" not in bozo_message and "atom" not in bozo_message)):
                    logger.error(f"Failed to fetch feed {feed_url}: Content type was not XML/RSS/Atom ({bozo_reason}). Skipping.")
                    continue
                # Check specifically for SSLError if needed
                elif "ssl error" in bozo_message:
                     logger.error(f"Failed to fetch feed {feed_url} due to SSL Error: {bozo_reason}. Skipping.")
                     continue
                else:
                    # Log other bozo reasons as warnings but proceed cautiously
                    logger.warning(f"Feed {feed_url} potentially malformed (bozo). Reason: {bozo_reason}. Attempting to process...")
            # --- END CORRECTED ERROR HANDLING BLOCK ---

            if not feed_data.entries: logger.info(f"No entries found in feed: {feed_url}"); continue
            logger.info(f"Feed {feed_url} fetched. Contains {len(feed_data.entries)} entries.")
            new_count_feed = 0
            for entry in feed_data.entries:
                if articles_saved_this_run >= MAX_ARTICLES_PER_RUN: logger.warning(f"Hit max ({MAX_ARTICLES_PER_RUN}) processing {feed_url}."); break

                article_id = get_article_id(entry, feed_url) # Get ID based on raw data if needed
                if article_id in processed_ids: continue

                # --- Decode Title ---
                title_raw = entry.get('title', '').strip()
                title = html.unescape(title_raw) # Decode HTML entities
                link = entry.get('link', '').strip()
                if not title or not link: logger.warning(f"Article skip no title/link {feed_url}."); continue

                published_parsed = entry.get('published_parsed'); published_iso = None
                if published_parsed:
                    try: dt_obj = datetime(*published_parsed[:6], tzinfo=timezone.utc); published_iso = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
                    except Exception as e: logger.warning(f"Date parse error {article_id}: {e}")

                # --- Decode Summary ---
                summary_raw = entry.content[0].get('value', '') if 'content' in entry and entry.content else entry.get('summary', entry.get('description', ''))
                summary = html.unescape(summary_raw.strip() if summary_raw else '') # Decode HTML entities

                if not summary: logger.warning(f"Article '{title}' ({article_id}) empty summary. Skip."); continue

                # Use the *decoded* title and summary for saving
                article_data = {'id': article_id, 'title': title, 'link': link, 'published_iso': published_iso, 'summary': summary, 'source_feed': feed_url, 'scraped_at_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

                if save_article_data(article_id, article_data):
                    processed_ids.add(article_id); save_processed_id(article_id)
                    new_count_feed += 1; articles_saved_this_run += 1
                else: logger.error(f"Failed save {title} ({article_id})")
            logger.info(f"Finished {feed_url}. Saved {new_count_feed}.")
        except Exception as e: logger.exception(f"Unexpected error processing {feed_url}: {e}"); continue
    logger.info(f"--- News Scraper Run Finished. Total new articles saved: {articles_saved_this_run} ---")
    return articles_saved_this_run

# --- Standalone Execution ---
if __name__ == "__main__":
    print("--- Running News Scraper Standalone ---")
    if not any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers):
         logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
         logger.setLevel(logging.INFO)
    try:
        current_processed_ids = load_processed_ids(); print(f"Loaded {len(current_processed_ids)} IDs.")
        num_saved = scrape_news(NEWS_FEED_URLS, current_processed_ids); print(f"Standalone run saved {num_saved}.")
    except Exception as standalone_e: logger.exception(f"Standalone scraper failed: {standalone_e}"); sys.exit(1)
    print("--- News Scraper Standalone Finished ---")
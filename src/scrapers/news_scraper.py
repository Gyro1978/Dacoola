# src/scrapers/news_scraper.py

import feedparser
# import time # <- Removed, not needed without the main loop
import os
import sys # <- Added sys for path check below
import json
import hashlib
import logging
from datetime import datetime # <- Simplified import

# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT) # Add project root for imports if needed

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# --- End Path Setup ---

# --- Configuration ---
# List of RSS Feed URLs (Keep this updated)
NEWS_FEED_URLS = [
    "https://techcrunch.com/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://www.anthropic.com/feed.xml",
    "https://openai.com/blog/rss.xml",
    "https://syncedreview.com/feed",
    "https://blogs.nvidia.com/feed/",
    "http://feeds.arstechnica.com/arstechnica/technology-lab"
    # --- Add new suggestions below ---
]
# File to store IDs of processed articles
PROCESSED_IDS_FILE = os.path.join(DATA_DIR, 'processed_article_ids.txt')
# Folder to save newly scraped articles as JSON files
OUTPUT_DIR = os.path.join(DATA_DIR, 'scraped_articles')
# Max *total* new articles to process across all feeds per run (controlled by main.py logic now, but good default)
MAX_ARTICLES_PER_RUN = 15
# --- End Configuration ---

# --- Setup Logging ---
# This setup is mainly for standalone testing. main.py's config will usually take precedence.
log_file_path_scraper = os.path.join(PROJECT_ROOT, 'dacoola.log')
# Ensure log directory exists if it's not the project root
try:
    os.makedirs(os.path.dirname(log_file_path_scraper), exist_ok=True)
    log_handlers_scraper = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path_scraper, encoding='utf-8')
    ]
except OSError as e:
    print(f"Scraper Log Error: Could not create log directory/file: {e}. Logging to console only.")
    log_handlers_scraper = [logging.StreamHandler(sys.stdout)]

# Configure a specific logger for this module if needed, or rely on root logger
logging.basicConfig(
    level=logging.INFO, # Use INFO or DEBUG as needed
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers_scraper,
    force=True # Allow reconfiguration by main.py if it runs first
)
logger = logging.getLogger(__name__) # Use module-specific logger
# --- End Setup Logging ---


def get_article_id(entry, feed_url): # <- Added feed_url parameter
    """Generate a unique ID for an article entry, using feed_url for uniqueness."""
    link = entry.get('link', '')
    guid = entry.get('id', entry.get('guid', link)) # Use link as fallback for guid

    # Determine the primary identifier string
    if not entry.get('guidislink', False) and link:
        identifier_base = link
    else:
        identifier_base = guid

    # If no link or guid, fall back to title + summary (less reliable)
    if not identifier_base:
        identifier_base = entry.get('title', '') + entry.get('summary', '')
        logger.warning(f"Using title+summary for ID base for entry in {feed_url}. Title: {entry.get('title', 'N/A')}")

    # Add the source feed URL to ensure uniqueness across different feeds
    # Use the passed feed_url argument directly
    identifier = f"{identifier_base}::{feed_url}" # Combine base ID with feed URL

    article_id = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    logger.debug(f"Generated ID {article_id} for article (Feed: {feed_url}): {entry.get('title', 'No Title')}")
    return article_id


def load_processed_ids():
    """Load the set of already processed article IDs from the file."""
    processed_ids = set()
    try:
        # Ensure the data directory exists
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(PROCESSED_IDS_FILE):
            with open(PROCESSED_IDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    processed_ids.add(line.strip())
            logger.debug(f"Loaded {len(processed_ids)} processed article IDs from {PROCESSED_IDS_FILE}")
        else:
            logger.debug(f"Processed IDs file not found at {PROCESSED_IDS_FILE}. Starting fresh.")
    except Exception as e:
        logger.error(f"Error loading processed IDs from {PROCESSED_IDS_FILE}: {e}")
    return processed_ids


def save_processed_id(article_id):
    """Append a new processed article ID to the file."""
    try:
        # Ensure the directory exists before trying to append
        os.makedirs(os.path.dirname(PROCESSED_IDS_FILE), exist_ok=True)
        with open(PROCESSED_IDS_FILE, 'a', encoding='utf-8') as f:
            f.write(article_id + '\n')
        logger.debug(f"Saved processed ID: {article_id}")
    except Exception as e:
        logger.error(f"Error saving processed ID {article_id} to {PROCESSED_IDS_FILE}: {e}")


def save_article_data(article_id, data):
    """Save the scraped article data as a JSON file in the designated output directory."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    except OSError as e:
        logger.error(f"Could not create or access output directory {OUTPUT_DIR}: {e}")
        return False # Cannot save if directory is inaccessible

    file_path = os.path.join(OUTPUT_DIR, f"{article_id}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        # Log saving action clearly
        logger.info(f"SAVED SCRAPED: {os.path.basename(file_path)} (Title: {data.get('title', 'N/A')})")
        return True
    except IOError as e:
        logger.error(f"Could not write article file {file_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving article {file_path}: {e}")
        return False


def scrape_news(feed_urls, processed_ids):
    """
    Fetches multiple news feeds, processes new entries, and saves them as JSON.
    This function is intended to be called once per run by an orchestrator.
    """
    logger.info(f"--- Starting News Scraper Run ({len(feed_urls)} feeds) ---")
    total_new_articles_saved_run = 0
    processed_article_count_this_run = 0 # Renamed for clarity

    for feed_url in feed_urls:
        # Check if max articles per run limit is reached
        if processed_article_count_this_run >= MAX_ARTICLES_PER_RUN:
            logger.warning(f"Reached max articles per run ({MAX_ARTICLES_PER_RUN}). Stopping feed processing for this run.")
            break

        logger.info(f"Checking feed: {feed_url}")
        try:
            # Use a consistent, identifiable User-Agent
            headers = {'User-Agent': 'DacoolaNewsBot/1.0 (+https://your-site-url.com)'} # Replace with your actual site URL
            feed_data = feedparser.parse(feed_url, agent=headers['User-Agent'])

            # Handle feedparser errors (bozo)
            if feed_data.bozo:
                bozo_reason = feed_data.get('bozo_exception', 'Unknown reason')
                # More specific check for critical fetch errors (like getting HTML instead of XML)
                if isinstance(bozo_reason, feedparser.exceptions.NotXMLContentType):
                     logger.error(f"Failed to fetch feed {feed_url}: Content type was not XML/RSS/Atom ({bozo_reason}). Skipping.")
                     continue
                elif hasattr(feed_data, 'status') and feed_data.status >= 400:
                     logger.error(f"Failed to fetch feed {feed_url}: HTTP Status {feed_data.status}. Skipping. Reason: {bozo_reason}")
                     continue
                else:
                    logger.warning(f"Feed {feed_url} potentially malformed (bozo). Reason: {bozo_reason}. Attempting to process...")

            # Check HTTP status if available
            if hasattr(feed_data, 'status') and feed_data.status not in [200, 304]: # 304 Not Modified is OK
                logger.error(f"Failed to fetch feed {feed_url}. HTTP Status: {feed_data.status}")
                continue

            if not feed_data.entries:
                logger.info(f"No entries found in feed: {feed_url}")
                continue

            logger.info(f"Feed {feed_url} fetched. Contains {len(feed_data.entries)} entries.")

            new_articles_this_feed = 0
            for entry in feed_data.entries:
                # Re-check limit within the inner loop
                if processed_article_count_this_run >= MAX_ARTICLES_PER_RUN:
                    logger.warning(f"Reached max articles per run ({MAX_ARTICLES_PER_RUN}) while processing feed {feed_url}.")
                    break

                # Generate ID using the entry and the specific feed_url
                article_id = get_article_id(entry, feed_url) # <- Pass feed_url

                if article_id in processed_ids:
                    logger.debug(f"Skipping already processed article ID: {article_id} (Title: {entry.get('title', 'N/A')})")
                    continue

                # --- Extract data ---
                title = entry.get('title', 'No Title Provided')
                link = entry.get('link', '')
                # Parse published date safely
                published_parsed = entry.get('published_parsed')
                published_iso = None
                if published_parsed:
                    try:
                        # Create datetime object and convert to UTC ISO format
                        dt_obj = datetime(*published_parsed[:6])
                        # Note: feedparser times are generally UTC, but this ensures it
                        published_iso = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
                    except Exception as e:
                        logger.warning(f"Error parsing date for article {article_id}: {e}. Date: {published_parsed}")

                # Get summary/content, prioritize 'content' if available
                content_list = entry.get('content', [])
                summary = content_list[0].get('value', '') if content_list else entry.get('summary', entry.get('description', ''))

                # Basic validation
                if not link:
                     logger.warning(f"Article '{title}' (ID: {article_id}) has no link. Skipping.")
                     continue
                if not summary or not summary.strip():
                    logger.warning(f"Article '{title}' (ID: {article_id}) has empty summary/content. Skipping.")
                    continue

                # Prepare data structure for saving
                article_data = {
                    'id': article_id,
                    'title': title.strip(), # Strip whitespace
                    'link': link,
                    'published_iso': published_iso,
                    'summary': summary.strip(), # Strip whitespace
                    'source_feed': feed_url,
                    'scraped_at_iso': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ') # Use UTC 'Z' format
                }

                # Save the article data
                if save_article_data(article_id, article_data):
                    processed_ids.add(article_id)
                    save_processed_id(article_id)
                    new_articles_this_feed += 1
                    processed_article_count_this_run += 1
                    total_new_articles_saved_run += 1
                    # logger.info(f"Successfully saved new article: {title}") # Covered by save_article_data log
                else:
                    logger.error(f"Failed to save article data for: {title} (ID: {article_id})")

            logger.info(f"Finished feed {feed_url}. Saved {new_articles_this_feed} new articles from this feed.")

        except Exception as e:
            logger.exception(f"Unexpected error processing feed {feed_url}: {e}")
            # Continue to the next feed even if one fails
            continue

    logger.info(f"--- News Scraper Run Finished. Total new articles saved this run: {total_new_articles_saved_run} ---")
    return total_new_articles_saved_run

# --- Standalone Execution (Optional for testing) ---
# This part is not used when called from main.py
if __name__ == "__main__":
    logger.info("--- Running News Scraper Standalone ---")
    try:
        current_processed_ids = load_processed_ids()
        scrape_news(NEWS_FEED_URLS, current_processed_ids)
    except Exception as standalone_e:
        logger.critical(f"Failed to run news scraper standalone: {standalone_e}")
        sys.exit(1)
    logger.info("--- News Scraper Standalone Finished ---")
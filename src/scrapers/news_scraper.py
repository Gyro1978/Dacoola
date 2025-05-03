# src/scrapers/news_scraper.py

import feedparser
import os
import sys
import json
import hashlib
import logging
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
    "https://techcrunch.com/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://www.anthropic.com/feed.xml",
    "https://openai.com/blog/rss.xml",
    "https://deepmind.google/blog/feed.xml/",
    "http://feeds.arstechnica.com/arstechnica/technology-lab"
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
    # Prefer 'id' field if it exists and seems unique enough
    guid = entry.get('id', '')
    link = entry.get('link', '')

    # Use GUID if available and not just the link itself
    if guid and guid != link:
        identifier_base = guid
    # Otherwise, use link if available
    elif link:
        identifier_base = link
    # Fallback to title + summary (less reliable)
    else:
        title = entry.get('title', '')
        summary = entry.get('summary', entry.get('description', ''))
        identifier_base = title + summary
        if not identifier_base: # If still empty, use timestamp as last resort
             identifier_base = str(datetime.now(timezone.utc).timestamp())
             logger.warning(f"Using timestamp for ID base for entry in {feed_url}. Title: {title}")
        else:
             logger.warning(f"Using title+summary for ID base for entry in {feed_url}. Title: {title}")


    # Combine base ID with feed URL for cross-feed uniqueness
    identifier = f"{identifier_base}::{feed_url}"

    # Use SHA-256 hash for consistent ID length
    article_id = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    # logger.debug(f"Generated ID {article_id} for article (Feed: {feed_url}): {entry.get('title', 'No Title')}")
    return article_id


def load_processed_ids():
    """Load the set of already processed article IDs from the file."""
    processed_ids = set()
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(PROCESSED_IDS_FILE):
            with open(PROCESSED_IDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    # Add only non-empty lines
                    stripped_line = line.strip()
                    if stripped_line:
                        processed_ids.add(stripped_line)
            logger.debug(f"Loaded {len(processed_ids)} processed article IDs from {PROCESSED_IDS_FILE}")
        else:
            logger.info(f"Processed IDs file not found at {PROCESSED_IDS_FILE}. Starting fresh.")
    except Exception as e:
        logger.error(f"Error loading processed IDs from {PROCESSED_IDS_FILE}: {e}")
    return processed_ids


def save_processed_id(article_id):
    """Append a new processed article ID to the file."""
    if not article_id: return # Don't save empty IDs
    try:
        os.makedirs(os.path.dirname(PROCESSED_IDS_FILE), exist_ok=True)
        with open(PROCESSED_IDS_FILE, 'a', encoding='utf-8') as f:
            f.write(article_id + '\n')
        # logger.debug(f"Saved processed ID: {article_id}")
    except Exception as e:
        logger.error(f"Error saving processed ID {article_id} to {PROCESSED_IDS_FILE}: {e}")


def save_article_data(article_id, data):
    """Save the scraped article data as a JSON file."""
    if not article_id or not data: return False
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    except OSError as e:
        logger.error(f"Could not create or access output directory {OUTPUT_DIR}: {e}")
        return False

    file_path = os.path.join(OUTPUT_DIR, f"{article_id}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"SAVED SCRAPED: {os.path.basename(file_path)} (Title: {data.get('title', 'N/A')[:50]}...)")
        return True
    except IOError as e:
        logger.error(f"Could not write article file {file_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving article {file_path}: {e}")
        return False


def scrape_news(feed_urls, processed_ids):
    """Fetches news feeds, processes new entries, saves them."""
    logger.info(f"--- Starting News Scraper Run ({len(feed_urls)} feeds) ---")
    total_new_articles_saved_run = 0
    # Use a different var name to avoid confusion with main.py's loop count
    articles_saved_this_scraper_run = 0

    for feed_url in feed_urls:
        if articles_saved_this_scraper_run >= MAX_ARTICLES_PER_RUN:
            logger.warning(f"Reached max articles per scraper run ({MAX_ARTICLES_PER_RUN}). Stopping feed processing.")
            break

        logger.info(f"Checking feed: {feed_url}")
        try:
            # Use a consistent, identifiable User-Agent
            headers = {'User-Agent': 'DacoolaNewsBot/1.0 (+https://dacoolaa.netlify.app)'} # Use your actual site URL
            feed_data = feedparser.parse(feed_url, agent=headers['User-Agent'], request_headers=headers)

            # Check HTTP status first if available
            http_status = getattr(feed_data, 'status', None)
            if http_status and (http_status < 200 or http_status >= 400):
                 logger.error(f"Failed to fetch feed {feed_url}. HTTP Status: {http_status}")
                 continue # Skip this feed on error

            # Handle feedparser bozo bit (indicates potential issues)
            if feed_data.bozo:
                bozo_reason = feed_data.get('bozo_exception', 'Unknown reason')
                # *** THIS IS THE CORRECTED CHECK ***
                # Check if the error message indicates a non-XML content type
                if "content-type" in str(bozo_reason).lower() and "xml" not in str(bozo_reason).lower():
                    logger.error(f"Failed to fetch feed {feed_url}: Content type was not XML/RSS/Atom ({bozo_reason}). Skipping.")
                    continue
                else:
                    # Log other bozo reasons as warnings but try processing anyway
                    logger.warning(f"Feed {feed_url} potentially malformed (bozo). Reason: {bozo_reason}. Attempting to process...")

            if not feed_data.entries:
                logger.info(f"No entries found in feed: {feed_url}")
                continue

            logger.info(f"Feed {feed_url} fetched. Contains {len(feed_data.entries)} entries.")

            new_articles_this_feed = 0
            for entry in feed_data.entries:
                # Re-check limit within the inner loop
                if articles_saved_this_scraper_run >= MAX_ARTICLES_PER_RUN:
                    logger.warning(f"Reached max articles per run ({MAX_ARTICLES_PER_RUN}) while processing feed {feed_url}.")
                    break

                article_id = get_article_id(entry, feed_url)

                if article_id in processed_ids:
                    # logger.debug(f"Skipping already processed article ID: {article_id}")
                    continue

                # --- Extract data ---
                title = entry.get('title', 'No Title Provided').strip()
                link = entry.get('link', '').strip()

                # Basic validation: Need title and link
                if not title or not link:
                     logger.warning(f"Article missing title or link in feed {feed_url}. Skipping. Link: '{link}', Title: '{title}'")
                     continue

                # Parse published date safely
                published_parsed = entry.get('published_parsed')
                published_iso = None
                if published_parsed:
                    try:
                        # Use feedparser's parsed time struct directly
                        dt_obj = datetime(*published_parsed[:6], tzinfo=timezone.utc) # Assume UTC from feed
                        published_iso = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ') # Standard UTC format
                    except Exception as e:
                        logger.warning(f"Error parsing date for article {article_id}: {e}. Date struct: {published_parsed}")

                # Get summary/content (prioritize content, fallback to summary/description)
                summary = ''
                if 'content' in entry and entry.content:
                    # content can be a list, take the first one's value
                    summary = entry.content[0].get('value', '')
                if not summary:
                     summary = entry.get('summary', entry.get('description', ''))

                # Clean and validate summary
                summary = summary.strip() if summary else ''
                if not summary:
                    logger.warning(f"Article '{title}' (ID: {article_id}) has empty summary/content. Skipping.")
                    continue

                # Prepare data structure for saving
                article_data = {
                    'id': article_id,
                    'title': title,
                    'link': link,
                    'published_iso': published_iso, # Store as ISO string
                    'summary': summary,
                    'source_feed': feed_url,
                    'scraped_at_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') # UTC timestamp
                }

                # Save the article data
                if save_article_data(article_id, article_data):
                    processed_ids.add(article_id) # Add to the set we're tracking *during this run*
                    save_processed_id(article_id) # Append to the persistent file
                    new_articles_this_feed += 1
                    articles_saved_this_scraper_run += 1 # Increment counter for this run
                    # Log is handled in save_article_data
                else:
                    logger.error(f"Failed to save article data for: {title} (ID: {article_id})")

            logger.info(f"Finished feed {feed_url}. Saved {new_articles_this_feed} new articles from this feed.")

        except Exception as e:
            logger.exception(f"Unexpected error processing feed {feed_url}: {e}")
            continue # Continue to the next feed

    logger.info(f"--- News Scraper Run Finished. Total new articles saved this run: {articles_saved_this_scraper_run} ---")
    return articles_saved_this_scraper_run # Return the count saved in this specific run


# --- Standalone Execution (for testing this script directly) ---
if __name__ == "__main__":
    print("--- Running News Scraper Standalone ---")
    # Ensure logger outputs to console for standalone test
    if not any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers):
         logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
         logging.getLogger().setLevel(logging.INFO)
         logger.setLevel(logging.INFO)

    try:
        current_processed_ids = load_processed_ids()
        print(f"Loaded {len(current_processed_ids)} previously processed IDs.")
        num_saved = scrape_news(NEWS_FEED_URLS, current_processed_ids)
        print(f"Standalone run saved {num_saved} new articles.")
    except Exception as standalone_e:
        logger.exception(f"Failed to run news scraper standalone: {standalone_e}")
        sys.exit(1)
    print("--- News Scraper Standalone Finished ---")
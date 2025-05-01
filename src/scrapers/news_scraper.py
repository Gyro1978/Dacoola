# src/scrapers/news_scraper.py

import feedparser
import time
import os
import json
import hashlib
import logging
from datetime import datetime

# --- Determine absolute paths based on script location ---
# Get the directory where this script (news_scraper.py) lives
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (which should be 'src')
SRC_DIR = os.path.dirname(SCRIPT_DIR)
# Get the root project directory (parent of 'src')
PROJECT_ROOT = os.path.dirname(SRC_DIR)
# Define data directory path relative to project root
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# --- End Path Calculation ---

# --- Configuration ---
# !!! --- List of RSS Feed URLs to scrape (Anthropic URL updated) --- !!!
NEWS_FEED_URLS = [
    "https://techcrunch.com/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "http://feeds.arstechnica.com/arstechnica/ai",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/tech/rss/index.xml",
    "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
    "https://news.ycombinator.com/rss",
    "https://www.anthropic.com/feed.xml",
    "https://ai.googleblog.com/feeds/posts/default?alt=rss",     
    "https://openai.com/blog/rss.xml",                           
    "https://deepmind.com/blog/feed/basic",                      
    "https://syncedreview.com/feed",                             
    "http://machinelearningmastery.com/blog/feed/",              
]

# How often to check all feeds (in seconds)
CHECK_INTERVAL_SECONDS = 900  # 15 minutes
# Folder to store IDs of processed articles (using absolute path)
PROCESSED_IDS_FILE = os.path.join(DATA_DIR, 'processed_article_ids.txt')
# Folder to save newly scraped articles as JSON files (using absolute path)
OUTPUT_DIR = os.path.join(DATA_DIR, 'scraped_articles')
# Max *total* new articles to process across all feeds per run
MAX_ARTICLES_PER_RUN = 30
# --- End Configuration ---

# --- Setup Logging ---
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detail
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT_ROOT, 'dacoola.log'))
    ]
)
# --- End Setup Logging ---


def get_article_id(entry):
    """Generate a unique ID for an article entry."""
    link = entry.get('link', '')
    guid = entry.get('id', entry.get('guid', link))
    if not entry.get('guidislink', False) and link:
        identifier = link
    else:
        identifier = guid
    if not identifier:
        identifier = entry.get('title', '') + entry.get('summary', '')
    # Add feed source to identifier hash to prevent collisions if different feeds list the exact same item/link
    source_url = entry.get('source', {}).get('href', entry.feedurl if hasattr(entry, 'feedurl') else '')  # Try to get source feed URL
    identifier += source_url  # Make ID unique per source
    article_id = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    logging.debug(f"Generated ID {article_id} for article: {entry.get('title', 'No Title')}")
    return article_id


def load_processed_ids():
    """Load the set of already processed article IDs from the file."""
    processed_ids = set()
    # Use the absolute path PROCESSED_IDS_FILE
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(PROCESSED_IDS_FILE):
            with open(PROCESSED_IDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    processed_ids.add(line.strip())
            logging.debug(f"Loaded {len(processed_ids)} processed article IDs from {PROCESSED_IDS_FILE}")
        else:
            logging.debug(f"Processed IDs file not found at {PROCESSED_IDS_FILE}. Starting fresh.")
    except Exception as e:
        logging.error(f"Error loading processed IDs from {PROCESSED_IDS_FILE}: {e}")
    return processed_ids


def save_processed_id(article_id):
    """Append a new processed article ID to the file."""
    try:
        # Use the absolute path PROCESSED_IDS_FILE
        # Ensure the directory exists before trying to append
        os.makedirs(os.path.dirname(PROCESSED_IDS_FILE), exist_ok=True)
        with open(PROCESSED_IDS_FILE, 'a', encoding='utf-8') as f:
            f.write(article_id + '\n')
        logging.debug(f"Saved processed ID: {article_id}")
    except Exception as e:
        logging.error(f"Error saving processed ID {article_id} to {PROCESSED_IDS_FILE}: {e}")


def save_article_data(article_id, data):
    """Save the scraped article data as a JSON file."""
    # Use the absolute path OUTPUT_DIR
    # Ensure the directory exists *before* creating the file path
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)  # exist_ok=True prevents error if dir already exists
    except OSError as e:
        logging.error(f"Could not create or access output directory {OUTPUT_DIR}: {e}")
        return False  # Can't save if directory is inaccessible

    # Now create the full file path
    file_path = os.path.join(OUTPUT_DIR, f"{article_id}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.debug(f"Saved article data to {file_path}")
        logging.info(f"Saved new article: {file_path} (Title: {data.get('title', 'N/A')})")
        return True
    except IOError as e:
        # This error might still occur if permissions are wrong, disk is full, etc.
        logging.error(f"Could not write article file {file_path}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error saving article {file_path}: {e}")
        return False


def scrape_news(feed_urls, processed_ids):
    """Fetches multiple news feeds, processes new entries, and saves them."""
    logging.info(f"Starting scrape run for {len(feed_urls)} feeds...")
    total_new_articles_found_run = 0
    processed_in_this_run = 0

    for feed_url in feed_urls:
        # Pass feed_url to get_article_id context if needed
        feedparser.mixin._FeedParserMixin.feedurl = feed_url  # Store feed url context for get_article_id

        if processed_in_this_run >= MAX_ARTICLES_PER_RUN:
            logging.warning(f"Reached max articles per run ({MAX_ARTICLES_PER_RUN}). Skipping remaining feeds.")
            break

        logging.info(f"Checking feed: {feed_url}")
        try:
            headers = {
                'User-Agent': 'DacoolaNewsBot/1.0 (Python Feedparser; +http://dacoola.com)',
                'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            feed = feedparser.parse(feed_url, agent=headers['User-Agent'])

            if feed.bozo:
                # Log bozo reason but try to process anyway, unless it's a known bad type like text/html from 404
                bozo_reason = feed.get('bozo_exception', 'Unknown reason')
                # Check if it's likely an HTML error page mistaken for feed
                if 'text/html' in str(bozo_reason) and hasattr(feed, 'status') and feed.status >= 400:
                    logging.error(f"Failed to fetch feed {feed_url}: Likely received HTML error page instead of XML. Status: {feed.get('status', 'N/A')}. Reason: {bozo_reason}")
                    continue  # Skip this feed
                else:
                    logging.warning(f"Feed {feed_url} potentially malformed. Reason: {bozo_reason}")

            if hasattr(feed, 'status') and feed.status not in [200, 304]:
                logging.error(f"Failed to fetch feed {feed_url}. HTTP Status: {feed.status}")
                continue

            if not feed.entries:
                logging.info(f"No entries found in feed: {feed_url}")
                continue

            logging.info(f"Feed {feed_url} fetched. Found {len(feed.entries)} entries.")

            new_articles_this_feed = 0
            for entry in feed.entries:
                if processed_in_this_run >= MAX_ARTICLES_PER_RUN:
                    logging.warning(f"Reached max articles per run ({MAX_ARTICLES_PER_RUN}) processing feed {feed_url}.")
                    break

                # Pass the feed URL context to ID generation
                article_id = get_article_id(entry)  # get_article_id now uses feedparser context

                if article_id in processed_ids:
                    logging.debug(f"Skipping already processed article: {entry.get('title', 'No Title')}")
                    continue

                logging.info(f"Found new article: {entry.get('title', 'No Title')} (ID: {article_id})")

                title = entry.get('title', 'No Title')
                link = entry.get('link', '')
                published_parsed = entry.get('published_parsed', None)
                published_iso = None
                if published_parsed:
                    try:
                        published_iso = datetime(*published_parsed[:6]).isoformat()
                    except Exception as e:
                        logging.error(f"Error parsing date for {article_id}: {e}")
                content_list = entry.get('content', [])
                summary = content_list[0].get('value', '') if content_list else entry.get('summary', entry.get('description', ''))

                if not summary or not summary.strip():
                    logging.warning(f"Article ID {article_id} from {feed_url} has empty summary/content. Skipping.")
                    continue

                article_data = {
                    'id': article_id,
                    'title': title,
                    'link': link,
                    'published_iso': published_iso,
                    'summary': summary,
                    'source_feed': feed_url,
                    'scraped_at_iso': datetime.utcnow().isoformat()
                }

                if save_article_data(article_id, article_data):
                    processed_ids.add(article_id)
                    save_processed_id(article_id)
                    new_articles_this_feed += 1
                    processed_in_this_run += 1
                    total_new_articles_found_run += 1
                    logging.info(f"Successfully saved new article: {title}")
                else:
                    logging.error(f"Failed to save article: {title}")

            logging.info(f"Finished feed {feed_url}. Saved {new_articles_this_feed} new articles.")

        except Exception as e:
            logging.exception(f"Failed to process feed {feed_url}: {e}")
            continue

    logging.info(f"Scrape run finished. Total new articles saved this run: {total_new_articles_found_run}.")
    return total_new_articles_found_run


def main():
    """Main function to run the news scraper."""
    logging.info("Starting multi-feed news scraper...")
    try:
        processed_ids = load_processed_ids()

        while True:
            try:
                new_articles = scrape_news(NEWS_FEED_URLS, processed_ids)
                logging.info(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds...")
                time.sleep(CHECK_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logging.info("News scraper stopped manually")
                break
            except Exception as e:
                logging.exception(f"Error in main scrape loop: {e}")
                logging.info(f"Sleeping for {CHECK_INTERVAL_SECONDS} seconds before retry...")
                time.sleep(CHECK_INTERVAL_SECONDS)

    except Exception as init_error:
        logging.critical(f"Failed to initialize news scraper: {init_error}")
        exit(1)


if __name__ == "__main__":
    main()
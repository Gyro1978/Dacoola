# src/scrapers/news_scraper.py

import feedparser
import os
import sys
import json
import hashlib
import logging
import html
import requests
from bs4 import BeautifulSoup, Comment # Import Comment for stripping
from datetime import datetime, timezone
try:
    import trafilatura
except ImportError:
    trafilatura = None
    logging.warning("trafilatura library not found. Full article fetching will rely on basic BeautifulSoup.")
    logging.warning("Install it with: pip install trafilatura")


# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# --- End Path Setup ---

# --- Configuration ---
NEWS_FEED_URLS = [
    "https://techcrunch.com/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://blogs.nvidia.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
    "https://www.microsoft.com/en-us/research/blog/category/artificial-intelligence/feed/",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
    "https://blog.google/technology/ai/rss/",
    "https://research.googleblog.com/feeds/posts/default?alt=rss",
]

PROCESSED_IDS_FILE = os.path.join(DATA_DIR, 'processed_article_ids.txt')
OUTPUT_DIR = os.path.join(DATA_DIR, 'scraped_articles')
MAX_ARTICLES_PER_RUN = 20
ARTICLE_FETCH_TIMEOUT = 20 # Increased timeout slightly for full page fetches
MIN_FULL_TEXT_LENGTH = 250 # Minimum characters to consider full text "successful"
# --- End Configuration ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def get_article_id(entry, feed_url):
    raw_title = entry.get('title', '')
    raw_summary = entry.get('summary', entry.get('description', ''))
    guid = entry.get('id', ''); link = entry.get('link', '')
    if guid and guid != link: identifier_base = guid
    elif link: identifier_base = link
    else:
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
    if not article_id: return
    try:
        os.makedirs(os.path.dirname(PROCESSED_IDS_FILE), exist_ok=True)
        with open(PROCESSED_IDS_FILE, 'a', encoding='utf-8') as f: f.write(article_id + '\n')
    except Exception as e: logger.error(f"Error saving ID {article_id}: {e}")

def save_article_data(article_id, data):
    if not article_id or not data: return False
    try: os.makedirs(OUTPUT_DIR, exist_ok=True)
    except OSError as e: logger.error(f"Could not create output dir {OUTPUT_DIR}: {e}"); return False
    file_path = os.path.join(OUTPUT_DIR, f"{article_id}.json")
    try:
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"SAVED SCRAPED: {os.path.basename(file_path)} (T: {data.get('title', 'N/A')[:50]}...)")
        return True
    except Exception as e: logger.error(f"Error saving article {file_path}: {e}"); return False

def fetch_full_article_text_with_trafilatura(article_url, downloaded_html):
    """Extracts main content using Trafilatura."""
    if not trafilatura:
        return None
    try:
        extracted_text = trafilatura.extract(downloaded_html,
                                             include_comments=False,
                                             include_tables=False, # Usually tables are not main prose
                                             output_format='txt', # Plain text output
                                             deduplicate=True)    # Remove duplicate text blocks
        if extracted_text and len(extracted_text) >= MIN_FULL_TEXT_LENGTH:
            logger.info(f"Successfully extracted text with Trafilatura from {article_url} (Length: {len(extracted_text)})")
            return extracted_text.strip()
        else:
            logger.debug(f"Trafilatura extracted insufficient text (Length: {len(extracted_text or '')}) from {article_url}. Will try fallback.")
            return None
    except Exception as e:
        logger.warning(f"Trafilatura extraction failed for {article_url}: {e}")
        return None

def fetch_full_article_text_bs_fallback(article_url, downloaded_html):
    """Fallback to BeautifulSoup for main content extraction if Trafilatura fails."""
    try:
        soup = BeautifulSoup(downloaded_html, 'html.parser')
        
        # Remove obviously non-content elements first
        tags_to_remove = ['script', 'style', 'nav', 'footer', 'aside', 'header', 'form', 'button', 'input',
                          '.related-posts', '.comments', '.sidebar', '.ad', '.banner', '.share-buttons',
                          '.newsletter-signup', '.cookie-banner', '.site-header', '.site-footer',
                          '.navigation', '.menu', '.social-links', '.author-bio', '.pagination',
                          '#comments', '#sidebar', '#header', '#footer', '#navigation', '.print-button',
                          '.breadcrumbs', 'figcaption', 'figure > div'] # Also remove divs inside figures if they are just containers
        for selector in tags_to_remove:
            for element in soup.select(selector): # Use select for CSS selectors
                element.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Try common main content selectors
        main_content_selectors = ['article[class*="content"]', 'article[class*="post"]', 'article[class*="article"]',
                                  'main[id*="content"]', 'main[class*="content"]', 'div[class*="article-body"]',
                                  'div[class*="post-body"]', 'div[class*="entry-content"]', 'div[class*="story-content"]',
                                  'div[id*="article"]', 'div#content', 'div#main', '.article-content']
        
        best_text = ""
        for selector in main_content_selectors:
            element = soup.select_one(selector)
            if element:
                # More refined text extraction from potential content blocks
                text_parts = []
                for child in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'pre']):
                    # Avoid extracting text from links within paragraphs too much unless they are the only content
                    if child.name == 'p' and child.find('a') and len(child.find_all(text=True, recursive=False)) == 0 and len(child.find_all('a')) == 1:
                        link_text = child.find('a').get_text(strip=True)
                        if link_text and len(link_text) > 20: # Heuristic for actual link text vs. short ones
                             text_parts.append(link_text)
                        continue # Skip paragraph if it's mostly just a link
                    text_parts.append(child.get_text(separator=' ', strip=True))
                
                current_text = "\n\n".join(filter(None, text_parts)).strip()
                if len(current_text) > len(best_text):
                    best_text = current_text
        
        if best_text and len(best_text) >= MIN_FULL_TEXT_LENGTH:
            logger.info(f"Successfully extracted text with BeautifulSoup (selector strategy) from {article_url} (Length: {len(best_text)})")
            return best_text
        
        # If still no good content, try a more aggressive body text extraction
        body = soup.find('body')
        if body:
            # (Decomposition of script/style already done above if selectors found body parts)
            # Let's refine get_text from body
            content_text = ""
            paragraphs = body.find_all('p') # Focus on paragraphs within the body
            if paragraphs:
                 text_parts = [p.get_text(separator=' ', strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50] # Heuristic for meaningful paragraphs
                 content_text = "\n\n".join(filter(None, text_parts)).strip()

            if content_text and len(content_text) >= MIN_FULL_TEXT_LENGTH:
                logger.info(f"Fetched meaningful paragraph text (aggressive fallback) from {article_url} (Length: {len(content_text)})")
                return content_text

        logger.warning(f"BeautifulSoup fallback could not extract substantial content from {article_url} after all attempts.")
        return None
    except Exception as e:
        logger.error(f"Error parsing full article with BeautifulSoup fallback from {article_url}: {e}")
        return None

def get_full_article_content(article_url):
    """Fetches HTML and tries multiple methods to extract main article text."""
    if not article_url or not article_url.startswith('http'):
        logger.debug(f"Invalid article_url for full content fetch: {article_url}")
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DacoolaNewsBot/1.0 (+https://dacoolaa.netlify.app)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/' # Common referer
        }
        response = requests.get(article_url, headers=headers, timeout=ARTICLE_FETCH_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"Content type for {article_url} is not HTML ({content_type}). Skipping full text extraction.")
            return None
            
        downloaded_html = response.text

        # Try Trafilatura first
        content_text = fetch_full_article_text_with_trafilatura(article_url, downloaded_html)

        # If Trafilatura fails or gets insufficient content, try BeautifulSoup fallback
        if not content_text:
            logger.info(f"Trafilatura insufficient for {article_url}, trying BeautifulSoup fallback.")
            content_text = fetch_full_article_text_bs_fallback(article_url, downloaded_html)
        
        return content_text

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch HTML for full article from {article_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_full_article_content for {article_url}: {e}")
        return None


def scrape_news(feed_urls, processed_ids):
    logger.info(f"--- Starting News Scraper Run ({len(feed_urls)} feeds) ---")
    articles_saved_this_run = 0
    for feed_url in feed_urls:
        if articles_saved_this_run >= MAX_ARTICLES_PER_RUN: logger.warning(f"Hit max articles ({MAX_ARTICLES_PER_RUN}). Stop scrape."); break
        logger.info(f"Checking feed: {feed_url}")
        try:
            feed_request_headers = {'User-Agent': 'DacoolaNewsBot/1.0 (+https://dacoolaa.netlify.app) FeedFetcher'}
            feed_data = feedparser.parse(feed_url, agent=feed_request_headers['User-Agent'], request_headers=feed_request_headers) # Use specific agent for feed fetching
            http_status = getattr(feed_data, 'status', None)

            if http_status and (http_status < 200 or http_status >= 400):
                logger.error(f"Failed to fetch feed {feed_url}. HTTP Status: {http_status}")
                continue
            if feed_data.bozo:
                bozo_reason = feed_data.get('bozo_exception', Exception("Unknown feedparser error"))
                bozo_message = str(bozo_reason).lower()
                if ("content-type" in bozo_message and
                    ("xml" not in bozo_message and "rss" not in bozo_message and "atom" not in bozo_message)):
                    logger.error(f"Failed to fetch feed {feed_url}: Content type was not XML/RSS/Atom ({bozo_reason}). Skipping.")
                    continue
                elif "ssl error" in bozo_message:
                     logger.error(f"Failed to fetch feed {feed_url} due to SSL Error: {bozo_reason}. Skipping.")
                     continue
                else:
                    logger.warning(f"Feed {feed_url} potentially malformed (bozo). Reason: {bozo_reason}. Attempting to process...")

            if not feed_data.entries: logger.info(f"No entries found in feed: {feed_url}"); continue
            logger.info(f"Feed {feed_url} fetched. Contains {len(feed_data.entries)} entries.")
            new_count_feed = 0
            for entry in feed_data.entries:
                if articles_saved_this_run >= MAX_ARTICLES_PER_RUN: logger.warning(f"Hit max ({MAX_ARTICLES_PER_RUN}) processing {feed_url}."); break

                article_id = get_article_id(entry, feed_url)
                if article_id in processed_ids: continue

                title_raw = entry.get('title', '').strip()
                title = html.unescape(title_raw)
                link = entry.get('link', '').strip()
                if not title or not link: logger.warning(f"Article skip no title/link {feed_url}."); continue

                published_parsed = entry.get('published_parsed'); published_iso = None
                if published_parsed:
                    try: dt_obj = datetime(*published_parsed[:6], tzinfo=timezone.utc); published_iso = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
                    except Exception as e: logger.warning(f"Date parse error {article_id}: {e}")

                summary_raw = entry.content[0].get('value', '') if 'content' in entry and entry.content else entry.get('summary', entry.get('description', ''))
                summary = html.unescape(summary_raw.strip() if summary_raw else '') # RSS summary

                full_article_text = get_full_article_content(link)

                if not full_article_text and not summary:
                    logger.warning(f"Article '{title}' ({article_id}) - Both RSS summary and full text scrape failed or empty. Skipping.")
                    continue
                
                final_content_for_agent = full_article_text if full_article_text and len(full_article_text) > len(summary) else summary # Prefer longer content

                article_data = {
                    'id': article_id, 'title': title, 'link': link,
                    'published_iso': published_iso,
                    'summary': summary, 
                    'full_text_content': full_article_text, 
                    'content_for_processing': final_content_for_agent, 
                    'source_feed': feed_url,
                    'scraped_at_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }

                if save_article_data(article_id, article_data):
                    processed_ids.add(article_id); save_processed_id(article_id)
                    new_count_feed += 1; articles_saved_this_run += 1
                else: logger.error(f"Failed save {title} ({article_id})")
            logger.info(f"Finished {feed_url}. Saved {new_count_feed} new articles.")
        except Exception as e: logger.exception(f"Unexpected error processing {feed_url}: {e}"); continue
    logger.info(f"--- News Scraper Run Finished. Total new articles saved: {articles_saved_this_run} ---")
    return articles_saved_this_run

# --- Standalone Execution ---
if __name__ == "__main__":
    print("--- Running News Scraper Standalone ---")
    if not any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers):
         logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
         logger.setLevel(logging.INFO)
    
    if trafilatura is None:
        print("WARNING: Trafilatura library not installed. Full article fetching will be limited.")

    # # Test fetching full article text on a known good URL
    # test_url = "https://techcrunch.com/2024/05/06/openai-reportedly-developing-search-product-to-compete-with-google/" # Example URL
    # print(f"\n--- Testing full article fetch for: {test_url} ---")
    # fetched_text = get_full_article_content(test_url)
    # if fetched_text:
    #     print(f"Fetched text (first 500 chars):\n{fetched_text[:500]}...")
    #     print(f"\nTotal length: {len(fetched_text)}")
    # else:
    #     print("Failed to fetch or parse full article text for test URL.")
    # print("--- End Full Article Test ---")

    try:
        current_processed_ids = load_processed_ids(); print(f"Loaded {len(current_processed_ids)} IDs.")
        num_saved = scrape_news(NEWS_FEED_URLS, current_processed_ids); print(f"Standalone run saved {num_saved} new articles.")
    except Exception as standalone_e: logger.exception(f"Standalone scraper failed: {standalone_e}"); sys.exit(1)
    print("--- News Scraper Standalone Finished ---")
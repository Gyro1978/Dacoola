# generate_sitemap.py
import sys
import os
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin
from dotenv import load_dotenv
from xml.sax.saxutils import escape # Ensure escape is imported

# --- Configuration ---
# Determine PROJECT_ROOT based on the location of generate_sitemap.py
# Assuming generate_sitemap.py is in the project root alongside .env and public/
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# If generate_sitemap.py is in a subdirectory like 'src', adjust PROJECT_ROOT:
# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) # If in src/

PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
SITEMAP_PATH = os.path.join(PUBLIC_DIR, 'sitemap.xml')

# Load environment variables to get the base URL
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Corrected Environment Variable Name ---
# Ensure BASE_URL ends with a slash
raw_base_url = os.getenv('YOUR_SITE_BASE_URL') # Now consistently using YOUR_SITE_BASE_URL
if not raw_base_url:
    # This error message will be printed if the script is run standalone and the var is missing
    # It will also be logged by the logger instance.
    error_msg_sitemap_base_url = "ERROR: YOUR_SITE_BASE_URL is not set in the environment variables or .env file. Cannot generate sitemap."
    print(error_msg_sitemap_base_url)
    try:
        # Attempt to log using a logger instance if available
        # Create a temporary logger for this specific error if main one isn't set up
        temp_sitemap_logger = logging.getLogger(__name__ + "_startup_error")
        if not temp_sitemap_logger.hasHandlers():
             temp_sitemap_logger.addHandler(logging.StreamHandler(sys.stdout)) # Fallback handler
        temp_sitemap_logger.error(error_msg_sitemap_base_url)
    except NameError: # sys might not be imported if this fails very early
        pass
    except Exception: # Catch any other logging issue
        pass
    sys.exit(1) # Exit if base URL is critical and not found

BASE_URL = raw_base_url.rstrip('/') + '/'
# --- End Corrected Environment Variable Name ---

# --- Logging Setup ---
# Configure logging (will be overridden if main.py runs first, but good for standalone)
# Ensure this is after dotenv load, so if a LOG_LEVEL is in .env, it could be used.
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO').upper(),
                    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
logger = logging.getLogger(__name__)

def get_sort_key_sitemap(article_dict_item): # Renamed to avoid conflict if imported elsewhere
    """Helper function to get a datetime object for sorting articles, specific to sitemap context."""
    fallback_past_date = datetime(1970, 1, 1, tzinfo=timezone.utc)
    date_iso_str = article_dict_item.get('published_iso')
    if not date_iso_str or not isinstance(date_iso_str, str):
        return fallback_past_date
    try:
        # Handle potential 'Z' timezone indicator if not already handled by fromisoformat
        if date_iso_str.endswith('Z'):
            date_iso_str = date_iso_str[:-1] + '+00:00'
        dt_obj = datetime.fromisoformat(date_iso_str)
        # Ensure datetime is timezone-aware (UTC)
        return dt_obj.replace(tzinfo=timezone.utc) if dt_obj.tzinfo is None else dt_obj
    except ValueError:
        logger.warning(f"Sitemap: Could not parse date '{date_iso_str}' for sorting article ID {article_dict_item.get('id', 'N/A')}. Using fallback date.")
        return fallback_past_date

def format_datetime_for_sitemap(iso_date_string):
    """Attempts to parse ISO date and format as YYYY-MM-DD."""
    if not iso_date_string:
        return None
    try:
        if iso_date_string.endswith('Z'):
            iso_date_string = iso_date_string[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_date_string)
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        logger.warning(f"Sitemap: Could not parse date '{iso_date_string}' for sitemap lastmod. Skipping.")
        return None
    except Exception as e:
        logger.error(f"Sitemap: Unexpected error parsing date '{iso_date_string}': {e}")
        return None

def generate_sitemap():
    """Generates the sitemap.xml file."""
    logger.info("Starting sitemap generation...")

    if not BASE_URL or BASE_URL == "/": # Double check after initial load
        logger.error("Sitemap generation aborted: YOUR_SITE_BASE_URL (derived as BASE_URL) is invalid or missing.")
        return

    try:
        if not os.path.exists(ALL_ARTICLES_FILE):
            logger.error(f"{ALL_ARTICLES_FILE} not found. Cannot generate sitemap.")
            return
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Expecting data to be {"articles": [...]}
        articles = data.get("articles", [])
        if not isinstance(articles, list):
            logger.error(f"Invalid format in {ALL_ARTICLES_FILE}: 'articles' key not found or not a list.")
            articles = [] # Treat as no articles

        if not articles:
            logger.warning("No articles found in all_articles.json. Sitemap will only contain homepage.")
    except Exception as e:
        logger.error(f"Failed to load or parse {ALL_ARTICLES_FILE}: {e}")
        return

    logger.info(f"Loaded {len(articles)} articles for sitemap generation.")

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    # Add Homepage URL
    xml_content += '  <url>\n'
    xml_content += f'    <loc>{escape(BASE_URL)}</loc>\n'
    
    homepage_lastmod = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if articles:
        try:
            # Sort articles by date to find the actual latest one for homepage lastmod
            # Using the sitemap-specific sort key function
            sorted_articles_for_lastmod = sorted(articles, key=get_sort_key_sitemap, reverse=True)
            if sorted_articles_for_lastmod:
                last_article_date_iso = sorted_articles_for_lastmod[0].get('published_iso')
                last_article_sitemap_date = format_datetime_for_sitemap(last_article_date_iso)
                if last_article_sitemap_date:
                    homepage_lastmod = last_article_sitemap_date
        except Exception as sort_err:
             logger.warning(f"Could not determine latest article date for homepage lastmod: {sort_err}. Using current date.")

    xml_content += f'    <lastmod>{homepage_lastmod}</lastmod>\n'
    xml_content += '    <changefreq>daily</changefreq>\n'
    xml_content += '    <priority>1.0</priority>\n'
    xml_content += '  </url>\n'

    processed_urls_count = 0
    for article in articles:
        if not isinstance(article, dict):
            logger.warning("Skipping non-dictionary item in articles list during sitemap generation.")
            continue

        relative_link = article.get('link')
        publish_date_iso = article.get('published_iso')

        if not relative_link:
            logger.warning(f"Skipping article with missing link (ID: {article.get('id', 'N/A')}) for sitemap.")
            continue

        absolute_url = urljoin(BASE_URL, relative_link.lstrip('/'))
        xml_content += '  <url>\n'
        xml_content += f'    <loc>{escape(absolute_url)}</loc>\n'
        lastmod_date = format_datetime_for_sitemap(publish_date_iso)
        if lastmod_date:
            xml_content += f'    <lastmod>{lastmod_date}</lastmod>\n'
        xml_content += '    <changefreq>weekly</changefreq>\n'
        xml_content += '    <priority>0.8</priority>\n'
        xml_content += '  </url>\n'
        processed_urls_count += 1

    xml_content += '</urlset>'

    try:
        os.makedirs(PUBLIC_DIR, exist_ok=True)
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        logger.info(f"Sitemap successfully generated with {processed_urls_count + 1} URLs and saved to {SITEMAP_PATH}") # +1 for homepage
    except Exception as e:
        logger.error(f"Failed to write sitemap file to {SITEMAP_PATH}: {e}")

if __name__ == "__main__":
    # This allows the script to be run standalone for testing sitemap generation.
    # It assumes `all_articles.json` is already populated correctly by `main.py`.
    logger.info("Running sitemap_generator.py as a standalone script.")
    generate_sitemap()
    logger.info("Standalone sitemap generation finished.")
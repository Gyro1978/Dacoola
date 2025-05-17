# generate_sitemap.py (Updated to include digests)

import os
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin
from dotenv import load_dotenv
from xml.sax.saxutils import escape # For escaping URLs

# --- Configuration ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) # Assumes sitemap.py is in project root
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
SITEMAP_PATH = os.path.join(PUBLIC_DIR, 'sitemap.xml')
DIGESTS_DIR = os.path.join(PUBLIC_DIR, 'digests') # Path to where digest HTML files will be stored

# Load environment variables to get the base URL
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

raw_base_url = os.getenv('YOUR_SITE_BASE_URL')
if not raw_base_url:
    # Try to log using default Python logging if script's own logger isn't set up yet
    print("ERROR: YOUR_SITE_BASE_URL is not set in the .env file. Cannot generate sitemap.")
    try:
        logging.getLogger(__name__).error("YOUR_SITE_BASE_URL is not set. Sitemap generation failed.")
    except Exception: # Fallback if logging itself fails during this early phase
        pass
    exit(1) # Critical error, cannot proceed
BASE_URL = raw_base_url.rstrip('/') + '/' # Ensure it ends with a slash

# --- Logging Setup ---
# Configure logging (will be overridden if main.py runs first, but good for standalone)
logger = logging.getLogger(__name__) # Use a logger specific to this module
if not logger.handlers: # Avoid adding handlers if already configured by main.py
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def format_datetime_for_sitemap(iso_date_string_or_datetime_obj):
    """Attempts to parse ISO date string or use datetime obj, format as YYYY-MM-DD."""
    if not iso_date_string_or_datetime_obj:
        return None
    
    dt_obj = None
    if isinstance(iso_date_string_or_datetime_obj, datetime):
        dt_obj = iso_date_string_or_datetime_obj
    elif isinstance(iso_date_string_or_datetime_obj, str):
        try:
            if iso_date_string_or_datetime_obj.endswith('Z'):
                iso_date_string_or_datetime_obj = iso_date_string_or_datetime_obj[:-1] + '+00:00'
            dt_obj = datetime.fromisoformat(iso_date_string_or_datetime_obj)
        except ValueError:
            logger.warning(f"Could not parse date string '{iso_date_string_or_datetime_obj}' for sitemap. Skipping lastmod.")
            return None
    else:
        logger.warning(f"Invalid date type for sitemap: {type(iso_date_string_or_datetime_obj)}. Skipping lastmod.")
        return None

    if dt_obj:
        # Ensure timezone-aware for consistent output if needed, though strftime('%Y-%m-%d') is fine.
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc) # Assume UTC if naive
        return dt_obj.strftime('%Y-%m-%d')
    return None

def generate_sitemap():
    """Generates the sitemap.xml file, including articles and digest pages."""
    logger.info("Starting sitemap generation (including digests)...")

    # --- Load Article Data (for articles section) ---
    articles_for_sitemap = []
    try:
        if not os.path.exists(ALL_ARTICLES_FILE):
            logger.error(f"{ALL_ARTICLES_FILE} not found. Article URLs will be missing from sitemap.")
        else:
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            articles_for_sitemap = data.get("articles", [])
            if not articles_for_sitemap:
                logger.warning("No articles found in all_articles.json. Article URLs will be missing.")
    except Exception as e:
        logger.error(f"Failed to load or parse {ALL_ARTICLES_FILE}: {e}")

    logger.info(f"Loaded {len(articles_for_sitemap)} articles for sitemap generation.")

    # --- Start building the XML string ---
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    # --- Add Homepage URL ---
    xml_content += '  <url>\n'
    xml_content += f'    <loc>{escape(BASE_URL)}</loc>\n'
    
    homepage_lastmod_dt = datetime.now(timezone.utc) # Default to now
    if articles_for_sitemap:
        # Find the most recent article publish date for homepage lastmod
        latest_article_date_obj = None
        for art in articles_for_sitemap:
            pub_iso = art.get('published_iso')
            if pub_iso:
                try:
                    current_art_dt = datetime.fromisoformat(pub_iso.replace('Z', '+00:00'))
                    if latest_article_date_obj is None or current_art_dt > latest_article_date_obj:
                        latest_article_date_obj = current_art_dt
                except ValueError:
                    continue # Skip if date is unparseable
        if latest_article_date_obj:
            homepage_lastmod_dt = latest_article_date_obj
            
    xml_content += f'    <lastmod>{homepage_lastmod_dt.strftime("%Y-%m-%d")}</lastmod>\n'
    xml_content += '    <changefreq>daily</changefreq>\n'
    xml_content += '    <priority>1.0</priority>\n'
    xml_content += '  </url>\n'

    # --- Add Article URLs ---
    processed_article_urls_count = 0
    for article in articles_for_sitemap:
        if not isinstance(article, dict):
            logger.warning("Skipping non-dictionary item in articles list during sitemap generation.")
            continue

        relative_link = article.get('link') # Should be like "articles/my-slug.html"
        publish_date_iso = article.get('published_iso')

        if not relative_link:
            logger.warning(f"Skipping article with missing link (ID: {article.get('id', 'N/A')}) for sitemap.")
            continue
        
        # Ensure link starts with "articles/" if not already, for consistency with urljoin
        if not relative_link.startswith('articles/'):
            logger.debug(f"Article link '{relative_link}' for ID {article.get('id','N/A')} does not start with 'articles/'. Prepending.")
            # This assumes links in all_articles.json might sometimes miss this prefix.
            # However, they *should* have it from the main processing logic.
            # For safety, we'll use it as is, assuming urljoin handles it.

        absolute_url = urljoin(BASE_URL, relative_link.lstrip('/'))

        xml_content += '  <url>\n'
        xml_content += f'    <loc>{escape(absolute_url)}</loc>\n'
        
        lastmod_date_str = format_datetime_for_sitemap(publish_date_iso)
        if lastmod_date_str:
            xml_content += f'    <lastmod>{lastmod_date_str}</lastmod>\n'
        
        xml_content += '    <changefreq>weekly</changefreq>\n' 
        xml_content += '    <priority>0.8</priority>\n'       
        xml_content += '  </url>\n'
        processed_article_urls_count += 1

    # --- Add Digest Page URLs ---
    processed_digest_urls_count = 0
    if os.path.exists(DIGESTS_DIR) and os.path.isdir(DIGESTS_DIR):
        logger.info(f"Scanning for digest pages in: {DIGESTS_DIR}")
        for filename in os.listdir(DIGESTS_DIR):
            if filename.endswith(".html"):
                digest_slug = filename
                relative_digest_path = f"digests/{digest_slug}" # e.g., digests/ai-healthcare-digest-20240101.html
                absolute_digest_url = urljoin(BASE_URL, relative_digest_path)
                
                xml_content += '  <url>\n'
                xml_content += f'    <loc>{escape(absolute_digest_url)}</loc>\n'
                
                # Use file modification time for digest lastmod
                try:
                    file_path = os.path.join(DIGESTS_DIR, filename)
                    mod_timestamp = os.path.getmtime(file_path)
                    lastmod_dt_obj = datetime.fromtimestamp(mod_timestamp, tz=timezone.utc)
                    lastmod_date_str_digest = format_datetime_for_sitemap(lastmod_dt_obj)
                    if lastmod_date_str_digest:
                        xml_content += f'    <lastmod>{lastmod_date_str_digest}</lastmod>\n'
                except Exception as e:
                    logger.warning(f"Could not get modification time for digest {filename}: {e}")
                
                xml_content += '    <changefreq>daily</changefreq>\n' # Digests might update daily
                xml_content += '    <priority>0.7</priority>\n'      # Slightly lower than articles, adjust as needed
                xml_content += '  </url>\n'
                processed_digest_urls_count += 1
        logger.info(f"Added {processed_digest_urls_count} digest pages to sitemap.")
    else:
        logger.info(f"Digest directory not found or not a directory: {DIGESTS_DIR}. No digest pages added.")

    # --- Close the urlset tag ---
    xml_content += '</urlset>'

    # --- Write the sitemap file ---
    try:
        os.makedirs(PUBLIC_DIR, exist_ok=True) 
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        total_urls = 1 + processed_article_urls_count + processed_digest_urls_count # 1 for homepage
        logger.info(f"Sitemap successfully generated with {total_urls} URLs and saved to {SITEMAP_PATH}")
    except Exception as e:
        logger.error(f"Failed to write sitemap file to {SITEMAP_PATH}: {e}")

if __name__ == "__main__":
    # This allows running the sitemap generator standalone for testing.
    # Ensure .env is in the project root for BASE_URL.
    # For standalone test, it's good if all_articles.json and some digest files exist.
    
    # Create dummy digest files for testing if they don't exist
    if not os.path.exists(DIGESTS_DIR):
        os.makedirs(DIGESTS_DIR, exist_ok=True)
    if not os.listdir(DIGESTS_DIR): # If directory is empty
        logger.info("Creating dummy digest files for standalone sitemap test...")
        with open(os.path.join(DIGESTS_DIR, "dummy-digest-1.html"), "w") as f: f.write("<h1>Dummy Digest 1</h1>")
        with open(os.path.join(DIGESTS_DIR, "another-sample-digest.html"), "w") as f: f.write("<h1>Dummy Digest 2</h1>")

    generate_sitemap()
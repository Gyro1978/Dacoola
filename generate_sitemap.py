# generate_sitemap.py

import os
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from dotenv import load_dotenv 
from xml.sax.saxutils import escape

# --- Configuration ---
# Determine PROJECT_ROOT assuming this script is in the project root or one level down (e.g., in a 'scripts' or 'src' folder)
# Adjust if your structure is different.
# If this script is in the project root:
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# If this script is in a subdirectory like 'src/' or 'scripts/':
# PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
SITEMAP_PATH = os.path.join(PUBLIC_DIR, 'sitemap.xml')
DIGESTS_DIR = os.path.join(PUBLIC_DIR, 'digests')

# --- Logging Setup ---
logger = logging.getLogger(__name__)
if not logger.handlers: # Setup basic logging if no handlers are configured
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] # Changed to sys.stdout from just StreamHandler()
    )
    # If you want to also log to a file from here (optional):
    # file_handler = logging.FileHandler(os.path.join(PROJECT_ROOT, 'sitemap_generator.log'), encoding='utf-8')
    # file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s'))
    # logger.addHandler(file_handler)


def format_datetime_for_sitemap(iso_date_string_or_datetime_obj):
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
        # Ensure datetime object is timezone-aware and set to UTC if naive
        if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc) 
        return dt_obj.strftime('%Y-%m-%d') # Format as YYYY-MM-DD
    return None

def generate_sitemap():
    """Generates the sitemap.xml file, including articles and digest pages."""
    
    # --- Load .env specifically for this function call ---
    # This ensures YOUR_SITE_BASE_URL is loaded even if this script is run standalone
    # or if the main script's .env loading doesn't persist to this module's scope.
    dotenv_path_sitemap = os.path.join(PROJECT_ROOT, '.env')
    load_success = load_dotenv(dotenv_path=dotenv_path_sitemap)
    if load_success:
        logger.info(f"Sitemap: Successfully loaded .env from {dotenv_path_sitemap}")
    else:
        logger.warning(f"Sitemap: .env file not found at {dotenv_path_sitemap}. Relying on environment variables if set globally.")

    raw_base_url_sitemap = os.getenv('YOUR_SITE_BASE_URL')
    if not raw_base_url_sitemap:
        logger.error("CRITICAL (Sitemap): YOUR_SITE_BASE_URL is not set in .env or environment. Cannot generate sitemap.")
        return # Exit function if base URL is missing
    
    # Ensure BASE_URL_SITEMAP ends with a slash
    BASE_URL_SITEMAP = raw_base_url_sitemap.rstrip('/') + '/'
    logger.info(f"Sitemap: Using base URL: {BASE_URL_SITEMAP}")
    # --- End of .env loading and BASE_URL_SITEMAP definition ---

    logger.info("Starting sitemap generation (including digests)...")

    articles_for_sitemap = []
    try:
        if not os.path.exists(ALL_ARTICLES_FILE):
            logger.error(f"Sitemap: {ALL_ARTICLES_FILE} not found. Article URLs will be missing from sitemap.")
        else:
            with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Check if 'data' is a dict and contains 'articles' list
            if isinstance(data, dict) and 'articles' in data and isinstance(data['articles'], list):
                articles_for_sitemap = data["articles"]
                if not articles_for_sitemap:
                    logger.warning("Sitemap: No articles found in all_articles.json. Article URLs will be missing.")
            else:
                logger.error(f"Sitemap: Invalid format in {ALL_ARTICLES_FILE}. Expected a JSON object with an 'articles' list.")
                articles_for_sitemap = [] # Ensure it's a list even on error
    except Exception as e:
        logger.error(f"Sitemap: Failed to load or parse {ALL_ARTICLES_FILE}: {e}", exc_info=True)
        articles_for_sitemap = [] # Ensure it's a list even on error

    logger.info(f"Sitemap: Loaded {len(articles_for_sitemap)} articles for sitemap generation.")

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    # Homepage URL
    xml_content += '  <url>\n'
    xml_content += f'    <loc>{escape(BASE_URL_SITEMAP)}</loc>\n' # Use function-local BASE_URL_SITEMAP
    
    homepage_lastmod_dt = datetime.now(timezone.utc) # Default to now
    if articles_for_sitemap:
        latest_article_date_obj = None
        for art in articles_for_sitemap:
            if not isinstance(art, dict): continue # Skip if not a dict
            pub_iso = art.get('published_iso')
            if pub_iso:
                try:
                    # Ensure proper ISO format handling
                    current_art_dt_str = pub_iso.replace('Z', '+00:00') if isinstance(pub_iso, str) else str(pub_iso)
                    current_art_dt = datetime.fromisoformat(current_art_dt_str)
                    if current_art_dt.tzinfo is None:
                        current_art_dt = current_art_dt.replace(tzinfo=timezone.utc)
                    
                    if latest_article_date_obj is None or current_art_dt > latest_article_date_obj:
                        latest_article_date_obj = current_art_dt
                except ValueError as ve:
                    logger.warning(f"Sitemap: Could not parse date for homepage lastmod from article '{art.get('id', 'N/A')}': {pub_iso} - {ve}")
                    continue 
        if latest_article_date_obj:
            homepage_lastmod_dt = latest_article_date_obj
            
    xml_content += f'    <lastmod>{homepage_lastmod_dt.strftime("%Y-%m-%d")}</lastmod>\n'
    xml_content += '    <changefreq>daily</changefreq>\n'
    xml_content += '    <priority>1.0</priority>\n'
    xml_content += '  </url>\n'

    # Article URLs
    processed_article_urls_count = 0
    for article in articles_for_sitemap:
        if not isinstance(article, dict):
            logger.warning("Sitemap: Skipping non-dictionary item in articles list.")
            continue
            
        relative_link = article.get('link') 
        publish_date_iso = article.get('published_iso') # This should be a string from JSON
        
        if not relative_link:
            logger.warning(f"Sitemap: Skipping article with missing link (ID: {article.get('id', 'N/A')}) for sitemap.")
            continue
            
        # Ensure the link starts with 'articles/' and doesn't have leading slashes from the JSON
        # but urljoin needs the base to end with / and the relative part not to start with /
        # or it will replace the base path.
        clean_relative_link = relative_link.lstrip('/')
        if not clean_relative_link.startswith('articles/'):
             logger.warning(f"Sitemap: Article link '{relative_link}' (ID: {article.get('id', 'N/A')}) does not start with 'articles/'. Skipping.")
             continue

        absolute_url = urljoin(BASE_URL_SITEMAP, clean_relative_link)
        
        xml_content += '  <url>\n'
        xml_content += f'    <loc>{escape(absolute_url)}</loc>\n'
        
        lastmod_date_str = format_datetime_for_sitemap(publish_date_iso)
        if lastmod_date_str:
            xml_content += f'    <lastmod>{lastmod_date_str}</lastmod>\n'
        
        xml_content += '    <changefreq>weekly</changefreq>\n' # Or daily if content changes often
        xml_content += '    <priority>0.8</priority>\n'       # Adjust priority as needed
        xml_content += '  </url>\n'
        processed_article_urls_count += 1

    # Digest Page URLs
    processed_digest_urls_count = 0
    if os.path.exists(DIGESTS_DIR) and os.path.isdir(DIGESTS_DIR):
        logger.info(f"Sitemap: Scanning for digest pages in: {DIGESTS_DIR}")
        for filename in os.listdir(DIGESTS_DIR):
            if filename.endswith(".html"):
                digest_slug = filename # e.g., "my-digest-slug.html"
                relative_digest_path = f"digests/{digest_slug}" 
                absolute_digest_url = urljoin(BASE_URL_SITEMAP, relative_digest_path.lstrip('/'))
                
                xml_content += '  <url>\n'
                xml_content += f'    <loc>{escape(absolute_digest_url)}</loc>\n'
                
                try:
                    file_path = os.path.join(DIGESTS_DIR, filename)
                    mod_timestamp = os.path.getmtime(file_path)
                    lastmod_dt_obj = datetime.fromtimestamp(mod_timestamp, tz=timezone.utc)
                    lastmod_date_str_digest = format_datetime_for_sitemap(lastmod_dt_obj)
                    if lastmod_date_str_digest:
                        xml_content += f'    <lastmod>{lastmod_date_str_digest}</lastmod>\n'
                except Exception as e:
                    logger.warning(f"Sitemap: Could not get modification time for digest {filename}: {e}")
                
                xml_content += '    <changefreq>daily</changefreq>\n' 
                xml_content += '    <priority>0.7</priority>\n'      
                xml_content += '  </url>\n'
                processed_digest_urls_count += 1
        logger.info(f"Sitemap: Added {processed_digest_urls_count} digest pages to sitemap.")
    else:
        logger.info(f"Sitemap: Digest directory not found or not a directory: {DIGESTS_DIR}. No digest pages added.")

    xml_content += '</urlset>'

    try:
        os.makedirs(PUBLIC_DIR, exist_ok=True) # Ensure public directory exists
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        total_urls = 1 + processed_article_urls_count + processed_digest_urls_count # 1 for homepage
        logger.info(f"Sitemap: Sitemap successfully generated with {total_urls} URLs and saved to {SITEMAP_PATH}")
    except Exception as e:
        logger.error(f"Sitemap: Failed to write sitemap file to {SITEMAP_PATH}: {e}", exc_info=True)

if __name__ == "__main__":
    import sys # Make sure sys is imported if not already
    # Ensure project root is in sys.path for standalone execution for imports like .env
    # This part is already at the top of the script, but good to double-check if running standalone issues.
    
    logger.info("--- Running generate_sitemap.py standalone for testing ---")
    
    # Create dummy .env if it doesn't exist for testing
    if not os.path.exists(os.path.join(PROJECT_ROOT, '.env')):
        with open(os.path.join(PROJECT_ROOT, '.env'), 'w') as f:
            f.write("YOUR_SITE_BASE_URL=https://standalone-test.example.com/\n")
            f.write("YOUR_WEBSITE_NAME=Standalone Test Site\n")
        logger.info("Sitemap Standalone: Created dummy .env for testing.")

    # Create dummy all_articles.json if it doesn't exist
    if not os.path.exists(ALL_ARTICLES_FILE):
        os.makedirs(PUBLIC_DIR, exist_ok=True)
        dummy_articles = {
            "articles": [
                {
                    "id": "dummy001", "title": "Dummy Article 1", 
                    "link": "articles/dummy-article-1.html", 
                    "published_iso": datetime.now(timezone.utc).isoformat(),
                    "summary_short": "This is a dummy article."
                },
                {
                    "id": "dummy002", "title": "Dummy Article 2", 
                    "link": "articles/another-dummy.html", 
                    "published_iso": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                    "summary_short": "Another dummy test article for sitemap."
                }
            ]
        }
        with open(ALL_ARTICLES_FILE, 'w') as f:
            json.dump(dummy_articles, f, indent=2)
        logger.info(f"Sitemap Standalone: Created dummy {os.path.basename(ALL_ARTICLES_FILE)} for testing.")
        
    # Ensure digests directory exists and create dummy digest files if empty
    if not os.path.exists(DIGESTS_DIR):
        os.makedirs(DIGESTS_DIR, exist_ok=True)
    if not os.listdir(DIGESTS_DIR): 
        logger.info("Sitemap Standalone: Creating dummy digest files for sitemap test...")
        with open(os.path.join(DIGESTS_DIR, "dummy-digest-1.html"), "w") as f: f.write("<h1>Dummy Digest 1</h1>")
        with open(os.path.join(DIGESTS_DIR, "another-sample-digest.html"), "w") as f: f.write("<h1>Dummy Digest 2</h1>")

    generate_sitemap()
    logger.info("--- Standalone sitemap generation test finished. Check sitemap.xml. ---")
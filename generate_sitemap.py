# generate_sitemap.py (Corrected for .env loading)

import os
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin
from dotenv import load_dotenv # Keep import at top
from xml.sax.saxutils import escape

# --- Configuration ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
SITEMAP_PATH = os.path.join(PUBLIC_DIR, 'sitemap.xml')
DIGESTS_DIR = os.path.join(PUBLIC_DIR, 'digests')

# --- Logging Setup ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def format_datetime_for_sitemap(iso_date_string_or_datetime_obj):
    # ... (this function remains the same)
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
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc) 
        return dt_obj.strftime('%Y-%m-%d')
    return None

def generate_sitemap():
    """Generates the sitemap.xml file, including articles and digest pages."""
    
    # <<< --- MOVED .ENV LOADING AND BASE_URL DEFINITION INSIDE THE FUNCTION --- >>>
    dotenv_path_sitemap = os.path.join(PROJECT_ROOT, '.env') # Recalculate path if needed, or assume PROJECT_ROOT is correct
    load_dotenv(dotenv_path=dotenv_path_sitemap) # Load .env specific to this function call
    
    raw_base_url_sitemap = os.getenv('YOUR_SITE_BASE_URL')
    if not raw_base_url_sitemap:
        logger.error("CRITICAL (Sitemap): YOUR_SITE_BASE_URL is not set in .env. Cannot generate sitemap.")
        return # Exit function if base URL is missing
    BASE_URL_SITEMAP = raw_base_url_sitemap.rstrip('/') + '/'
    # <<< --- END OF MOVED SECTION --- >>>

    logger.info("Starting sitemap generation (including digests)...")

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

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    xml_content += '  <url>\n'
    xml_content += f'    <loc>{escape(BASE_URL_SITEMAP)}</loc>\n' # Use function-local BASE_URL_SITEMAP
    
    homepage_lastmod_dt = datetime.now(timezone.utc) 
    if articles_for_sitemap:
        latest_article_date_obj = None
        for art in articles_for_sitemap:
            pub_iso = art.get('published_iso')
            if pub_iso:
                try:
                    current_art_dt = datetime.fromisoformat(pub_iso.replace('Z', '+00:00'))
                    if latest_article_date_obj is None or current_art_dt > latest_article_date_obj:
                        latest_article_date_obj = current_art_dt
                except ValueError:
                    continue 
        if latest_article_date_obj:
            homepage_lastmod_dt = latest_article_date_obj
            
    xml_content += f'    <lastmod>{homepage_lastmod_dt.strftime("%Y-%m-%d")}</lastmod>\n'
    xml_content += '    <changefreq>daily</changefreq>\n'
    xml_content += '    <priority>1.0</priority>\n'
    xml_content += '  </url>\n'

    processed_article_urls_count = 0
    for article in articles_for_sitemap:
        if not isinstance(article, dict):
            logger.warning("Skipping non-dictionary item in articles list during sitemap generation.")
            continue
        relative_link = article.get('link') 
        publish_date_iso = article.get('published_iso')
        if not relative_link:
            logger.warning(f"Skipping article with missing link (ID: {article.get('id', 'N/A')}) for sitemap.")
            continue
        absolute_url = urljoin(BASE_URL_SITEMAP, relative_link.lstrip('/')) # Use function-local
        xml_content += '  <url>\n'
        xml_content += f'    <loc>{escape(absolute_url)}</loc>\n'
        lastmod_date_str = format_datetime_for_sitemap(publish_date_iso)
        if lastmod_date_str:
            xml_content += f'    <lastmod>{lastmod_date_str}</lastmod>\n'
        xml_content += '    <changefreq>weekly</changefreq>\n' 
        xml_content += '    <priority>0.8</priority>\n'       
        xml_content += '  </url>\n'
        processed_article_urls_count += 1

    processed_digest_urls_count = 0
    if os.path.exists(DIGESTS_DIR) and os.path.isdir(DIGESTS_DIR):
        logger.info(f"Scanning for digest pages in: {DIGESTS_DIR}")
        for filename in os.listdir(DIGESTS_DIR):
            if filename.endswith(".html"):
                digest_slug = filename
                relative_digest_path = f"digests/{digest_slug}" 
                absolute_digest_url = urljoin(BASE_URL_SITEMAP, relative_digest_path) # Use function-local
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
                    logger.warning(f"Could not get modification time for digest {filename}: {e}")
                xml_content += '    <changefreq>daily</changefreq>\n' 
                xml_content += '    <priority>0.7</priority>\n'      
                xml_content += '  </url>\n'
                processed_digest_urls_count += 1
        logger.info(f"Added {processed_digest_urls_count} digest pages to sitemap.")
    else:
        logger.info(f"Digest directory not found or not a directory: {DIGESTS_DIR}. No digest pages added.")

    xml_content += '</urlset>'

    try:
        os.makedirs(PUBLIC_DIR, exist_ok=True) 
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        total_urls = 1 + processed_article_urls_count + processed_digest_urls_count 
        logger.info(f"Sitemap successfully generated with {total_urls} URLs and saved to {SITEMAP_PATH}")
    except Exception as e:
        logger.error(f"Failed to write sitemap file to {SITEMAP_PATH}: {e}")

if __name__ == "__main__":
    if not os.path.exists(DIGESTS_DIR):
        os.makedirs(DIGESTS_DIR, exist_ok=True)
    if not os.listdir(DIGESTS_DIR): 
        logger.info("Creating dummy digest files for standalone sitemap test...")
        with open(os.path.join(DIGESTS_DIR, "dummy-digest-1.html"), "w") as f: f.write("<h1>Dummy Digest 1</h1>")
        with open(os.path.join(DIGESTS_DIR, "another-sample-digest.html"), "w") as f: f.write("<h1>Dummy Digest 2</h1>")
    generate_sitemap()
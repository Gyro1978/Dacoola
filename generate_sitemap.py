import os
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin
from dotenv import load_dotenv

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(PROJECT_ROOT, 'public')
ALL_ARTICLES_FILE = os.path.join(PUBLIC_DIR, 'all_articles.json')
SITEMAP_PATH = os.path.join(PUBLIC_DIR, 'sitemap.xml')

# Load environment variables to get the base URL
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
# Ensure BASE_URL ends with a slash
raw_base_url = os.getenv('YOUR_SITE_BASE_URL')
if not raw_base_url:
    print("ERROR: YOUR_SITE_BASE_URL is not set in the .env file. Cannot generate sitemap.")
    exit(1)
BASE_URL = raw_base_url.rstrip('/') + '/'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def format_datetime_for_sitemap(iso_date_string):
    """Attempts to parse ISO date and format as YYYY-MM-DD."""
    if not iso_date_string:
        return None
    try:
        # Handle potential 'Z' timezone indicator
        if iso_date_string.endswith('Z'):
            iso_date_string = iso_date_string[:-1] + '+00:00'

        dt = datetime.fromisoformat(iso_date_string)
        # Format to YYYY-MM-DD
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        logger.warning(f"Could not parse date '{iso_date_string}' for sitemap. Skipping lastmod.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing date '{iso_date_string}': {e}")
        return None

def generate_sitemap():
    """Generates the sitemap.xml file."""
    logger.info("Starting sitemap generation...")

    # Load article data
    try:
        if not os.path.exists(ALL_ARTICLES_FILE):
            logger.error(f"{ALL_ARTICLES_FILE} not found. Cannot generate sitemap.")
            return
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        articles = data.get("articles", [])
        if not articles:
            logger.warning("No articles found in all_articles.json.")
            # Optionally generate a sitemap with just the homepage
            # return # Or continue to just generate homepage entry
    except Exception as e:
        logger.error(f"Failed to load or parse {ALL_ARTICLES_FILE}: {e}")
        return

    logger.info(f"Loaded {len(articles)} articles.")

    # Start building the XML string
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    # Add Homepage URL
    xml_content += '  <url>\n'
    xml_content += f'    <loc>{BASE_URL}</loc>\n' # Assumes homepage is at base URL
    # You might want to use the last article's date or current date for homepage lastmod
    homepage_lastmod = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if articles:
        last_article_date = format_datetime_for_sitemap(articles[0].get('published_iso'))
        if last_article_date:
             homepage_lastmod = last_article_date
    xml_content += f'    <lastmod>{homepage_lastmod}</lastmod>\n'
    xml_content += '    <changefreq>daily</changefreq>\n'
    xml_content += '    <priority>1.0</priority>\n'
    xml_content += '  </url>\n'

    # Add Article URLs
    processed_urls_count = 0
    for article in articles:
        if not isinstance(article, dict):
            logger.warning("Skipping non-dictionary item in articles list.")
            continue

        relative_link = article.get('link')
        publish_date_iso = article.get('published_iso')

        if not relative_link:
            logger.warning(f"Skipping article with missing link (ID: {article.get('id', 'N/A')}).")
            continue

        # Construct absolute URL
        absolute_url = urljoin(BASE_URL, relative_link.lstrip('/'))

        xml_content += '  <url>\n'
        xml_content += f'    <loc>{absolute_url}</loc>\n'

        # Add last modified date if available and parseable
        lastmod_date = format_datetime_for_sitemap(publish_date_iso)
        if lastmod_date:
            xml_content += f'    <lastmod>{lastmod_date}</lastmod>\n'

        # Add change frequency and priority (adjust as needed)
        xml_content += '    <changefreq>weekly</changefreq>\n' # Or 'monthly', 'never' for older articles
        xml_content += '    <priority>0.8</priority>\n'       # Articles slightly lower priority than homepage

        xml_content += '  </url>\n'
        processed_urls_count += 1

    # Close the urlset tag
    xml_content += '</urlset>'

    # Write the sitemap file
    try:
        os.makedirs(PUBLIC_DIR, exist_ok=True)
        with open(SITEMAP_PATH, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        logger.info(f"Sitemap successfully generated with {processed_urls_count + 1} URLs and saved to {SITEMAP_PATH}")
    except Exception as e:
        logger.error(f"Failed to write sitemap file to {SITEMAP_PATH}: {e}")

if __name__ == "__main__":
    generate_sitemap()
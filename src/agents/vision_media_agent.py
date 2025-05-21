# src/agents/vision_media_agent.py (Simplified for Headline Image)
import sys
import os
import json
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import time
import io
import random
from PIL import Image, UnidentifiedImageError, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv

# --- Path Setup & Env Load ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Import from image_scraper
try:
    from src.scrapers.image_scraper import find_best_image as scrape_with_image_scraper
    IMAGE_SCRAPER_AVAILABLE = True
    logging.info("Successfully imported find_best_image from image_scraper.")
except ImportError as e:
    IMAGE_SCRAPER_AVAILABLE = False
    logging.error(f"Failed to import from image_scraper: {e}. Image scraping capabilities will be limited.")
    scrape_with_image_scraper = None # Ensure it's defined

__all__ = ['run_vision_media_agent']

# --- Library Availability Flags (Simplified) ---
DDGS_AVAILABLE = False
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
    logging.info("duckduckgo_search library found.")
except ImportError:
    DDGS = None
    logging.warning("duckduckgo_search library import FAILED. DDG fallback search disabled.")

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s-%(name)s-%(levelname)s-[%(module)s.%(funcName)s:%(lineno)d]-%(message)s', handlers=[logging.StreamHandler(sys.stdout)])

# --- Configuration Constants (Simplified) ---
IMAGE_DOWNLOAD_TIMEOUT_VMA = int(os.getenv("VMA_DOWNLOAD_TIMEOUT", "40"))
IMAGE_DOWNLOAD_RETRIES_VMA = int(os.getenv("VMA_DOWNLOAD_RETRIES", "3"))
IMAGE_RETRY_DELAY_VMA = int(os.getenv("VMA_RETRY_DELAY", "15"))
MIN_IMAGE_WIDTH_VMA = int(os.getenv("VMA_MIN_WIDTH_STRICT", "600")) # Adjusted for headline
MIN_IMAGE_HEIGHT_VMA = int(os.getenv("VMA_MIN_HEIGHT_STRICT", "300")) # Adjusted for headline
MIN_IMAGE_FILESIZE_BYTES_VMA = int(os.getenv("VMA_MIN_FILESIZE_KB_STRICT", "50")) * 1024 # Adjusted
DEFAULT_PLACEHOLDER_IMAGE_URL = os.getenv("VMA_DEFAULT_PLACEHOLDER_URL", "https://via.placeholder.com/1200x675.png?text=Image+Not+Available")
DDG_MAX_RESULTS_FOR_IMAGE_PAGES = int(os.getenv("VMA_DDG_PAGE_SEARCH_RESULTS", "5")) # Simplified
DDG_QUERY_DELAY_MIN = int(os.getenv("VMA_DDG_QUERY_DELAY_MIN", "7"))
DDG_QUERY_DELAY_MAX = int(os.getenv("VMA_DDG_QUERY_DELAY_MAX", "15"))
DDG_PAGE_SCRAPE_DELAY_MIN = int(os.getenv("VMA_DDG_PAGE_SCRAPE_DELAY_MIN", "3"))
DDG_PAGE_SCRAPE_DELAY_MAX = int(os.getenv("VMA_DDG_PAGE_SCRAPE_DELAY_MAX", "7"))
ALT_TEXT_TARGET_MAX_LEN = int(os.getenv("VMA_ALT_TEXT_MAX_LEN", "125"))
USER_AGENT_LIST_VMA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]
WEBSITE_URL_VMA = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')


def requests_retry_session(retries=IMAGE_DOWNLOAD_RETRIES_VMA, backoff_factor=IMAGE_RETRY_DELAY_VMA/3, status_forcelist=(500, 502, 503, 504, 403, 429, 408), session=None):
    session = session or requests.Session()
    retry = Retry(total=retries, read=retries, connect=retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist, allowed_methods=frozenset(['HEAD', 'GET']))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter); session.mount('https://', adapter)
    return session

# --- Stage 1 (DDG Fallback): Aggressive Source URL Image Extraction ---
# This is kept for the DDG fallback path if image_scraper fails
def _scrape_images_from_url_aggressively_stage1_impl(page_url: str, base_url_for_relative: str, session: requests.Session) -> list:
    if not page_url or not page_url.startswith('http'): return []
    logger.info(f"DDG Fallback: Stage 1 (Aggressive Scrape) for images: {page_url}")
    candidate_images = []; seen_urls_scrape = set()
    current_user_agent = random.choice(USER_AGENT_LIST_VMA)
    session.headers.update({'User-Agent': current_user_agent, 'Referer': base_url_for_relative, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    try:
        response = session.get(page_url, timeout=IMAGE_DOWNLOAD_TIMEOUT_VMA, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if not ('html' in content_type or 'xml' in content_type):
            logger.warning(f"DDG Fallback: Content type not HTML/XML for aggressive scrape: {page_url} (Type: {content_type})"); return []
        soup = BeautifulSoup(response.content, 'lxml')
        meta_selectors = [{'property': 'og:image'}, {'property': 'og:image:secure_url'}, {'name': 'twitter:image'}, {'name': 'twitter:image:src'}, {'itemprop': 'image'}]
        for selector in meta_selectors:
            tag = soup.find('meta', attrs=selector)
            if tag and tag.get('content'):
                img_url = urljoin(base_url_for_relative, tag['content'].strip())
                if img_url.startswith('http') and img_url not in seen_urls_scrape:
                     candidate_images.append({'url': img_url, 'title': 'Meta Tag Image', 'source_engine': 'DDG Fallback Direct Scrape (Meta)'}); seen_urls_scrape.add(img_url)
        # Simplified: Only taking meta images for DDG fallback pages for now. Could add img tag search if needed.
        logger.info(f"DDG Fallback: Stage 1 (Aggressive Scrape) found {len(candidate_images)} unique candidates from {page_url}.")
        return candidate_images
    except requests.exceptions.RequestException as e:
        logger.error(f"DDG Fallback: Stage 1 (Aggressive Scrape) error for {page_url}: {e}")
    except Exception as e: logger.error(f"DDG Fallback: Stage 1 (Aggressive Scrape) unexpected error {page_url}: {e}", exc_info=True)
    return []

# --- Stage 2 (DDG Fallback): Indirect Image Search via DuckDuckGo Page Search ---
def _search_pages_for_images_stage2_impl(query_list: list, session: requests.Session) -> list:
    if not DDGS_AVAILABLE: logger.error("DDG Fallback: DDGS not available for Stage 2 page search."); return []
    logger.info(f"DDG Fallback: Stage 2 (DDG Page Search) for pages with {len(query_list)} queries.")
    all_img_candidates = []
    ddgs_instance = DDGS(timeout=35, proxies=session.proxies if session and hasattr(session, 'proxies') else None) if DDGS else None
    if not ddgs_instance: logger.error("DDG Fallback: DDGS instance could not be created."); return []
    
    for i, query in enumerate(query_list):
        if not query: continue
        logger.debug(f"DDG Fallback: Text Query {i+1}/{len(query_list)}: '{query}'")
        page_hits = []
        try:
            page_hits = list(ddgs_instance.text(query, max_results=DDG_MAX_RESULTS_FOR_IMAGE_PAGES, region='wt-wt', safesearch='Off'))
        except Exception as e:
            logger.error(f"DDG Fallback: DDG text search failed for '{query}': {e}")
            if "rate limit" in str(e).lower(): time.sleep(random.uniform(60, 120))
            continue
        for hit in page_hits:
            page_url = hit.get('href')
            if page_url:
                parsed_hit_url = urlparse(page_url); base_hit_url = f"{parsed_hit_url.scheme}://{parsed_hit_url.netloc}"
                imgs_from_page = _scrape_images_from_url_aggressively_stage1_impl(page_url, base_hit_url, session)
                for img_d in imgs_from_page:
                    img_d['source_engine'] = 'DDG Fallback Page Scrape'; img_d['original_search_query'] = query
                all_img_candidates.extend(imgs_from_page)
                time.sleep(random.uniform(DDG_PAGE_SCRAPE_DELAY_MIN, DDG_PAGE_SCRAPE_DELAY_MAX))
        if i < len(query_list) - 1: time.sleep(random.uniform(DDG_QUERY_DELAY_MIN, DDG_QUERY_DELAY_MAX))
            
    unique_final = list({d['url']:d for d in all_img_candidates if d.get('url')}.values())
    logger.info(f"DDG Fallback: Stage 2 (DDG Page Search) found {len(unique_final)} total unique img candidates."); return unique_final

# --- Stage 3 (DDG Fallback): Image Download, Validation (Robust) ---
def _download_and_validate_image_stage3_impl(url: str, session: requests.Session) -> dict | None:
    if not url or not url.startswith('http'): logger.warning(f"DDG Fallback: Invalid image URL: {url}"); return None
    logger.debug(f"DDG Fallback: Stage 3 (Download & Validation) for: {url}")
    current_session = session or requests_retry_session()
    current_user_agent = random.choice(USER_AGENT_LIST_VMA)
    current_session.headers.update({'User-Agent': current_user_agent, 'Accept': 'image/avif,image/webp,image/apng,image/jpeg,image/png,image/*,*/*;q=0.8'})
    try:
        response = current_session.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT_VMA, stream=True, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        is_image = any(ct in content_type for ct in ['image/jpeg', 'image/png', 'image/webp'])
        if not is_image: logger.warning(f"DDG Fallback: URL content-type not a supported image ({content_type}): {url}"); return None
        
        image_content_bytes = response.content
        if len(image_content_bytes) < MIN_IMAGE_FILESIZE_BYTES_VMA: logger.warning(f"DDG Fallback: Img too small ({len(image_content_bytes)}B): {url}"); return None
        
        img = Image.open(io.BytesIO(image_content_bytes))
        if img.width < MIN_IMAGE_WIDTH_VMA or img.height < MIN_IMAGE_HEIGHT_VMA: logger.warning(f"DDG Fallback: Img too small dim ({img.width}x{img.height}): {url}"); return None
        
        if img.mode not in ['RGB', 'RGBA']: img = img.convert('RGB')
        logger.info(f"DDG Fallback: Stage 3 Validated: {url} ({img.width}x{img.height})")
        return {"url": url, "image_obj": img} # Only returning obj for validation, not for storage
    except Exception as e: logger.error(f"DDG Fallback: Stage 3 error for {url}: {e}", exc_info=False); return None

# --- Main Agent Orchestrator ---
def run_vision_media_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    article_title = article_pipeline_data.get('final_page_h1', article_pipeline_data.get('initial_title_from_web', 'Untitled Article'))
    primary_keyword = article_pipeline_data.get('final_keywords', [article_title])[0] if article_pipeline_data.get('final_keywords') else article_title
    source_url = article_pipeline_data.get('original_source_url')
    
    logger.info(f"--- [VMA Simplified] Running for ID: {article_id} ---")
    article_pipeline_data.update({'selected_image_url': None, 'final_featured_image_alt_text': None})

    selected_image_url = None

    # Step 1: Try image_scraper.py (which does direct scrape then SerpApi)
    if IMAGE_SCRAPER_AVAILABLE and scrape_with_image_scraper:
        logger.info(f"Attempting image fetch via image_scraper for: {article_title[:60]}")
        search_query_for_scraper = primary_keyword if primary_keyword else article_title
        try:
            selected_image_url = scrape_with_image_scraper(search_query=search_query_for_scraper, article_url_for_scrape=source_url)
            if selected_image_url:
                logger.info(f"Image scraper found URL: {selected_image_url}")
            else:
                logger.info("Image scraper did not find a suitable image.")
        except Exception as e_scraper:
            logger.error(f"Error calling image_scraper: {e_scraper}", exc_info=True)
            selected_image_url = None # Ensure it's None if scraper errors out
    else:
        logger.warning("Image scraper not available. Proceeding to DDG fallback directly.")

    # Step 2: Fallback to DuckDuckGo search if image_scraper failed
    if not selected_image_url and DDGS_AVAILABLE:
        logger.info(f"Image scraper failed or unavailable. Attempting DDG fallback for: {article_title[:60]}")
        http_session = requests_retry_session()
        # Simplified query generation: use title and primary keyword
        ddg_queries = list(set(filter(None, [article_title, primary_keyword])))
        if not ddg_queries: ddg_queries = ["generic technology image"] # ultimate fallback query
        
        logger.info(f"DDG Fallback: Using queries: {ddg_queries}")
        ddg_cand_url_metas = _search_pages_for_images_stage2_impl(ddg_queries, http_session)
        
        if ddg_cand_url_metas:
            logger.info(f"DDG Fallback: Found {len(ddg_cand_url_metas)} potential candidates. Validating...")
            for cand_meta in ddg_cand_url_metas:
                img_data_dict = _download_and_validate_image_stage3_impl(cand_meta.get('url'), http_session)
                if img_data_dict:
                    selected_image_url = img_data_dict['url']
                    logger.info(f"DDG Fallback: Selected image: {selected_image_url}")
                    break # Found a valid one
        else:
            logger.info("DDG Fallback: No candidates found from page search.")
        http_session.close()

    # Step 3: Set results or default placeholder
    if selected_image_url:
        article_pipeline_data['selected_image_url'] = selected_image_url
        alt_text = f"{article_title} - featured image" # Simple alt text
        if len(alt_text) > ALT_TEXT_TARGET_MAX_LEN:
            alt_text = alt_text[:ALT_TEXT_TARGET_MAX_LEN-3] + "..."
        article_pipeline_data['final_featured_image_alt_text'] = alt_text
        article_pipeline_data['vision_media_agent_status'] = "SUCCESS_SIMPLIFIED_VMA"
    else:
        article_pipeline_data['selected_image_url'] = DEFAULT_PLACEHOLDER_IMAGE_URL
        article_pipeline_data['final_featured_image_alt_text'] = f"{article_title[:ALT_TEXT_TARGET_MAX_LEN-20]} - Image not available".strip()
        article_pipeline_data['vision_media_agent_status'] = "FAILED_SIMPLIFIED_VMA_DEFAULT_PLACEHOLDER"
        logger.warning(f"Using default placeholder for {article_id}.")

    logger.info(f"[VMA Simplified] Result for {article_id}: URL='{article_pipeline_data['selected_image_url']}', Alt='{article_pipeline_data['final_featured_image_alt_text']}'")
    logger.info(f"--- [VMA Simplified] Finished for ID: {article_id} ---")
    return article_pipeline_data

if __name__ == "__main__":
    logger.info(f"--- Starting Vision & Media Agent (Simplified) Standalone Test ---")
    
    # Ensure image_scraper can be found for the test if run directly
    # This might require adjustments if image_scraper itself has issues being found
    if not IMAGE_SCRAPER_AVAILABLE:
         logger.error("Standalone test cannot proceed effectively: image_scraper module not loaded.")
         # Attempt to load it directly for test context if path is simple
         try:
             from src.scrapers.image_scraper import find_best_image as scrape_with_image_scraper_test
             scrape_with_image_scraper = scrape_with_image_scraper_test # Override if loaded late
             IMAGE_SCRAPER_AVAILABLE = True
             logger.info("Late load of image_scraper for test successful.")
         except ImportError:
             logger.error("Late load of image_scraper for test FAILED.")


    sample_article_data_vma = {
        'id': 'test_vma_simplified_001',
        'final_page_h1': "New AI Chip Unveiled by Tech Giant",
        'final_keywords': ["AI chip", "Tech Giant", "innovation"],
        'initial_title_from_web': "Tech Giant's New AI Chip",
        'original_source_url': 'https://www.example.com/news/ai-chip', # Replace with a real URL for better testing if possible
        'processed_summary': 'A new AI chip has been unveiled, promising greater speeds.'
    }
    
    # To make DDG fallback testable without live DDG, one might need to mock DDGS_AVAILABLE = False
    # or provide dummy page content if _search_pages_for_images_stage2_impl is called.
    # For now, assume it will try image_scraper first.
    
    # If you have a SerpApi key in .env, image_scraper will use it.
    # If not, image_scraper.find_best_image will return None (if direct scrape also fails).
    # Then, VMA will try DDG fallback.
    
    result_data_vma = run_vision_media_agent(sample_article_data_vma.copy())
    
    logger.info("
--- VMA (Simplified) Test Results ---")
    logger.info(f"Status: {result_data_vma.get('vision_media_agent_status')}")
    logger.info(f"Selected Img URL: {result_data_vma.get('selected_image_url')}")
    logger.info(f"Featured Img Alt: {result_data_vma.get('final_featured_image_alt_text')}")
    assert 'media_candidates_for_body' not in result_data_vma or not result_data_vma['media_candidates_for_body']
    logger.info("--- VMA (Simplified) Standalone Test Complete ---")

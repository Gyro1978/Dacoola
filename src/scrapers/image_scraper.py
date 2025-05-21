# src/scrapers/image_scraper.py (Updated download_image)

import os
import sys
import requests
import logging
import io
import time # For retry delay
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
from bs4 import BeautifulSoup, Comment # Comment not used currently, but good to have
from serpapi import GoogleSearch

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# --- CLIP Integration ---
CLIP_MODEL_NAME = 'clip-ViT-B-32'
CLIP_AVAILABLE = False
clip_model = None
try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim 
    # clip_model will be loaded on first use in filter_images_with_clip
    CLIP_AVAILABLE = True # Mark as potentially available
    logging.info(f"SentenceTransformer library found. CLIP model '{CLIP_MODEL_NAME}' can be loaded on demand.")
except ImportError:
    logging.warning("sentence-transformers library not found. CLIP filtering will be disabled.")
except Exception as e:
    logging.error(f"Error importing SentenceTransformer for CLIP: {e}. CLIP filtering disabled.")
# --- End CLIP Integration ---

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
WEBSITE_URL_FOR_AGENT = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')

# --- Configuration ---
IMAGE_SEARCH_PARAMS = {
    "engine": "google_images", "ijn": "0", "safe": "active",
    "tbs": "isz:l,itp:photo,iar:w", 
}
ENABLE_CLIP_FILTERING = CLIP_AVAILABLE 
IMAGE_DOWNLOAD_TIMEOUT = 20 
IMAGE_DOWNLOAD_RETRIES = 2
IMAGE_RETRY_DELAY = 3 
MIN_IMAGE_WIDTH = 400  
MIN_IMAGE_HEIGHT = 250 
MIN_CLIP_SCORE = 0.23 
MIN_IMAGE_FILESIZE_BYTES_FOR_VALIDATION = 1024 * 5 # 5KB, very small images are likely icons/errors

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers: 
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] 
    )
# --- End Setup Logging ---

def download_image(url, attempt=1):
    """Downloads an image, converts to RGB, checks content type, dimensions, and minimum filesize. Includes retries."""
    if not url or not url.startswith('http'):
        logger.warning(f"Invalid image URL format: {url}")
        return None
    try:
        headers = {'User-Agent': f'DacoolaImageScraper/1.1 (+{WEBSITE_URL_FOR_AGENT})'}
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=headers, stream=True)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            logger.warning(f"URL content-type not an image ({content_type}): {url}")
            return None

        image_content_bytes = response.content
        if len(image_content_bytes) < MIN_IMAGE_FILESIZE_BYTES_FOR_VALIDATION:
            logger.warning(f"Downloaded image content too small ({len(image_content_bytes)} bytes) from {url}. Likely not a valid content image.")
            return None
            
        image_data = io.BytesIO(image_content_bytes)
        img = Image.open(image_data)
        
        if img.width < MIN_IMAGE_WIDTH or img.height < MIN_IMAGE_HEIGHT:
            logger.warning(f"Image too small ({img.width}x{img.height}) from {url}. Min: {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}.")
            return None

        if img.mode != 'RGB': img = img.convert('RGB')
        logger.debug(f"Successfully downloaded and validated image: {url} (Size: {img.size}, Content-Type: {content_type})")
        return img

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout downloading image (attempt {attempt}): {url}")
        if attempt < IMAGE_DOWNLOAD_RETRIES:
            logger.info(f"Retrying download for {url} in {IMAGE_RETRY_DELAY}s...")
            time.sleep(IMAGE_RETRY_DELAY)
            return download_image(url, attempt + 1)
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None
    except UnidentifiedImageError:
         logger.warning(f"Could not identify image file (Invalid image format?) from: {url}")
         return None
    except Exception as e:
        logger.error(f"Error processing image {url}: {e}", exc_info=True) # Added exc_info for more detail
        return None

def filter_images_with_clip(image_results, text_prompt):
    global clip_model # Allow modification of the global model instance

    if not ENABLE_CLIP_FILTERING or not CLIP_AVAILABLE:
        logger.info("CLIP filtering skipped: Disabled by config or SentenceTransformer library not available.")
        # Fallback: return first downloadable image from results
        for img_data in image_results:
            if img_data.get('url') and download_image(img_data.get('url')):
                return img_data.get('url')
        return None

    if not clip_model:
        try:
            logger.info(f"Loading CLIP model for filtering: {CLIP_MODEL_NAME}")
            clip_model = SentenceTransformer(CLIP_MODEL_NAME)
        except Exception as e:
            logger.error(f"Failed to load CLIP model ({CLIP_MODEL_NAME}) on demand: {e}. CLIP disabled for this call.")
            # Fallback to first downloadable image if CLIP load fails
            for img_data in image_results:
                if img_data.get('url') and download_image(img_data.get('url')):
                    return img_data.get('url')
            return None
    
    logger.info(f"CLIP filtering {len(image_results)} candidates for prompt: '{text_prompt}'")
    image_objects, valid_original_urls = [], []
    for img_data in image_results:
        url = img_data.get('url')
        if url:
            pil_image = download_image(url) 
            if pil_image:
                image_objects.append(pil_image); valid_original_urls.append(url)
            else: logger.debug(f"Skipping image for CLIP (download/validation failed): {url}")

    if not image_objects:
        logger.warning("No images suitable for CLIP analysis after download/validation.")
        return image_results[0].get('url') if image_results and download_image(image_results[0].get('url')) else None

    try:
        logger.debug(f"Encoding {len(image_objects)} images and text prompt with CLIP...")
        image_embeddings = clip_model.encode(image_objects, batch_size=8, convert_to_tensor=True, show_progress_bar=False) 
        text_embedding = clip_model.encode([text_prompt], convert_to_tensor=True, show_progress_bar=False)
        similarities = cos_sim(text_embedding, image_embeddings)[0]

        scored_images = [{'score': score.item(), 'url': valid_original_urls[i]} for i, score in enumerate(similarities)]
        scored_images.sort(key=lambda x: x['score'], reverse=True) 

        for i, item in enumerate(scored_images[:3]):
            logger.debug(f"CLIP Candidate {i+1}: {item['url']}, Score: {item['score']:.4f}")

        best_above_threshold = next((item for item in scored_images if item['score'] >= MIN_CLIP_SCORE), None)

        if best_above_threshold:
            logger.info(f"CLIP selected best image above threshold: {best_above_threshold['url']} (Score: {best_above_threshold['score']:.4f})")
            return best_above_threshold['url']
        elif scored_images: 
            logger.warning(f"No images met MIN_CLIP_SCORE ({MIN_CLIP_SCORE}). Taking highest overall: {scored_images[0]['url']} (Score: {scored_images[0]['score']:.4f})")
            return scored_images[0]['url']
        else: 
            logger.error("Critical CLIP error: No similarities or images processed. Using first original result if valid.")
            return image_results[0].get('url') if image_results and download_image(image_results[0].get('url')) else None

    except Exception as e:
        logger.exception(f"Exception during CLIP processing: {e}")
        if valid_original_urls: return valid_original_urls[0]
        return image_results[0].get('url') if image_results and download_image(image_results[0].get('url')) else None


def scrape_source_for_image(article_url):
    if not article_url or not article_url.startswith('http'):
        logger.debug(f"Invalid article URL for scraping: {article_url}")
        return None
    logger.info(f"Attempting to scrape meta image tag from source: {article_url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DacoolaImageBot/1.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(article_url, headers=headers, timeout=15, allow_redirects=True) 
        response.raise_for_status()
        if 'html' not in response.headers.get('content-type', '').lower():
             logger.warning(f"Source URL content type not HTML: {article_url}"); return None

        soup = BeautifulSoup(response.content, 'html.parser')
        meta_selectors = [
            {'property': 'og:image'}, {'property': 'og:image:secure_url'},
            {'name': 'twitter:image'}, {'name': 'twitter:image:src'},
            {'itemprop': 'image'}
        ]
        for selector in meta_selectors:
            tag = soup.find('meta', attrs=selector)
            if tag and tag.get('content') and tag['content'].startswith('http'):
                candidate_url = tag['content']
                # Quick check for common non-image file extensions if present in URL
                if any(ext in candidate_url.lower() for ext in ['.gif', '.svg', '.webp']): # webp could be fine but sometimes problematic
                    logger.debug(f"Skipping meta image {candidate_url} due to potentially non-ideal extension for main image.")
                    continue
                logger.info(f"Found meta image ({selector}): {candidate_url}")
                return candidate_url
        
        main_content_areas = soup.select('article, main, .article-body, .post-content, .entry-content, .td-main-content, .td-post-content') # Added common theme classes
        largest_image_src = None
        max_area = 0
        for area in main_content_areas:
            if area:
                for img_tag in area.find_all('img'):
                    src = img_tag.get('src') or img_tag.get('data-src') # Check data-src for lazy loaded
                    if src and src.startswith('http'):
                        if any(skip_term in src.lower() for skip_term in ['ads.', 'pixel.', 'stats.', 'counter.', '.gif', 'logo', 'icon', 'avatar', 'spinner', 'loading', 'placeholder', 'banner', 'sprite', 'data:image/']):
                            continue
                        width = img_tag.get('width', '0'); height = img_tag.get('height', '0')
                        try: 
                            w_val = int(str(width).replace('px',''))
                            h_val = int(str(height).replace('px',''))
                            if w_val < MIN_IMAGE_WIDTH / 2 or h_val < MIN_IMAGE_HEIGHT / 2 : continue # Must be somewhat large
                            area_val = w_val * h_val
                        except ValueError: area_val = 0
                        if area_val > max_area:
                            max_area = area_val
                            largest_image_src = src
        if largest_image_src:
            logger.info(f"Found largest image in content as fallback: {largest_image_src}")
            return largest_image_src

        logger.warning(f"No suitable image meta tag or large content image found at: {article_url}")
        return None
    except requests.exceptions.RequestException as e: logger.warning(f"Failed to fetch/scrape source {article_url}: {e}"); return None
    except Exception as e: logger.exception(f"Error scraping source image from {article_url}: {e}"); return None


def search_images_serpapi(query, num_results=7): 
    if not SERPAPI_API_KEY:
        logger.error("SERPAPI_API_KEY not found. Cannot perform image search.")
        return None
    if not GoogleSearch:
        logger.error("SerpApi client (google-search-results) not installed. Cannot perform image search.")
        return None
        
    params = IMAGE_SEARCH_PARAMS.copy(); params['q'] = query; params['api_key'] = SERPAPI_API_KEY
    try:
        logger.debug(f"Sending SerpApi request: '{query}'")
        search = GoogleSearch(params); results = search.get_dict()
        if 'error' in results: logger.error(f"SerpApi error for '{query}': {results['error']}"); return None
        if results.get('images_results'):
            image_data = [{"url": img.get("original"), "title": img.get("title"), "source": img.get("source")}
                          for img in results['images_results'][:num_results] if img.get("original")]
            if not image_data: logger.warning(f"SerpApi: No results with 'original' URL for '{query}'"); return []
            logger.info(f"SerpApi found {len(image_data)} image candidates for '{query}'")
            return image_data
        logger.warning(f"No image results via SerpApi for '{query}'"); return []
    except Exception as e: logger.exception(f"SerpApi image search exception for '{query}': {e}"); return None

def find_best_image(search_query, use_clip=ENABLE_CLIP_FILTERING, article_url_for_scrape=None):
    if not search_query: logger.error("Cannot find image: search_query is empty."); return None
    logger.info(f"Finding best image for query: '{search_query}' (CLIP: {use_clip and CLIP_AVAILABLE})")

    if article_url_for_scrape:
        scraped_image_url = scrape_source_for_image(article_url_for_scrape)
        if scraped_image_url:
            img_obj = download_image(scraped_image_url)
            if img_obj: 
                logger.info(f"Using valid image directly scraped from source: {scraped_image_url}")
                return scraped_image_url
            else:
                logger.warning(f"Scraped image {scraped_image_url} was invalid/too small. Proceeding to search.")
    else:
        logger.debug("No article_url_for_scrape provided to find_best_image, skipping direct source scrape step.")

    serpapi_results = search_images_serpapi(search_query)
    if not serpapi_results: 
        logger.error(f"SerpApi returned no image results for '{search_query}'. Cannot find image."); return None

    best_image_url = None
    if use_clip and CLIP_AVAILABLE:
        best_image_url = filter_images_with_clip(serpapi_results, search_query)
    else:
        if not CLIP_AVAILABLE and use_clip: logger.warning("CLIP requested but model unavailable. Using first valid SerpApi result.")
        for res in serpapi_results:
            if res.get('url'):
                img_obj = download_image(res.get('url'))
                if img_obj:
                    best_image_url = res.get('url')
                    logger.info(f"Using first valid SerpApi result (CLIP disabled or invalid): {best_image_url}")
                    break
        if not best_image_url:
             logger.error(f"None of the initial SerpApi results were downloadable/valid for '{search_query}'.")

    if best_image_url: logger.info(f"Selected image URL for '{search_query}': {best_image_url}")
    else: logger.error(f"Could not determine a best image URL for '{search_query}' after all steps.")
    return best_image_url

if __name__ == "__main__":
    test_query = "NVIDIA Blackwell B200 event"
    logger.info(f"\n--- Running Image Scraper Standalone Test ---")
    logger.info(f"Test Query: '{test_query}'")
    logger.info(f"CLIP Available: {CLIP_AVAILABLE}, CLIP Filtering Enabled: {ENABLE_CLIP_FILTERING}")

    test_article_page_url = "https://techcrunch.com/2024/03/18/nvidia-unveils-blackwell-ai-superchip-platform/"
    logger.info(f"\nTesting with article_url_for_scrape: {test_article_page_url}")
    best_image_with_scrape = find_best_image(test_query, use_clip=True, article_url_for_scrape=test_article_page_url)
    if best_image_with_scrape:
        logger.info(f"Result (with source scrape): {best_image_with_scrape}")
        img_obj = download_image(best_image_with_scrape)
        if img_obj: logger.info(f"Successfully downloaded scraped/selected image! Size: {img_obj.size}")
        else: logger.error("Failed to download the scraped/selected image.")
    else: logger.error("Test (with source scrape) failed to find an image URL.")

    logger.info(f"\nTesting with query only (no direct scrape URL): '{test_query}'")
    best_image_query_only = find_best_image(test_query, use_clip=True)
    if best_image_query_only:
        logger.info(f"Result (query only): {best_image_query_only}")
        img_obj = download_image(best_image_query_only)
        if img_obj: logger.info(f"Successfully downloaded query-only image! Size: {img_obj.size}")
        else: logger.error("Failed to download the query-only selected image.")
    else: logger.error("Test (query only) failed to find an image URL.")
    
    logger.info("\nTesting TikTok API URL image download (expected to fail validation):")
    tiktok_api_url = "https://www.tiktok.com/api/img/?itemId=7430656270497238318&location=0&aid=1988"
    tiktok_img_obj = download_image(tiktok_api_url)
    if tiktok_img_obj:
        logger.error(f"UNEXPECTED SUCCESS: TikTok API URL {tiktok_api_url} yielded an image object: {tiktok_img_obj.size}")
    else:
        logger.info(f"EXPECTED FAIL: TikTok API URL {tiktok_api_url} did not yield a valid image object.")


    logger.info("--- Image Scraper Standalone Test Complete ---\n")
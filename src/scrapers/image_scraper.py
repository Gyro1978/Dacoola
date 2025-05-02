# src/scrapers/image_scraper.py

import os
import sys # <- Added sys for path check below
import requests
import logging
import io
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError # <- Added UnidentifiedImageError explicitly
from bs4 import BeautifulSoup
from serpapi import GoogleSearch # Moved SerpAPI import up

# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT) # Add project root for imports if needed
# --- End Path Setup ---

# --- CLIP Integration ---
CLIP_MODEL_NAME = 'clip-ViT-B-32' # Or 'clip-ViT-L-14'
CLIP_AVAILABLE = False
clip_model = None
try:
    from sentence_transformers import SentenceTransformer
    clip_model = SentenceTransformer(CLIP_MODEL_NAME)
    CLIP_AVAILABLE = True
    logging.info(f"Successfully loaded CLIP model: {CLIP_MODEL_NAME}")
except ImportError:
    logging.warning("sentence-transformers library not found. CLIP filtering will be disabled.")
    logging.warning("Install it with: pip install sentence-transformers")
except Exception as e:
    logging.error(f"Error loading CLIP model ({CLIP_MODEL_NAME}): {e}. CLIP filtering disabled.")
# --- End CLIP Integration ---


# --- Load Environment Variables ---
# Ensure .env is loaded relative to the project root
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
# Get website URL for User-Agent from .env, default to placeholder
WEBSITE_URL_FOR_AGENT = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com') # Use real URL if available

# --- Configuration ---
IMAGE_SEARCH_PARAMS = {
    "engine": "google_images",
    "ijn": "0", # Page number (0 is first page)
    "safe": "active", # Enable SafeSearch
    "tbs": "isz:l,itp:photo,iar:w", # Size:Large, Type:Photo, Aspect Ratio: Wide
}
ENABLE_CLIP_FILTERING = CLIP_AVAILABLE # Use CLIP only if the model loaded
IMAGE_DOWNLOAD_TIMEOUT = 15 # Increased timeout slightly
MIN_CLIP_SCORE = 0.25 # Similarity threshold (adjust based on results)

# --- Setup Logging ---
# This setup is mainly for standalone testing. main.py's config will usually take precedence.
log_file_path_img_scraper = os.path.join(PROJECT_ROOT, 'dacoola.log')
try:
    os.makedirs(os.path.dirname(log_file_path_img_scraper), exist_ok=True)
    log_handlers_img_scraper = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path_img_scraper, encoding='utf-8')
    ]
except OSError as e:
    print(f"Image Scraper Log Error: Could not create log directory/file: {e}. Logging to console only.")
    log_handlers_img_scraper = [logging.StreamHandler(sys.stdout)]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers_img_scraper,
    force=True # Allow reconfiguration by main.py
)
logger = logging.getLogger(__name__) # Use module-specific logger
# --- End Setup Logging ---

def download_image(url):
    """Downloads an image from a URL and returns a PIL Image object, converted to RGB."""
    if not url or not url.startswith('http'):
        logger.warning(f"Invalid image URL provided for download: {url}")
        return None
    try:
        # Use a clear User-Agent
        headers = {'User-Agent': f'DacoolaImageScraper/1.0 (+{WEBSITE_URL_FOR_AGENT})'}
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=headers, stream=True)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            logger.warning(f"URL did not return an image content-type ({content_type}): {url}")
            # Allow common misconfigurations like application/octet-stream if needed, but log warning
            # if 'application/octet-stream' not in content_type: return None
            return None # Strict check for now

        image_data = io.BytesIO(response.content)
        img = Image.open(image_data)

        # Convert to RGB for CLIP compatibility
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout downloading image: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None
    except UnidentifiedImageError:
         logger.warning(f"Could not identify image file (Invalid format?) from: {url}")
         return None
    except Exception as e:
        # Catch other potential PIL errors or unexpected issues
        logger.warning(f"Error processing image {url}: {e}")
        return None

def filter_images_with_clip(image_results, text_prompt):
    """Filters/ranks image URLs using CLIP similarity to a text prompt."""
    if not image_results or not clip_model:
        logger.warning("CLIP filtering skipped: Model not available or no image results.")
        # Fallback: return the URL of the first image result if available
        return image_results[0].get('url') if image_results else None

    logger.info(f"CLIP filtering {len(image_results)} candidate images against prompt: '{text_prompt}'")

    image_objects = []
    valid_original_urls = []

    # Download and prepare images for encoding
    for img_data in image_results:
        url = img_data.get('url') # Changed from 'original' for consistency if source changes
        if url:
            pil_image = download_image(url)
            if pil_image:
                image_objects.append(pil_image)
                valid_original_urls.append(url)
            else:
                 logger.debug(f"Skipping image for CLIP (download/processing failed): {url}")

    if not image_objects:
        logger.warning("No images could be successfully downloaded/processed for CLIP analysis.")
        return image_results[0].get('url') if image_results else None # Fallback

    try:
        logger.debug(f"Encoding {len(image_objects)} images and 1 text prompt with CLIP...")
        # Batch encode for efficiency
        image_embeddings = clip_model.encode(image_objects, batch_size=16, convert_to_tensor=True, show_progress_bar=False)
        text_embedding = clip_model.encode([text_prompt], convert_to_tensor=True, show_progress_bar=False)

        # Calculate cosine similarities using sentence-transformers util
        from sentence_transformers.util import cos_sim
        similarities = cos_sim(text_embedding, image_embeddings)[0] # Similarities for the single text prompt

        scored_images = []
        for i, score_tensor in enumerate(similarities):
            score = score_tensor.item() # Get float value from tensor
            url = valid_original_urls[i]
            logger.debug(f"Image: {url}, CLIP Score: {score:.4f}")
            # Keep images that meet the minimum score
            if score >= MIN_CLIP_SCORE:
                 scored_images.append({'score': score, 'url': url})
            else:
                 logger.debug(f"Image rejected by CLIP (low score < {MIN_CLIP_SCORE}): {url}")

        # If no images meet the threshold, fallback to the highest scoring one
        if not scored_images:
            logger.warning(f"No images met the minimum CLIP score ({MIN_CLIP_SCORE}). Falling back to highest scoring image.")
            if len(similarities) > 0:
                 max_score_idx = similarities.argmax().item() # Find index of max score
                 fallback_url = valid_original_urls[max_score_idx]
                 logger.info(f"Fallback: Using image {fallback_url} (Score: {similarities[max_score_idx].item():.4f})")
                 return fallback_url
            else:
                 logger.error("Critical CLIP error: No similarities calculated. Returning first original result.")
                 return image_results[0].get('url') if image_results else None

        # Sort the qualified images by score (highest first)
        scored_images.sort(key=lambda x: x['score'], reverse=True)

        best_image_url = scored_images[0]['url']
        logger.info(f"CLIP selected best image: {best_image_url} (Score: {scored_images[0]['score']:.4f})")
        return best_image_url

    except Exception as e:
        logger.exception(f"Exception during CLIP encoding/similarity calculation: {e}")
        # Fallback strategy if CLIP processing fails unexpectedly
        return valid_original_urls[0] if valid_original_urls else (image_results[0].get('url') if image_results else None)

def scrape_source_for_image(article_url):
    """Tries to scrape og:image or twitter:image meta tags from the source article URL."""
    if not article_url or not article_url.startswith('http'):
        logger.debug(f"Invalid article URL for scraping: {article_url}")
        return None

    logger.info(f"Attempting to scrape meta image tag from source: {article_url}")
    try:
        headers = {'User-Agent': f'DacoolaImageScraper/1.0 (+{WEBSITE_URL_FOR_AGENT})'} # Consistent User-Agent
        response = requests.get(article_url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()

        if 'html' not in response.headers.get('content-type', '').lower():
             logger.warning(f"Source URL content type is not HTML: {article_url}")
             return None

        # Use html.parser for robustness
        soup = BeautifulSoup(response.content, 'html.parser')

        # Prioritize og:image, then twitter:image
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content') and og_image['content'].startswith('http'):
            img_url = og_image['content']
            logger.info(f"Found og:image: {img_url}")
            return img_url

        tw_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content') and tw_image['content'].startswith('http'):
             img_url = tw_image['content']
             logger.info(f"Found twitter:image: {img_url}")
             return img_url

        logger.warning(f"No suitable og:image or twitter:image meta tag found at: {article_url}")
        return None

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch source URL {article_url} for scraping: {e}")
        return None
    except Exception as e:
        # Catch potential BeautifulSoup errors or others
        logger.exception(f"Error scraping source image from {article_url}: {e}")
        return None

def search_images_serpapi(query, num_results=5):
    """Searches Google Images using SerpApi and returns top results' data."""
    if not SERPAPI_API_KEY:
        logger.error("SERPAPI_API_KEY not found in environment variables. Cannot perform image search.")
        return None # Cannot proceed without API key

    params = IMAGE_SEARCH_PARAMS.copy()
    params['q'] = query
    params['api_key'] = SERPAPI_API_KEY

    try:
        logger.debug(f"Sending SerpApi request with query: '{query}'")
        search = GoogleSearch(params)
        results = search.get_dict()

        # Handle API errors specifically
        if 'error' in results:
            logger.error(f"SerpApi error for query '{query}': {results['error']}")
            return None

        # Process successful results
        if 'images_results' in results and results['images_results']:
            # Extract relevant data, ensuring 'original' URL exists
            image_data = [
                {"url": img.get("original"), "title": img.get("title"), "source": img.get("source")}
                for img in results['images_results'][:num_results] if img.get("original")
            ]
            # Check if any valid images were extracted
            if not image_data:
                logger.warning(f"SerpApi returned results, but none had an 'original' URL for query: '{query}'")
                return [] # Return empty list if no usable URLs

            logger.info(f"SerpApi found {len(image_data)} image candidates for query: '{query}'")
            return image_data
        else:
            # Log cases where the API call succeeded but found no images
            logger.warning(f"No image results found via SerpApi for query: '{query}'")
            return [] # Return empty list for no results

    except Exception as e:
        # Catch broader exceptions during API interaction
        logger.exception(f"Exception occurred during SerpApi image search for query '{query}': {e}")
        return None # Return None on unexpected errors

def find_best_image(search_query, use_clip=ENABLE_CLIP_FILTERING):
    """
    Finds the best image URL for a given query.
    Attempts SerpApi search, then optionally filters with CLIP.
    """
    if not search_query:
        logger.error("Cannot find image: search_query is empty.")
        return None

    logger.info(f"Finding best image for query: '{search_query}' (CLIP Enabled: {use_clip and CLIP_AVAILABLE})")

    # Step 1: Search using SerpApi
    serpapi_results = search_images_serpapi(search_query)

    # Handle cases where SerpApi fails or returns no results
    if serpapi_results is None:
        logger.error(f"SerpApi search failed critically for query: '{search_query}'. Cannot find image.")
        return None
    if not serpapi_results: # Empty list returned
        logger.error(f"SerpApi returned no image results for query: '{search_query}'. Cannot find image.")
        return None

    # Step 2: Optionally filter with CLIP
    if use_clip and CLIP_AVAILABLE:
        best_image_url = filter_images_with_clip(serpapi_results, search_query)
    else:
        # Fallback if CLIP is disabled or unavailable
        if not CLIP_AVAILABLE and use_clip:
             logger.warning("CLIP filtering requested but model unavailable. Using first SerpApi result.")
        best_image_url = serpapi_results[0].get('url') # Get URL from the first result
        logger.info(f"Using first SerpApi result (CLIP disabled or unavailable): {best_image_url}")

    # Final check: Ensure we actually have a URL
    if best_image_url is None:
         logger.warning("Image selection process resulted in None. Falling back again to first SerpAPI result URL.")
         best_image_url = serpapi_results[0].get('url') if serpapi_results else None

    if best_image_url:
        logger.info(f"Selected image URL for '{search_query}': {best_image_url}")
    else:
        logger.error(f"Could not determine a best image URL for query: '{search_query}' after all steps.")

    return best_image_url

# --- Standalone Execution (for testing this script directly) ---
if __name__ == "__main__":
    test_query = "NVIDIA Blackwell GPU launch event"
    logger.info(f"\n--- Running Image Scraper Standalone Test ---")
    logger.info(f"Test Query: '{test_query}'")

    # Attempt to scrape a source URL (replace with a real URL for testing)
    test_source_url = "https://techcrunch.com/2024/03/18/nvidia-unveils-blackwell-ai-superchip-platform/" # Example URL
    logger.info(f"\nTesting source scraping ({test_source_url})...")
    scraped_url = scrape_source_for_image(test_source_url)
    if scraped_url: logger.info(f"Source Scraped Image: {scraped_url}")
    else: logger.info("Source scraping failed or no image found.")

    # Test WITH CLIP (if available)
    if ENABLE_CLIP_FILTERING:
        logger.info("\nTesting API search WITH CLIP filtering...")
        best_image_clip = find_best_image(test_query, use_clip=True)
        if best_image_clip:
            logger.info(f"Result (CLIP): {best_image_clip}")
            # Try downloading the selected image
            logger.info("Attempting to download CLIP selected image...")
            img_obj = download_image(best_image_clip)
            if img_obj: logger.info(f"Successfully downloaded image! Size: {img_obj.size}")
            else: logger.error("Failed to download the CLIP selected image.")
        else:
            logger.error("Test (CLIP) failed to find an image URL.")
    else:
         logger.info("\nCLIP filtering is disabled or unavailable, skipping specific CLIP test.")
         # Test without CLIP explicitly if CLIP is unavailable
         logger.info("\nTesting API search WITHOUT CLIP filtering...")
         best_image_no_clip = find_best_image(test_query, use_clip=False)
         if best_image_no_clip:
             logger.info(f"Result (No CLIP): {best_image_no_clip}")
             # Try downloading this image
             logger.info("Attempting to download No-CLIP selected image...")
             img_obj = download_image(best_image_no_clip)
             if img_obj: logger.info(f"Successfully downloaded image! Size: {img_obj.size}")
             else: logger.error("Failed to download the No-CLIP selected image.")
         else:
             logger.error("Test (No CLIP) failed to find an image URL.")


    logger.info("--- Image Scraper Standalone Test Complete ---\n")
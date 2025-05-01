# src/scrapers/image_scraper.py

import os
import requests
import logging
from serpapi import GoogleSearch
from dotenv import load_dotenv
from PIL import Image
import io
from bs4 import BeautifulSoup

# --- CLIP Integration ---
try:
    from sentence_transformers import SentenceTransformer
    # Load a pre-trained CLIP model
    # Common choices: 'clip-ViT-B-32', 'clip-ViT-L-14' (larger, potentially better)
    CLIP_MODEL_NAME = 'clip-ViT-B-32'
    clip_model = SentenceTransformer(CLIP_MODEL_NAME)
    CLIP_AVAILABLE = True
    logging.info(f"Successfully loaded CLIP model: {CLIP_MODEL_NAME}")
except ImportError:
    logging.warning("sentence-transformers library not found. CLIP filtering will be disabled.")
    logging.warning("Install it with: pip install sentence-transformers")
    clip_model = None
    CLIP_AVAILABLE = False
except Exception as e:
    logging.error(f"Error loading CLIP model ({CLIP_MODEL_NAME}): {e}. CLIP filtering disabled.")
    clip_model = None
    CLIP_AVAILABLE = False
# --- End CLIP Integration ---


# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')

# --- Configuration ---
IMAGE_SEARCH_PARAMS = {
    "engine": "google_images",
    "ijn": "0",
    "safe": "active",
    "tbs": "isz:l,itp:photo,iar:w", # Size:Large, Color:Color, Type:Photo
}

# Enable CLIP filtering if the model loaded successfully
ENABLE_CLIP_FILTERING = CLIP_AVAILABLE

# Timeout for downloading images (in seconds)
IMAGE_DOWNLOAD_TIMEOUT = 10

# Minimum acceptable CLIP score (adjust based on testing)
MIN_CLIP_SCORE = 0.25 # Example threshold

# --- Setup Logging ---
# (Keep the logging setup from the previous version)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Setup Logging ---

def download_image(url):
    """Downloads an image from a URL and returns a PIL Image object."""
    try:
        headers = {'User-Agent': 'DacoolaImageScraper/1.0'} # Be polite
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=headers, stream=True)
        response.raise_for_status() # Raise an exception for bad status codes

        # Check content type if possible
        content_type = response.headers.get('content-type')
        if content_type and not content_type.startswith('image/'):
            logger.warning(f"URL {url} did not return an image content-type ({content_type}). Skipping.")
            return None

        # Read image data into memory
        image_data = io.BytesIO(response.content)
        img = Image.open(image_data)
        # Convert to RGB to ensure consistency for CLIP
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None
    except UnidentifiedImageError:
         logger.warning(f"Could not identify image file from {url}. Invalid format?")
         return None
    except Exception as e:
        logger.warning(f"Error processing image {url}: {e}")
        return None

def filter_images_with_clip(images, text_prompt):
    """Filters/ranks images using CLIP similarity."""
    if not images or not clip_model:
        logger.warning("CLIP model not available or no images to filter.")
        return images[0]['url'] if images else None # Fallback

    logger.info(f"CLIP filtering {len(images)} images against prompt: '{text_prompt}'")

    image_objects = []
    original_urls = []

    # Download and prepare images
    for img_data in images:
        url = img_data.get('url')
        if url:
            pil_image = download_image(url)
            if pil_image:
                image_objects.append(pil_image)
                original_urls.append(url)
            else:
                 logger.debug(f"Skipping image {url} due to download/processing issue.")

    if not image_objects:
        logger.warning("No images could be successfully downloaded/processed for CLIP analysis.")
        return images[0]['url'] if images else None # Fallback

    try:
        # Encode images and text
        logger.debug(f"Encoding {len(image_objects)} images and 1 text prompt with CLIP...")
        image_embeddings = clip_model.encode(image_objects, batch_size=8, convert_to_tensor=True, show_progress_bar=False) # Batch processing
        text_embedding = clip_model.encode([text_prompt], convert_to_tensor=True, show_progress_bar=False)

        # Calculate cosine similarities
        # Use util.cos_sim from sentence-transformers for efficiency
        from sentence_transformers.util import cos_sim
        similarities = cos_sim(text_embedding, image_embeddings)[0] # Get similarities for the single text prompt

        # Create list of (score, url) pairs
        scored_images = []
        for i, score_tensor in enumerate(similarities):
            score = score_tensor.item() # Convert tensor to float
            url = original_urls[i]
            logger.debug(f"Image: {url}, CLIP Score: {score:.4f}")
            if score >= MIN_CLIP_SCORE:
                 scored_images.append({'score': score, 'url': url})
            else:
                 logger.debug(f"Image {url} rejected due to low score ({score:.4f} < {MIN_CLIP_SCORE})")

        if not scored_images:
            logger.warning(f"No images met the minimum CLIP score ({MIN_CLIP_SCORE}). Falling back to highest scoring raw image.")
            # Fallback: find highest score even if below threshold
            if len(similarities) > 0:
                 max_score_idx = similarities.argmax().item()
                 fallback_url = original_urls[max_score_idx]
                 logger.info(f"Fallback: Using image {fallback_url} with score {similarities[max_score_idx].item():.4f}")
                 return fallback_url
            else:
                 logger.error("Critical CLIP error: No similarities calculated.")
                 return images[0]['url'] if images else None # Final fallback


        # Sort by score (highest first)
        scored_images.sort(key=lambda x: x['score'], reverse=True)

        best_image_url = scored_images[0]['url']
        logger.info(f"CLIP selected best image: {best_image_url} with score {scored_images[0]['score']:.4f}")
        return best_image_url

    except Exception as e:
        logger.exception(f"Exception during CLIP encoding/similarity calculation: {e}")
        # Fallback to the first successfully downloaded image URL if CLIP process fails
        return original_urls[0] if original_urls else (images[0]['url'] if images else None)


def scrape_source_for_image(article_url):
    """Tries to scrape og:image or twitter:image from the source URL."""
    if not article_url:
        return None
    logger.info(f"Attempting to scrape image from source: {article_url}")
    try:
        headers = {'User-Agent': 'DacoolaImageScraper/1.0 (+http://your-website.com)'}
        response = requests.get(article_url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()

        # Check content type to avoid parsing non-html
        if 'html' not in response.headers.get('content-type', '').lower():
             logger.warning(f"Source URL {article_url} is not HTML content.")
             return None

        soup = BeautifulSoup(response.content, 'html.parser')

        # Prioritize og:image
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            logger.info(f"Found og:image: {img_url}")
            # Optional: Add basic validation (e.g., starts with http)
            if img_url.startswith('http'): return img_url

        # Fallback to twitter:image
        tw_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
             img_url = tw_image['content']
             logger.info(f"Found twitter:image: {img_url}")
             if img_url.startswith('http'): return img_url

        # Add more fallbacks if needed (e.g., largest image on page)

        logger.warning(f"No suitable meta image tag found at {article_url}")
        return None

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch source URL {article_url} for scraping: {e}")
        return None
    except Exception as e:
        logger.exception(f"Error scraping source image from {article_url}: {e}")
        return None


# --- SerpApi Search Function (keep from previous version) ---
def search_images_serpapi(query, num_results=5):
    """Searches Google Images using SerpApi and returns top results."""
    if not SERPAPI_API_KEY:
        logger.error("SERPAPI_API_KEY not found in environment variables.")
        return None

    params = IMAGE_SEARCH_PARAMS.copy()
    params['q'] = query
    params['api_key'] = SERPAPI_API_KEY

    try:
        logger.debug(f"Sending SerpApi request with params: {params}")
        search = GoogleSearch(params)
        results = search.get_dict()

        if 'error' in results:
            logger.error(f"SerpApi error for query '{query}': {results['error']}")
            return None

        if 'images_results' in results and results['images_results']:
            image_data = [
                {"url": img.get("original"), "title": img.get("title"), "source": img.get("source")}
                for img in results['images_results'][:num_results] if img.get("original")
            ]
            logger.info(f"SerpApi found {len(image_data)} relevant images for query: '{query}'")
            return image_data
        else:
            logger.warning(f"No image results found via SerpApi for query: '{query}'")
            return []

    except Exception as e:
        logger.exception(f"Exception occurred during SerpApi image search for query '{query}': {e}")
        return None

# --- Main Finder Function (updated to use ENABLE_CLIP_FILTERING) ---
def find_best_image(search_query, use_clip=ENABLE_CLIP_FILTERING):
    """Finds the best image: Searches SerpApi, optionally filters with CLIP."""
    logger.info(f"Finding best image for query: '{search_query}' (CLIP Enabled: {use_clip})")

    serpapi_results = search_images_serpapi(search_query)

    if not serpapi_results:
        logger.error(f"Failed to get any image results from SerpApi for query: '{search_query}'")
        return None

    if use_clip and CLIP_AVAILABLE:
        best_image_url = filter_images_with_clip(serpapi_results, search_query)
    else:
        if not CLIP_AVAILABLE and use_clip:
             logger.warning("CLIP filtering requested but model unavailable. Falling back.")
        best_image_url = serpapi_results[0]['url']
        logger.info(f"Using first SerpApi result (CLIP disabled or unavailable): {best_image_url}")

    # Final check if somehow we ended up with None
    if best_image_url is None and serpapi_results:
         logger.warning("Best image selection resulted in None, falling back to first SerpAPI result.")
         best_image_url = serpapi_results[0].get('url')

    return best_image_url


# --- Example Usage (keep from previous version) ---
if __name__ == "__main__":
    from PIL import UnidentifiedImageError # Need this for the example test

    test_query = "AI generating realistic human faces controversy"
    logger.info(f"\n--- Running Image Scraper Test ---")
    logger.info(f"Test Query: '{test_query}'")

    # Test WITH CLIP (if available)
    if ENABLE_CLIP_FILTERING:
        logger.info("\nTesting WITH CLIP filtering...")
        best_image_clip = find_best_image(test_query, use_clip=True)
        if best_image_clip:
            logger.info(f"Result (CLIP): {best_image_clip}")
        else:
            logger.error("Test (CLIP) failed to find an image.")
    else:
         logger.info("\nCLIP filtering is disabled or unavailable, skipping CLIP test.")

    # Test without CLIP
    # logger.info("\nTesting WITHOUT CLIP filtering...")
    # best_image_no_clip = find_best_image(test_query, use_clip=False)
    # if best_image_no_clip:
    #     logger.info(f"Result (No CLIP): {best_image_no_clip}")
    # else:
    #     logger.error("Test (No CLIP) failed to find an image.")

    logger.info("--- Image Scraper Test Complete ---\n")
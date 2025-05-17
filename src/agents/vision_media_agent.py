# src/agents/vision_media_agent.py

import os
import sys
import json
import logging
import requests 
import re
from PIL import Image, UnidentifiedImageError 
import io
from bs4 import BeautifulSoup

# --- SerpApi import for image search ---
try:
    from serpapi import GoogleSearch
except ImportError:
    GoogleSearch = None
    logging.warning("serpapi library not found. Google Image search via SerpApi will be disabled. pip install google-search-results")


# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logger.setLevel(logging.DEBUG)

# --- Configuration ---
DEEPSEEK_API_KEY_VLM = os.getenv('DEEPSEEK_API_KEY')
HAS_DEEPSEEK_VLM_CONFIG = False 

IMAGE_DOWNLOAD_TIMEOUT = 20 
MIN_IMAGE_WIDTH = 300
MIN_IMAGE_HEIGHT = 200
MAX_IMAGE_FILESIZE_BYTES = 2 * 1024 * 1024 

CLIP_MODEL_NAME = 'clip-ViT-B-32'
CLIP_AVAILABLE = False # Initial status
clip_model = None 
try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim
    # We will attempt to load clip_model on first use in filter_images_with_clip_vlm
    CLIP_AVAILABLE = True # Mark as potentially available
    logger.info(f"SentenceTransformer library found, CLIP can be loaded on demand.")
except ImportError:
    logging.warning("sentence-transformers library not found. CLIP filtering will be disabled.")
    CLIP_AVAILABLE = False # Explicitly set to false
except Exception as e:
    logging.error(f"Error importing SentenceTransformer for CLIP: {e}. CLIP filtering disabled.")
    CLIP_AVAILABLE = False # Explicitly set to false


ENABLE_CLIP_FILTERING_CONFIG = True 
MIN_CLIP_SCORE = 0.23

SERPAPI_API_KEY_IMG = os.getenv('SERPAPI_API_KEY')
WEBSITE_URL_FOR_AGENT_IMG = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')
IMAGE_SEARCH_PARAMS_IMG = {
    "engine": "google_images", "ijn": "0", "safe": "active",
    "tbs": "isz:l,itp:photo,iar:w", 
}


def download_image_as_base64_vlm(image_url): 
    if not image_url or not image_url.startswith('http'): return None
    try:
        response = requests.get(image_url, timeout=IMAGE_DOWNLOAD_TIMEOUT, stream=True)
        response.raise_for_status()
        image_bytes = response.content
        import base64
        return base64.b64encode(image_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"Error processing image {image_url} for base64: {e}")
        return None

VLM_ANALYSIS_PROMPT_TEMPLATE_DS = """
Analyze the image based on its URL and the provided context.
Image URL: {image_url_for_analysis}
Contextual Information: "{context_description}"

Provide a JSON response:
{{
  "image_description": "Factual description of image.",
  "relevance_score": float (0.0-1.0, relevance to context),
  "alt_text_suggestion": "SEO-friendly alt text.",
  "suitability_notes": "Suitability notes."
}}"""

def analyze_image_with_deepseek_vlm(image_url_for_vlm, context_description):
    if not HAS_DEEPSEEK_VLM_CONFIG or not DEEPSEEK_API_KEY_VLM:
        return {"image_description": "Analysis N/A", "relevance_score": 0.5, "alt_text_suggestion": context_description[:100], "suitability_notes": "VLM not configured."}
    logger.error("analyze_image_with_deepseek_vlm is a placeholder and not implemented without actual API details.")
    return {"image_description": "DeepSeek VLM Placeholder", "relevance_score": 0.5, "alt_text_suggestion": context_description[:100], "suitability_notes": "DeepSeek VLM not implemented."}


def download_image_pil(url, attempt=1): 
    if not url or not url.startswith('http'): return None
    try:
        headers = {'User-Agent': f'DacoolaImageScraper/1.1 (+{WEBSITE_URL_FOR_AGENT_IMG})'}
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=headers, stream=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'): return None
        image_data = io.BytesIO(response.content)
        if image_data.getbuffer().nbytes == 0: return None
        img = Image.open(image_data)
        if img.width < MIN_IMAGE_WIDTH or img.height < MIN_IMAGE_HEIGHT: return None
        if img.mode != 'RGB': img = img.convert('RGB')
        return img
    except UnidentifiedImageError: 
         logger.warning(f"Could not identify image file from: {url}")
         return None
    except Exception: return None


def filter_images_with_clip_vlm(image_results, text_prompt): 
    global clip_model, CLIP_AVAILABLE # Declare upfront that we might modify global CLIP_AVAILABLE

    if not ENABLE_CLIP_FILTERING_CONFIG or not CLIP_AVAILABLE: # Check initial availability
        logger.info("CLIP filtering skipped: Disabled by config or SentenceTransformer library not available.")
        for img_data in image_results: # Fallback
            if img_data.get('url') and download_image_pil(img_data.get('url')): return img_data.get('url')
        return None

    if not clip_model: 
        try:
            logger.info(f"Loading CLIP model for filtering: {CLIP_MODEL_NAME}")
            clip_model = SentenceTransformer(CLIP_MODEL_NAME) # Attempt to load
        except Exception as e:
            logger.error(f"Failed to load CLIP model ({CLIP_MODEL_NAME}) on demand: {e}. Disabling CLIP for this run.")
            CLIP_AVAILABLE = False # Modify global if loading fails
            for img_data in image_results: # Fallback
                if img_data.get('url') and download_image_pil(img_data.get('url')): return img_data.get('url')
            return None
    
    # If model loaded successfully (or was already loaded), proceed
    logger.info(f"CLIP filtering {len(image_results)} candidates for prompt: '{text_prompt}'")
    image_objects, valid_original_urls = [], []
    for img_data in image_results:
        url = img_data.get('url')
        if url:
            pil_image = download_image_pil(url)
            if pil_image: image_objects.append(pil_image); valid_original_urls.append(url)
    
    if not image_objects: 
        logger.warning("No valid images to process with CLIP after download step.")
        return image_results[0].get('url') if image_results else None # Fallback to first original if any

    try:
        image_embeddings = clip_model.encode(image_objects, batch_size=8, convert_to_tensor=True, show_progress_bar=False)
        text_embedding = clip_model.encode([text_prompt], convert_to_tensor=True, show_progress_bar=False)
        similarities = cos_sim(text_embedding, image_embeddings)[0]
        scored_images = [{'score': score.item(), 'url': valid_original_urls[i]} for i, score in enumerate(similarities)]
        scored_images.sort(key=lambda x: x['score'], reverse=True)
        best_above_threshold = next((item for item in scored_images if item['score'] >= MIN_CLIP_SCORE), None)
        
        if best_above_threshold: 
            logger.info(f"CLIP selected: {best_above_threshold['url']} (Score: {best_above_threshold['score']:.2f})")
            return best_above_threshold['url']
        elif scored_images: 
            logger.warning(f"No image met CLIP threshold {MIN_CLIP_SCORE}. Best score: {scored_images[0]['score']:.2f} for {scored_images[0]['url']}")
            return scored_images[0]['url'] # Return highest score even if below threshold
        
        logger.warning("CLIP: No scored images available.")
        return image_results[0].get('url') if image_results else None
    except Exception as e:
        logger.exception(f"Exception during CLIP processing: {e}")
        return valid_original_urls[0] if valid_original_urls else (image_results[0].get('url') if image_results else None)


def scrape_source_for_image_vlm(article_url): 
    if not article_url or not article_url.startswith('http'): return None
    logger.info(f"Attempting to scrape meta image tag from source: {article_url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; DacoolaImageScraper/1.1)'}
        response = requests.get(article_url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        meta_selectors = [{'property': 'og:image'}, {'name': 'twitter:image'}]
        for selector in meta_selectors:
            tag = soup.find('meta', attrs=selector)
            if tag and tag.get('content') and tag['content'].startswith('http'): return tag['content']
        return None
    except Exception: return None

def search_images_serpapi_vlm(query, num_results=7): 
    if not SERPAPI_API_KEY_IMG or not GoogleSearch: 
        logger.error("SerpApi key missing or google-search-results library not installed.")
        return None
    params = IMAGE_SEARCH_PARAMS_IMG.copy(); params['q'] = query; params['api_key'] = SERPAPI_API_KEY_IMG
    try:
        search = GoogleSearch(params); results = search.get_dict() 
        if 'error' in results: logger.error(f"SerpApi error: {results['error']}"); return None
        if results.get('images_results'):
            return [{"url": img.get("original"), "title": img.get("title")} for img in results['images_results'][:num_results] if img.get("original")]
        return []
    except Exception as e: logger.exception(f"SerpApi search failed: {e}"); return None

def find_best_image_vlm(search_query, use_clip=ENABLE_CLIP_FILTERING_CONFIG, article_url_for_scrape=None): 
    if not search_query: return None
    logger.info(f"Finding best image for query: '{search_query}' (CLIP: {use_clip and CLIP_AVAILABLE})")
    if article_url_for_scrape:
        scraped_image_url = scrape_source_for_image_vlm(article_url_for_scrape)
        if scraped_image_url and download_image_pil(scraped_image_url):
            logger.info(f"Using valid image directly scraped from source: {scraped_image_url}")
            return scraped_image_url
    
    serpapi_results = search_images_serpapi_vlm(search_query)
    if not serpapi_results: 
        logger.warning(f"No SerpApi results for query '{search_query}'.")
        return None
    
    if use_clip and CLIP_AVAILABLE: # Check CLIP_AVAILABLE again as it might have been set to False
        return filter_images_with_clip_vlm(serpapi_results, search_query)
    else: 
        for res in serpapi_results:
            if res.get('url') and download_image_pil(res.get('url')): 
                logger.info(f"Using first valid SerpApi result (CLIP disabled/failed): {res.get('url')}")
                return res.get('url')
    logger.warning(f"Could not find any valid image for '{search_query}' from SerpApi results.")
    return None


def run_vision_media_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Vision & Media Agent for Article ID: {article_id} (VLM analysis may be limited) ---")

    article_pipeline_data['media_candidates_for_body'] = []
    article_pipeline_data['final_featured_image_alt_text'] = article_pipeline_data.get('initial_title_from_web', 'Article image')

    featured_image_search_query = article_pipeline_data.get('initial_title_from_web', 'technology news')
    source_url_for_scrape = article_pipeline_data.get('original_source_url')
    
    # Check CLIP_AVAILABLE before passing use_clip=True
    actual_use_clip = ENABLE_CLIP_FILTERING_CONFIG and CLIP_AVAILABLE

    best_url_featured = find_best_image_vlm(
        featured_image_search_query, 
        use_clip=actual_use_clip, 
        article_url_for_scrape=source_url_for_scrape
    )

    if best_url_featured:
        article_pipeline_data['selected_image_url'] = best_url_featured
        article_pipeline_data['final_featured_image_alt_text'] = article_pipeline_data.get('initial_title_from_web', 'Featured article image')
        logger.info(f"Selected featured image for {article_id}: {best_url_featured}")
    elif not article_pipeline_data.get('selected_image_url'): 
        article_pipeline_data['selected_image_url'] = "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"
        logger.warning(f"Could not find a suitable featured image for {article_id}. Using placeholder.")

    markdown_body = article_pipeline_data.get('seo_agent_results', {}).get('generated_article_body_md', '')
    if not markdown_body:
        logger.info(f"No markdown body found for {article_id}, skipping in-article image selection.")
        return article_pipeline_data

    image_placeholders = re.findall(r'<!-- IMAGE_PLACEHOLDER:\s*(.*?)\s*-->', markdown_body)
    if not image_placeholders:
        logger.info(f"No image placeholders found in markdown for {article_id}.")
        return article_pipeline_data
    
    logger.info(f"Found {len(image_placeholders)} image placeholders. Attempting to find images via search...")
    
    for i, placeholder_desc in enumerate(image_placeholders):
        logger.info(f"Finding image for placeholder: '{placeholder_desc[:60]}...'")
        found_image_for_placeholder = find_best_image_vlm(
            placeholder_desc, 
            use_clip=actual_use_clip, # Use actual_use_clip here too
            article_url_for_scrape=None 
        ) 
        if found_image_for_placeholder and found_image_for_placeholder != article_pipeline_data.get('selected_image_url'):
            alt_text_for_placeholder = placeholder_desc[:120] 
            article_pipeline_data['media_candidates_for_body'].append({
                'placeholder_description_original': placeholder_desc, 
                'best_image_url': found_image_for_placeholder,
                'alt_text': alt_text_for_placeholder,
                'relevance_score': 0.5, 
                'vlm_image_description': "Image selected based on search query match."
            })
            logger.info(f"Selected image for placeholder '{placeholder_desc[:30]}...': {found_image_for_placeholder}")
        else:
            logger.warning(f"Could not find a suitable image for placeholder '{placeholder_desc[:30]}...'")
            
    logger.info(f"--- Vision & Media Agent finished for Article ID: {article_id} ---")
    return article_pipeline_data

if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    logger.info("--- Starting Vision & Media Agent Standalone Test (DeepSeek VLM - Conceptual) ---")
    
    if not SERPAPI_API_KEY_IMG :
        logger.warning("SERPAPI_API_KEY not set. Image search part of the test will be limited/fail.")
    if not GoogleSearch:
        logger.warning("google-search-results (SerpApi client) not installed. Test will be limited.")
    
    sample_article_data_for_vision = {
        'id': 'test_vision_ds_001',
        'initial_title_from_web': "Exploring Mars with AI Rovers",
        'processed_summary': "New AI algorithms are enabling Mars rovers to make autonomous decisions...",
        'original_source_url': 'https://www.nasa.gov/fake-mars-rover-news', 
        'selected_image_url': None, 
        'seo_agent_results': {
            'generated_article_body_md': """
            ## AI on Mars
            <!-- IMAGE_PLACEHOLDER: A Mars rover exploring a crater -->
            ### Autonomous Navigation
            <!-- IMAGE_PLACEHOLDER: Diagram of AI pathfinding algorithm -->
            """
        }
    }
    
    original_has_ds_vlm = HAS_DEEPSEEK_VLM_CONFIG
    sys.modules[__name__].HAS_DEEPSEEK_VLM_CONFIG = False 
    logger.info(f"Note: Running with HAS_DEEPSEEK_VLM_CONFIG = {HAS_DEEPSEEK_VLM_CONFIG} (VLM calls will be placeholders)")

    result_data = run_vision_media_agent(sample_article_data_for_vision.copy())
    
    sys.modules[__name__].HAS_DEEPSEEK_VLM_CONFIG = original_has_ds_vlm 

    logger.info("\n--- Vision & Media Test Results (DeepSeek VLM Conceptual) ---")
    logger.info(f"Selected Featured Image URL: {result_data.get('selected_image_url')}")
    logger.info(f"Featured Image Alt Text: {result_data.get('final_featured_image_alt_text')}")
    logger.info("\nMedia Candidates for Body:")
    if result_data.get('media_candidates_for_body'):
        for candidate in result_data.get('media_candidates_for_body'):
            logger.info(f"  Placeholder: '{candidate.get('placeholder_description_original')}', Image: {candidate.get('best_image_url')}, Alt: {candidate.get('alt_text')}")
    else: logger.info("  No media candidates for body.")
    logger.info("--- Vision & Media Agent Standalone Test Complete ---")
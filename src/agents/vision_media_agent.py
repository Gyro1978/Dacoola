# src/agents/vision_media_agent.py

import os
import sys
import json
import logging
import requests # For Ollama and image downloads
import re
from PIL import Image
import io
from bs4 import BeautifulSoup # <<< ADDED MISSING IMPORT

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
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
OLLAMA_API_GENERATE_URL = "http://localhost:11434/api/generate" 
OLLAMA_VLM_MODEL = "llava:latest" 

IMAGE_DOWNLOAD_TIMEOUT = 20 
MIN_IMAGE_WIDTH = 300
MIN_IMAGE_HEIGHT = 200
MAX_IMAGE_FILESIZE_BYTES = 2 * 1024 * 1024 

# --- Helper: Download Image and Convert to Base64 ---
def download_image_as_base64(image_url):
    if not image_url or not image_url.startswith('http'):
        logger.debug(f"Invalid image URL for download: {image_url}")
        return None
    try:
        logger.debug(f"Downloading image: {image_url}")
        response = requests.get(image_url, timeout=IMAGE_DOWNLOAD_TIMEOUT, stream=True)
        response.raise_for_status()

        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            logger.warning(f"URL content-type not image ({content_type}): {image_url}")
            return None

        image_bytes = response.content
        if not image_bytes:
            logger.warning(f"Downloaded image is empty: {image_url}")
            return None
        
        if len(image_bytes) > MAX_IMAGE_FILESIZE_BYTES:
            logger.warning(f"Image {image_url} too large ({len(image_bytes)} bytes) for VLM. Max: {MAX_IMAGE_FILESIZE_BYTES}.")
            return None

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.width < MIN_IMAGE_WIDTH or img.height < MIN_IMAGE_HEIGHT:
                logger.warning(f"Image {image_url} too small ({img.width}x{img.height}). Min: {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}.")
                return None
        except Exception as pil_e:
            logger.warning(f"Pillow validation failed for {image_url}: {pil_e}")
            return None 

        import base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        logger.debug(f"Successfully downloaded and base64 encoded image: {image_url}")
        return base64_image
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to download image {image_url}: {e}")
    except Exception as e:
        logger.error(f"Error processing image {image_url} for base64: {e}")
    return None

# --- Helper: Analyze Image with VLM (LLaVA via Ollama) ---
VLM_ANALYSIS_PROMPT_TEMPLATE = """
You are an expert image analyst. Analyze the provided image.
Contextual Information for relevance assessment: "{context_description}"

Based on the image and the contextual information, provide a JSON response with the following keys:
- "image_description": A concise, factual description of the image content.
- "relevance_score": A float score from 0.0 to 1.0 indicating how relevant the image is to the `Contextual Information`. 0.0 is not relevant, 1.0 is highly relevant.
- "alt_text_suggestion": A brief, SEO-friendly alt text for this image, under 125 characters.
- "suitability_notes": Brief notes on why this image is or isn't suitable for the given context.

Example JSON response:
{{
  "image_description": "A detailed graph showing performance benchmarks of AI Model X against competitors A and B, with Model X outperforming both across multiple metrics.",
  "relevance_score": 0.9,
  "alt_text_suggestion": "Graph comparing AI Model X performance benchmarks.",
  "suitability_notes": "Highly relevant as it visually supports claims of Model X's superior performance."
}}

Analyze the image now.
"""

def analyze_image_with_vlm(base64_image_data, context_description):
    if not base64_image_data:
        return None

    prompt_for_vlm = VLM_ANALYSIS_PROMPT_TEMPLATE.format(context_description=context_description)
    
    payload = {
        "model": OLLAMA_VLM_MODEL,
        "prompt": prompt_for_vlm,
        "images": [base64_image_data], 
        "format": "json", 
        "stream": False
    }
    try:
        logger.debug(f"Sending image analysis request to Ollama VLM (model: {OLLAMA_VLM_MODEL}) for context: '{context_description[:50]}...'")
        response = requests.post(OLLAMA_API_GENERATE_URL, json=payload, timeout=90) 
        response.raise_for_status()
        
        response_json = response.json()
        vlm_json_response_str = response_json.get("response")
        if not vlm_json_response_str:
            logger.error(f"Ollama VLM response missing 'response' field: {response_json}")
            return None
            
        try:
            analysis = json.loads(vlm_json_response_str)
            required_keys = ["image_description", "relevance_score", "alt_text_suggestion", "suitability_notes"]
            if all(key in analysis for key in required_keys) and isinstance(analysis["relevance_score"], (int, float)):
                logger.info(f"VLM analysis successful. Relevance: {analysis['relevance_score']:.2f}. Alt: '{analysis['alt_text_suggestion']}'")
                return analysis
            else:
                logger.error(f"VLM returned JSON missing required keys or invalid score type: {analysis}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from VLM response string: '{vlm_json_response_str}'. Error: {e}")
            match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', vlm_json_response_str, re.DOTALL)
            if match:
                try:
                    analysis = json.loads(match.group(1))
                    if all(key in analysis for key in required_keys) and isinstance(analysis["relevance_score"], (int, float)):
                        logger.info(f"VLM fallback JSON extraction successful. Relevance: {analysis['relevance_score']:.2f}")
                        return analysis
                except Exception as fallback_e:
                     logger.error(f"VLM fallback JSON extraction also failed: {fallback_e}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request for VLM image analysis failed: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in analyze_image_with_vlm: {e}")
    return None


def scrape_image_urls_from_source_page(page_url):
    if not page_url or not page_url.startswith('http'):
        return []
    
    found_image_urls = set()
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; DacoolaImageScraper/1.0)'}
        response = requests.get(page_url, headers=headers, timeout=IMAGE_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser') # Corrected: Uses imported BeautifulSoup
        
        for img_tag in soup.find_all('img'):
            src = img_tag.get('src')
            if src and src.startswith('http') and not src.endswith(('.gif', '.svg', '.ico')): 
                if 'pixel' in src or 'sprite' in src or 'icon' in src.lower() or 'avatar' in src.lower():
                    if not (img_tag.get('width') and int(str(img_tag.get('width')).replace('px','')) > 100): 
                        continue
                found_image_urls.add(src)
            
            srcset = img_tag.get('srcset')
            if srcset:
                parts = srcset.split(',')
                for part in parts:
                    url_part = part.strip().split(' ')[0]
                    if url_part.startswith('http') and not url_part.endswith(('.gif', '.svg', '.ico')):
                        found_image_urls.add(url_part)
                        break 

        logger.info(f"Scraped {len(found_image_urls)} potential image URLs from {page_url}")
        return list(found_image_urls)
    except Exception as e:
        logger.error(f"Error scraping image URLs from {page_url}: {e}")
        return []


def run_vision_media_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Vision & Media Agent for Article ID: {article_id} ---")

    article_pipeline_data['media_candidates_for_body'] = []
    article_pipeline_data['final_featured_image_alt_text'] = article_pipeline_data.get('initial_title_from_web', 'Article image')

    source_url = article_pipeline_data.get('original_source_url')
    all_scraped_image_urls = []
    if source_url:
        all_scraped_image_urls = scrape_image_urls_from_source_page(source_url)
    
    if not all_scraped_image_urls:
        logger.warning(f"No image URLs found from scraping or initially for {article_id}. Vision agent cannot select images.")
        if not article_pipeline_data.get('selected_image_url'):
             article_pipeline_data['selected_image_url'] = "https://via.placeholder.com/1200x675.png?text=Image+Unavailable"
        return article_pipeline_data

    featured_image_context = f"Article Title: {article_pipeline_data.get('initial_title_from_web', '')}. Summary: {article_pipeline_data.get('processed_summary', '')}"
    best_featured_image_info = {'url': None, 'score': -1.0, 'alt': article_pipeline_data.get('initial_title_from_web','Featured Image')}

    logger.info(f"Analyzing {len(all_scraped_image_urls)} candidates for FEATURED image for {article_id}...")
    for img_url_candidate in all_scraped_image_urls[:10]: 
        base64_img = download_image_as_base64(img_url_candidate)
        if base64_img:
            vlm_analysis = analyze_image_with_vlm(base64_img, featured_image_context)
            if vlm_analysis and vlm_analysis.get('relevance_score', 0) > best_featured_image_info['score']:
                best_featured_image_info['url'] = img_url_candidate
                best_featured_image_info['score'] = vlm_analysis['relevance_score']
                best_featured_image_info['alt'] = vlm_analysis.get('alt_text_suggestion', best_featured_image_info['alt'])
                logger.debug(f"New best featured candidate: {img_url_candidate}, Score: {vlm_analysis['relevance_score']:.2f}")

    if best_featured_image_info['url'] and best_featured_image_info['score'] > 0.3: 
        article_pipeline_data['selected_image_url'] = best_featured_image_info['url']
        article_pipeline_data['final_featured_image_alt_text'] = best_featured_image_info['alt']
        logger.info(f"Selected featured image for {article_id}: {best_featured_image_info['url']} (Score: {best_featured_image_info['score']:.2f})")
    elif not article_pipeline_data.get('selected_image_url'): 
        article_pipeline_data['selected_image_url'] = "https://via.placeholder.com/1200x675.png?text=Image+Not+Found"
        logger.warning(f"Could not find a suitable featured image for {article_id} via VLM. Using placeholder.")
    else:
        logger.info(f"Retaining pre-existing selected_image_url for {article_id} as VLM did not find a better one.")

    markdown_body = article_pipeline_data.get('seo_agent_results', {}).get('generated_article_body_md', '')
    if not markdown_body:
        logger.info(f"No markdown body found for {article_id}, skipping in-article image analysis.")
        return article_pipeline_data

    image_placeholders = re.findall(r'<!-- IMAGE_PLACEHOLDER:\s*(.*?)\s*-->', markdown_body)
    if not image_placeholders:
        logger.info(f"No image placeholders found in markdown for {article_id}.")
        return article_pipeline_data

    logger.info(f"Found {len(image_placeholders)} image placeholders in markdown for {article_id}. Analyzing candidates...")
    
    for i, placeholder_desc in enumerate(image_placeholders):
        placeholder_id = f"placeholder_{i+1}" 
        logger.info(f"Finding image for placeholder '{placeholder_id}': '{placeholder_desc[:60]}...'")
        
        best_candidate_for_placeholder = {'url': None, 'score': -1.0, 'alt': placeholder_desc[:100]} 
        
        for img_url_candidate in all_scraped_image_urls[:15]: 
            if img_url_candidate == article_pipeline_data.get('selected_image_url'): 
                continue

            base64_img = download_image_as_base64(img_url_candidate)
            if base64_img:
                vlm_analysis = analyze_image_with_vlm(base64_img, placeholder_desc) 
                if vlm_analysis and vlm_analysis.get('relevance_score', 0) > best_candidate_for_placeholder['score']:
                    best_candidate_for_placeholder = {
                        'url': img_url_candidate,
                        'score': vlm_analysis['relevance_score'],
                        'alt': vlm_analysis.get('alt_text_suggestion', placeholder_desc[:100]),
                        'vlm_description': vlm_analysis.get('image_description')
                    }
                    logger.debug(f"New best candidate for '{placeholder_desc[:30]}...': {img_url_candidate}, Score: {vlm_analysis['relevance_score']:.2f}")

        if best_candidate_for_placeholder['url'] and best_candidate_for_placeholder['score'] > 0.25: 
            article_pipeline_data['media_candidates_for_body'].append({
                'placeholder_description_original': placeholder_desc, 
                'best_image_url': best_candidate_for_placeholder['url'],
                'alt_text': best_candidate_for_placeholder['alt'],
                'relevance_score': best_candidate_for_placeholder['score'],
                'vlm_image_description': best_candidate_for_placeholder.get('vlm_description')
            })
            logger.info(f"Selected image for placeholder '{placeholder_desc[:30]}...': {best_candidate_for_placeholder['url']}")
        else:
            logger.warning(f"Could not find a suitable image for placeholder '{placeholder_desc[:30]}...'")
            
    logger.info(f"--- Vision & Media Agent finished for Article ID: {article_id} ---")
    return article_pipeline_data

if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    logger.info("--- Starting Vision & Media Agent Standalone Test ---")
    
    sample_article_data_for_vision = {
        'id': 'test_vision_001',
        'initial_title_from_web': "NVIDIA's New AI Chip Architecture Explained",
        'processed_summary': "NVIDIA announced its next-generation 'Athena' AI chip architecture...",
        'original_source_url': 'https://blogs.nvidia.com/blog/sample-athena-announcement/', 
        'selected_image_url': None, 
        'seo_agent_results': {
            'generated_article_body_md': """
            ## Introduction to Athena Architecture
            <!-- IMAGE_PLACEHOLDER: A diagram of the Athena chip layout -->
            ### Performance Gains
            <!-- IMAGE_PLACEHOLDER: A bar graph comparing Athena to previous generation chip H100 -->
            """
        }
    }
    def mock_scrape_image_urls(url):
        logger.info(f"MOCK scraping image URLs for: {url}")
        return [
            "https://images.nvidia.com/blogs/images/athena-chip-diagram.jpg", 
            "https://images.nvidia.com/blogs/images/athena-vs-h100-benchmarks.png",
            "https://images.nvidia.com/blogs/images/nvidia-ceo-gtc-stage.jpg", 
        ]
    
    original_scraper_func = sys.modules[__name__].scrape_image_urls_from_source_page
    sys.modules[__name__].scrape_image_urls_from_source_page = mock_scrape_image_urls
    
    MOCK_IMAGE_ANALYSIS_DB = {
        "https://images.nvidia.com/blogs/images/athena-chip-diagram.jpg": {"desc": "Diagram of Athena chip", "score": 0.9, "alt": "Athena chip architecture diagram"},
        "https://images.nvidia.com/blogs/images/athena-vs-h100-benchmarks.png": {"desc": "Benchmark graph Athena vs H100", "score": 0.95, "alt": "Athena GPU performance benchmarks"},
        "https://images.nvidia.com/blogs/images/nvidia-ceo-gtc-stage.jpg": {"desc": "NVIDIA CEO on stage", "score": 0.7, "alt": "NVIDIA CEO presentation"},
    }

    def mock_download_b64(url):
        if url in MOCK_IMAGE_ANALYSIS_DB: return "dummy_base64_data_for_" + url.split('/')[-1]
        return None
    
    def mock_analyze_vlm(b64_data, context):
        mock_url_key = None
        if b64_data:
            try:
                filename_part = b64_data.replace("dummy_base64_data_for_", "")
                for url_key in MOCK_IMAGE_ANALYSIS_DB.keys():
                    if filename_part in url_key: mock_url_key = url_key; break
            except: pass

        if mock_url_key and mock_url_key in MOCK_IMAGE_ANALYSIS_DB:
            analysis = MOCK_IMAGE_ANALYSIS_DB[mock_url_key]
            context_lower = context.lower(); simulated_relevance = analysis["score"]
            if "diagram" in context_lower and "diagram" in analysis["desc"].lower(): simulated_relevance += 0.05
            if "benchmark" in context_lower and "benchmark" in analysis["desc"].lower(): simulated_relevance += 0.05
            return {
                "image_description": analysis["desc"], "relevance_score": min(1.0, simulated_relevance),
                "alt_text_suggestion": analysis["alt"], "suitability_notes": "Mock suitability."
            }
        return {"image_description": "Mock generic", "relevance_score": 0.2, "alt_text_suggestion": "Generic image", "suitability_notes": "Low relevance."}

    original_download_func = sys.modules[__name__].download_image_as_base64
    original_vlm_func = sys.modules[__name__].analyze_image_with_vlm
    sys.modules[__name__].download_image_as_base64 = mock_download_b64
    sys.modules[__name__].analyze_image_with_vlm = mock_analyze_vlm

    result_data = run_vision_media_agent(sample_article_data_for_vision.copy())

    sys.modules[__name__].scrape_image_urls_from_source_page = original_scraper_func
    sys.modules[__name__].download_image_as_base64 = original_download_func
    sys.modules[__name__].analyze_image_with_vlm = original_vlm_func

    logger.info("\n--- Vision & Media Test Results ---")
    logger.info(f"Selected Featured Image URL: {result_data.get('selected_image_url')}")
    logger.info(f"Featured Image Alt Text: {result_data.get('final_featured_image_alt_text')}")
    logger.info("\nMedia Candidates for Body:")
    if result_data.get('media_candidates_for_body'):
        for candidate in result_data.get('media_candidates_for_body'):
            logger.info(f"  Placeholder: '{candidate.get('placeholder_description_original')}', Image: {candidate.get('best_image_url')}, Alt: {candidate.get('alt_text')}")
    else: logger.info("  No media candidates for body.")
    logger.info("--- Vision & Media Agent Standalone Test Complete ---")
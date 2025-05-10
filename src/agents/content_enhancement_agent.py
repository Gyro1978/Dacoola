import os
import sys
import json
import logging
import requests
import re
import time
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import trafilatura
from PIL import Image
import io

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# Import existing image scraper functionality
try:
    from src.scrapers.image_scraper import (
        download_image, filter_images_with_clip,
        scrape_source_for_image, search_images_serpapi
    )
except ImportError:
    # Fallback to relative import if running from within the agents directory
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scrapers.image_scraper import (
        download_image, filter_images_with_clip,
        scrape_source_for_image, search_images_serpapi
    )

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# API Keys
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_VISION_URL = "https://api.openai.com/v1/chat/completions"
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', GOOGLE_API_KEY)  # Fallback to GOOGLE_API_KEY if not set

# Site Configuration
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')
YOUR_SITE_BASE_URL = os.getenv('YOUR_SITE_BASE_URL', '')

# --- Configuration ---
# AI Models
CONTENT_AGENT_MODEL = "deepseek-chat"  # Default model
VISION_MODEL = "gpt-4-vision-preview"  # For image analysis
CROSS_REF_MODEL = "gpt-4-turbo"  # For cross-referencing

# API Settings
MAX_TOKENS_RESPONSE = 4000
TEMPERATURE = 0.5
API_TIMEOUT_SECONDS = 180

# Image Settings
MAX_IMAGES_PER_ARTICLE = 5
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 250
IMAGE_QUALITY_THRESHOLD = 0.7
ALLOWED_IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'webp']

# Video Settings
MAX_VIDEOS_PER_ARTICLE = 2
MIN_VIDEO_DURATION_SECONDS = 30
MAX_VIDEO_DURATION_SECONDS = 900  # 15 minutes
VIDEO_RELEVANCE_THRESHOLD = 0.75

# Cross-Reference Settings
MAX_CROSS_REFERENCES = 5
MIN_CROSS_REF_CONFIDENCE = 0.8
CROSS_REF_MAX_AGE_DAYS = 30

# --- Helper Functions ---
def is_valid_url(url: str) -> bool:
    """Check if a URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed_uri = urlparse(url)
        domain = '{uri.netloc}'.format(uri=parsed_uri)
        # Remove www. if present
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except:
        return ""

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for filesystem."""
    # Replace unsafe characters with underscores
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    if len(filename) > 200:
        filename = filename[:197] + "..."
    return filename

def get_current_datetime_iso():
    """Get current datetime in ISO format with timezone."""
    return datetime.now(timezone.utc).isoformat()

# --- API Call Functions ---
def call_deepseek_api(system_prompt: str, user_prompt: str, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Call the Deepseek API with system and user prompts."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json"
    }

    payload = {
        "model": CONTENT_AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }

    try:
        logger.debug(f"Sending request to Deepseek API (model: {CONTENT_AGENT_MODEL})...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()

        usage = result.get('usage')
        if usage:
            logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                # Handle JSON or code block formatting
                if content_stripped.startswith("```json"):
                    content_stripped = content_stripped[7:-3].strip() if content_stripped.endswith("```") else content_stripped[7:].strip()
                elif content_stripped.startswith("```"):
                    content_stripped = content_stripped[3:-3].strip() if content_stripped.endswith("```") else content_stripped[3:].strip()

                return content_stripped

            logger.error("API response choice message content is empty.")
            return None
        else:
            logger.error(f"API response missing 'choices' or 'choices' is empty: {result}")
            return None

    except requests.exceptions.Timeout:
        logger.error(f"Timeout calling Deepseek API after {API_TIMEOUT_SECONDS} seconds")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling Deepseek API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Deepseek API: {e}")
        return None

def call_openai_api(system_prompt: str, user_prompt: str, model="gpt-4-turbo", max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    """Call the OpenAI API with system and user prompts."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Accept": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    try:
        logger.debug(f"Sending request to OpenAI API (model: {model})...")
        response = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()

        usage = result.get('usage')
        if usage:
            logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                return message_content.strip()

            logger.error("API response choice message content is empty.")
            return None
        else:
            logger.error(f"API response missing 'choices' or 'choices' is empty: {result}")
            return None

    except requests.exceptions.Timeout:
        logger.error(f"Timeout calling OpenAI API after {API_TIMEOUT_SECONDS} seconds")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling OpenAI API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling OpenAI API: {e}")
        return None

def call_vision_api(image_url: str, prompt: str):
    """Call the OpenAI Vision API to analyze an image."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set for Vision API.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        "max_tokens": 1000
    }

    try:
        logger.debug(f"Sending request to Vision API for image: {image_url}")
        response = requests.post(OPENAI_VISION_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                return message_content.strip()

            logger.error("Vision API response message content is empty.")
            return None
        else:
            logger.error(f"Vision API response missing 'choices' or 'choices' is empty: {result}")
            return None

    except requests.exceptions.Timeout:
        logger.error(f"Timeout calling Vision API after {API_TIMEOUT_SECONDS} seconds")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling Vision API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Vision API: {e}")
        return None

# --- Core Functionality Implementation ---

# --- Multiple Image Extraction ---
def extract_images_from_source(article_url: str) -> List[Dict[str, Any]]:
    """
    Extract multiple images from the source article URL.
    Returns a list of image data dictionaries with url, alt_text, dimensions, etc.
    """
    if not article_url or not is_valid_url(article_url):
        logger.warning(f"Invalid article URL for image extraction: {article_url}")
        return []

    logger.info(f"Extracting multiple images from source: {article_url}")
    images = []

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        response = requests.get(article_url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()

        if 'html' not in response.headers.get('content-type', '').lower():
            logger.warning(f"Source URL content type not HTML: {article_url}")
            return []

        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        # First, check for meta image tags (usually the main featured image)
        meta_selectors = [
            {'property': 'og:image'},
            {'property': 'og:image:secure_url'},
            {'name': 'twitter:image'},
            {'name': 'twitter:image:src'},
            {'itemprop': 'image'}
        ]

        meta_images = []
        for selector in meta_selectors:
            tag = soup.find('meta', attrs=selector)
            if tag and tag.get('content') and tag['content'].startswith('http'):
                meta_images.append({
                    'url': tag['content'],
                    'alt_text': '',
                    'source': 'meta_tag',
                    'selector': str(selector)
                })

        # Then find all image tags in the article body
        article_containers = soup.select('article, .article, .post, .content, main, #content, .entry, .entry-content')

        if not article_containers:
            # If no specific article container found, use the whole body
            article_containers = [soup.body] if soup.body else []

        body_images = []
        for container in article_containers:
            if not container:
                continue

            # Find all img tags
            for img in container.find_all('img'):
                img_url = img.get('src', '')

                # Handle relative URLs
                if img_url and not img_url.startswith(('http://', 'https://')):
                    img_url = urljoin(article_url, img_url)

                if img_url and is_valid_url(img_url):
                    # Check for data-src or similar attributes if src is empty or a placeholder
                    if not img_url or img_url.endswith(('placeholder.png', 'placeholder.jpg', 'blank.gif')):
                        for attr in ['data-src', 'data-original', 'data-lazy-src', 'data-original-src']:
                            if img.get(attr) and img[attr].strip():
                                img_url = img[attr]
                                if not img_url.startswith(('http://', 'https://')):
                                    img_url = urljoin(article_url, img_url)
                                break

                    # Skip small icons, spacers, and tracking pixels
                    width = img.get('width', '')
                    height = img.get('height', '')

                    try:
                        width = int(width) if width and width.isdigit() else 0
                        height = int(height) if height and height.isdigit() else 0

                        if (width > 0 and width < 100) or (height > 0 and height < 100):
                            continue
                    except (ValueError, TypeError):
                        pass

                    # Get alt text and figure captions
                    alt_text = img.get('alt', '').strip()

                    # Look for caption in parent figure tag
                    caption = ''
                    parent_figure = img.find_parent('figure')
                    if parent_figure:
                        figcaption = parent_figure.find('figcaption')
                        if figcaption:
                            caption = figcaption.get_text(strip=True)

                    body_images.append({
                        'url': img_url,
                        'alt_text': alt_text or caption,
                        'caption': caption,
                        'width': width,
                        'height': height,
                        'source': 'article_body'
                    })

        # Combine meta images and body images, prioritizing meta images
        all_images = meta_images + body_images

        # Remove duplicates while preserving order
        seen_urls = set()
        unique_images = []
        for img in all_images:
            if img['url'] not in seen_urls:
                seen_urls.add(img['url'])
                unique_images.append(img)

        # Download and validate each image
        validated_images = []
        for img_data in unique_images:
            img_url = img_data['url']
            pil_image = download_image(img_url)

            if pil_image:
                # Add image dimensions from the actual image
                img_data['width'] = pil_image.width
                img_data['height'] = pil_image.height
                img_data['aspect_ratio'] = pil_image.width / pil_image.height
                img_data['valid'] = True
                validated_images.append(img_data)
            else:
                logger.debug(f"Image failed validation: {img_url}")

        # Limit to maximum number of images
        return validated_images[:MAX_IMAGES_PER_ARTICLE]

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout extracting images from: {article_url}")
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request error extracting images from {article_url}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error extracting images from {article_url}: {e}")
        return []

def analyze_image_content(image_url: str, article_context: str) -> Dict[str, Any]:
    """
    Use AI vision to analyze image content and determine relevance to the article.
    Returns analysis data including description, relevance score, and tags.
    """
    if not image_url or not is_valid_url(image_url):
        logger.warning(f"Invalid image URL for analysis: {image_url}")
        return {"success": False, "error": "Invalid image URL"}

    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key not set for image analysis")
        return {"success": False, "error": "API key not set"}

    logger.info(f"Analyzing image content with AI vision: {image_url}")

    # Create a prompt for the vision model
    prompt = f"""
    Analyze this image in the context of the following article topic:

    ARTICLE CONTEXT: {article_context}

    Please provide:
    1. A detailed description of what's in the image (1-2 sentences)
    2. Relevance to the article topic (score 0-10)
    3. Key entities or objects visible in the image
    4. Any text visible in the image
    5. Image quality assessment (low, medium, high)

    Format your response as a JSON object with these keys:
    - description
    - relevance_score (0-10 numeric value)
    - entities (array of strings)
    - visible_text (empty string if none)
    - quality (low, medium, or high)
    - is_chart_or_diagram (boolean)
    - is_product_image (boolean)
    - is_person_or_portrait (boolean)
    """

    try:
        # Call the vision API
        response = call_vision_api(image_url, prompt)

        if not response:
            return {"success": False, "error": "Failed to get vision API response"}

        # Try to extract JSON from the response
        try:
            # Look for JSON pattern in the response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON-like content with curly braces
                json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = response

            analysis_data = json.loads(json_str)
            analysis_data["success"] = True
            return analysis_data

        except json.JSONDecodeError:
            # If JSON parsing fails, create a structured response from the text
            logger.warning(f"Failed to parse JSON from vision API response. Creating structured data from text.")

            # Extract information using regex patterns
            description_match = re.search(r'description[:\s]+(.*?)(?=\n\d|\n[A-Za-z]|$)', response, re.DOTALL)
            description = description_match.group(1).strip() if description_match else ""

            relevance_match = re.search(r'relevance[^:]*?:\s*(\d+(?:\.\d+)?)', response, re.DOTALL | re.IGNORECASE)
            relevance_score = float(relevance_match.group(1)) if relevance_match else 5.0

            entities_match = re.search(r'entities[^:]*?:\s*(.*?)(?=\n\d|\n[A-Za-z]|$)', response, re.DOTALL | re.IGNORECASE)
            entities_text = entities_match.group(1).strip() if entities_match else ""
            entities = [e.strip() for e in entities_text.split(',') if e.strip()]

            text_match = re.search(r'text[^:]*?:\s*(.*?)(?=\n\d|\n[A-Za-z]|$)', response, re.DOTALL | re.IGNORECASE)
            visible_text = text_match.group(1).strip() if text_match else ""

            quality_match = re.search(r'quality[^:]*?:\s*(low|medium|high)', response, re.DOTALL | re.IGNORECASE)
            quality = quality_match.group(1).lower() if quality_match else "medium"

            # Determine image type based on description
            is_chart = any(word in description.lower() for word in ['chart', 'graph', 'diagram', 'plot'])
            is_product = any(word in description.lower() for word in ['product', 'device', 'gadget', 'item'])
            is_person = any(word in description.lower() for word in ['person', 'people', 'face', 'portrait'])

            return {
                "success": True,
                "description": description,
                "relevance_score": relevance_score,
                "entities": entities,
                "visible_text": visible_text,
                "quality": quality,
                "is_chart_or_diagram": is_chart,
                "is_product_image": is_product,
                "is_person_or_portrait": is_person
            }

    except Exception as e:
        logger.error(f"Error analyzing image with vision API: {e}")
        return {"success": False, "error": str(e)}

def search_additional_images(article_data: Dict[str, Any], num_images: int = 3) -> List[Dict[str, Any]]:
    """
    Search for additional relevant images based on article content.
    Returns a list of image data dictionaries.
    """
    if not SERPAPI_API_KEY:
        logger.warning("SERPAPI_API_KEY not set for additional image search")
        return []

    title = article_data.get('title', '')
    keywords = article_data.get('keywords', [])

    if not title and not keywords:
        logger.warning("No title or keywords for additional image search")
        return []

    # Create search queries based on title and keywords
    search_queries = []

    if title:
        search_queries.append(title)

    # Add top keywords as search queries
    if keywords and isinstance(keywords, list):
        for keyword in keywords[:3]:
            if keyword and isinstance(keyword, str) and keyword not in title:
                search_queries.append(keyword)

    # Add title + main entity as a query
    if title and keywords and len(keywords) > 0:
        search_queries.append(f"{title} {keywords[0]}")

    logger.info(f"Searching for additional images with queries: {search_queries}")

    all_images = []
    for query in search_queries:
        try:
            # Use the existing search_images_serpapi function
            image_results = search_images_serpapi(query, num_results=5)

            if image_results and isinstance(image_results, list):
                # Filter and validate images
                for img_data in image_results:
                    img_url = img_data.get('url')
                    if img_url and is_valid_url(img_url):
                        # Download and validate the image
                        pil_image = download_image(img_url)

                        if pil_image:
                            # Add to our results with metadata
                            all_images.append({
                                'url': img_url,
                                'alt_text': img_data.get('title', ''),
                                'width': pil_image.width,
                                'height': pil_image.height,
                                'aspect_ratio': pil_image.width / pil_image.height,
                                'source': 'serpapi_search',
                                'search_query': query,
                                'source_page': img_data.get('source', ''),
                                'valid': True
                            })

        except Exception as e:
            logger.warning(f"Error searching for additional images with query '{query}': {e}")

    # Remove duplicates
    seen_urls = set()
    unique_images = []
    for img in all_images:
        if img['url'] not in seen_urls:
            seen_urls.add(img['url'])
            unique_images.append(img)

    # Limit to requested number
    return unique_images[:num_images]

def select_best_images(source_images: List[Dict[str, Any]], additional_images: List[Dict[str, Any]],
                      article_data: Dict[str, Any], max_images: int = MAX_IMAGES_PER_ARTICLE) -> List[Dict[str, Any]]:
    """
    Select the best images from source and additional images based on relevance, quality, and diversity.
    Returns a list of the best image data dictionaries.
    """
    if not source_images and not additional_images:
        logger.warning("No images available for selection")
        return []

    # Combine all images
    all_images = source_images + additional_images

    if not all_images:
        return []

    # If we have fewer images than the maximum, return all of them
    if len(all_images) <= max_images:
        return all_images

    # Get article context for relevance analysis
    article_title = article_data.get('title', '')
    article_content = article_data.get('content', '')
    article_context = f"{article_title}\n\n{article_content[:500]}..."

    # Analyze images for relevance if we have OpenAI API key
    if OPENAI_API_KEY:
        for img in all_images:
            if not img.get('analyzed'):
                analysis = analyze_image_content(img['url'], article_context)
                if analysis.get('success'):
                    img['relevance_score'] = analysis.get('relevance_score', 5.0)
                    img['description'] = analysis.get('description', '')
                    img['analyzed'] = True
                else:
                    # Default values if analysis fails
                    img['relevance_score'] = 5.0
                    img['description'] = ''
                    img['analyzed'] = False

    # Prioritize images:
    # 1. Always include the main image (first source image) if available
    # 2. Sort remaining images by relevance score
    # 3. Ensure diversity (mix of source and additional images)

    selected_images = []

    # Always include the main image if available
    if source_images:
        selected_images.append(source_images[0])

    # Sort remaining images by relevance score
    remaining_images = all_images[len(selected_images):]
    remaining_images.sort(key=lambda x: x.get('relevance_score', 5.0), reverse=True)

    # Ensure diversity by alternating between source and additional images
    source_remaining = [img for img in remaining_images if img.get('source') == 'article_body' or img.get('source') == 'meta_tag']
    additional_remaining = [img for img in remaining_images if img.get('source') == 'serpapi_search']

    # Interleave the two sources until we reach max_images
    while len(selected_images) < max_images and (source_remaining or additional_remaining):
        if source_remaining and (len(selected_images) % 2 == 0 or not additional_remaining):
            selected_images.append(source_remaining.pop(0))
        elif additional_remaining:
            selected_images.append(additional_remaining.pop(0))

    return selected_images[:max_images]

def process_images_for_article(article_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to process and enhance article with multiple images.
    Returns updated article data with multiple images.
    """
    article_url = article_data.get('source_url', '')

    if not article_url or not is_valid_url(article_url):
        logger.warning(f"Invalid article URL for image processing: {article_url}")
        return article_data

    logger.info(f"Processing images for article: {article_data.get('title', 'Untitled')}")

    # Extract images from source
    source_images = extract_images_from_source(article_url)
    logger.info(f"Found {len(source_images)} images from source article")

    # If we don't have enough images from source, search for additional images
    additional_images = []
    if len(source_images) < MAX_IMAGES_PER_ARTICLE:
        additional_images = search_additional_images(article_data, num_images=MAX_IMAGES_PER_ARTICLE - len(source_images))
        logger.info(f"Found {len(additional_images)} additional images from search")

    # Select the best images
    best_images = select_best_images(source_images, additional_images, article_data)
    logger.info(f"Selected {len(best_images)} best images for article")

    # Update article data with multiple images
    article_data['images'] = best_images

    # Set the main image (first image) as the article's featured image
    if best_images:
        article_data['image_url'] = best_images[0]['url']
        article_data['image_alt'] = best_images[0].get('alt_text', '')

    return article_data

# --- Video Embedding ---
def search_relevant_videos(article_data: Dict[str, Any], max_videos: int = MAX_VIDEOS_PER_ARTICLE) -> List[Dict[str, Any]]:
    """
    Search for relevant videos based on article content using YouTube API.
    Returns a list of video data dictionaries.
    """
    if not YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY not set for video search")
        return []

    title = article_data.get('title', '')
    keywords = article_data.get('keywords', [])

    if not title and not keywords:
        logger.warning("No title or keywords for video search")
        return []

    # Create search queries based on title and keywords
    search_queries = []

    if title:
        search_queries.append(title)

    # Add top keywords as search queries
    if keywords and isinstance(keywords, list):
        for keyword in keywords[:2]:  # Limit to top 2 keywords
            if keyword and isinstance(keyword, str) and keyword not in title:
                search_queries.append(keyword)

    # Add title + main entity as a query
    if title and keywords and len(keywords) > 0:
        search_queries.append(f"{title} {keywords[0]}")

    logger.info(f"Searching for relevant videos with queries: {search_queries}")

    all_videos = []
    for query in search_queries:
        try:
            # YouTube API search request
            youtube_search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                'key': YOUTUBE_API_KEY,
                'q': query,
                'part': 'snippet',
                'type': 'video',
                'maxResults': 5,
                'videoEmbeddable': 'true',
                'relevanceLanguage': 'en',
                'safeSearch': 'moderate'
            }

            response = requests.get(youtube_search_url, params=params, timeout=20)
            response.raise_for_status()
            search_results = response.json()

            if 'items' in search_results:
                # Get video details for each search result
                video_ids = [item['id']['videoId'] for item in search_results['items'] if 'videoId' in item['id']]

                if video_ids:
                    # Get detailed video information
                    video_details_url = "https://www.googleapis.com/youtube/v3/videos"
                    details_params = {
                        'key': YOUTUBE_API_KEY,
                        'id': ','.join(video_ids),
                        'part': 'snippet,contentDetails,statistics'
                    }

                    details_response = requests.get(video_details_url, params=details_params, timeout=20)
                    details_response.raise_for_status()
                    video_details = details_response.json()

                    if 'items' in video_details:
                        for video in video_details['items']:
                            # Parse duration (in ISO 8601 format)
                            duration_str = video['contentDetails'].get('duration', 'PT0S')
                            duration_seconds = 0

                            # Convert ISO 8601 duration to seconds
                            duration_match = re.match(r'PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?', duration_str)
                            if duration_match:
                                duration_parts = duration_match.groupdict(default='0')
                                duration_seconds = (int(duration_parts['hours']) * 3600 +
                                                 int(duration_parts['minutes']) * 60 +
                                                 int(duration_parts['seconds']))

                            # Skip videos that are too short or too long
                            if duration_seconds < MIN_VIDEO_DURATION_SECONDS or duration_seconds > MAX_VIDEO_DURATION_SECONDS:
                                continue

                            # Create video data dictionary
                            video_data = {
                                'id': video['id'],
                                'title': video['snippet']['title'],
                                'description': video['snippet']['description'],
                                'thumbnail_url': video['snippet']['thumbnails'].get('high', {}).get('url', ''),
                                'channel_title': video['snippet']['channelTitle'],
                                'published_at': video['snippet']['publishedAt'],
                                'duration_seconds': duration_seconds,
                                'view_count': int(video['statistics'].get('viewCount', 0)),
                                'like_count': int(video['statistics'].get('likeCount', 0)),
                                'comment_count': int(video['statistics'].get('commentCount', 0)),
                                'embed_url': f"https://www.youtube.com/embed/{video['id']}",
                                'watch_url': f"https://www.youtube.com/watch?v={video['id']}",
                                'search_query': query
                            }

                            all_videos.append(video_data)

        except requests.exceptions.RequestException as e:
            logger.warning(f"Error searching for videos with query '{query}': {e}")
        except Exception as e:
            logger.warning(f"Unexpected error in video search for query '{query}': {e}")

    # Remove duplicates
    seen_ids = set()
    unique_videos = []
    for video in all_videos:
        if video['id'] not in seen_ids:
            seen_ids.add(video['id'])
            unique_videos.append(video)

    # Sort by view count (popularity) and limit to max_videos
    unique_videos.sort(key=lambda x: x['view_count'], reverse=True)
    return unique_videos[:max_videos]

def analyze_video_relevance(video_data: Dict[str, Any], article_data: Dict[str, Any]) -> float:
    """
    Analyze the relevance of a video to the article content.
    Returns a relevance score between 0 and 1.
    """
    # Extract video metadata
    video_title = video_data.get('title', '').lower()
    video_description = video_data.get('description', '').lower()

    # Extract article metadata
    article_title = article_data.get('title', '').lower()
    article_content = article_data.get('content', '').lower()
    article_keywords = [k.lower() for k in article_data.get('keywords', []) if isinstance(k, str)]

    # Calculate relevance score based on keyword matching
    relevance_score = 0.0

    # Check if article title words appear in video title (highest relevance)
    article_title_words = set(re.findall(r'\b\w{3,}\b', article_title))
    video_title_words = set(re.findall(r'\b\w{3,}\b', video_title))
    title_match_ratio = len(article_title_words.intersection(video_title_words)) / max(1, len(article_title_words))
    relevance_score += title_match_ratio * 0.5  # Title matches are weighted heavily

    # Check if keywords appear in video title or description
    if article_keywords:
        keyword_matches = 0
        for keyword in article_keywords:
            if keyword in video_title:
                keyword_matches += 2  # Double weight for title matches
            elif keyword in video_description:
                keyword_matches += 1

        keyword_match_ratio = keyword_matches / (len(article_keywords) * 2)  # Normalize to 0-1
        relevance_score += keyword_match_ratio * 0.3  # Keywords are moderately weighted

    # Check for content similarity (basic approach)
    # Extract important terms from article content
    content_terms = set(re.findall(r'\b\w{5,}\b', article_content[:1000]))  # Use first 1000 chars only
    video_desc_terms = set(re.findall(r'\b\w{5,}\b', video_description))

    if content_terms:
        content_match_ratio = len(content_terms.intersection(video_desc_terms)) / len(content_terms)
        relevance_score += content_match_ratio * 0.2  # Content similarity is less weighted

    # Bonus for very popular videos (viral content is often relevant)
    view_count = video_data.get('view_count', 0)
    if view_count > 1000000:  # 1M+ views
        relevance_score += 0.1  # Small bonus for very popular content
    elif view_count > 100000:  # 100K+ views
        relevance_score += 0.05

    # Cap at 1.0
    return min(1.0, relevance_score)

def embed_videos_in_article(article_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Find and embed relevant videos in the article content.
    Returns updated article data with embedded videos.
    """
    logger.info(f"Finding and embedding videos for article: {article_data.get('title', 'Untitled')}")

    # Search for relevant videos
    videos = search_relevant_videos(article_data)

    if not videos:
        logger.info("No relevant videos found for article")
        return article_data

    logger.info(f"Found {len(videos)} potentially relevant videos")

    # Analyze video relevance
    for video in videos:
        relevance_score = analyze_video_relevance(video, article_data)
        video['relevance_score'] = relevance_score

    # Filter videos by relevance threshold
    relevant_videos = [v for v in videos if v.get('relevance_score', 0) >= VIDEO_RELEVANCE_THRESHOLD]

    if not relevant_videos:
        logger.info(f"No videos met the relevance threshold ({VIDEO_RELEVANCE_THRESHOLD})")
        return article_data

    # Sort by relevance score
    relevant_videos.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

    # Limit to maximum number of videos
    selected_videos = relevant_videos[:MAX_VIDEOS_PER_ARTICLE]
    logger.info(f"Selected {len(selected_videos)} videos for embedding")

    # Add videos to article data
    article_data['videos'] = selected_videos

    return article_data

# --- Cross-Referencing Information ---
def find_related_sources(article_data: Dict[str, Any], max_sources: int = MAX_CROSS_REFERENCES) -> List[Dict[str, Any]]:
    """
    Find additional sources related to the article topic for cross-referencing.
    Returns a list of source data dictionaries.
    """
    if not SERPAPI_API_KEY:
        logger.warning("SERPAPI_API_KEY not set for finding related sources")
        return []

    title = article_data.get('title', '')
    keywords = article_data.get('keywords', [])
    source_url = article_data.get('source_url', '')
    source_domain = extract_domain(source_url) if source_url else ''

    if not title and not keywords:
        logger.warning("No title or keywords for finding related sources")
        return []

    # Create search queries based on title and keywords
    search_queries = []

    if title:
        search_queries.append(title)

    # Add top keywords as search queries
    if keywords and isinstance(keywords, list):
        for keyword in keywords[:3]:
            if keyword and isinstance(keyword, str) and keyword not in title:
                search_queries.append(keyword)

    logger.info(f"Finding related sources with queries: {search_queries}")

    all_sources = []
    for query in search_queries:
        try:
            # Use SerpAPI to search for related articles
            search_params = {
                "engine": "google",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "num": 10,  # Request more results to filter later
                "tbm": "nws"  # News search
            }

            response = requests.get("https://serpapi.com/search", params=search_params, timeout=30)
            response.raise_for_status()
            search_results = response.json()

            if 'news_results' in search_results:
                for result in search_results['news_results']:
                    result_url = result.get('link')
                    result_domain = extract_domain(result_url) if result_url else ''

                    # Skip the original source and duplicate domains for diversity
                    if result_domain and result_domain != source_domain:
                        source_data = {
                            'url': result_url,
                            'title': result.get('title', ''),
                            'snippet': result.get('snippet', ''),
                            'source': result.get('source', ''),
                            'published_date': result.get('date', ''),
                            'domain': result_domain,
                            'search_query': query
                        }
                        all_sources.append(source_data)

        except requests.exceptions.RequestException as e:
            logger.warning(f"Error searching for related sources with query '{query}': {e}")
        except Exception as e:
            logger.warning(f"Unexpected error in related source search for query '{query}': {e}")

    # Remove duplicates and prioritize diverse sources
    seen_domains = set()
    unique_sources = []

    for source in all_sources:
        domain = source.get('domain', '')
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            unique_sources.append(source)

            # Once we have enough diverse sources, stop
            if len(unique_sources) >= max_sources:
                break

    return unique_sources[:max_sources]

def extract_information_from_source(source_url: str) -> Dict[str, Any]:
    """
    Extract relevant information from a source URL using trafilatura.
    Returns a dictionary with extracted content and metadata.
    """
    if not source_url or not is_valid_url(source_url):
        logger.warning(f"Invalid source URL for extraction: {source_url}")
        return {'success': False, 'error': 'Invalid URL'}

    logger.info(f"Extracting information from source: {source_url}")

    try:
        # Use trafilatura for high-quality content extraction
        downloaded = trafilatura.fetch_url(source_url)

        if not downloaded:
            logger.warning(f"Failed to download content from {source_url}")
            return {'success': False, 'error': 'Download failed'}

        # Extract main content
        extracted_text = trafilatura.extract(downloaded, include_comments=False, include_tables=True, output_format='text')
        extracted_html = trafilatura.extract(downloaded, include_comments=False, include_tables=True, output_format='html')

        # Extract metadata
        metadata = trafilatura.extract_metadata(downloaded)

        if not extracted_text:
            logger.warning(f"No content extracted from {source_url}")
            return {'success': False, 'error': 'No content extracted'}

        # Create result dictionary
        result = {
            'success': True,
            'url': source_url,
            'domain': extract_domain(source_url),
            'content_text': extracted_text,
            'content_html': extracted_html,
            'title': metadata.title if metadata else '',
            'author': metadata.author if metadata else '',
            'date': metadata.date if metadata else '',
            'hostname': metadata.hostname if metadata else '',
            'description': metadata.description if metadata else ''
        }

        return result

    except Exception as e:
        logger.warning(f"Error extracting information from {source_url}: {e}")
        return {'success': False, 'error': str(e)}

def cross_reference_information(article_data: Dict[str, Any], source_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Cross-reference information from multiple sources to enhance the article.
    Uses AI to analyze and combine information from different sources.
    Returns a dictionary with cross-referenced information.
    """
    if not source_data_list:
        logger.warning("No sources provided for cross-referencing")
        return {'success': False, 'error': 'No sources provided'}

    # Extract main article content
    article_title = article_data.get('title', '')
    article_content = article_data.get('content', '')

    if not article_title or not article_content:
        logger.warning("Article title or content missing for cross-referencing")
        return {'success': False, 'error': 'Article data incomplete'}

    # Prepare source content for analysis
    source_contents = []
    for i, source in enumerate(source_data_list):
        if source.get('success') and source.get('content_text'):
            source_header = f"Source {i+1} ({source.get('domain', 'unknown')}):"
            source_title = source.get('title', '')
            source_text_content = source.get('content_text', '')[:1500] + "..." # Use text content
            source_contents.append(f"{source_header}\n{source_title}\n{source_text_content}")

    if not source_contents:
        logger.warning("No valid source content for cross-referencing")
        return {'success': False, 'error': 'No valid source content'}

    # Create a prompt for the AI to analyze and cross-reference information
    system_prompt = """
    You are an expert research analyst and fact-checker. Your task is to analyze multiple sources on the same topic and identify:
    1. Additional facts or details not mentioned in the main article
    2. Different perspectives or viewpoints on the topic
    3. Contradicting information or disagreements between sources
    4. Supporting evidence or confirmation of claims in the main article
    5. Recent developments or updates not covered in the main article

    Provide your analysis in a structured JSON format with these sections. Be specific and precise, citing which source each piece of information comes from.
    Focus on the most important and relevant information only.
    """

    json_template = '''
    {"additional_facts": [{"fact": "specific fact", "source": "source number", "confidence": 0.0-1.0}],
    "different_perspectives": [{"perspective": "description", "source": "source number", "confidence": 0.0-1.0}],
    "contradictions": [{"claim": "original claim", "contradiction": "contradicting info", "source": "source number", "confidence": 0.0-1.0}],
    "supporting_evidence": [{"claim": "claim being supported", "evidence": "supporting evidence", "source": "source number", "confidence": 0.0-1.0}],
    "recent_developments": [{"development": "new information", "source": "source number", "confidence": 0.0-1.0}]}
    '''
    
    # Pre-join source_contents
    joined_source_contents_for_prompt = "\n\n".join(source_contents)

    user_prompt = f"""
    Main Article Title: {article_title}

    Main Article Content (excerpt):
    {article_content[:1500]}...

    Additional Sources to Cross-Reference:
    {joined_source_contents_for_prompt}

    Please analyze these sources and provide a comprehensive cross-reference analysis in the following JSON format:
    {json_template}

    Only include high-confidence (0.7+) information that genuinely adds value. Quality over quantity.
    """

    try:
        # Call the AI API for cross-referencing analysis
        if OPENAI_API_KEY:
            response = call_openai_api(system_prompt, user_prompt, model=CROSS_REF_MODEL)
        elif DEEPSEEK_API_KEY:
            response = call_deepseek_api(system_prompt, user_prompt)
        else:
            logger.warning("No API key available for cross-referencing analysis")
            return {'success': False, 'error': 'No API key available'}

        if not response:
            logger.warning("Failed to get AI response for cross-referencing")
            return {'success': False, 'error': 'AI analysis failed'}

        # Parse the JSON response
        try:
            # Extract JSON from the response if needed
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = response

            cross_ref_data = json.loads(json_str)
            cross_ref_data['success'] = True
            return cross_ref_data

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from cross-reference response: {e}")
            return {'success': False, 'error': f'JSON parse error: {str(e)}'}

    except Exception as e:
        logger.error(f"Error in cross-referencing analysis: {e}")
        return {'success': False, 'error': str(e)}

def enhance_article_with_cross_references(article_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to enhance article with cross-referenced information from multiple sources.
    Returns updated article data with cross-referenced information.
    """
    logger.info(f"Enhancing article with cross-references: {article_data.get('title', 'Untitled')}")

    # Find related sources
    related_sources = find_related_sources(article_data)

    if not related_sources:
        logger.info("No related sources found for cross-referencing")
        return article_data

    logger.info(f"Found {len(related_sources)} related sources for cross-referencing")

    # Extract information from each source
    source_data_list = []
    for source in related_sources:
        source_url = source.get('url')
        if source_url:
            source_info = extract_information_from_source(source_url) # Renamed from source_data to source_info
            if source_info.get('success'):
                source_data_list.append(source_info)

    if not source_data_list:
        logger.info("No valid source data extracted for cross-referencing")
        return article_data

    logger.info(f"Extracted information from {len(source_data_list)} sources")

    # Cross-reference information from sources
    cross_ref_data = cross_reference_information(article_data, source_data_list)

    if not cross_ref_data.get('success'):
        logger.warning(f"Cross-referencing failed: {cross_ref_data.get('error')}")
        return article_data

    # Add cross-referenced information to article data
    article_data['cross_references'] = cross_ref_data
    article_data['cross_reference_sources'] = [{
        'url': source.get('url'),
        'title': source.get('title'),
        'domain': source.get('domain')
    } for source in source_data_list]

    logger.info("Successfully enhanced article with cross-referenced information")

    return article_data

# --- Main Integration Function ---
def run_content_enhancement_agent(article_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to run all content enhancement features:
    1. Multiple image extraction and analysis
    2. Video embedding
    3. Cross-referencing information from multiple sources

    Returns the enhanced article data with all features integrated.
    """
    if not article_data:
        logger.error("No article data provided for content enhancement")
        return {}

    logger.info(f"Starting advanced content enhancement for article: {article_data.get('title', 'Untitled')}")

    # Step 1: Enhance with multiple images
    try:
        logger.info("Step 1: Enhancing article with multiple images")
        article_data = process_images_for_article(article_data)
    except Exception as e:
        logger.error(f"Error in image enhancement process: {e}")

    # Step 2: Embed relevant videos
    try:
        logger.info("Step 2: Finding and embedding relevant videos")
        article_data = embed_videos_in_article(article_data)
    except Exception as e:
        logger.error(f"Error in video embedding process: {e}")

    # Step 3: Cross-reference information from multiple sources
    try:
        logger.info("Step 3: Cross-referencing information from multiple sources")
        article_data = enhance_article_with_cross_references(article_data)
    except Exception as e:
        logger.error(f"Error in cross-referencing process: {e}")

    # Generate a summary of enhancements
    enhancements_summary = {
        'images_count': len(article_data.get('images', [])),
        'videos_count': len(article_data.get('videos', [])),
        'cross_references': bool(article_data.get('cross_references', {}).get('success', False)),
        'cross_reference_sources_count': len(article_data.get('cross_reference_sources', [])),
    }

    article_data['enhancements_summary'] = enhancements_summary

    logger.info(f"Content enhancement completed with summary: {enhancements_summary}")

    return article_data

# For standalone testing
if __name__ == "__main__":
    # Test with a sample article
    test_article = {
        'title': 'NVIDIA Unveils New AI Chips',
        'content': 'NVIDIA has announced new AI chips that promise significant performance improvements...',
        'source_url': 'https://example.com/nvidia-new-ai-chips', # Make sure this is a real or mockable URL for testing
        'keywords': ['NVIDIA', 'AI chips', 'GPU', 'artificial intelligence', 'hardware']
    }

    # Mocking the source_url to prevent actual web requests during simple CLI testing
    # In a real test, you might use a local file URL or a mock server.
    # For this example, we'll assume the URL might fail but the functions should handle it.
    # test_article['source_url'] = 'http://nonexistent.invalid/test-article'
    # Or, provide a real URL if you want to test the scraping parts.
    test_article['source_url'] = 'https://nvidianews.nvidia.com/news/nvidia-unveils-next-generation-ai-supercomputer' # Example real URL

    enhanced_article = run_content_enhancement_agent(test_article)

    # Print summary of enhancements
    print("\nEnhancement Summary:")
    print(f"Images: {len(enhanced_article.get('images', []))}")
    print(f"Videos: {len(enhanced_article.get('videos', []))}")
    print(f"Cross-references: {enhanced_article.get('cross_references', {}).get('success', False)}")
    print(f"Cross-reference sources: {len(enhanced_article.get('cross_reference_sources', []))}")

    # Print details of first image if available
    if enhanced_article.get('images'):
        first_image = enhanced_article['images'][0]
        print("\nFirst Image:")
        print(f"URL: {first_image.get('url')}")
        print(f"Alt text: {first_image.get('alt_text')}")
        print(f"Dimensions: {first_image.get('width')}x{first_image.get('height')}")

    # Print details of first video if available
    if enhanced_article.get('videos'):
        first_video = enhanced_article['videos'][0]
        print("\nFirst Video:")
        print(f"Title: {first_video.get('title')}")
        print(f"URL: {first_video.get('watch_url')}")
        print(f"Relevance score: {first_video.get('relevance_score')}")

    # Print cross-reference highlights if available
    if enhanced_article.get('cross_references', {}).get('additional_facts'):
        print("\nAdditional Facts from Cross-References:")
        for fact in enhanced_article['cross_references']['additional_facts'][:3]:  # Show first 3
            print(f"- {fact.get('fact')} (Source: {fact.get('source')}, Confidence: {fact.get('confidence')})")
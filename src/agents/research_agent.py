# src/agents/research_agent.py

"""
Research Agent: The ASI-level "Discovery & Enrichment" Core.

This agent is the primary entry point for all raw content acquisition and initial data enrichment.
It consolidates and significantly enhances the capabilities previously handled by:
    - news_scraper.py (fetching RSS feeds, extracting summaries, fetching full article text)
    - image_scraper.py (finding optimal images via source scraping and SerpApi, filtering with CLIP)
    - vision_agent.py (its conceptual role of intelligent image selection/filtering)

Its comprehensive mission includes:
1.  **Feed Aggregation**: Systematically fetch and parse news feeds from configured sources.
2.  **Gyro Pick Integration**: Process user-defined "Gyro Pick" URLs as priority research items.
3.  **Content Extraction**: Robustly extract the most complete and relevant text content from articles (prioritizing full web page text over RSS summaries).
4.  **Intelligent Image Sourcing**: Automatically find the best, most relevant image for each article by:
    *   Prioritizing direct scraping of the article's source page for meta images.
    *   Falling back to intelligent Google Image searches via SerpApi.
    *   Utilizing advanced CLIP (Contrastive Language-Image Pre-training) for semantic relevance filtering to ensure images truly match the article's content and intent.
    *   Performing strict dimension and format validation on all potential images.
5.  **Duplicate Prevention**: Efficiently manage and check against a list of already processed article IDs to avoid redundant research.
6.  **Data Structuring**: Return a standardized, rich data dictionary for each newly discovered and enriched article, ready for downstream processing agents.

This agent is designed for high reliability, efficiency, and intelligence, ensuring that
only high-quality, relevant raw material enters the content generation pipeline.
"""

import os
import sys
import requests
import json
import logging
import hashlib
import html
import re
import time
import io
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any, Union, Type
from urllib.parse import urljoin

# Path Setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Logging Setup
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

# Graceful Degradation for External Libraries
FEEDPARSER_AVAILABLE: bool
try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None 
    FEEDPARSER_AVAILABLE = False
    logger.warning("feedparser library not found. RSS feed scraping will be disabled. Install with: pip install feedparser")

TRAFILATURA_AVAILABLE: bool
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    trafilatura = None 
    TRAFILATURA_AVAILABLE = False
    logger.warning("trafilatura library not found. Advanced full article fetching will be limited. Install with: pip install trafilatura")

BS4_AVAILABLE: bool
BeautifulSoup: Optional[Type[Any]] = None 
Comment: Optional[Type[Any]] = None 
try:
    from bs4 import BeautifulSoup as BS, Comment as BComment
    BeautifulSoup = BS
    Comment = BComment
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("BeautifulSoup library (bs4) not found. HTML parsing for content and images will be disabled. Install with: pip install beautifulsoup4")

SERPAPI_AVAILABLE: bool
GoogleSearch: Optional[Type[Any]] = None 
try:
    from serpapi import GoogleSearch as SerpGSearch
    GoogleSearch = SerpGSearch
    SERPAPI_AVAILABLE = True
except ImportError:
    SERPAPI_AVAILABLE = False
    logger.warning("serpapi library not found. Google Image Search via SerpApi will be disabled. Install with: pip install google-search-results")

PIL_AVAILABLE: bool
Image: Optional[Type[Any]] = None 
UnidentifiedImageError: Optional[Type[Any]] = None 
try:
    from PIL import Image as PILImage, UnidentifiedImageError as PILUnidentifiedImageError
    Image = PILImage
    UnidentifiedImageError = PILUnidentifiedImageError
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow (PIL) library not found. Image processing and validation will be skipped. Install with: pip install Pillow")

SENTENCE_TRANSFORMERS_AVAILABLE: bool
SentenceTransformer: Optional[Type[Any]] = None 
st_cos_sim: Optional[Any] = None 
CLIP_MODEL_INSTANCE: Optional[Any] = None 
try:
    from sentence_transformers import SentenceTransformer as STSentenceTransformer
    from sentence_transformers.util import cos_sim
    SentenceTransformer = STSentenceTransformer
    st_cos_sim = cos_sim
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers library not found. CLIP-based image filtering will be disabled. Install with: pip install sentence-transformers")


# Configuration & Constants
CLIP_MODEL_NAME: str = 'clip-ViT-B-32'
NEWS_FEED_URLS: List[str] = [
    "https://techcrunch.com/feed/", "https://www.technologyreview.com/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/", "https://blogs.nvidia.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index/", "https://venturebeat.com/category/ai/feed/",
    "https://www.wired.com/feed/category/business/latest/rss", "https://www.wired.com/feed/category/science/latest/rss",
    "https://www.wired.com/feed/tag/ai/latest/rss", "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
    "https://www.zdnet.com/topic/hardware/rss.xml", "https://www.microsoft.com/en-us/research/blog/feed/",
    "https://feeds.bbci.co.uk/news/technology/rss.xml", "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://aws.amazon.com/blogs/ai/feed/", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
    "https://spectrum.ieee.org/feeds/topic/robotics.rss", "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
    "https://blog.google/technology/ai/rss/", "https://blog.google/products/search/rss/",
    "https://research.googleblog.com/feeds/posts/default?alt=rss", "https://www.theverge.com/rss/index.xml",
    "https://www.engadget.com/rss.xml", "https://www.cnet.com/rss/news/", "https://www.pcmag.com/rss/news",
    "https://www.techradar.com/news/rss", "https://www.digitaltrends.com/feed/", "https://www.tomsguide.com/feeds/all",
    "https://www.tomshardware.com/feeds/all", "https://www.androidauthority.com/feed/",
    "https://www.macrumors.com/macrumors.rss", "https://www.theregister.com/headlines.atom",
    "https://www.infoworld.com/category/artificial-intelligence/index.rss",
    "https://www.computerworld.com/category/artificial-intelligence/index.rss",
    "https://www.forbes.com/innovation/feed/", "https://www.forbes.com/ai/feed/",
    "https://www.axios.com/technology/rss", "https://www.axios.com/ai/rss",
    "https://www.reuters.com/technology/feed", "https://www.wsj.com/news/types/technology?format=rss",
    "https://www.ft.com/technology?format=rss", "https://www.economist.com/science-and-technology/rss.xml",
    "https://www.nature.com/subjects/computer-science.rss", "https://www.science.org/rss/news_current.xml",
    "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
    "https://www.sciencedaily.com/rss/computers_math/robotics.xml",
    "https://www.quantamagazine.org/tag/artificial-intelligence/feed/",
    "https://www.quantamagazine.org/tag/computer-science/feed/", "https://openai.com/blog/rss.xml",
    "https://deepmind.google/blog/rss/", "https://ai.meta.com/blog/rss/",
    "https://www.apple.com/newsroom/rss-feed.rss", "https://news.samsung.com/global/feed",
    "https://blog.unity.com/topic/ai-robotics/feed", "https://blogs.cisco.com/tag/artificial-intelligence/feed",
    "https://www.ibm.com/blogs/research/category/artificial-intelligence/feed/",
    "https://www.intel.com/content/www/us/en/newsroom/news/feed.xml", "https://www.qualcomm.com/news/rss",
    "https://news.mit.edu/topic/artificial-intelligence2/rss", "https://engineering.stanford.edu/magazine/feed",
    "https://hai.stanford.edu/news/feed", "https://news.berkeley.edu/category/research/technology-engineering/feed/",
    "https://news.cmu.edu/media-relations/topics/artificial-intelligence/rss",
    "https://techxplore.com/rss-feed/tags/artificial+intelligence/",
    "https://techxplore.com/rss-feed/tags/machine+learning/", "https://techxplore.com/rss-feed/tags/robotics/",
    "https://www.euronews.com/next/feed", "https://sifted.eu/feed",
    "https://www.businessinsider.com/sai/rss", "https://www.fastcompany.com/technology/rss",
    "https://hbr.org/topic/technology-and-digital-media/feed", "https://www.protocol.com/feed/",
    "https://www.theinformation.com/feed", "https://stratechery.com/feed/",
    "https://www.ben-evans.com/benedictevans?format=rss", "https://news.ycombinator.com/rss",
    "https://www.reddit.com/r/artificial/.rss", "https://www.reddit.com/r/MachineLearning/.rss",
    "https://www.reddit.com/r/singularity/.rss", "https://www.reddit.com/r/Futurology/.rss",
    "https://www.reddit.com/r/hardware/.rss", "https://www.reddit.com/r/robotics/.rss",
    "https://www.reddit.com/r/technology/.rss", "https://developer.nvidia.com/blog/feed",
    "https://pytorch.org/blog/feed.xml", "https://blog.tensorflow.org/feeds/posts/default?alt=rss",
    "https://huggingface.co/blog/feed.xml", "https://www.semianalysis.com/feed/",
    "https://machinelearning.apple.com/feed.xml", "https://www.kdnuggets.com/feed",
    "https://news.mit.edu/topic/computers-electronics-and-robotics/rss",
    "https://news.mit.edu/topic/machine-learning/rss", "https://www.technology.org/feed/",
    "https://www.nextplatform.com/feed/",
    "https://www.gartner.com/en/newsroom/rss", "https://www.forrester.com/feed/",
    "https://arstechnica.com/science/feed/", "https://arstechnica.com/gadgets/feed/",
    "https://www.anandtech.com/rss/", "https://www.techspot.com/rss/news/",
    "https://www.extremetech.com/feed", "https://iottechnews.com/feed/",
    "https://roboticsandautomationnews.com/feed/", "https://www.ainews.com/feed/",
    "https://www.artificialintelligence-news.com/feed/", "https://www.robotreport.com/feed/",
    "https://www.darkreading.com/rss_simple.asp", "https://www.bleepingcomputer.com/feed/",
    "https://krebsonsecurity.com/feed/", "https://www.schneier.com/feed/",
    "https://www.wired.co.uk/feed/technology/rss", "https://www.techworld.com/news/feed/",
    "https://www.computerweekly.com/rss/Latest-Computer-Weekly-news-RSS-feed.xml",
    "https://www.itpro.co.uk/feed", "https://www.techcentral.ie/feed/",
    "https://www.tech.eu/feed", "https://thenextweb.com/feed/",
    "https://www.techmeme.com/feed.xml", "https://www.vox.com/technology/rss/index.xml",
    "https://www.statnews.com/feed/", "https://medcitynews.com/feed",
    "https://www.fiercebiotech.com/rss.xml", "https://www.fierceelectronics.com/rss.xml",
    "https://www.fiercehealthcare.com/rss.xml", "https://singularityhub.com/feed/",
    "https://www.kurzweilai.net/feed",
    "https://cacm.acm.org/browse-by-subject/artificial-intelligence.rss",
    "https://cacm.acm.org/browse-by-subject/robotics.rss",
    "https://www.brookings.edu/series/artificial-intelligence-and-emerging-technology-initiative/feed/",
    "https://www.csis.org/programs/technology-and-intelligence-program/rss.xml",
    "https://www.cfr.org/topic/technology-and-innovation/rss.xml", "https://www.eff.org/rss/updates.xml",
    "https://epic.org/feed/", "https://www.technologyreview.com/topic/blockchain/feed/",
    "https://www.technologyreview.com/topic/biotechnology/feed/",
    "https://www.technologyreview.com/topic/computing/feed/",
    "https://www.technologyreview.com/topic/humans-and-technology/feed/",
    "https://www.technologyreview.com/topic/space/feed/",
    "https://www.technologyreview.com/topic/sustainability/feed/",
    "https://developer.apple.com/news/rss/news.rss",
    "https://android-developers.googleblog.com/feeds/posts/default",
    "https://blog.chromium.org/feeds/posts/default", "https://kubernetes.io/feed.xml",
    "https://www.docker.com/blog/feed/", "https://www.djangoproject.com/rss/weblog/",
    "https://news.python.sc/feed", "https://www.linux.com/feeds/all-news",
    "https://lwn.net/headlines/rss", "https://www.phoronix.com/rss.php",
    "https://www.servethehome.com/feed/", "https://www.tweaktown.com/feed/",
    "https://www.guru3d.com/news/rss/", "https://www.overclock3d.net/feed",
    "https://videocardz.com/feed", "https://wccftech.com/feed/",
    "https://seekingalpha.com/api/sa/combined/NVDA.xml",
    "https://seekingalpha.com/api/sa/combined/AMD.xml",
    "https://seekingalpha.com/api/sa/combined/INTC.xml",
    "https://seekingalpha.com/api/sa/combined/TSM.xml",
    "https://seekingalpha.com/api/sa/combined/MSFT.xml",
    "https://seekingalpha.com/api/sa/combined/GOOG.xml",
    "https://seekingalpha.com/api/sa/combined/AAPL.xml",
    "https://seekingalpha.com/api/sa/combined/AMZN.xml",
    "https://seekingalpha.com/api/sa/combined/META.xml",
    "https://www.eetimes.com/feed/", "https://www.edn.com/feed/",
    "https://www.electronicdesign.com/rss.xml", "https://www.designnews.com/rss.xml",
    "https://www.mouser.com/blog/feed",
    "https://www.arrow.com/en/research-and-events/articles/feed",
    "https://www.digikey.com/en/blog/feed", "https://www.eenewseurope.com/news/feed",
    "https://www.eenewsanalog.com/news/feed", "https://www.eenewspower.com/news/feed",
    "https://www.eenewsembedded.com/news/feed", "https://www.eenewsautomotive.com/news/feed",
    "https://spectrum.ieee.org/feed", "https://news.ieeeusa.org/feed/",
    "https://theinstitute.ieee.org/feed/",
    "https://standards.ieee.org/content/ieee-standards/en/news/feed.xml",
    "https://ai.googleblog.com/feeds/posts/default", "https://aws.amazon.com/blogs/aws/feed/",
    "https://azure.microsoft.com/en-us/blog/feed/", "https://cloud.google.com/blog/rss/",
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
]

SERPAPI_API_KEY: Optional[str] = os.getenv('SERPAPI_API_KEY')
WEBSITE_URL_FOR_AGENT: str = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')

IMAGE_SEARCH_PARAMS: Dict[str, str] = {
    "engine": "google_images", "ijn": "0", "safe": "active",
    "tbs": "isz:l,itp:photo,iar:w",
}
IMAGE_DOWNLOAD_TIMEOUT: int = 20
IMAGE_DOWNLOAD_RETRIES: int = 2
IMAGE_RETRY_DELAY: int = 3

MIN_IMAGE_WIDTH: int = int(os.getenv('MIN_IMAGE_WIDTH', '400'))
MIN_IMAGE_HEIGHT: int = int(os.getenv('MIN_IMAGE_HEIGHT', '250'))
MIN_CLIP_SCORE: float = float(os.getenv('MIN_CLIP_SCORE', '0.5'))
ENABLE_CLIP_FILTERING: bool = SENTENCE_TRANSFORMERS_AVAILABLE and PIL_AVAILABLE

ARTICLE_FETCH_TIMEOUT: int = 20
MIN_FULL_TEXT_LENGTH: int = 250


def _get_article_id(entry: Dict[str, Any], source_identifier: str) -> str:
    raw_title: str = entry.get('title', '')
    raw_summary: str = entry.get('summary', entry.get('description', ''))
    guid: str = entry.get('id', '')
    link: str = entry.get('link', '')
    identifier_base: str = ""
    if guid and guid != link:
        identifier_base = guid
    elif link:
        identifier_base = link
    elif raw_title and raw_summary:
        identifier_base = raw_title + raw_summary
    else:
        identifier_base = f"{datetime.now(timezone.utc).timestamp()}-{random.random()}"
        logger.warning(f"Using timestamp/random ID for entry from {source_identifier}. Title: {raw_title[:50]}...")
    identifier: str = f"{identifier_base}::{source_identifier}"
    article_id: str = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    return article_id

def _load_sentence_model_clip() -> bool:
    global CLIP_MODEL_INSTANCE, ENABLE_CLIP_FILTERING
    if not PIL_AVAILABLE: 
        logger.debug("Pillow not available, CLIP filtering cannot proceed.")
        ENABLE_CLIP_FILTERING = False
        return False
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        ENABLE_CLIP_FILTERING = False
        return False
    if not ENABLE_CLIP_FILTERING: 
        return False
    if CLIP_MODEL_INSTANCE is None:
        try:
            logger.info(f"Loading CLIP model: {CLIP_MODEL_NAME}...")
            CLIP_MODEL_INSTANCE = SentenceTransformer(CLIP_MODEL_NAME) if SentenceTransformer else None
            if CLIP_MODEL_INSTANCE:
                logger.info("CLIP model loaded successfully.")
                return True
            else: 
                logger.error(f"SentenceTransformer was None despite _AVAILABLE flag. Disabling CLIP.")
                ENABLE_CLIP_FILTERING = False
                return False
        except Exception as e:
            logger.error(f"Failed to load CLIP model '{CLIP_MODEL_NAME}': {e}. Disabling CLIP filtering.")
            ENABLE_CLIP_FILTERING = False
            return False
    return True

def _download_image(url: str, attempt: int = 1) -> Tuple[Optional[Union[Any, bytes]], Optional[str]]:
    if not PIL_AVAILABLE:
        logger.warning("Pillow not available. Image dimension validation skipped. Returning raw content if download succeeds.")
        try:
            headers: Dict[str, str] = {'User-Agent': f'DacoolaImageScraper/1.1 (+{WEBSITE_URL_FOR_AGENT})'}
            response: requests.Response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=headers, stream=True)
            response.raise_for_status()
            return response.content, url 
        except Exception as e:
            logger.warning(f"Pillow unavailable & basic image download failed for {url}: {e}")
            return None, None

    if not url or not url.startswith('http'):
        logger.warning(f"Invalid image URL: {url}")
        return None, None
    try:
        headers = {'User-Agent': f'DacoolaImageScraper/1.1 (+{WEBSITE_URL_FOR_AGENT})'}
        response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT, headers=headers, stream=True)
        response.raise_for_status()
        content_type: str = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            logger.warning(f"URL content-type not image ({content_type}): {url}")
            return None, None
        image_data: io.BytesIO = io.BytesIO(response.content)
        if image_data.getbuffer().nbytes == 0:
            logger.warning(f"Downloaded image is empty: {url}")
            return None, None
        
        img_pil: Any = Image.open(image_data) if Image else None 
        if not img_pil: 
            logger.error(f"Image.open failed for {url} despite PIL_AVAILABLE being True (or Image module is None).")
            return None, None
            
        if img_pil.width < MIN_IMAGE_WIDTH or img_pil.height < MIN_IMAGE_HEIGHT:
            logger.warning(f"Image too small ({img_pil.width}x{img_pil.height}) from {url}. Min: {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}.")
            return None, None
        if img_pil.mode != 'RGB':
            img_pil = img_pil.convert('RGB')
        logger.debug(f"Successfully downloaded and validated image: {url} (Size: {img_pil.size})")
        return img_pil, url
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout downloading image (attempt {attempt}): {url}")
        if attempt < IMAGE_DOWNLOAD_RETRIES:
            logger.info(f"Retrying download for {url} in {IMAGE_RETRY_DELAY}s...")
            time.sleep(IMAGE_RETRY_DELAY)
            return _download_image(url, attempt + 1)
        return None, None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None, None
    except UnidentifiedImageError: 
        logger.warning(f"Could not identify image file (Invalid format?) from: {url}")
        return None, None
    except Exception as e:
        logger.warning(f"Error processing image {url}: {e}")
        return None, None

def _filter_images_with_clip(image_results_candidates: List[Dict[str, str]], text_prompt: str) -> Optional[str]:
    if not image_results_candidates: return None
    if not ENABLE_CLIP_FILTERING or not _load_sentence_model_clip() or not CLIP_MODEL_INSTANCE or not st_cos_sim:
        logger.debug("CLIP filtering skipped or model/library unavailable. Returning first downloadable candidate.")
        for img_data_fallback in image_results_candidates:
            url_fallback = img_data_fallback.get('url')
            if url_fallback:
                _, validated_url_fallback = _download_image(url_fallback)
                if validated_url_fallback: return validated_url_fallback
        return None

    logger.info(f"CLIP filtering {len(image_results_candidates)} candidates for prompt: '{text_prompt}'")
    image_objects_for_clip: List[Any] = [] 
    valid_original_urls: List[str] = []
    for img_data in image_results_candidates:
        url: Optional[str] = img_data.get('url')
        if url:
            pil_image_or_bytes, validated_url = _download_image(url)
            if pil_image_or_bytes and validated_url:
                if PIL_AVAILABLE and Image and isinstance(pil_image_or_bytes, Image.Image): 
                    image_objects_for_clip.append(pil_image_or_bytes)
                    valid_original_urls.append(validated_url)
                elif not PIL_AVAILABLE: 
                    logger.warning(f"CLIP filtering attempted but PIL is not available. Cannot process image {validated_url} for CLIP.")
                else:
                    logger.debug(f"Downloaded content for {validated_url} is not a PIL Image. Skipping for CLIP.")
            else: logger.debug(f"Skipping image for CLIP (download/validation failed): {url}")

    if not image_objects_for_clip:
        logger.warning("No images suitable for CLIP analysis after download/validation. Returning first valid candidate from original list if any.")
        for img_data_fallback_post_dl in image_results_candidates:
            url_fallback_post_dl = img_data_fallback_post_dl.get('url')
            if url_fallback_post_dl:
                 _, validated_url_fb_post_dl = _download_image(url_fallback_post_dl)
                 if validated_url_fb_post_dl: return validated_url_fb_post_dl
        return None

    try:
        logger.debug(f"Encoding {len(image_objects_for_clip)} images and text prompt with CLIP...")
        image_embeddings: Any = CLIP_MODEL_INSTANCE.encode(image_objects_for_clip, batch_size=8, convert_to_tensor=True, show_progress_bar=False)
        text_embedding: Any = CLIP_MODEL_INSTANCE.encode([text_prompt], convert_to_tensor=True, show_progress_bar=False)
        similarities: Any = st_cos_sim(text_embedding, image_embeddings)[0] 
        scored_images: List[Dict[str, Any]] = [{'score': score.item(), 'url': valid_original_urls[i]} for i, score in enumerate(similarities)]
        scored_images.sort(key=lambda x: x['score'], reverse=True)
        for i, item in enumerate(scored_images[:3]): logger.debug(f"CLIP Candidate {i+1}: {item['url']}, Score: {item['score']:.4f}")
        best_above_threshold: Optional[Dict[str, Any]] = next((item for item in scored_images if item['score'] >= MIN_CLIP_SCORE), None)
        if best_above_threshold:
            logger.info(f"CLIP selected best image above threshold: {best_above_threshold['url']} (Score: {best_above_threshold['score']:.4f})")
            return best_above_threshold['url']
        elif scored_images:
            logger.warning(f"No images met MIN_CLIP_SCORE ({MIN_CLIP_SCORE}). Taking highest overall: {scored_images[0]['url']} (Score: {scored_images[0]['score']:.4f})")
            return scored_images[0]['url']
        else:
            logger.error("Critical CLIP error: No similarities or images processed. Falling back to first valid original URL if available.")
            return valid_original_urls[0] if valid_original_urls else None
    except Exception as e:
        logger.exception(f"Exception during CLIP processing: {e}. Falling back to first valid original URL if available.")
        return valid_original_urls[0] if valid_original_urls else None

def _scrape_source_for_image(article_url: str) -> Optional[str]:
    if not BS4_AVAILABLE: logger.warning("BeautifulSoup not available. Skipping source image scraping."); return None
    if not article_url or not article_url.startswith('http'): logger.debug(f"Invalid article URL for scraping: {article_url}"); return None
    logger.info(f"Attempting to scrape meta image tag from source: {article_url}")
    try:
        headers: Dict[str, str] = {
            'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DacoolaNewsBot/1.0 (+{WEBSITE_URL_FOR_AGENT})',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        response: requests.Response = requests.get(article_url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()
        if 'html' not in response.headers.get('content-type', '').lower():
            logger.warning(f"Source URL content type not HTML: {article_url}"); return None
        soup: Any = BeautifulSoup(response.content, 'html.parser') if BeautifulSoup else None
        if not soup: return None 
        meta_selectors: List[Dict[str, str]] = [
            {'property': 'og:image'}, {'property': 'og:image:secure_url'},
            {'name': 'twitter:image'}, {'name': 'twitter:image:src'},
            {'itemprop': 'image'}
        ]
        for selector in meta_selectors:
            tag: Optional[Any] = soup.find('meta', attrs=selector)
            if tag and tag.get('content'):
                image_src_candidate = str(tag['content'])
                if image_src_candidate.startswith('//'): image_src_candidate = "https:" + image_src_candidate
                if not image_src_candidate.startswith('http'): image_src_candidate = urljoin(article_url, image_src_candidate)
                if image_src_candidate.startswith('http'):
                    logger.info(f"Found meta image ({selector}): {image_src_candidate}")
                    return image_src_candidate
        logger.warning(f"No suitable image meta tag found at: {article_url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch/scrape source {article_url}: {e}"); return None
    except Exception as e:
        logger.exception(f"Error scraping source image from {article_url}: {e}"); return None

def _search_images_serpapi(query: str, num_results: int = 7) -> Optional[List[Dict[str, str]]]:
    if not SERPAPI_AVAILABLE: logger.error("SerpApi client (google-search-results) not available. Cannot perform image search."); return None
    if not SERPAPI_API_KEY: logger.error("SERPAPI_API_KEY not found. Cannot perform image search."); return None
    params: Dict[str, Any] = IMAGE_SEARCH_PARAMS.copy()
    params['q'] = query
    params['api_key'] = SERPAPI_API_KEY
    try:
        logger.debug(f"Sending SerpApi request: '{query}'")
        search: Any = GoogleSearch(params) if GoogleSearch else None 
        if not search: return None 
        results: Dict[str, Any] = search.get_dict()
        if 'error' in results: logger.error(f"SerpApi error for '{query}': {results['error']}"); return None
        if results.get('images_results'):
            image_data: List[Dict[str, str]] = [{"url": img.get("original"), "title": img.get("title"), "source": img.get("source")}
                                                for img in results['images_results'][:num_results] if img.get("original")]
            if not image_data: logger.warning(f"SerpApi: No results with 'original' URL for '{query}'"); return []
            logger.info(f"SerpApi found {len(image_data)} image candidates for '{query}'")
            return image_data
        logger.warning(f"No image results via SerpApi for '{query}'"); return []
    except Exception as e:
        logger.exception(f"SerpApi image search exception for '{query}': {e}"); return None

def _find_best_image(search_query: str, article_url_for_scrape: Optional[str] = None) -> Optional[str]:
    if not search_query: logger.error("Cannot find image: search_query is empty."); return None
    logger.info(f"Finding best image for query: '{search_query}' (CLIP: {ENABLE_CLIP_FILTERING})")
    if article_url_for_scrape:
        scraped_image_url: Optional[str] = _scrape_source_for_image(article_url_for_scrape)
        if scraped_image_url:
            img_obj, validated_url = _download_image(scraped_image_url)
            if img_obj and validated_url:
                logger.info(f"Using valid image directly scraped from source: {validated_url}")
                return validated_url
            else: logger.warning(f"Scraped image {scraped_image_url} was invalid/too small. Proceeding to search.")
    serpapi_results: Optional[List[Dict[str, str]]] = _search_images_serpapi(search_query)
    if not serpapi_results: logger.error(f"SerpApi returned no image results for '{search_query}'. Cannot find image."); return None
    best_image_url: Optional[str] = None
    if ENABLE_CLIP_FILTERING: # Relies on _load_sentence_model_clip and PIL_AVAILABLE being true
        if _load_sentence_model_clip() and CLIP_MODEL_INSTANCE:
            best_image_url = _filter_images_with_clip(serpapi_results, search_query)
        else:
            logger.debug("CLIP model loading failed or instance not available. Falling back.")
            # Fallback to first valid SerpApi result if CLIP setup fails
            for res in serpapi_results:
                url: Optional[str] = res.get('url')
                if url:
                    img_obj_fb, validated_url_fb = _download_image(url)
                    if img_obj_fb and validated_url_fb:
                        best_image_url = validated_url_fb
                        logger.info(f"Using first valid SerpApi result (CLIP model load failed): {best_image_url}")
                        break
    else:
        logger.debug("CLIP filtering disabled or prerequisites missing. Taking first valid SerpApi result.")
        for res in serpapi_results:
            url = res.get('url')
            if url:
                img_obj, validated_url = _download_image(url)
                if img_obj and validated_url:
                    best_image_url = validated_url
                    logger.info(f"Using first valid SerpApi result (CLIP disabled): {best_image_url}")
                    break
    if not best_image_url: logger.error(f"None of the initial SerpApi results were downloadable/valid for '{search_query}'.")
    if best_image_url: logger.info(f"Selected image URL for '{search_query}': {best_image_url}")
    else: logger.error(f"Could not determine a best image URL for '{search_query}' after all steps.")
    return best_image_url

def _fetch_full_article_text_with_trafilatura(downloaded_html: str, article_url: str) -> Optional[str]:
    if not TRAFILATURA_AVAILABLE: logger.debug(f"Trafilatura not available for {article_url}."); return None
    try:
        extracted_text: Optional[str] = trafilatura.extract(downloaded_html, # type: ignore
                                             include_comments=False, include_tables=False,
                                             output_format='txt', deduplicate=True)
        if extracted_text and len(extracted_text) >= MIN_FULL_TEXT_LENGTH:
            logger.info(f"Successfully extracted text with Trafilatura from {article_url} (Length: {len(extracted_text)})")
            return extracted_text.strip()
        else:
            logger.debug(f"Trafilatura extracted insufficient text (Length: {len(extracted_text or '')}) from {article_url}. Will try fallback.")
            return None
    except Exception as e:
        logger.warning(f"Trafilatura extraction failed for {article_url}: {e}")
        return None

def _fetch_full_article_text_bs_fallback(downloaded_html: str, article_url: str) -> Optional[str]:
    if not BS4_AVAILABLE: logger.warning(f"BeautifulSoup not available for {article_url}."); return None
    try:
        soup: Any = BeautifulSoup(downloaded_html, 'html.parser') if BeautifulSoup else None 
        if not soup: return None 
        tags_to_remove: List[str] = ['script', 'style', 'nav', 'footer', 'aside', 'header', 'form', 'button', 'input',
                          '.related-posts', '.comments', '.sidebar', '.ad', '.banner', '.share-buttons',
                          '.newsletter-signup', '.cookie-banner', '.site-header', '.site-footer',
                          '.navigation', '.menu', '.social-links', '.author-bio', '.pagination',
                          '#comments', '#sidebar', '#header', '#footer', '#navigation', '.print-button',
                          '.breadcrumbs', 'figcaption', 'figure > div']
        for selector in tags_to_remove:
            for element in soup.select(selector): element.decompose()
        for comment_tag in soup.find_all(string=lambda text: isinstance(text, Comment if Comment else object)): comment_tag.extract() 
        main_content_selectors: List[str] = ['article[class*="content"]', 'article[class*="post"]', 'article[class*="article"]',
                                  'main[id*="content"]', 'main[class*="content"]', 'div[class*="article-body"]',
                                  'div[class*="post-body"]', 'div[class*="entry-content"]', 'div[class*="story-content"]',
                                  'div[id*="article"]', 'div#content', 'div#main', '.article-content']
        best_text: str = ""
        for selector in main_content_selectors:
            element: Optional[Any] = soup.select_one(selector)
            if element:
                text_parts: List[str] = []
                for child in element.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'pre']):
                    if child.name == 'p' and child.find('a') and len(child.find_all(text=True, recursive=False)) == 0 and len(child.find_all('a')) == 1:
                        link_text: str = child.find('a').get_text(strip=True)
                        if link_text and len(link_text) > 20: text_parts.append(link_text)
                        continue
                    text_parts.append(child.get_text(separator=' ', strip=True))
                current_text: str = "\n\n".join(filter(None, text_parts)).strip()
                if len(current_text) > len(best_text): best_text = current_text
        if best_text and len(best_text) >= MIN_FULL_TEXT_LENGTH:
            logger.info(f"Successfully extracted text with BeautifulSoup (selector strategy) from {article_url} (Length: {len(best_text)})")
            return best_text
        body: Optional[Any] = soup.find('body')
        if body:
            content_text_from_body: str = ""
            paragraphs: List[Any] = body.find_all('p')
            if paragraphs:
                 text_parts_from_body: List[str] = [p.get_text(separator=' ', strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50]
                 content_text_from_body = "\n\n".join(filter(None, text_parts_from_body)).strip()
            if content_text_from_body and len(content_text_from_body) >= MIN_FULL_TEXT_LENGTH:
                logger.info(f"Fetched meaningful paragraph text (aggressive fallback) from {article_url} (Length: {len(content_text_from_body)})")
                return content_text_from_body
        logger.warning(f"BeautifulSoup fallback could not extract substantial content from {article_url} after all attempts.")
        return None
    except Exception as e:
        logger.error(f"Error parsing full article with BeautifulSoup fallback from {article_url}: {e}")
        return None

def _get_full_article_content(article_url: str) -> Optional[str]:
    if not article_url or not article_url.startswith('http'):
        logger.debug(f"Invalid article_url for full content fetch: {article_url}"); return None
    if not BS4_AVAILABLE and not TRAFILATURA_AVAILABLE : 
        logger.warning("Neither BeautifulSoup nor Trafilatura available. Skipping full article content fetch."); return None
    try:
        headers: Dict[str, str] = {
            'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 DacoolaNewsBot/1.0 (+{WEBSITE_URL_FOR_AGENT})',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9', 'Referer': 'https://www.google.com/'
        }
        response: requests.Response = requests.get(article_url, headers=headers, timeout=ARTICLE_FETCH_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        content_type: str = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"Content type for {article_url} is not HTML ({content_type}). Skipping full text extraction."); return None
        downloaded_html: str = response.text
        content_text: Optional[str] = None
        if TRAFILATURA_AVAILABLE:
            content_text = _fetch_full_article_text_with_trafilatura(downloaded_html, article_url)
        if not content_text and BS4_AVAILABLE:
            logger.info(f"Trafilatura insufficient or unavailable for {article_url}, trying BeautifulSoup fallback.")
            content_text = _fetch_full_article_text_bs_fallback(downloaded_html, article_url)
        return content_text
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch HTML for full article from {article_url}: {e}"); return None
    except Exception as e:
        logger.error(f"Unexpected error in _get_full_article_content for {article_url}: {e}"); return None

def _process_feed_entry(entry: Dict[str, Any], feed_url: str, processed_ids_set: Set[str]) -> Optional[Dict[str, Any]]:
    article_id: str = _get_article_id(entry, feed_url)
    if article_id in processed_ids_set: logger.debug(f"Article ID {article_id} already processed. Skipping."); return None
    title_raw: str = entry.get('title', '').strip()
    title: str = html.unescape(title_raw)
    link: str = entry.get('link', '').strip()
    if not title or not link: logger.warning(f"Skipping entry from {feed_url}: missing title or link. ID: {article_id[:8]}..."); return None
    published_parsed: Optional[Any] = entry.get('published_parsed')
    published_iso: Optional[str] = None
    if published_parsed:
        try:
            dt_obj: datetime = datetime(*published_parsed[:6], tzinfo=timezone.utc)
            published_iso = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception as e: logger.warning(f"Date parse error for {article_id}: {e}. Skipping published_iso.")
    summary_raw_list: List[Dict[str,str]] = entry.get('content', [])
    summary_raw: str = summary_raw_list[0].get('value', '') if summary_raw_list else entry.get('summary', entry.get('description', ''))
    summary: str = html.unescape(summary_raw.strip() if summary_raw else '')
    full_article_text: Optional[str] = _get_full_article_content(link)
    final_content_for_processing: str = ""
    if full_article_text and len(full_article_text) > len(summary): final_content_for_processing = full_article_text
    elif summary: final_content_for_processing = summary
    if not final_content_for_processing or len(final_content_for_processing) < 50:
        logger.warning(f"Article '{title}' ({article_id}) has insufficient content ({len(final_content_for_processing or '')} chars). Skipping."); return None
    image_search_query: str = title or summary
    selected_image_url: Optional[str] = _find_best_image(image_search_query, article_url_for_scrape=link)
    if not selected_image_url: logger.error(f"FATAL: No suitable image found for {article_id}. Skipping processing of this article."); return None
    article_data: Dict[str, Any] = {
        'id': article_id, 'title': title, 'link': link, 'published_iso': published_iso,
        'summary': summary, 'raw_scraped_text': full_article_text,
        'processed_summary': final_content_for_processing, 'source_feed': feed_url,
        'scraped_at_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'selected_image_url': selected_image_url
    }
    logger.info(f"RESEARCH: Processed entry {article_id[:8]}... ('{title[:50]}...') - Image: {selected_image_url[:40]}...")
    return article_data

def _process_gyro_pick_entry(gyro_pick_data: Dict[str, Any], processed_ids_set: Set[str]) -> Optional[Dict[str, Any]]:
    article_id: Optional[str] = gyro_pick_data.get('id')
    primary_url: Optional[str] = gyro_pick_data.get('original_source_url')
    initial_title: Optional[str] = gyro_pick_data.get('initial_title_from_web')
    if not article_id or not primary_url: logger.error(f"Invalid Gyro Pick data: missing ID or URL. Skipping."); return None
    if article_id in processed_ids_set: logger.debug(f"Gyro Pick ID {article_id} already processed. Skipping."); return None
    logger.info(f"RESEARCH: Processing Gyro Pick: {article_id} from {primary_url}")
    raw_scraped_text: Optional[str] = gyro_pick_data.get('raw_scraped_text')
    if not raw_scraped_text:
        logger.info(f"Gyro Pick {article_id}: No manual content, scraping {primary_url}...")
        raw_scraped_text = _get_full_article_content(primary_url)
        if not raw_scraped_text: logger.error(f"Gyro Pick {article_id}: Failed to scrape content from {primary_url}. Skipping."); return None
    title_for_processing: str = initial_title if initial_title else f"Content from {primary_url}"
    if not title_for_processing or len(title_for_processing) < 10: title_for_processing = f"Gyro Pick: {primary_url}"
    selected_image_url: Optional[str] = gyro_pick_data.get('user_provided_image_url_gyro')
    if selected_image_url:
        img_obj, validated_url = _download_image(selected_image_url)
        if not img_obj or not validated_url:
            logger.warning(f"Gyro Pick {article_id}: User-provided image '{selected_image_url}' is invalid. Finding a new one.")
            selected_image_url = _find_best_image(title_for_processing, article_url_for_scrape=primary_url)
            if not selected_image_url: logger.error(f"Gyro Pick {article_id}: User image invalid and no alternative found. Skipping."); return None
        else: selected_image_url = validated_url
    else:
        logger.info(f"Gyro Pick {article_id}: No user image, finding image for '{title_for_processing}'...")
        selected_image_url = _find_best_image(title_for_processing, article_url_for_scrape=primary_url)
        if not selected_image_url: logger.error(f"Gyro Pick {article_id}: No suitable image found. Skipping."); return None
    article_data: Dict[str, Any] = {
        'id': article_id, 'title': initial_title, 'link': primary_url,
        'published_iso': gyro_pick_data.get('published_iso', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')),
        'summary': gyro_pick_data.get('initial_title_from_web', 'Gyro Pick Content'),
        'raw_scraped_text': raw_scraped_text, 'processed_summary': raw_scraped_text,
        'source_feed': 'Gyro Pick', 'scraped_at_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'selected_image_url': selected_image_url, 'is_gyro_pick': True,
        'gyro_pick_mode': gyro_pick_data.get('gyro_pick_mode', 'Unknown'),
        'user_importance_override_gyro': gyro_pick_data.get('user_importance_override_gyro'),
        'user_is_trending_pick_gyro': gyro_pick_data.get('user_is_trending_pick_gyro'),
        'all_source_links_gyro': gyro_pick_data.get('all_source_links_gyro', [])
    }
    logger.info(f"RESEARCH: Processed Gyro Pick {article_id[:8]}... ('{initial_title[:50]}...') - Image: {selected_image_url[:40]}...")
    return article_data

def run_research_agent(processed_ids_set: Set[str], max_articles_to_fetch: int, gyro_picks_data_list: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    logger.info(f"--- Research Agent Starting Run ---")
    logger.info(f"Current processed IDs count: {len(processed_ids_set)}")
    logger.info(f"Max articles to fetch this run: {max_articles_to_fetch}")
    newly_researched_articles: List[Dict[str, Any]] = []
    articles_fetched_this_run: int = 0
    if gyro_picks_data_list:
        logger.info(f"Processing {len(gyro_picks_data_list)} Gyro Pick(s)...")
        for gyro_data in gyro_picks_data_list:
            if articles_fetched_this_run >= max_articles_to_fetch:
                logger.warning(f"Hit max articles ({max_articles_to_fetch}) while processing Gyro Picks. Stopping.")
                break
            processed_gyro_article: Optional[Dict[str, Any]] = _process_gyro_pick_entry(gyro_data, processed_ids_set)
            if processed_gyro_article:
                newly_researched_articles.append(processed_gyro_article)
                processed_ids_set.add(processed_gyro_article['id'])
                articles_fetched_this_run += 1
                time.sleep(1)
    if not FEEDPARSER_AVAILABLE:
        logger.error("feedparser is not installed. Skipping RSS feed processing.")
    else:
        logger.info(f"Processing {len(NEWS_FEED_URLS)} RSS Feeds...")
        for feed_url in NEWS_FEED_URLS:
            if articles_fetched_this_run >= max_articles_to_fetch:
                logger.warning(f"Hit max articles ({max_articles_to_fetch}) while processing RSS feeds. Stopping.")
                break
            logger.info(f"Checking feed: {feed_url}")
            try:
                feed_request_headers: Dict[str, str] = {'User-Agent': 'DacoolaNewsBot/1.0 (+https://dacoolaa.netlify.app) FeedFetcher'}
                feed_data: Any = feedparser.parse(feed_url, agent=feed_request_headers['User-Agent'], request_headers=feed_request_headers) # type: ignore
                http_status: Optional[int] = getattr(feed_data, 'status', None)
                if http_status and (http_status < 200 or http_status >= 400):
                    logger.error(f"Failed to fetch feed {feed_url}. HTTP Status: {http_status}")
                    continue
                if feed_data.bozo:
                    bozo_reason: Any = feed_data.get('bozo_exception', Exception("Unknown feedparser error"))
                    bozo_message: str = str(bozo_reason).lower()
                    if ("content-type" in bozo_message and
                        ("xml" not in bozo_message and "rss" not in bozo_message and "atom" not in bozo_message)):
                        logger.error(f"Failed to fetch feed {feed_url}: Content type was not XML/RSS/Atom ({bozo_reason}). Skipping.")
                        continue
                    elif "ssl error" in bozo_message:
                         logger.error(f"Failed to fetch feed {feed_url} due to SSL Error: {bozo_reason}. Skipping.")
                         continue
                    else:
                        logger.warning(f"Feed {feed_url} potentially malformed (bozo). Reason: {bozo_reason}. Attempting to process...")
                if not feed_data.entries: logger.info(f"No entries found in feed: {feed_url}"); continue
                logger.info(f"Feed {feed_url} contains {len(feed_data.entries)} entries.")
                for entry in feed_data.entries:
                    if articles_fetched_this_run >= max_articles_to_fetch:
                        logger.warning(f"Hit max articles ({max_articles_to_fetch}) while processing {feed_url}. Stopping.")
                        break
                    processed_article: Optional[Dict[str, Any]] = _process_feed_entry(entry, feed_url, processed_ids_set)
                    if processed_article:
                        newly_researched_articles.append(processed_article)
                        processed_ids_set.add(processed_article['id'])
                        articles_fetched_this_run += 1
                        time.sleep(1)
            except Exception as e: logger.exception(f"Unexpected error processing feed {feed_url}: {e}")
    logger.info(f"--- Research Agent Finished. Total new articles fetched and enriched: {len(newly_researched_articles)} ---")
    return newly_researched_articles

if __name__ == "__main__":
    logger.info("--- Running Research Agent Standalone Test ---")
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    test_processed_ids: Set[str] = set()
    # Using a more stable, known-good URL for the Gyro Pick test
    test_gyro_picks_data: List[Dict[str, Any]] = [
        {
            'id': 'gyro-test-stable-001',
            'original_source_url': 'https://www.theverge.com/2023/10/26/23933448/meta-stock-q3-2023-earnings-reality-labs-losses', # Example of a stable past article
            'initial_title_from_web': 'Meta Q3 2023 Earnings Report',
            'raw_scraped_text': None,
            'user_provided_image_url_gyro': None,
            'published_iso': '2023-10-26T10:00:00Z',
            'is_gyro_pick': True, 'gyro_pick_mode': 'Advanced',
            'user_importance_override_gyro': 'Interesting', 'user_is_trending_pick_gyro': False
        }
    ]
    fetched_articles_for_test: List[Dict[str, Any]] = run_research_agent(
        processed_ids_set=test_processed_ids,
        max_articles_to_fetch=3, # Fetch a few articles for testing
        gyro_picks_data_list=test_gyro_picks_data
    )
    print("\n--- Research Agent Standalone Test Results Summary ---")
    print(f"Total articles fetched and enriched: {len(fetched_articles_for_test)}")
    for article in fetched_articles_for_test:
        print(f"\nID: {article['id']}")
        print(f"Title: {article['title']}")
        print(f"Link: {article['link']}")
        print(f"Image: {article['selected_image_url']}")
        print(f"Content Length (raw_scraped_text): {len(article.get('raw_scraped_text', ''))}")
        print(f"Content Length (processed_summary): {len(article.get('processed_summary', ''))}")
        print(f"Source: {article.get('source_feed')}")
        print(f"Is Gyro Pick: {article.get('is_gyro_pick', False)}")
    print("\n--- Research Agent Standalone Test Complete ---")
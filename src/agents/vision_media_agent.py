# src/agents/vision_media_agent.py
"""
Vision & Media Agent (ASI-Level ULTRA v3.9 - Corrected LLaVA Processor Import)
Multi-Stage Image Strategy & Selection with advanced VLM capabilities,
robust validation, and intelligent curation.
Uses AutoProcessor for LLaVA compatibility with transformers >= 4.31 (approx).
"""

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
from PIL import Image, UnidentifiedImageError, ImageFile, ExifTags
ImageFile.LOAD_TRUNCATED_IMAGES = True

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

# --- Path Setup & Env Load ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Public API of this module ---
__all__ = ['run_vision_media_agent']

# --- Global flag for controlling simulation during standalone test ---
STANDALONE_TEST_MODE_SIMULATION_ACTIVE = False

# --- Library Availability Flags & Initializations ---
DDGS_AVAILABLE = False
SELENIUM_AVAILABLE = False
HF_TRANSFORMERS_AVAILABLE = False
TORCH_AVAILABLE = False
FLORENCE2_MODEL_LOADED = False
LLAVA_MODEL_LOADED = False
CLIP_MODEL_LOADED_ST = False
IMAGEHASH_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
    DEVICE_VLM = "cuda" if torch.cuda.is_available() else "cpu"
    if DEVICE_VLM == "cuda":
        if hasattr(torch.cuda, 'is_bf16_supported') and torch.cuda.is_bf16_supported():
            TORCH_DTYPE_VLM = torch.bfloat16
        else:
            TORCH_DTYPE_VLM = torch.float16
    else:
        TORCH_DTYPE_VLM = torch.float32
    logging.info(f"PyTorch {torch.__version__} found. Device: {DEVICE_VLM}, Target DType for VLM: {TORCH_DTYPE_VLM}")
except ImportError:
    DEVICE_VLM = "cpu"; TORCH_DTYPE_VLM = None
    logging.warning("PyTorch import FAILED. VLM capabilities will be severely limited.")

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True; logging.info("duckduckgo_search library found.")
except ImportError:
    DDGS = None; logging.warning("duckduckgo_search library import FAILED. Web page image search disabled.")

AutoProcessorImport, AutoModelForVision2SeqImport, AutoModelForCausalLMImport, LlavaForConditionalGenerationImport = None, None, None, None
try:
    # For LLaVA, AutoProcessor should generally work. We don't need a specific LlavaProcessor or LlavaAutoProcessor.
    from transformers import AutoProcessor, AutoModelForVision2Seq, AutoModelForCausalLM, LlavaForConditionalGeneration
    HF_TRANSFORMERS_AVAILABLE = True
    AutoProcessorImport = AutoProcessor
    AutoModelForVision2SeqImport = AutoModelForVision2Seq
    AutoModelForCausalLMImport = AutoModelForCausalLM
    LlavaForConditionalGenerationImport = LlavaForConditionalGeneration
    logging.info("Hugging Face Transformers library and key components (using AutoProcessor for LLaVA) imported successfully.")
except ImportError as e_hf:
    logging.warning(f"Hugging Face Transformers components import FAILED: {e_hf}. Florence-2 & LLaVA VLM will be disabled.")
    HF_TRANSFORMERS_AVAILABLE = False


ST_CLIPModelImport, ST_utilImport, cos_sim = None, None, None
try:
    from sentence_transformers import SentenceTransformer as ST_CLIPModelImport_lib, util as ST_utilImport_lib
    CLIP_AVAILABLE_ST = True
    ST_CLIPModelImport = ST_CLIPModelImport_lib
    ST_utilImport = ST_utilImport_lib
    cos_sim = ST_utilImport.cos_sim
    logging.info("SentenceTransformer library (for CLIP) imported successfully.")
except ImportError as e_st:
    logging.warning(f"SentenceTransformer (for CLIP) import FAILED: {e_st}. CLIP scoring will be disabled.")
    CLIP_AVAILABLE_ST = False

try:
    import imagehash
    IMAGEHASH_AVAILABLE = True; logging.info("imagehash library found.")
except ImportError:
    imagehash = None; logging.warning("imagehash library import FAILED. Visual diversity checks disabled.")

WEBDRIVER_PATH = os.getenv("VMA_WEBDRIVER_PATH")
SELENIUM_HEADLESS = os.getenv("VMA_SELENIUM_HEADLESS", "true").lower() == "true"
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.common.exceptions import WebDriverException
    SELENIUM_AVAILABLE = True
    logging.info("Selenium library found.")
except ImportError:
    logging.warning("Selenium library import FAILED. Advanced scraping with headless browser will be disabled.")

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s-%(name)s-%(levelname)s-[%(module)s.%(funcName)s:%(lineno)d]-%(message)s', handlers=[logging.StreamHandler(sys.stdout)])

# --- Configuration Constants ---
DEEPSEEK_API_KEY_VMA = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_VMA = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_STRATEGY = os.getenv("VMA_MODEL_STRATEGY", "deepseek-chat")
DEEPSEEK_MODEL_CURATOR = os.getenv("VMA_MODEL_CURATOR", "deepseek-chat")
API_TIMEOUT_MEDIA_STRATEGY = int(os.getenv("VMA_TIMEOUT_STRATEGY", "240"))
API_TIMEOUT_CURATOR_LLM = int(os.getenv("VMA_TIMEOUT_CURATOR", "240"))
HF_FLORENCE2_MODEL_ID = os.getenv("VMA_FLORENCE2_MODEL_ID", "microsoft/Florence-2-large-ft")
HF_LLAVA_MODEL_ID = os.getenv("VMA_LLAVA_MODEL_ID", "llava-hf/llava-1.5-13b-hf")
WEBSITE_URL_VMA = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')
IMAGE_DOWNLOAD_TIMEOUT_VMA = int(os.getenv("VMA_DOWNLOAD_TIMEOUT", "40"))
IMAGE_DOWNLOAD_RETRIES_VMA = int(os.getenv("VMA_DOWNLOAD_RETRIES", "3"))
IMAGE_RETRY_DELAY_VMA = int(os.getenv("VMA_RETRY_DELAY", "15"))
MIN_IMAGE_WIDTH_VMA = int(os.getenv("VMA_MIN_WIDTH_STRICT", "680"))
MIN_IMAGE_HEIGHT_VMA = int(os.getenv("VMA_MIN_HEIGHT_STRICT", "380"))
MIN_IMAGE_FILESIZE_BYTES_VMA = int(os.getenv("VMA_MIN_FILESIZE_KB_STRICT", "80")) * 1024
ADAPTIVE_MIN_IMAGE_WIDTH_VMA = int(os.getenv("VMA_MIN_WIDTH_ADAPTIVE", "480"))
ADAPTIVE_MIN_IMAGE_HEIGHT_VMA = int(os.getenv("VMA_MIN_HEIGHT_ADAPTIVE", "300"))
ADAPTIVE_MIN_IMAGE_FILESIZE_BYTES_VMA = int(os.getenv("VMA_MIN_FILESIZE_KB_ADAPTIVE", "40")) * 1024
ADAPTIVE_THRESHOLD_TRIGGER_CANDIDATE_COUNT = int(os.getenv("VMA_ADAPTIVE_TRIGGER_COUNT", "3"))
DEFAULT_PLACEHOLDER_IMAGE_URL = os.getenv("VMA_DEFAULT_PLACEHOLDER_URL", "https://via.placeholder.com/1200x675.png?text=Image+Not+Available")
DDG_MAX_RESULTS_FOR_IMAGE_PAGES = int(os.getenv("VMA_DDG_PAGE_SEARCH_RESULTS", "7"))
DDG_QUERY_DELAY_MIN = int(os.getenv("VMA_DDG_QUERY_DELAY_MIN", "10"))
DDG_QUERY_DELAY_MAX = int(os.getenv("VMA_DDG_QUERY_DELAY_MAX", "20"))
DDG_PAGE_SCRAPE_DELAY_MIN = int(os.getenv("VMA_DDG_PAGE_SCRAPE_DELAY_MIN", "3"))
DDG_PAGE_SCRAPE_DELAY_MAX = int(os.getenv("VMA_DDG_PAGE_SCRAPE_DELAY_MAX", "7"))
CLIP_MODEL_NAME_ST = os.getenv("VMA_CLIP_MODEL_NAME", 'openai/clip-vit-large-patch14')
ENABLE_CLIP_SCORING = CLIP_AVAILABLE_ST and (os.getenv("VMA_ENABLE_CLIP", "true").lower() == "true")
MIN_CLIP_SCORE_VMA = float(os.getenv("VMA_MIN_CLIP_SCORE", "0.28"))
IMAGEHASH_SIMILARITY_THRESHOLD = int(os.getenv("VMA_IMAGEHASH_THRESHOLD", "2"))
ALT_TEXT_TARGET_MIN_LEN = int(os.getenv("VMA_ALT_TEXT_MIN_LEN", "90"))
ALT_TEXT_TARGET_MAX_LEN = int(os.getenv("VMA_ALT_TEXT_MAX_LEN", "125"))
MAX_CANDIDATES_TO_VALIDATE_PER_SLOT = int(os.getenv("VMA_MAX_VALIDATE_PER_SLOT", "40"))
MAX_CANDIDATES_TO_ANALYZE_VLM_PER_SLOT = int(os.getenv("VMA_MAX_ANALYZE_VLM_PER_SLOT", "15"))
MAX_CANDIDATES_TO_CURATOR_LLM_PER_SLOT = int(os.getenv("VMA_MAX_CURATE_LLM_PER_SLOT", "7"))
USER_AGENT_LIST_VMA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    f"Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) DacoolaImageFetcher/3.9 (+{WEBSITE_URL_VMA})", # Version bump
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)"
]

vlm_processor_florence, vlm_model_florence = None, None
vlm_processor_llava, vlm_model_llava = None, None
clip_model_instance_st = None

def requests_retry_session(retries=IMAGE_DOWNLOAD_RETRIES_VMA, backoff_factor=IMAGE_RETRY_DELAY_VMA/3, status_forcelist=(500, 502, 503, 504, 403, 429, 408), session=None):
    session = session or requests.Session()
    retry = Retry(total=retries, read=retries, connect=retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist, allowed_methods=frozenset(['HEAD', 'GET']))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter); session.mount('https://', adapter)
    return session

# --- Stage 0 Prompt (Media Strategist Prime) ---
MEDIA_STRATEGIST_PRIME_SYSTEM_PROMPT_V2 = """
You are **MEDIA_STRATEGIST_PRIME**, a world-class ASI-level media strategist for a high-end autonomous tech news platform. Your role is to design the **perfect image acquisition strategy** for a news article by outputting a **precise JSON strategy object** with the structure outlined below.

---

**Your mission: Maximize visual storytelling, SEO, and emotional impact.** Act like an elite tech editorial director, visual branding expert, and AI vision strategist combined.

---

**YOU WILL RECEIVE (as part of the user message, within a JSON object):**
* `article_title` (string)
* `primary_keyword` (string)
* `article_summary` (string)
* `source_url` (string, optional)
* `image_placeholders_input`: Array of objects (or empty) like: `{"id": "ph1", "description": "desired visual", "section_context": "context"}`

---

**REQUIRED JSON OUTPUT STRUCTURE (STRICT):**
```json
{
  "featured_image_strategy": {
    "ideal_image_type_description": "<string, max 350 chars>",
    "preferred_aspect_ratio": "<string, e.g., '16:9 landscape', '4:3 landscape', '1:1 square', 'flexible'>",
    "primary_search_query": "<string, 3-8 words, hyper-relevant to article>",
    "secondary_search_queries": ["<string>", "<string>", "<string>"]
  },
  "in_article_image_strategies": [
    {
      "placeholder_id_ref": "<string, echoed from input>",
      "placeholder_description_original": "<string, echoed from input>",
      "ideal_image_type_description": "<string, max 350 chars, specific to placeholder>",
      "primary_search_query": "<string, 3-8 words, specific to placeholder>",
      "secondary_search_queries": ["<string>", "<string>", "<string>"],
      "preliminary_alt_text_suggestion": "<string, 100-125 chars, human-grade SEO, specific to placeholder>"
    }
  ]
}
```
* If your output deviates from this schema, respond with an error JSON: `{ "error": "schema_violation", "details": "Explanation of deviation" }`. This is critical for automated parsing.

---

**MANDATES:**
* **ideal_image_type_description**: Describe the perfect image: mood (dramatic, minimal), composition (close-up, wide-angle), style (photojournalism, cinematic, 3D render, cyberpunk, infographic). Enforce character limit <350 chars>.
* **preferred_aspect_ratio**: Suggest '16:9 landscape', '4:3 landscape', '1:1 square', or 'flexible' if no strong preference.
* **primary_search_query**: Focused, high-signal search query. Use specific model names, company names, or event types if known.
* **secondary_search_queries**: Three creative variations, including conceptual terms, action verbs, or related technologies.
* **preliminary_alt_text_suggestion** (in-article only): 100–125 characters, descriptive, human-grade, screen-reader optimized, SEO-aligned with the placeholder's context and primary article keyword.

---

**RULES:**
1. **Return ONLY the JSON object.** No other text.
2. Every suggestion must aim for **tech editorial excellence, engagement, and accessibility.**
3. Tailor in-article strategies to `description` and `section_context`. `placeholder_id_ref` and `placeholder_description_original` must match input.
4. Featured image: most impactful for the whole article, considering `article_title`, `primary_keyword`, and `article_summary`.

---

**FEW-SHOT EXAMPLES:**

*Example 1: AI Ethics Article*
Input: `{"article_title": "The AI Bias Trap: How Algorithms Reinforce Inequality", "primary_keyword": "AI ethics", "article_summary": "Deep dive into how AI models can perpetuate societal biases, with examples in hiring and criminal justice. Explores mitigation strategies.", "image_placeholders_input": [{"id": "ph_bias_example", "description": "Image depicting AI making a biased decision related to hiring", "section_context": "Section discussing algorithmic bias in recruitment"}]}`
Output (Conceptual):
```json
{
  "featured_image_strategy": {
    "ideal_image_type_description": "Symbolic representation of AI and justice. A split image: one side a diverse group of people, other side algorithm nodes; a subtle crack or imbalance between them. Mood: Concerned, thoughtful. Style: Abstract digital art with clean lines. <350 chars>",
    "preferred_aspect_ratio": "16:9 landscape",
    "primary_search_query": "AI algorithmic bias ethical concerns abstract",
    "secondary_search_queries": ["machine learning fairness ethics concept art", "AI decision making bias representation", "artificial intelligence societal impact diversity"]
  },
  "in_article_image_strategies": [
    {
      "placeholder_id_ref": "ph_bias_example",
      "placeholder_description_original": "Image depicting AI making a biased decision related to hiring",
      "ideal_image_type_description": "Professional, editorial-style illustration showing diverse job candidates with an AI algorithm icon subtly favoring one group over others. Mood: Illustrative, serious. Style: Clean vector illustration or a desaturated photo-composite. <350 chars>",
      "primary_search_query": "AI hiring bias infographic diverse candidates",
      "secondary_search_queries": ["algorithmic discrimination recruitment illustration", "AI fairness job application example", "biased AI HR tool visual"],
      "preliminary_alt_text_suggestion": "Illustration depicting an AI algorithm reviewing job applications, highlighting potential AI ethics concerns and bias in hiring processes."
    }
  ]
}
```
---
**This is elite-level image planning. Precision is mandatory.**
"""

# --- Stage 5 LLM Prompt (Image Curator Prime) ---
IMAGE_CURATOR_PRIME_SYSTEM_PROMPT_V2 = """
You are **IMAGE_CURATOR_PRIME**, an ASI-level image curator and vision expert. Your job is to analyze candidate images using advanced reasoning and visual understanding, select the **single best** image per image slot, and return a **final JSON object** with your judgment.

You must apply **extremely high standards** of visual quality, semantic alignment, SEO, and accessibility.

---

**INPUTS YOU RECEIVE (as a JSON object in the user message):**
```json
{
  "image_slot_type": "<'featured_image' or 'in_article_placeholder'>",
  "placeholder_id_ref": "<string, if in_article_placeholder, otherwise 'featured_image'>",
  "original_context_description": "<string, description of where and why this image appears>",
  "ideal_image_type_description": "<string, gold standard image blueprint from Media Strategist Prime>",
  "primary_keyword_for_alt_text": "<string, core keyword/topic for SEO purposes>",
  "candidate_images": [
    {
      "url": "<string>", "vlm_description": "<string>",
      "relevance_score": "<float>", "quality_score": "<float>",
      "preliminary_alt_text": "<string>",
      "exif_data_summary": "<string, e.g., 'Copyright: Example Corp, Artist: John Doe' or 'No relevant EXIF'>"
    }
    // ... more candidates (up to 5-7 top ones will be provided)
  ]
}
```

---

**YOUR OUTPUT MUST BE THIS JSON FORMAT (STRICTLY):**
```json
{
  "selected_image_url": "<string or null>",
  "final_alt_text": "<string, 100-125 chars, human-readable, SEO-optimized>",
  "curation_rationale": "<string, 1-3 sentences explaining choice or rejection, referencing specific visual elements and alignment with ideal_image_type_description>"
}
```
* If your output deviates from this schema, respond with an error JSON: `{ "error": "schema_violation", "details": "Explanation of deviation" }`. This is critical for automated parsing.

---

**SELECTION CRITERIA:**
1. **Perfect alignment with `ideal_image_type_description`**: Match **mood**, **composition**, **style**. The image must visually embody the concept.
2. **High visual quality**: No artifacts, blur, poor lighting, clutter. High resolution, professional aesthetic.
3. **Semantic clarity & Relevance**: Confirmed by `vlm_description` and your own visual assessment – must visually represent the topic from `original_context_description` & `ideal_image_type_description`.
4. **SEO-perfect alt text**: Must be between 100 and 125 characters. Natural, descriptive. Includes `primary_keyword_for_alt_text` (or close variant) naturally. No "Image of..." or "Picture of...". You must validate this length and keyword inclusion.
5. **Uniqueness/Licensing Hint (from EXIF)**: If EXIF data suggests a stock photo or restrictive copyright, and a more unique/original-looking option of similar quality exists, prefer the unique one. Note this in rationale.
6. **Curation rationale**: Clear, specific explanation referencing visual elements and strategic alignment.

---

**FEW-SHOT EXAMPLE (Illustrative Logic):**
Input:
```json
{
  "image_slot_type": "featured_image", "placeholder_id_ref": "featured_image",
  "original_context_description": "NVIDIA's new Blackwell B200 AI GPU launch event highlights",
  "ideal_image_type_description": "Dynamic, high-tech shot of the NVIDIA Blackwell B200 GPU being presented on stage, possibly by CEO, with dramatic lighting. Mood: Exciting, groundbreaking. Style: Event photography, cinematic.",
  "primary_keyword_for_alt_text": "NVIDIA Blackwell B200",
  "candidate_images": [
    {"url": "url1.jpg", "vlm_description": "Close-up of a generic, older-looking computer chip on a workbench.", "relevance_score": 0.5, "quality_score": 0.6, "preliminary_alt_text": "Old computer chip", "exif_data_summary": "No relevant EXIF"},
    {"url": "url2.jpg", "vlm_description": "Wide shot of Jensen Huang on stage presenting the NVIDIA Blackwell B200 GPU, with the GPU clearly visible on screen behind him. Stage lighting is vibrant.", "relevance_score": 0.95, "quality_score": 0.9, "preliminary_alt_text": "Jensen Huang presents NVIDIA Blackwell B200", "exif_data_summary": "Copyright: NVIDIA Corp."},
    {"url": "url3.jpg", "vlm_description": "Abstract representation of AI data flows with blue and green colors.", "relevance_score": 0.6, "quality_score": 0.8, "preliminary_alt_text": "AI data abstract", "exif_data_summary": "Artist: AI Art Generator"}
  ]
}
```
Expected Output:
```json
{
  "selected_image_url": "url2.jpg",
  "final_alt_text": "NVIDIA CEO Jensen Huang unveils the groundbreaking Blackwell B200 AI GPU on stage at GTC, showcasing its next-generation architecture.",
  "curation_rationale": "Selected 'url2.jpg' for its excellent alignment with the 'on-stage presentation' and 'dynamic lighting' aspects of the ideal description, clearly featuring the NVIDIA Blackwell B200. High relevance and quality. EXIF indicates official source."
}
```
---
**Deliver editorial-grade, accessible, emotionally resonant image selection. Never settle.**
If no candidate meets the bar, respond with `selected_image_url: null` and explain in rationale.
**Internally verify that the `primary_keyword_for_alt_text` is present in your `final_alt_text` before outputting.**
"""

# --- Stage 0 Function ---
def _get_image_strategy_from_llm_impl(article_title, primary_keyword, article_summary, image_placeholders_input, source_url=None) -> dict | None:
    if not DEEPSEEK_API_KEY_VMA: logger.error("DEEPSEEK_API_KEY_VMA not set for Media Strategist Prime."); return None
    llm_input_data = {"article_title": article_title, "primary_keyword": primary_keyword, "article_summary": article_summary, "image_placeholders_input": image_placeholders_input or []}
    if source_url: llm_input_data["source_url"] = source_url
    user_content_json_str = json.dumps(llm_input_data)
    payload = {"model": DEEPSEEK_MODEL_STRATEGY, "messages": [{"role": "system", "content": MEDIA_STRATEGIST_PRIME_SYSTEM_PROMPT_V2}, {"role": "user", "content": user_content_json_str}], "temperature": 0.55, "max_tokens": 3000, "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_VMA}", "Content-Type": "application/json"}
    strategy_text_for_error_log = ""
    try:
        logger.info(f"Requesting LLM image strategy for: {article_title[:50]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_VMA, headers=headers, json=payload, timeout=API_TIMEOUT_MEDIA_STRATEGY)
        response.raise_for_status()
        strategy_text_for_error_log = response.json()["choices"][0]["message"]["content"]
        strategy = json.loads(strategy_text_for_error_log)
        if "featured_image_strategy" not in strategy or "in_article_image_strategies" not in strategy:
            logger.error(f"LLM strategy output missing core keys for {article_title[:50]}. Output: {strategy_text_for_error_log[:200]}"); return None
        logger.info(f"LLM image strategy received for {article_title[:50]}.")
        return strategy
    except json.JSONDecodeError as je:
        logger.error(f"LLM image strategy JSON decode failed for {article_title[:50]}: {je}. Raw text: {strategy_text_for_error_log[:500]}")
        if "error\": \"schema_violation" in strategy_text_for_error_log.lower():
            logger.error("LLM reported a schema violation for its own strategy output.")
        return None
    except Exception as e: logger.error(f"LLM image strategy failed for {article_title[:50]}: {e}", exc_info=True); return None

# --- Stage 1: Aggressive Source URL Image Extraction ---
def _scrape_images_from_url_aggressively_stage1_impl(page_url: str, base_url_for_relative: str, session: requests.Session) -> list:
    if not page_url or not page_url.startswith('http'): return []
    logger.info(f"Stage 1 (Aggressive): Scraping URL for images: {page_url}")
    candidate_images = []; seen_urls_scrape = set()
    current_user_agent = random.choice(USER_AGENT_LIST_VMA)
    session.headers.update({'User-Agent': current_user_agent, 'Referer': base_url_for_relative, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    try:
        response = session.get(page_url, timeout=IMAGE_DOWNLOAD_TIMEOUT_VMA, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if not ('html' in content_type or 'xml' in content_type):
            logger.warning(f"Content type not HTML/XML for aggressive scrape: {page_url} (Type: {content_type})"); return []
        soup = BeautifulSoup(response.content, 'lxml') # Changed to lxml for potentially better parsing
        meta_selectors = [{'property': 'og:image'}, {'property': 'og:image:secure_url'}, {'name': 'twitter:image'}, {'name': 'twitter:image:src'}, {'itemprop': 'image'}, {'name': 'sailthru.image.full'}, {'name': 'sailthru.image.thumb'}]
        for selector in meta_selectors:
            tag = soup.find('meta', attrs=selector)
            if tag and tag.get('content'):
                img_url = urljoin(base_url_for_relative, tag['content'].strip())
                if img_url.startswith('http') and img_url not in seen_urls_scrape:
                     candidate_images.append({'url': img_url, 'title': 'Meta Tag Image', 'source_engine': 'Direct Scrape (Meta)'}); seen_urls_scrape.add(img_url)
        for script_tag in soup.find_all('script', type='application/ld+json'):
            try:
                ld_data_str = script_tag.string
                if not ld_data_str: continue
                # Remove comments from JSON-LD before parsing
                ld_data_str_no_comments = re.sub(r'//.*?\n|/\*.*?\*/', '', ld_data_str, flags=re.DOTALL)
                ld_data = json.loads(ld_data_str_no_comments); img_sources_ld = []
                if isinstance(ld_data, list): ld_data = ld_data[0] if ld_data else {}
                img_ld_prop = ld_data.get('image')
                if isinstance(img_ld_prop, str): img_sources_ld.append(img_ld_prop)
                elif isinstance(img_ld_prop, dict): img_sources_ld.append(img_ld_prop.get('url'))
                elif isinstance(img_ld_prop, list):
                    for item in img_ld_prop:
                        if isinstance(item, str): img_sources_ld.append(item)
                        elif isinstance(item, dict): img_sources_ld.append(item.get('url'))
                for ld_url in filter(None, img_sources_ld):
                    img_url = urljoin(base_url_for_relative, ld_url.strip())
                    if img_url.startswith('http') and img_url not in seen_urls_scrape:
                        candidate_images.append({'url': img_url, 'title': 'JSON-LD Image', 'source_engine': 'Direct Scrape (JSON-LD)'}); seen_urls_scrape.add(img_url)
            except Exception as e_jsonld: logger.debug(f"Error parsing JSON-LD on {page_url}: {e_jsonld}")
        for img_tag in soup.find_all('img', limit=75):
            srcs = list(filter(None, [img_tag.get('src'), img_tag.get('data-src'), img_tag.get('data-lazy-src'), img_tag.get('data-original'), img_tag.get('data-fallback-src')]))
            if img_tag.get('srcset'):
                try:
                    srcset_parts = [s.strip().split(' ')[0] for s in img_tag.get('srcset').split(',')]
                    srcset_urls = [url_part for url_part in srcset_parts if url_part]
                    srcset_urls.sort(key=lambda x: (('avatar' in x.lower() or 'thumb' in x.lower() or 'profile' in x.lower() or 'icon' in x.lower() or 'logo' in x.lower()), -len(x)))
                    if srcset_urls: srcs.insert(0, srcset_urls[0])
                except Exception as e_srcset: logger.debug(f"Error parsing srcset for an image on {page_url}: {e_srcset}")
            parent_picture = img_tag.find_parent('picture')
            if parent_picture:
                for source_tag in parent_picture.find_all('source'):
                    srcset = source_tag.get('srcset')
                    if srcset: srcs.extend(s.strip().split(' ')[0] for s in srcset.split(','))
            for p_url in set(srcs):
                img_url = urljoin(base_url_for_relative, p_url.strip())
                if img_url.startswith('http') and not any(skip in img_url.lower() for skip in ['.gif', '.svg', 'logo', 'icon', 'avatar', 'ads.', 'pixel.', 'spinner', 'loading', 'banner', 'sprite', 'data:image/', 'badge', 'button', 'thumb', 'profile', 'gravatar', 'share', 'symbol', 'pattern', 'background', 'gradient', 'overlay', 'placeholder', 'spacer', 'emote', 'sticker', 'flag', 'feed', 'icon-', '-icon', '_icon', '/icon/', '.ico', 'sharelogo', 'reaction', 'captcha', 'rating', 'counter', 'loader', 'empty', 'blank', 'pixel', 'track', 'lazy', 'skeleton']) and img_url not in seen_urls_scrape:
                    candidate_images.append({'url': img_url, 'title': img_tag.get('alt','Content Img from page scrape'), 'source_engine': 'Direct Scrape (Img Tag)'}); seen_urls_scrape.add(img_url)
        logger.info(f"Stage 1 (Aggressive): Found {len(candidate_images)} unique candidates from {page_url}.")
        return candidate_images
    except requests.exceptions.RequestException as e:
        logger.error(f"Stage 1 (Aggressive) scrape error for {page_url} after retries: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.debug(f"  Final response status: {e.response.status_code}, Headers: {e.response.headers}")
    except Exception as e: logger.error(f"Stage 1 (Aggressive) unexpected error {page_url}: {e}", exc_info=True)
    return []

# --- Stage 2: Indirect Image Search via DuckDuckGo Page Search ---
def _search_pages_for_images_stage2_impl(query_list: list, session: requests.Session) -> list:
    if not DDGS_AVAILABLE: logger.error("DDGS not available for Stage 2 page search."); return []
    logger.info(f"Stage 2 (DDG Page Search): Searching for pages with {len(query_list)} queries.")
    all_img_candidates = []
    ddgs_instance = DDGS(timeout=35, proxies=session.proxies if session and hasattr(session, 'proxies') else None) if DDGS else None
    if not ddgs_instance: logger.error("DDGS instance could not be created."); return []
    for i, query in enumerate(query_list):
        if not query: continue
        logger.debug(f"  DDG Text Query {i+1}/{len(query_list)}: '{query}'")
        page_hits = []
        try:
            page_hits = list(ddgs_instance.text(query, max_results=DDG_MAX_RESULTS_FOR_IMAGE_PAGES, region='wt-wt', safesearch='Off'))
            logger.debug(f"DDG text search for '{query}' found {len(page_hits)} page results.")
        except Exception as e:
            logger.error(f"  DDG text search failed for '{query}': {e}")
            if "rate limit" in str(e).lower() or (hasattr(e, 'response') and e.response and e.response.status_code == 429):
                logger.warning("DDG Rate limit likely hit. Sleeping for a longer duration.")
                time.sleep(random.uniform(90, 180))
            continue
        for hit_idx, hit in enumerate(page_hits):
            page_url = hit.get('href')
            if page_url:
                logger.debug(f"    Scraping page {hit_idx+1}/{len(page_hits)} from DDG result: {page_url}")
                parsed_hit_url = urlparse(page_url); base_hit_url = f"{parsed_hit_url.scheme}://{parsed_hit_url.netloc}"
                imgs_from_page = _scrape_images_from_url_aggressively_stage1_impl(page_url, base_hit_url, session)
                for img_d in imgs_from_page:
                    img_d['source_engine'] = 'DDG Page Scrape'; img_d['original_search_query'] = query
                all_img_candidates.extend(imgs_from_page)
                time.sleep(random.uniform(DDG_PAGE_SCRAPE_DELAY_MIN, DDG_PAGE_SCRAPE_DELAY_MAX))
        if i < len(query_list) - 1:
            query_delay = random.uniform(DDG_QUERY_DELAY_MIN, DDG_QUERY_DELAY_MAX)
            logger.debug(f"Sleeping for {query_delay:.1f}s before next DDG query.")
            time.sleep(query_delay)
    unique_final = list({d['url']:d for d in all_img_candidates if d.get('url')}.values())
    logger.info(f"Stage 2 (DDG Page Search): Found {len(unique_final)} total unique img candidates after processing {len(query_list)} queries."); return unique_final


# --- Stage 3: Image Download, Validation (Robust) ---
def _download_and_validate_image_stage3_impl(url: str, preferred_aspect_ratio_str: str = "flexible", attempt: int = 1, use_strict_dims: bool = True, session: requests.Session = None) -> dict | None:
    if not url or not url.startswith('http'): logger.warning(f"Invalid image URL format: {url}"); return None
    logger.debug(f"Stage 3: Download & Validation attempt {attempt}/{IMAGE_DOWNLOAD_RETRIES_VMA} for: {url} (Strict Dims: {use_strict_dims})")
    
    current_session = session or requests_retry_session()
    current_user_agent = random.choice(USER_AGENT_LIST_VMA)
    current_session.headers.update({'User-Agent': current_user_agent, 'Accept': 'image/avif,image/webp,image/apng,image/jpeg,image/png,image/*,*/*;q=0.8'})

    try:
        response = current_session.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT_VMA, stream=True, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()

        is_image_type = any(ct in content_type for ct in ['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'image/jp2', 'image/heic', 'image/heif'])
        is_octet_stream_image_extension = content_type == 'application/octet-stream' and any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.avif', '.jp2', '.heic', '.heif'])
        if not (is_image_type or is_octet_stream_image_extension):
            logger.warning(f"URL content-type not a supported image ({content_type}): {url}"); return None

        image_content_bytes = response.content
        min_fs = MIN_IMAGE_FILESIZE_BYTES_VMA if use_strict_dims else ADAPTIVE_MIN_IMAGE_FILESIZE_BYTES_VMA
        if len(image_content_bytes) < min_fs: logger.warning(f"Img content too small ({len(image_content_bytes)}B) from {url}. Min: {min_fs}B"); return None

        img = Image.open(io.BytesIO(image_content_bytes))
        min_w = MIN_IMAGE_WIDTH_VMA if use_strict_dims else ADAPTIVE_MIN_IMAGE_WIDTH_VMA
        min_h = MIN_IMAGE_HEIGHT_VMA if use_strict_dims else ADAPTIVE_MIN_IMAGE_HEIGHT_VMA
        if img.width < min_w or img.height < min_h: logger.warning(f"Img too small ({img.width}x{img.height}) from {url}. Min: {min_w}x{min_h}"); return None

        if preferred_aspect_ratio_str != "flexible" and preferred_aspect_ratio_str != "any":
            try:
                target_w_str, target_h_str = preferred_aspect_ratio_str.split(' ')[0].split(':')
                target_w, target_h = int(target_w_str), int(target_h_str)
                target_ratio = target_w / target_h; actual_ratio = img.width / img.height
                tolerance_factor = 0.25 if abs(target_ratio - 1) < 0.1 else 0.40 # More generous tolerance
                if not (target_ratio * (1 - tolerance_factor) <= actual_ratio <= target_ratio * (1 + tolerance_factor)):
                    logger.debug(f"Img {url} (ratio {actual_ratio:.2f}) rejected for preferred aspect {target_ratio:.2f} ({preferred_aspect_ratio_str}) with tolerance {tolerance_factor*100}%."); return None
            except Exception as e_ar: logger.warning(f"Could not parse/apply preferred_aspect_ratio '{preferred_aspect_ratio_str}': {e_ar}")

        if img.mode not in ['RGB', 'RGBA', 'L', 'P']: img = img.convert('RGB')
        elif img.mode == 'P' and 'transparency' in img.info: img = img.convert('RGBA')
        elif img.mode == 'P': img = img.convert('RGB')

        logger.info(f"Stage 3: Validated: {url} ({img.width}x{img.height}, Mode: {img.mode})")
        return {"url": url, "image_obj": img, "width": img.width, "height": img.height}

    except requests.exceptions.RetryError as retry_err:
        logger.error(f"All retries failed for {url}: {retry_err}")
    except requests.exceptions.RequestException as e_req:
        logger.warning(f"Download/validation RequestException (attempt {attempt}) for {url}: {e_req}")
    except (UnidentifiedImageError, IOError) as e_img: logger.warning(f"Image format/IO error (attempt {attempt}) for {url}: {e_img}")
    except Exception as e: logger.error(f"Unexpected Stage 3 error for {url}: {e}", exc_info=True)
    return None

# --- Stage 4 Helper Functions (for VLM & CLIP) ---
def _initialize_florence2_model_impl():
    global vlm_model_florence, vlm_processor_florence, FLORENCE2_MODEL_LOADED
    if STANDALONE_TEST_MODE_SIMULATION_ACTIVE or FLORENCE2_MODEL_LOADED: return
    if not FLORENCE2_MODEL_LOADED and HF_TRANSFORMERS_AVAILABLE and AutoProcessorImport and AutoModelForVision2SeqImport and TORCH_AVAILABLE:
        try:
            logger.info(f"Attempting to load VLM model (Florence-2): {HF_FLORENCE2_MODEL_ID} to {DEVICE_VLM} with {TORCH_DTYPE_VLM}...")
            vlm_processor_florence = AutoProcessorImport.from_pretrained(HF_FLORENCE2_MODEL_ID, trust_remote_code=True)
            vlm_model_florence = AutoModelForVision2SeqImport.from_pretrained(HF_FLORENCE2_MODEL_ID, torch_dtype=TORCH_DTYPE_VLM, trust_remote_code=True).to(DEVICE_VLM)
            FLORENCE2_MODEL_LOADED = True; logger.info(f"Florence-2 model ({HF_FLORENCE2_MODEL_ID}) loaded successfully.")
        except Exception as e: logger.error(f"Failed to load Florence-2 model ({HF_FLORENCE2_MODEL_ID}): {e}", exc_info=True); vlm_model_florence, vlm_processor_florence = None, None

def _initialize_llava_model_impl():
    global vlm_model_llava, vlm_processor_llava, LLAVA_MODEL_LOADED
    if STANDALONE_TEST_MODE_SIMULATION_ACTIVE or LLAVA_MODEL_LOADED: return
    if not LLAVA_MODEL_LOADED and HF_TRANSFORMERS_AVAILABLE and AutoProcessorImport and LlavaForConditionalGenerationImport and TORCH_AVAILABLE:
        processor_to_use_for_llava = AutoProcessorImport # Use AutoProcessor for LLaVA
        try:
            logger.info(f"Attempting to load VLM model (LLaVA): {HF_LLAVA_MODEL_ID} to {DEVICE_VLM} with {TORCH_DTYPE_VLM} using AutoProcessor...")
            vlm_processor_llava = processor_to_use_for_llava.from_pretrained(HF_LLAVA_MODEL_ID, trust_remote_code=True) # Added trust_remote_code
            vlm_model_llava = LlavaForConditionalGenerationImport.from_pretrained(HF_LLAVA_MODEL_ID, torch_dtype=TORCH_DTYPE_VLM, low_cpu_mem_usage=(DEVICE_VLM == 'cpu'), trust_remote_code=True).to(DEVICE_VLM) # Added trust_remote_code
            LLAVA_MODEL_LOADED = True; logger.info(f"LLaVA model ({HF_LLAVA_MODEL_ID}) loaded successfully.")
        except Exception as e: logger.error(f"Failed to load LLaVA model ({HF_LLAVA_MODEL_ID}): {e}", exc_info=True); vlm_model_llava, vlm_processor_llava = None, None

def _call_florence2_impl(pil_image: Image.Image, task_prompt: str) -> str | None:
    if not FLORENCE2_MODEL_LOADED or not vlm_model_florence or not vlm_processor_florence: return None
    try:
        effective_f2_prompt = f"<MORE_DETAILED_CAPTION_WITH_CONTEXT>{task_prompt}</MORE_DETAILED_CAPTION_WITH_CONTEXT>"
        with torch.no_grad():
            inputs = vlm_processor_florence(text=effective_f2_prompt, images=pil_image, return_tensors="pt").to(DEVICE_VLM)
            if hasattr(inputs, "to") and callable(inputs.to):
                 inputs = inputs.to(TORCH_DTYPE_VLM) if DEVICE_VLM == "cuda" else inputs
            generated_ids = vlm_model_florence.generate(input_ids=inputs["input_ids"], pixel_values=inputs["pixel_values"], max_new_tokens=1024, num_beams=3)
        generated_text = vlm_processor_florence.batch_decode(generated_ids, skip_special_tokens=False)[0]
        cleaned_text = generated_text.split(effective_f2_prompt)[-1] if effective_f2_prompt in generated_text else generated_text
        cleaned_text = cleaned_text.replace("</s>", "").replace("<s>", "").strip()
        return cleaned_text if len(cleaned_text) > 10 else None
    except Exception as e: logger.error(f"Florence-2 error: {e}", exc_info=False); return None

def _call_llava_impl(pil_image: Image.Image, vlm_task_prompt: str) -> str | None:
    if not LLAVA_MODEL_LOADED or not vlm_model_llava or not vlm_processor_llava: return None
    try:
        full_prompt = f"USER: <image>\n{vlm_task_prompt}\nASSISTANT:"
        with torch.no_grad():
            inputs = vlm_processor_llava(text=full_prompt, images=pil_image, return_tensors="pt").to(DEVICE_VLM)
            if DEVICE_VLM == "cuda":
                inputs = {k: v.to(TORCH_DTYPE_VLM) if hasattr(v, 'to') and hasattr(v, 'dtype') and v.dtype.is_floating_point else v for k, v in inputs.items()}
            generate_ids = vlm_model_llava.generate(**inputs, max_new_tokens=350, do_sample=True, temperature=0.2, top_p=0.9, num_beams=1)
        generated_text_full = vlm_processor_llava.batch_decode(generate_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
        parts = generated_text_full.split("ASSISTANT:"); assistant_response = parts[-1].strip() if len(parts) > 1 else generated_text_full.strip()
        return assistant_response if len(assistant_response) > 10 else None
    except Exception as e: logger.error(f"LLaVA error: {e}", exc_info=False); return None

def _call_clip_st_impl(pil_image: Image.Image, text_for_clip: str) -> float | None:
    global clip_model_instance_st, CLIP_MODEL_LOADED_ST
    if not ENABLE_CLIP_SCORING or not CLIP_AVAILABLE_ST: return None
    if not CLIP_MODEL_LOADED_ST and ST_CLIPModelImport:
        try:
            logger.info(f"Loading ST CLIP on demand: {CLIP_MODEL_NAME_ST} to {DEVICE_VLM}")
            clip_model_instance_st = ST_CLIPModelImport(CLIP_MODEL_NAME_ST, device=DEVICE_VLM)
            CLIP_MODEL_LOADED_ST = True; logger.info(f"ST CLIP model '{CLIP_MODEL_NAME_ST}' loaded.")
        except Exception as e: logger.error(f"Failed to load ST CLIP: {e}", exc_info=True); return None
    if not clip_model_instance_st or not cos_sim or not isinstance(pil_image, Image.Image): return None
    try:
        with torch.no_grad():
            processed_image_for_clip = pil_image if pil_image.mode == 'RGB' else pil_image.convert('RGB')
            img_emb = clip_model_instance_st.encode(processed_image_for_clip, convert_to_tensor=True, show_progress_bar=False)
            txt_emb = clip_model_instance_st.encode(text_for_clip, convert_to_tensor=True, show_progress_bar=False)
        sim = cos_sim(txt_emb, img_emb)[0][0].item()
        normalized_score = round(max(0.0, min(1.0, (sim / 0.4))), 3)
        logger.debug(f"  ST CLIP (Image vs '{text_for_clip[:40]}...'): Raw Sim {sim:.4f} -> Normalized Score {normalized_score:.3f}")
        return normalized_score
    except Exception as e: logger.error(f"  ST CLIP analysis error: {e}", exc_info=False); return None

# --- Stage 4: Advanced Image Understanding (VLM + CLIP) ---
def _analyze_image_advanced_stage4_impl(image_data_with_obj: dict, context_text: str, ideal_type_desc: str) -> dict:
    global STANDALONE_TEST_MODE_SIMULATION_ACTIVE
    image_obj = image_data_with_obj.get("image_obj"); image_url = image_data_with_obj.get("url")
    if not image_obj or not image_url: return {"vlm_description": "N/A - Input Error", "relevance_score": 0.0, "quality_score": 0.0, "alt_text_suggestion": "Image analysis error", **image_data_with_obj}
    logger.info(f"Stage 4: Advanced analysis for: {image_url} (Context: {context_text[:30]}...)")
    analysis_result = {"vlm_description": "N/A", "relevance_score": 0.20, "quality_score": 0.40, "alt_text_suggestion": context_text[:ALT_TEXT_TARGET_MAX_LEN]}
    if STANDALONE_TEST_MODE_SIMULATION_ACTIVE:
        logger.warning("STANDALONE_TEST_MODE_SIMULATION_ACTIVE: Simulating VLM/CLIP analysis.")
        analysis_result["vlm_description"] = f"Simulated VLM: Image depicts '{ideal_type_desc[:50]}' for context '{context_text[:40]}'."
        analysis_result["relevance_score"] = round(random.uniform(0.50, 0.85), 3)
        analysis_result["quality_score"] = round(random.uniform(0.55, 0.85), 3)
        analysis_result["alt_text_suggestion"] = f"Simulated alt text for {ideal_type_desc[:50]}"[:ALT_TEXT_TARGET_MAX_LEN].strip()
        return {**image_data_with_obj, **analysis_result}

    vlm_used = "None"
    vlm_task_prompt_refined = f"Provide a detailed, objective description of this image, focusing on its relevance to '{context_text[:100]}...' and the ideal type: '{ideal_type_desc}'. Highlight main subjects, setting, actions, and overall visual style."
    if FLORENCE2_MODEL_LOADED:
        f2_desc = _call_florence2_impl(image_obj, vlm_task_prompt_refined)
        if f2_desc: analysis_result["vlm_description"] = f2_desc; vlm_used = "Florence-2"
    if (analysis_result["vlm_description"] == "N/A" or len(analysis_result["vlm_description"]) < 30) and LLAVA_MODEL_LOADED:
        llava_desc = _call_llava_impl(image_obj, vlm_task_prompt_refined)
        if llava_desc: analysis_result["vlm_description"] = llava_desc; vlm_used = "LLaVA" if vlm_used == "None" else "Florence-2_then_LLaVA"
    if analysis_result["vlm_description"] != "N/A":
        analysis_result["alt_text_suggestion"] = analysis_result["vlm_description"][:ALT_TEXT_TARGET_MAX_LEN].replace('\n',' ').strip()
        desc_len = len(analysis_result["vlm_description"])
        if desc_len > 150: analysis_result["quality_score"] = min(1.0, analysis_result.get("quality_score", 0.40) + 0.35)
        elif desc_len > 75: analysis_result["quality_score"] = min(1.0, analysis_result.get("quality_score", 0.40) + 0.25)
        elif desc_len > 30: analysis_result["quality_score"] = min(1.0, analysis_result.get("quality_score", 0.40) + 0.15)
    clip_text_prompt_for_relevance = f"{ideal_type_desc}. {context_text}. Additional details: {analysis_result['vlm_description'] if analysis_result['vlm_description'] != 'N/A' else ''}"
    clip_score = _call_clip_st_impl(image_obj, clip_text_prompt_for_relevance.strip())
    if clip_score is not None: analysis_result["relevance_score"] = round(clip_score, 3)
    return {**image_data_with_obj, **analysis_result}

# --- Stage 5: Final Image Selection & Alt Text ---
def _call_image_curator_prime_llm_impl(image_slot_type, original_context_desc, ideal_type_desc, primary_keyword_for_alt, candidate_images_data, placeholder_id_ref_for_llm="N/A") -> dict | None:
    global STANDALONE_TEST_MODE_SIMULATION_ACTIVE
    if not candidate_images_data: return None
    if STANDALONE_TEST_MODE_SIMULATION_ACTIVE:
        logger.warning(f"STANDALONE_TEST_MODE_SIMULATION_ACTIVE: Simulating Image Curator Prime for '{original_context_desc[:50]}...'.")
        if not candidate_images_data: return {"selected_image_url": None, "final_alt_text": "No candidates for simulated curation.", "curation_rationale": "Simulated: No candidates provided."}
        best_candidate = max(candidate_images_data, key=lambda x: x.get('relevance_score', 0.0)*0.7 + x.get('quality_score',0.0)*0.3, default=None)
        if not best_candidate: return {"selected_image_url": None, "final_alt_text": "No candidates for simulated curation.", "curation_rationale": "Simulated: No candidates available after filtering."}
        simulated_alt = f"Curated Alt: {best_candidate.get('alt_text_suggestion', original_context_desc[:80])} featuring {primary_keyword_for_alt}"
        if len(simulated_alt) > ALT_TEXT_TARGET_MAX_LEN: simulated_alt = simulated_alt[:ALT_TEXT_TARGET_MAX_LEN-3] + "..."
        elif len(simulated_alt) < ALT_TEXT_TARGET_MIN_LEN: simulated_alt = (simulated_alt + " " + primary_keyword_for_alt + " visual context.")[:ALT_TEXT_TARGET_MAX_LEN]
        return {"selected_image_url": best_candidate.get("url"), "final_alt_text": simulated_alt.strip(), "curation_rationale": "Simulated: Chose by composite score. Alt text simulated and length adjusted."}

    if not DEEPSEEK_API_KEY_VMA: logger.error("DEEPSEEK_API_KEY_VMA not set for Image Curator Prime."); return None
    curator_input = {
        "image_slot_type": image_slot_type, "placeholder_id_ref": placeholder_id_ref_for_llm,
        "original_context_description": original_context_desc, "ideal_image_type_description": ideal_type_desc,
        "primary_keyword_for_alt_text": primary_keyword_for_alt,
        "candidate_images": [{"url": c.get("url"), "vlm_description": c.get("vlm_description","N/A")[:400], "relevance_score": c.get("relevance_score"), "quality_score": c.get("quality_score"), "preliminary_alt_text": c.get("alt_text_suggestion","")[:150], "exif_data_summary": str(c.get("exif_data", {}))[:200]} for c in sorted(candidate_images_data, key=lambda x: (x.get('relevance_score',0)*0.7 + x.get('quality_score',0)*0.3), reverse=True)[:MAX_CANDIDATES_TO_CURATOR_LLM_PER_SLOT]]}
    user_content_json_str = json.dumps(curator_input)
    payload = {"model": DEEPSEEK_MODEL_CURATOR, "messages": [{"role": "system", "content": IMAGE_CURATOR_PRIME_SYSTEM_PROMPT_V2}, {"role": "user", "content": user_content_json_str}], "temperature": 0.45, "max_tokens": 700, "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_VMA}", "Content-Type": "application/json"}
    curator_text_for_error_log = ""
    try:
        logger.info(f"Requesting LLM Image Curation for slot '{placeholder_id_ref_for_llm}' (Context: '{original_context_desc[:50]}...')"); response = requests.post(DEEPSEEK_CHAT_API_URL_VMA, headers=headers, json=payload, timeout=API_TIMEOUT_CURATOR_LLM); response.raise_for_status(); curator_text_for_error_log = response.json()["choices"][0]["message"]["content"]; curated_choice = json.loads(curator_text_for_error_log)
        if "selected_image_url" not in curated_choice or "final_alt_text" not in curated_choice or "curation_rationale" not in curated_choice:
            logger.error(f"Image Curator LLM output missing keys for slot '{placeholder_id_ref_for_llm}'. Output: {curator_text_for_error_log[:200]}"); return None
        if curated_choice.get("final_alt_text"):
            alt = str(curated_choice["final_alt_text"])
            if len(alt) > ALT_TEXT_TARGET_MAX_LEN: logger.warning(f"LLM Curator alt text for '{placeholder_id_ref_for_llm}' too long ({len(alt)} chars), truncating: '{alt}'"); curated_choice["final_alt_text"] = alt[:ALT_TEXT_TARGET_MAX_LEN-3] + "..."
            elif len(alt) < ALT_TEXT_TARGET_MIN_LEN: logger.warning(f"LLM Curator alt text for '{placeholder_id_ref_for_llm}' too short ({len(alt)} chars): '{alt}'. Consider manual review.")
        logger.info(f"LLM Image Curation successful for slot '{placeholder_id_ref_for_llm}'."); return curated_choice
    except json.JSONDecodeError as je:
        logger.error(f"Image Curator LLM JSON decode failed for slot '{placeholder_id_ref_for_llm}': {je}. Raw: {curator_text_for_error_log[:500]}")
        if "error\": \"schema_violation" in curator_text_for_error_log.lower(): logger.error("LLM reported a schema violation for its own curator output.")
        return None
    except Exception as e: logger.error(f"Image Curator LLM failed for slot '{placeholder_id_ref_for_llm}': {e}", exc_info=True); return None

def _select_final_images_stage5_impl(candidates_data: list, num_to_select: int,
                               original_context_desc: str, ideal_type_desc_from_llm: str,
                               primary_keyword_for_alt: str,
                               placeholder_id_for_curation: str | None,
                               is_featured: bool = False, existing_selections_hashes=None,
                               article_data_for_fallback_alt: dict = None) -> list:
    if not candidates_data: return []
    if existing_selections_hashes is None: existing_selections_hashes = set()
    slot_identifier = placeholder_id_for_curation if placeholder_id_for_curation else ("featured_image" if is_featured else "unknown_slot")
    logger.info(f"Stage 5: Selecting {num_to_select} image(s) from {len(candidates_data)} for slot '{slot_identifier}' (Context: '{original_context_desc[:50]}').")
    curated_selections = []
    use_llm_curator = DEEPSEEK_API_KEY_VMA and (not STANDALONE_TEST_MODE_SIMULATION_ACTIVE or (STANDALONE_TEST_MODE_SIMULATION_ACTIVE and os.getenv("VMA_FORCE_LLM_CURATION_IN_TEST") == "true"))

    if use_llm_curator:
        llm_curated_choice = _call_image_curator_prime_llm_impl(
            "featured_image" if is_featured else "in_article_placeholder",
            original_context_desc, ideal_type_desc_from_llm, primary_keyword_for_alt,
            candidates_data, placeholder_id_ref_for_llm = slot_identifier
        )
        if llm_curated_choice and llm_curated_choice.get("selected_image_url"):
            chosen_cand_full = next((c for c in candidates_data if c.get("url") == llm_curated_choice["selected_image_url"]), None)
            current_hash = None
            if IMAGEHASH_AVAILABLE and chosen_cand_full and chosen_cand_full.get("image_obj") and imagehash:
                try: current_hash = imagehash.dhash(chosen_cand_full["image_obj"])
                except Exception as e: logger.warning(f"Imagehash failed for LLM selected image: {e}")
            if current_hash is None or not any((current_hash - sel_hash) < IMAGEHASH_SIMILARITY_THRESHOLD for sel_hash in existing_selections_hashes):
                sel_details = {"placeholder_id_ref": placeholder_id_for_curation, "placeholder_description_original": original_context_desc, "best_image_url": llm_curated_choice["selected_image_url"], "alt_text": llm_curated_choice["final_alt_text"].strip(), "relevance_score": chosen_cand_full.get('relevance_score', 0.85) if chosen_cand_full else 0.85, "vlm_image_description": chosen_cand_full.get('vlm_description', 'N/A') if chosen_cand_full else 'N/A', "curation_method": "LLM_Curated", "exif_data": chosen_cand_full.get("exif_data", {}) if chosen_cand_full else {}}
                curated_selections.append(sel_details)
                if current_hash: existing_selections_hashes.add(current_hash)
                logger.info(f"  LLM CURATED for '{slot_identifier}': {sel_details['best_image_url']}, Alt: '{sel_details['alt_text']}'. Rationale: {llm_curated_choice.get('curation_rationale')}")
            else: logger.info(f"  LLM curated image visually similar for slot '{slot_identifier}'. Falling back if more needed.")
        elif llm_curated_choice and llm_curated_choice.get("selected_image_url") is None: logger.info(f"LLM Curator explicitly chose NO image for slot '{slot_identifier}'. Rationale: {llm_curated_choice.get('curation_rationale')}")
        else: logger.warning(f"LLM Curator failed/no selection for slot '{slot_identifier}'. Proceeding with rule-based if needed.")
    if len(curated_selections) >= num_to_select: return curated_selections[:num_to_select]
    logger.debug(f"Using rule-based selection for slot '{slot_identifier}' (Context: '{original_context_desc[:50]}...') (or remaining).")
    for cand in candidates_data: cand['composite_score'] = 0.75 * cand.get('relevance_score', 0.0) + 0.25 * cand.get('quality_score', 0.5)
    sorted_candidates = sorted(candidates_data, key=lambda x: x['composite_score'], reverse=True)
    final_selections_rb, seen_urls_in_this_slot_selection = [], set(s['best_image_url'] for s in curated_selections)
    for cand in sorted_candidates:
        if len(curated_selections) + len(final_selections_rb) >= num_to_select: break
        if cand['url'] in seen_urls_in_this_slot_selection : continue
        seen_urls_in_this_slot_selection.add(cand['url'])
        current_hash = None
        if IMAGEHASH_AVAILABLE and cand.get("image_obj") and imagehash:
            try:
                current_hash = imagehash.dhash(cand["image_obj"])
                if any((current_hash - sel_hash) < IMAGEHASH_SIMILARITY_THRESHOLD for sel_hash in existing_selections_hashes): logger.debug(f"  RULE: Skipping {cand['url']} (visually similar to already selected)."); continue
            except Exception as e: logger.warning(f"  RULE: Imagehash failed for {cand['url']}: {e}")
        final_alt = cand.get("alt_text_suggestion", cand.get("preliminary_alt_text_suggestion","")).strip()
        if not final_alt or len(final_alt) < ALT_TEXT_TARGET_MIN_LEN / 2 or "placeholder" in final_alt.lower() or "contextual image" in final_alt.lower():
            title_for_fallback = original_context_desc
            if is_featured and article_data_for_fallback_alt: title_for_fallback = article_data_for_fallback_alt.get('final_page_h1', article_data_for_fallback_alt.get('initial_title_from_web', original_context_desc))
            final_alt = f"{title_for_fallback[:80]} - {primary_keyword_for_alt if primary_keyword_for_alt and primary_keyword_for_alt.lower() not in title_for_fallback[:80].lower() else ''}".strip(" - ")
        final_alt = re.sub(r'\s+', ' ', final_alt).strip()
        if len(final_alt) > ALT_TEXT_TARGET_MAX_LEN: final_alt = final_alt[:ALT_TEXT_TARGET_MAX_LEN-3] + "..."
        elif len(final_alt) < ALT_TEXT_TARGET_MIN_LEN and len(final_alt) > 0: final_alt = (final_alt + f", related to {primary_keyword_for_alt}" if primary_keyword_for_alt else final_alt + ", visual content")[:ALT_TEXT_TARGET_MAX_LEN]
        if not final_alt: final_alt = primary_keyword_for_alt if primary_keyword_for_alt else "Relevant image"
        sel_details = {"placeholder_id_ref": cand.get("placeholder_id_ref", placeholder_id_for_curation), "placeholder_description_original": cand.get("placeholder_description_original", original_context_desc), "best_image_url": cand['url'], "alt_text": final_alt, "relevance_score": cand.get('relevance_score'), "vlm_image_description": cand.get("vlm_description", "N/A"), "curation_method": "Rule-Based", "exif_data": cand.get("exif_data", {})}
        final_selections_rb.append(sel_details)
        if current_hash: existing_selections_hashes.add(current_hash)
        logger.info(f"  RULE-SELECTED for '{slot_identifier}': {cand['url']} (Score: {cand['composite_score']:.2f}), Alt: '{final_alt}'")
    return curated_selections + final_selections_rb

# Helper: Extract EXIF data
def get_exif_data(pil_image):
    exif_data = {}
    if not pil_image: return exif_data
    try:
        exif = pil_image._getexif()
        if exif:
            for k, v in exif.items():
                if k in ExifTags.TAGS:
                    tag_name = ExifTags.TAGS[k]
                    if tag_name in ['Copyright', 'Artist', 'XPAuthor', 'ImageDescription', 'UserComment', 'Make', 'Model', 'Software', 'DateTimeOriginal', 'LensModel']:
                        if isinstance(v, bytes):
                            try: exif_data[tag_name] = v.decode('utf-8', errors='replace')
                            except UnicodeDecodeError:
                                try: exif_data[tag_name] = v.decode('latin-1', errors='replace')
                                except: exif_data[tag_name] = str(v)
                        else: exif_data[tag_name] = str(v)
        if exif_data: logger.debug(f"Extracted EXIF data: {json.dumps(exif_data, indent=2)}")
    except AttributeError: logger.debug("No EXIF data found or image format does not support EXIF extraction.")
    except Exception as e: logger.debug(f"Could not extract EXIF data: {e}")
    return exif_data

# --- Main Agent Orchestrator ---
def run_vision_media_agent(article_pipeline_data: dict) -> dict:
    global clip_model_instance_st, STANDALONE_TEST_MODE_SIMULATION_ACTIVE, FLORENCE2_MODEL_LOADED, LLAVA_MODEL_LOADED, CLIP_MODEL_LOADED_ST
    article_id = article_pipeline_data.get('id', 'unknown_id')
    article_title = article_pipeline_data.get('final_page_h1', article_pipeline_data.get('initial_title_from_web', 'Untitled Article'))
    final_keywords_list = article_pipeline_data.get('final_keywords', [])
    primary_keyword = final_keywords_list[0] if final_keywords_list and isinstance(final_keywords_list, list) and final_keywords_list else article_title
    article_summary = article_pipeline_data.get('generated_meta_description', article_pipeline_data.get('processed_summary', ''))
    source_url = article_pipeline_data.get('original_source_url')
    logger.info(f"--- [VMA Orchestrator] Running Vision & Media Agent (ASI ULTRA v3.9) for ID: {article_id} ---")

    if (__name__ == "__main__" and not os.getenv("VMA_FORCE_LIVE_MODELS_IN_TEST", "false").lower() == "true") :
        STANDALONE_TEST_MODE_SIMULATION_ACTIVE = True
        logger.warning("VMA Orchestrator running in STANDALONE_TEST_MODE_SIMULATION_ACTIVE (VLM/CLIP simulated).")
    else:
        STANDALONE_TEST_MODE_SIMULATION_ACTIVE = False
        logger.info("VMA Orchestrator running in LIVE model mode (or VMA_FORCE_LIVE_MODELS_IN_TEST is true).")
        if not FLORENCE2_MODEL_LOADED and HF_TRANSFORMERS_AVAILABLE: _initialize_florence2_model_impl()
        if not LLAVA_MODEL_LOADED and not FLORENCE2_MODEL_LOADED and HF_TRANSFORMERS_AVAILABLE: _initialize_llava_model_impl()
        if ENABLE_CLIP_SCORING and not CLIP_MODEL_LOADED_ST and CLIP_AVAILABLE_ST and ST_CLIPModelImport :
            try:
                dummy_img_for_clip_init = Image.new("RGB", (64,64), color="red")
                _call_clip_st_impl(dummy_img_for_clip_init, "Initialize CLIP model")
                del dummy_img_for_clip_init
            except Exception as e_clip_init: logger.error(f"Failed to pre-load/initialize ST CLIP model: {e_clip_init}")

    raw_markdown_body = article_pipeline_data.get('assembled_article_body_md', article_pipeline_data.get('seo_agent_results',{}).get('generated_article_body_md',''))
    placeholders_from_md = []
    if raw_markdown_body:
        found_ph_in_md = re.findall(r'<!--\s*IMAGE_PLACEHOLDER:\s*(.*?)\s*-->', raw_markdown_body, re.IGNORECASE)
        for idx, desc in enumerate(found_ph_in_md):
            if desc.strip(): placeholders_from_md.append({"id": f"placeholder_{idx+1}", "description": desc.strip(), "section_context": f"In-article image context (approx. placeholder {idx+1})"})

    image_strategy = _get_image_strategy_from_llm_impl(article_title, primary_keyword, article_summary, placeholders_from_md, source_url)
    article_pipeline_data['llm_image_strategy_output'] = image_strategy

    if not image_strategy or not image_strategy.get("featured_image_strategy"):
        logger.error(f"Failed LLM strategy for {article_id}. Defaulting featured.");
        article_pipeline_data.update({'selected_image_url': DEFAULT_PLACEHOLDER_IMAGE_URL, 'final_featured_image_alt_text': article_title[:ALT_TEXT_TARGET_MAX_LEN], 'media_candidates_for_body': [], 'vision_media_agent_status': "FAILED_STRATEGY_DEFAULT_FEATURED"}); return article_pipeline_data

    article_pipeline_data.update({'selected_image_url': None, 'final_featured_image_alt_text': article_title[:ALT_TEXT_TARGET_MAX_LEN], 'media_candidates_for_body': []})
    all_run_image_hashes = set()
    
    http_session = requests_retry_session()

    feat_strat = image_strategy["featured_image_strategy"]
    logger.info(f"[VMA Orchestrator] Processing Featured Image. Ideal='{feat_strat.get('ideal_image_type_description', '')[:60]}...', Query='{feat_strat.get('primary_search_query')}'")
    feat_queries = [feat_strat.get("primary_search_query")] + feat_strat.get("secondary_search_queries", [])
    feat_cand_url_metas = []
    if source_url:
        parsed_s_url = urlparse(source_url); base_s_url = f"{parsed_s_url.scheme}://{parsed_s_url.netloc}"
        feat_cand_url_metas.extend(_scrape_images_from_url_aggressively_stage1_impl(source_url, base_s_url, http_session))
    if DDGS_AVAILABLE:
        feat_cand_url_metas.extend(_search_pages_for_images_stage2_impl(list(filter(None, feat_queries)), http_session))
    unique_feat_cand_metas_for_validation = list({d['url']:d for d in feat_cand_url_metas if d.get('url')}.values())

    validated_feat_cands_with_obj_list = []
    strict_dims_feat = True
    for cand_meta_dict in unique_feat_cand_metas_for_validation[:MAX_CANDIDATES_TO_VALIDATE_PER_SLOT]:
        img_data_dict = _download_and_validate_image_stage3_impl(cand_meta_dict.get('url'), feat_strat.get("preferred_aspect_ratio", "flexible"), use_strict_dims=strict_dims_feat, session=http_session)
        if img_data_dict: validated_feat_cands_with_obj_list.append({**cand_meta_dict, **img_data_dict})
    
    if not validated_feat_cands_with_obj_list and len(unique_feat_cand_metas_for_validation) >= ADAPTIVE_THRESHOLD_TRIGGER_CANDIDATE_COUNT:
        logger.info("Featured image strict validation yielded too few results. Retrying with adaptive dimensions.")
        strict_dims_feat = False
        for cand_meta_dict in unique_feat_cand_metas_for_validation[:MAX_CANDIDATES_TO_VALIDATE_PER_SLOT]:
            if not any(val_cand['url'] == cand_meta_dict.get('url') for val_cand in validated_feat_cands_with_obj_list):
                img_data_dict = _download_and_validate_image_stage3_impl(cand_meta_dict.get('url'), feat_strat.get("preferred_aspect_ratio", "flexible"), use_strict_dims=strict_dims_feat, session=http_session)
                if img_data_dict: validated_feat_cands_with_obj_list.append({**cand_meta_dict, **img_data_dict})
        validated_feat_cands_with_obj_list = list({d['url']:d for d in validated_feat_cands_with_obj_list if d.get('url')}.values())

    analyzed_feat_cands = []
    if validated_feat_cands_with_obj_list:
        for img_dict_val in validated_feat_cands_with_obj_list[:MAX_CANDIDATES_TO_ANALYZE_VLM_PER_SLOT]:
             analyzed_feat_cands.append(_analyze_image_advanced_stage4_impl(img_dict_val, article_title, feat_strat.get("ideal_image_type_description", primary_keyword)))
    final_featured_selection_list = _select_final_images_stage5_impl(analyzed_feat_cands, 1, article_title, feat_strat.get("ideal_image_type_description"), primary_keyword, "featured_image", True, all_run_image_hashes, article_pipeline_data)

    if final_featured_selection_list:
        selected_feat = final_featured_selection_list[0]
        article_pipeline_data.update({'selected_image_url': selected_feat['best_image_url'], 'final_featured_image_alt_text': selected_feat['alt_text']})
    else:
        article_pipeline_data['selected_image_url'] = DEFAULT_PLACEHOLDER_IMAGE_URL
        article_pipeline_data['final_featured_image_alt_text'] = f"{article_title[:ALT_TEXT_TARGET_MAX_LEN-20]} - Image not available".strip()
        logger.warning(f"Using default placeholder for FEATURED IMAGE for {article_id}.")
    logger.info(f"[VMA Orchestrator] FINAL Featured Image: {article_pipeline_data['selected_image_url']} (Alt: '{article_pipeline_data['final_featured_image_alt_text']}')")

    for ph_strat in image_strategy.get("in_article_image_strategies", []):
        ph_id = ph_strat.get("placeholder_id_ref"); ph_desc_orig = ph_strat.get("placeholder_description_original")
        ideal_type = ph_strat.get("ideal_image_type_description")
        logger.info(f"[VMA Orchestrator] Proc. In-Article Placeholder ID: {ph_id} ('{ph_desc_orig[:50]}...'). Ideal='{ideal_type[:50]}...'")
        ph_queries = [ph_strat.get("primary_search_query")] + ph_strat.get("secondary_search_queries", [])
        ph_cand_url_metas = _search_pages_for_images_stage2_impl(list(filter(None, ph_queries)), http_session)
        unique_ph_cand_metas_for_validation = list({d['url']:d for d in ph_cand_url_metas if d.get('url')}.values())

        validated_ph_cands_with_obj_list = []
        strict_dims_ph = True
        for cand_meta_ph_val in unique_ph_cand_metas_for_validation[:MAX_CANDIDATES_TO_VALIDATE_PER_SLOT]:
            img_data_ph = _download_and_validate_image_stage3_impl(cand_meta_ph_val.get('url'), "flexible", use_strict_dims=strict_dims_ph, session=http_session)
            if img_data_ph: validated_ph_cands_with_obj_list.append({**cand_meta_ph_val, **img_data_ph})
        if not validated_ph_cands_with_obj_list and len(unique_ph_cand_metas_for_validation) >= ADAPTIVE_THRESHOLD_TRIGGER_CANDIDATE_COUNT:
            logger.info(f"In-article PH {ph_id} strict validation yielded too few results. Retrying with adaptive.")
            strict_dims_ph = False
            for cand_meta_ph_val in unique_ph_cand_metas_for_validation[:MAX_CANDIDATES_TO_VALIDATE_PER_SLOT]:
                if not any(val_cand['url'] == cand_meta_ph_val.get('url') for val_cand in validated_ph_cands_with_obj_list):
                    img_data_ph = _download_and_validate_image_stage3_impl(cand_meta_ph_val.get('url'), "flexible", use_strict_dims=strict_dims_ph, session=http_session)
                    if img_data_ph: validated_ph_cands_with_obj_list.append({**cand_meta_ph_val, **img_data_ph})
            validated_ph_cands_with_obj_list = list({d['url']:d for d in validated_ph_cands_with_obj_list if d.get('url')}.values())

        analyzed_ph_cands = []
        if validated_ph_cands_with_obj_list:
            for img_data_ph_val in validated_ph_cands_with_obj_list[:MAX_CANDIDATES_TO_ANALYZE_VLM_PER_SLOT]:
                analyzed_ph_cands.append(_analyze_image_advanced_stage4_impl(img_data_ph_val, ph_desc_orig, ideal_type))
        final_ph_selection_list = _select_final_images_stage5_impl(analyzed_ph_cands, 1, ph_desc_orig, ideal_type, primary_keyword, ph_id, False, all_run_image_hashes, article_pipeline_data)
        if final_ph_selection_list: article_pipeline_data['media_candidates_for_body'].append(final_ph_selection_list[0])
        else: logger.warning(f"Could not select/curate image for placeholder ID '{ph_id}' ('{ph_desc_orig[:50]}...').")

    http_session.close()
    article_pipeline_data['vision_media_agent_status'] = f"SUCCESS_ASI_ULTRA_V3.9_IMPORTS_FIXED{'_SIM_FALLBACK' if STANDALONE_TEST_MODE_SIMULATION_ACTIVE else ''}"
    logger.info(f"--- [VMA Orchestrator] Vision & Media Agent finished for ID: {article_id}. Status: {article_pipeline_data['vision_media_agent_status']} ---")
    return article_pipeline_data


if __name__ == "__main__":
    logger.info(f"--- Starting Vision & Media Agent (ASI-Level ULTRA v3.9) Standalone Test ---")
    if os.getenv("VMA_FORCE_LIVE_MODELS_IN_TEST", "false").lower() == "true":
        STANDALONE_TEST_MODE_SIMULATION_ACTIVE = False
        logger.info("VMA Standalone Test: VMA_FORCE_LIVE_MODELS_IN_TEST is true. Attempting to use live models.")
    else:
        STANDALONE_TEST_MODE_SIMULATION_ACTIVE = True
        logger.info("VMA Standalone Test: Defaulting to STANDALONE_TEST_MODE_SIMULATION_ACTIVE (VLM/CLIP simulated). Set VMA_FORCE_LIVE_MODELS_IN_TEST=true to override.")

    if not DEEPSEEK_API_KEY_VMA and not STANDALONE_TEST_MODE_SIMULATION_ACTIVE : logger.error("DEEPSEEK_API_KEY_VMA not set. LLM calls will fail for live mode.")
    if not DDGS_AVAILABLE: logger.warning("DuckDuckGo Search not available. Image sourcing will be limited.")

    sample_article_data_for_vma = {
        'id': 'test_vma_ultra_v39_live_001',
        'final_page_h1': "NVIDIA Announces Blackwell Platform: The Future of Accelerated Computing",
        'final_keywords': ["NVIDIA Blackwell", "AI Superchip", "Accelerated Computing", "Data Center AI"],
        'generated_meta_description': "Discover NVIDIA's Blackwell platform, the next-generation AI superchip delivering breakthroughs in trillion-parameter model training, data processing, and scientific computing.",
        'processed_summary': "NVIDIA today unveiled its next-generation AI platform, Blackwell, designed to power a new era of computing. The Blackwell architecture promises massive performance leaps for AI, data analytics, and high-performance computing.",
        'original_source_url': 'https://nvidianews.nvidia.com/news/nvidia-blackwell-platform-arrives-to-power-a-new-era-of-computing',
        'assembled_article_body_md': """
## NVIDIA Unveils Blackwell: A New Computing Paradigm
The tech world is buzzing after NVIDIA's CEO unveiled the **NVIDIA Blackwell** platform. This marks a significant leap in **Accelerated Computing**.
<!-- IMAGE_PLACEHOLDER: Cinematic shot of the NVIDIA Blackwell GPU or platform, glowing with intricate light patterns, on a dark, futuristic background -->

### Core Blackwell Architecture and Innovations
The Blackwell architecture integrates groundbreaking chip design with advanced networking capabilities. This is central to its power in **Data Center AI**.
<!-- IMAGE_PLACEHOLDER: Detailed infographic: NVIDIA Blackwell architecture highlighting new chiplet designs, NVLink generation, and memory advancements -->

### Performance for Trillion-Parameter Models
Early projections show Blackwell outperforming previous generations by orders of magnitude for training and inference on massive AI models.
<!-- IMAGE_PLACEHOLDER: Bar chart comparing NVIDIA Blackwell performance (e.g., LLM training throughput) against previous NVIDIA GPUs like Hopper or Ampere -->

NVIDIA Blackwell is set to redefine AI superchips.
        """
    }
    result_data_vma = run_vision_media_agent(sample_article_data_for_vma.copy())
    logger.info("\n--- VMA (ASI ULTRA v3.9) Test Results ---")
    logger.info(f"Status: {result_data_vma.get('vision_media_agent_status')}")
    logger.info(f"Featured Img URL: {result_data_vma.get('selected_image_url')}")
    logger.info(f"Featured Img Alt: {result_data_vma.get('final_featured_image_alt_text')}")
    logger.info("\nMedia Candidates for Body (In-Article Images Selected):")
    if result_data_vma.get('media_candidates_for_body'):
        for candidate in result_data_vma.get('media_candidates_for_body'):
            logger.info(f"  - Placeholder Ref: {candidate.get('placeholder_id_ref')}, URL: {candidate.get('best_image_url')}, Alt: {candidate.get('alt_text')}, Method: {candidate.get('curation_method')}")
    else: logger.info("  No in-article images selected.")
    if result_data_vma.get('llm_image_strategy_output'): logger.info("\nLLM Image Strategy:\n" + json.dumps(result_data_vma.get('llm_image_strategy_output'), indent=2))
    logger.info("--- VMA (ASI ULTRA v3.9) Standalone Test Complete ---")

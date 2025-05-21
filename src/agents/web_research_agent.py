# src/agents/vision_media_agent.py
"""
Vision & Media Agent (ASI-Level ULTRA v3.7 - Import Logic Refined)
Multi-Stage Image Strategy & Selection with advanced VLM capabilities,
robust validation, and intelligent curation.
Focus on maximizing live model usage and overcoming common scraping issues.
Refined import logic and availability flags based on testing.py results.
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
# These will be set to True if the corresponding import succeeds.
DDGS_AVAILABLE = False
SELENIUM_AVAILABLE = False
HF_TRANSFORMERS_AVAILABLE = False
TORCH_AVAILABLE = False
FLORENCE2_MODEL_LOADED = False
LLAVA_MODEL_LOADED = False
CLIP_MODEL_LOADED_ST = False # Specific to SentenceTransformer-based CLIP
IMAGEHASH_AVAILABLE = False

# Attempt to import and set flags
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
    DEVICE_VLM = "cpu"; TORCH_DTYPE_VLM = torch.float32 if 'torch' in globals() and hasattr(torch, 'float32') else None # Conceptual
    logging.warning("PyTorch import FAILED. VLM capabilities will be severely limited.")

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True; logging.info("duckduckgo_search library found.")
except ImportError:
    DDGS = None; logging.warning("duckduckgo_search library import FAILED. Web page image search disabled.")

AutoProcessorImport, AutoModelForVision2SeqImport, AutoModelForCausalLMImport, LlavaForConditionalGenerationImport, LlavaAutoProcessorImport = None, None, None, None, None
try:
    from transformers import AutoProcessor, AutoModelForVision2Seq, AutoModelForCausalLM, LlavaForConditionalGeneration, LlavaAutoProcessor as HFLlavaAutoProcessor
    HF_TRANSFORMERS_AVAILABLE = True # This flag is key
    AutoProcessorImport = AutoProcessor
    AutoModelForVision2SeqImport = AutoModelForVision2Seq
    AutoModelForCausalLMImport = AutoModelForCausalLM
    LlavaForConditionalGenerationImport = LlavaForConditionalGeneration
    LlavaAutoProcessorImport = HFLlavaAutoProcessor
    logging.info("Hugging Face Transformers library and key components imported successfully.")
except ImportError as e_hf:
    logging.warning(f"Hugging Face Transformers components import FAILED: {e_hf}. Florence-2 & LLaVA VLM will be disabled.")
    # Ensure HF_TRANSFORMERS_AVAILABLE is False if critical components fail
    HF_TRANSFORMERS_AVAILABLE = False


ST_CLIPModelImport, ST_utilImport, cos_sim = None, None, None
try:
    from sentence_transformers import SentenceTransformer as ST_CLIPModelImport_lib, util as ST_utilImport_lib
    CLIP_AVAILABLE_ST = True # Indicates sentence_transformers library is present
    ST_CLIPModelImport = ST_CLIPModelImport_lib
    ST_utilImport = ST_utilImport_lib
    cos_sim = ST_utilImport.cos_sim # For type hinting if needed
    logging.info("SentenceTransformer library (for CLIP) imported successfully.")
except ImportError as e_st:
    logging.warning(f"SentenceTransformer (for CLIP) import FAILED: {e_st}. CLIP scoring will be disabled.")
    CLIP_AVAILABLE_ST = False


try:
    import imagehash
    IMAGEHASH_AVAILABLE = True; logging.info("imagehash library found.")
except ImportError:
    imagehash = None; logging.warning("imagehash library import FAILED. Visual diversity checks disabled.")

# Selenium (Optional)
WEBDRIVER_PATH = os.getenv("VMA_WEBDRIVER_PATH")
SELENIUM_HEADLESS = os.getenv("VMA_SELENIUM_HEADLESS", "true").lower() == "true"
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.common.exceptions import WebDriverException
    SELENIUM_AVAILABLE = True
    logging.info("Selenium library found. Advanced scraping via headless browser is an option if configured.")
except ImportError:
    logging.warning("Selenium library import FAILED. Advanced scraping with headless browser will be disabled.")


logger = logging.getLogger(__name__)
# Ensure logger is configured, especially if this module is run standalone early
if not logging.getLogger().hasHandlers(): # Check root logger
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
elif not logger.handlers: # Check module-specific logger
    logger.parent.handlers.clear() # Avoid duplicate logs if root is configured
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


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
MIN_CLIP_SCORE_VMA = float(os.getenv("VMA_MIN_CLIP_SCORE", "0.28")) # Stricter CLIP
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
    f"Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) DacoolaImageFetcher/3.7 (+{WEBSITE_URL_VMA})",
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)"
]

# VLM Model Instances (Global for caching)
vlm_processor_florence, vlm_model_florence = None, None
vlm_processor_llava, vlm_model_llava = None, None
clip_model_instance_st = None

# Retry session for requests
def requests_retry_session(retries=IMAGE_DOWNLOAD_RETRIES_VMA, backoff_factor=IMAGE_RETRY_DELAY_VMA/3, status_forcelist=(500, 502, 503, 504, 403, 429, 408), session=None):
    session = session or requests.Session()
    retry = Retry(
        total=retries, read=retries, connect=retries,
        backoff_factor=backoff_factor, status_forcelist=status_forcelist,
        allowed_methods=frozenset(['HEAD', 'GET'])
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# ------------------------------------------------------
#  Stage-0 through Stage-5 Helper Functions
# ------------------------------------------------------

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

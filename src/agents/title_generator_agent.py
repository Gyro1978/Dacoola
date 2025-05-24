# src/agents/title_generator_agent.py
"""
Title Generator Agent: Creates SEO-optimized Title Tags and H1 Headings.

This agent utilizes an LLM to generate compelling titles based on article content,
keywords, and summaries, aiming for high click-through rates and search engine
visibility while adhering to strict length, single-sentence flow, and colon-prohibition guidelines.
It also handles mojibake and prevents double branding.
"""

import os
import sys
import json
import logging
import torch # Added for Gemma
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig # Added for Gemma
import re
import ftfy # For fixing text encoding issues
import time

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
# --- End Setup Logging ---

# --- Configuration & Constants ---
LLM_MODEL_NAME = "google/gemma-3n-e4b-it" # Changed to Gemma model ID
WEBSITE_NAME = os.getenv('WEBSITE_NAME', 'Dacoola') # Retain for branding logic
BRAND_SUFFIX_FOR_TITLE_TAG = f" - {WEBSITE_NAME}"

# Global variables for Gemma model and tokenizer
gemma_tokenizer = None
gemma_model = None

MAX_SUMMARY_SNIPPET_LEN_CONTEXT = 1000
MAX_CONTENT_SNIPPET_LEN_CONTEXT = 200

TITLE_TAG_CONTENT_TARGET_MAX_LEN = 60 # Max length for content part of title tag
TITLE_TAG_HARD_MAX_LEN = 65           # Absolute max for title tag (content + suffix)
SEO_H1_TARGET_MAX_LEN = 70            # Target max for H1
SEO_H1_HARD_MAX_LEN = 75              # Absolute max for H1


# Fallback definitions
DEFAULT_FALLBACK_TITLE_TAG_RAW = "Key Update on {primary_keyword}"
DEFAULT_FALLBACK_H1_RAW = "Breaking News Regarding {primary_keyword} Developments"

# --- Helper: Title Case Function ---
def to_title_case(text_str: str) -> str:
    if not text_str: return ""
    
    # Normalize common apostrophe variants first
    text_str = text_str.replace('’', "'").replace('‘', "'")
    text_str = text_str.replace('“', '"').replace('”', '"')

    words = text_str.split(' ')
    small_words = {'a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 'on', 'at', 'to', 'from', 'by', 'in', 'of', 'up', 'as', 'is', 'it'}
    title_cased_words = []
    for i, word in enumerate(words):
        if word.isupper() and len(word) > 1:
             title_cased_words.append(word)
             continue

        # Handle words with internal caps like "GPT-4o" - keep them as is if not first/last and not small word
        if any(c.isupper() for c in word[1:]) and not (i == 0 or i == len(words) -1 or word.lower() in small_words) :
            title_cased_words.append(word)
            continue

        cap_word = word.upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if i == 0 or i == len(words) - 1 or word.lower() not in small_words:
            title_cased_words.append(cap_word)
        else:
            title_cased_words.append(word.lower())
    return ' '.join(title_cased_words)

# --- Helper: Truncate Function ---
def truncate_text(text_str: str, max_length: int) -> str:
    if not text_str: return ""
    
    if len(text_str) <= max_length:
        return text_str.strip()

    truncated = text_str[:max_length]
    # Try to cut at a sentence ender first if within a reasonable range
    sentence_enders = ".!?"
    best_cut_sentence = -1
    for char_idx in range(max_length -1, max(0, max_length - 20), -1):
        if truncated[char_idx] in sentence_enders:
            best_cut_sentence = char_idx + 1
            break
    if best_cut_sentence != -1:
        return truncated[:best_cut_sentence].strip()

    # Fallback to word boundary
    last_space = truncated.rfind(' ')
    if last_space > max_length - 30 and last_space > 0: 
        return truncated[:last_space].rstrip(' .,:;') + "..." 
    return truncated.rstrip(' .,:;') + "..."

# --- Agent Prompts ---
TITLE_AGENT_SYSTEM_PROMPT = """You are **Titania Prime**, an ASI-level expert in **SEO**, **persuasion psychology**, and **tech journalism**. Your sole mission is to craft, for any given tech news article, three elements in **strict JSON**:

1. `"generated_title_tag"` (This is the content part *before* any branding like " - Website Name" is appended by code)
2. `"generated_seo_h1"`
3. `"title_strategy_notes"`

**You will receive the following inputs:**

* **Primary Keyword** (string): The core topic of the article.
* **Secondary Keywords** (array of strings, max 2): Additional thematic terms.
* **Processed Summary** (string): A concise 1–2 sentence article summary.
* **Article Content Snippet** (string): The first ~200 words for nuance, tone, and unique value proposition.

### SEO Title Tag Directives (`generated_title_tag` - content part only)

* **Length**: Target 50–60 characters for *this content part*. The system will append branding.
* **Primary Keyword Placement**: Must begin with the primary keyword or a very close, natural variant.
* **Secondary Keywords**: Optional (1–2 max), only if they flow naturally.
* **Colon Prohibition & Single-Sentence Flow**: Titles **MUST NOT** use colons (':') unless the colon is an intrinsic part of a specific, widely recognized proper noun, product name, or established technical term (e.g., 'Project: Chimera' - this is extremely rare for titles). For all general title construction, colons are forbidden as they disrupt the flow of a single, compelling sentence. Craft titles as complete, grammatically sound sentences or exceptionally strong declarative/interrogative statements that flow as a single thought. Avoid structures that feel like 'Topic: Sub-topic'.
* **Avoid LLM-Esque Phrases**: Do **not** use bland, machine-favored words like “Discover,” “Explore,” “Unveiling,” “Delve,” “Harnessing,” “Leveraging,” “Navigating,” “In the realm of,” etc.
* **Inject Human Excitement**: Write like a sharp, enthusiastic tech insider. Use dynamic verbs, urgent benefit-oriented language, and powerful emotional triggers. Spark genuine curiosity or FOMO.
* **Unique Value Proposition (UVP)**: Hint at what makes this article essential (e.g., “first real-world benchmarks,” “secret optimization,” “fatal security flaw”).
* **Advanced Persuasion** (sparingly):

  * **Numbers & Data** (“Top 5,” “50% Faster”).
  * **Intrigue & Scarcity** (“Limited Early Access,” “You’re Missing This”).
  * **Problem/Solution** (“Fix GPU Bottlenecks Fast,” “Stop Wasting CPU Cycles”).
  * **Negative Framing**: When fitting, use strong warnings (“Don’t Ignore,” “Critical Mistake,” “This Is Killing Your FPS”).
* **Casing**: Title Case. Ensure acronyms like AI, GPU, CPU, API, USA, EU are kept uppercase.
* **Uniqueness**: Must differ from the H1.
* **NO BRANDING**: Do NOT include the website name (e.g., "Dacoola") in your `generated_title_tag` output; the system will append it.

### SEO H1 Heading Directives (`generated_seo_h1`)

* **Length**: Target 60–70 characters. Hard limit: 75.
* **Keyword Use & Flow**: Feature the Primary Keyword prominently. The H1 **MUST** also adhere to the **Colon Prohibition & Single-Sentence Flow** directive, crafting a compelling statement or question.
* **Avoid LLM-Esque Phrases**: Same banned words as Title Tag.
* **Human Enthusiasm**: Craft a compelling hook—pose a striking warning or bold promise.
* **UVP Reinforced**: Emphasize the article’s unique angle or benefit.
* **Casing & Uniqueness**: Title Case (respecting acronyms like Title Tag). Distinct from the Title Tag.

### Title Strategy Notes

* In 1–2 sentences, explain:

  * **Why** keyword placement was chosen for both Title Tag and H1.
  * **Which** persuasive tactics were used (UVP, urgency, emotional triggers, sentence structure).
  * How single-sentence flow without colons was achieved.

**CRITICAL REMINDER: Your entire response MUST be a single, valid JSON object. No other text or formatting outside of the JSON structure is permitted.**

### Contrasting Examples (Focus on Colon-Free, Flowing Titles)

**1) Next-Gen AI Chips**
*   `generated_title_tag`: "New AI Chips CRUSH Records! See Speed Tests Now" (Content Part)
*   `generated_seo_h1`: "Warning! These New AI Chips Will Make Your Current PC Obsolete"

**2) Zero-Day Cybersecurity Threat**
*   `generated_title_tag`: "Patch This Zero-Day Now or Your Entire Network Is at Risk" (Content Part)
*   `generated_seo_h1`: "Don’t Wait—This Zero-Day Flaw Could Cost Your Business Millions"

Use these style rules and examples as your creative blueprint.
"""
# --- End Agent Prompts ---

def call_llm_for_titles(primary_keyword: str,
                        secondary_keywords_list: list,
                        processed_summary: str,
                        article_content_snippet_val: str) -> str | None:
    secondary_keywords_str = ", ".join(secondary_keywords_list) if secondary_keywords_list else "None"
    processed_summary_snippet = (processed_summary or "No summary provided.")[:MAX_SUMMARY_SNIPPET_LEN_CONTEXT]
    content_snippet_context = (article_content_snippet_val or "No content snippet provided.")[:MAX_CONTENT_SNIPPET_LEN_CONTEXT]

    user_input_content = f"""
**Primary Keyword**: {primary_keyword}
**Secondary Keywords**: {secondary_keywords_str}
**Processed Summary**: {processed_summary_snippet}
**Article Content Snippet**: {content_snippet_context}
    """.strip()

    max_new_tokens_for_titles = 450 
    temperature_for_titles = 0.65

    messages_for_gemma = [
        {"role": "system", "content": TITLE_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_input_content}
    ]
    
    LOCAL_MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    LOCAL_RETRY_DELAY_BASE = int(os.getenv('BASE_RETRY_DELAY', 5))

    global gemma_tokenizer, gemma_model

    for attempt in range(LOCAL_MAX_RETRIES):
        try:
            if gemma_tokenizer is None or gemma_model is None:
                logger.info(f"Initializing Gemma model and tokenizer for Title Agent (attempt {attempt + 1}/{LOCAL_MAX_RETRIES}). Model: {LLM_MODEL_NAME}")
                gemma_tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME)
                quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
                gemma_model = AutoModelForCausalLM.from_pretrained(
                    LLM_MODEL_NAME,
                    quantization_config=quantization_config,
                    device_map="auto"
                )
                gemma_model.eval()
                logger.info("Gemma model and tokenizer initialized successfully for Title Agent.")

            input_text = gemma_tokenizer.apply_chat_template(
                messages_for_gemma,
                tokenize=False,
                add_generation_prompt=True
            )
            input_ids = gemma_tokenizer(input_text, return_tensors="pt").to(gemma_model.device)

            logger.debug(f"Gemma generation attempt {attempt + 1}/{LOCAL_MAX_RETRIES} for titles (PK: '{primary_keyword}')")
            with torch.no_grad():
                outputs = gemma_model.generate(
                    **input_ids,
                    max_new_tokens=max_new_tokens_for_titles,
                    temperature=temperature_for_titles if temperature_for_titles > 0.001 else None,
                    do_sample=temperature_for_titles > 0.001,
                    pad_token_id=gemma_tokenizer.eos_token_id
                )
            
            generated_ids = outputs[0, input_ids['input_ids'].shape[1]:]
            json_str = gemma_tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            
            logger.info(f"Gemma local LLM title gen successful for '{primary_keyword}'.")
            logger.debug(f"Raw JSON for titles from Gemma: {json_str}")
            return json_str
        
        except Exception as e:
            logger.exception(f"Error during Gemma local call for titles (attempt {attempt + 1}/{LOCAL_MAX_RETRIES}): {e}")
            if attempt == LOCAL_MAX_RETRIES - 1:
                logger.error("All Gemma local attempts for titles failed due to errors.")
                if isinstance(e, (RuntimeError, ImportError, OSError)): # Errors likely during model loading
                    logger.warning("Resetting global gemma_model and gemma_tokenizer for Title Agent due to critical error.")
                    gemma_tokenizer = None
                    gemma_model = None
                return None
        
        delay = min(LOCAL_RETRY_DELAY_BASE * (2 ** attempt), 60)
        logger.warning(f"Gemma local call for titles failed (attempt {attempt+1}/{LOCAL_MAX_RETRIES}). Retrying in {delay}s.")
        time.sleep(delay)
            
    logger.error(f"Gemma LLM local call for titles failed after {LOCAL_MAX_RETRIES} attempts for PK '{primary_keyword}'.")
    return None

def _clean_and_validate_title(title_str: str | None, max_len: int, title_type: str, pk_for_log: str, is_title_tag_content: bool = False) -> str:
    """Cleans, title cases, truncates, and validates a title string."""
    if not title_str or not isinstance(title_str, str) or not title_str.strip():
        logger.warning(f"Empty or invalid {title_type} received from LLM for '{pk_for_log}'.")
        return ""

    cleaned_title = title_str
    # Remove any leading/trailing markdown or JSON fences if LLM mistakenly adds them
    cleaned_title = re.sub(r"^```(?:json|text)?\s*|\s*```$", "", cleaned_title.strip())
    if cleaned_title.startswith('{') and cleaned_title.endswith('}'): 
        try:
            json_data = json.loads(cleaned_title)
            if isinstance(json_data, dict):
                potential_key = "generated_title_tag" if is_title_tag_content else "generated_seo_h1"
                if potential_key in json_data and isinstance(json_data[potential_key], str):
                    cleaned_title = json_data[potential_key]
                elif "title" in json_data and isinstance(json_data["title"], str):
                     cleaned_title = json_data["title"]
                else:
                    for val in json_data.values():
                        if isinstance(val, str): cleaned_title = val; break
                    else: 
                         logger.warning(f"LLM returned JSON object for {title_type}, and no clear title field found. PK: '{pk_for_log}'.")
                         return ""
                logger.warning(f"LLM returned JSON object for {title_type}, extracted '{cleaned_title}'. PK: '{pk_for_log}'.")
        except json.JSONDecodeError:
            pass 

    # Apply ftfy for fixing encoding issues and normalizing text early
    cleaned_title = ftfy.fix_text(cleaned_title)
    
    # Remove " - WebsiteName" or "WebsiteName" if LLM accidentally added it
    if is_title_tag_content and WEBSITE_NAME: # Only for title tag content part
        brand_pattern_suffix = re.compile(r'\s*-\s*' + re.escape(WEBSITE_NAME) + r'\s*$', re.IGNORECASE)
        brand_pattern_direct = re.compile(re.escape(WEBSITE_NAME) + r'\s*$', re.IGNORECASE) # if it ends with brand
        
        original_for_log = cleaned_title
        cleaned_title = brand_pattern_suffix.sub('', cleaned_title)
        if len(cleaned_title) == len(original_for_log): # if suffix pattern didn't match, try direct
            cleaned_title = brand_pattern_direct.sub('', cleaned_title)
        
        cleaned_title = cleaned_title.strip().rstrip(' -') # Remove trailing hyphen if any
        if len(cleaned_title) < len(original_for_log):
             logger.info(f"Removed LLM-generated branding from {title_type} for '{pk_for_log}'. Original: '{original_for_log}', Cleaned: '{cleaned_title}'")


    # Basic cleaning of quotes (LLM might still use them despite examples)
    cleaned_title = cleaned_title.replace('"', '').replace("'", "").strip()

    # Colon check - more aggressive removal
    if ":" in cleaned_title and not re.search(r"(Project|Version|API|Module|Part):\s*\w+", cleaned_title, re.IGNORECASE):
        parts = [p.strip() for p in cleaned_title.split(":", 1)]
        if len(parts) == 2:
            # Prioritize the part with the primary keyword if it exists and is substantial
            if pk_for_log.lower() in parts.lower() and len(parts) > len(parts) * 0.4:
                 merged_title = parts
            elif pk_for_log.lower() in parts.lower():
                 merged_title = parts
            # Otherwise, try to merge or pick the longer/more descriptive part
            elif len(parts) > len(parts) * 0.6 or len(parts) < 10: # If first part is significantly longer or second is too short
                merged_title = parts + " " + parts
            else: # Second part is likely more descriptive
                merged_title = parts
            cleaned_title_before_colon_removal = cleaned_title
            cleaned_title = re.sub(r'\s+', ' ', merged_title).strip() # Consolidate spaces
            logger.info(f"Colon processed for {title_type} for '{pk_for_log}'. Original: '{cleaned_title_before_colon_removal}', Processed: '{cleaned_title}'")
        else: 
            cleaned_title = cleaned_title.replace(":", " ").replace("  ", " ").strip()


    title_cased = to_title_case(cleaned_title)
    truncated_title = truncate_text(title_cased, max_len)

    # Log truncation only if it actually happened and wasn't just a whitespace strip
    if len(title_cased) > max_len and len(truncated_title) < len(title_cased):
        logger.warning(f"LLM {title_type} for '{pk_for_log}' (len: {len(title_cased)}) > max_len ({max_len}), truncated: '{title_cased}' -> '{truncated_title}'")
    
    return truncated_title


def parse_llm_title_response(json_string: str | None, primary_keyword_for_fallback: str) -> dict:
    parsed_data = {'generated_title_tag': None, 'generated_seo_h1': None, 'title_strategy_notes': None, 'error': None}
    pk_fallback_clean = primary_keyword_for_fallback or "Tech News"

    def create_fallback_title_tag():
        raw_fallback = DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword=pk_fallback_clean)
        title_cased = to_title_case(raw_fallback)
        # Truncate content part before adding suffix
        content_part = truncate_text(title_cased, TITLE_TAG_CONTENT_TARGET_MAX_LEN)
        return content_part + BRAND_SUFFIX_FOR_TITLE_TAG

    def create_fallback_h1():
        raw_fallback = DEFAULT_FALLBACK_H1_RAW.format(primary_keyword=pk_fallback_clean)
        title_cased = to_title_case(raw_fallback)
        return truncate_text(title_cased, SEO_H1_HARD_MAX_LEN)

    if not json_string:
        parsed_data['error'] = "LLM response for titles was empty."
        parsed_data['generated_title_tag'] = create_fallback_title_tag()
        parsed_data['generated_seo_h1'] = create_fallback_h1()
        logger.warning(f"Using fallback titles for '{pk_fallback_clean}' (empty LLM response).")
        return parsed_data

    try:
        # Apply ftfy to the whole raw JSON string from LLM
        fixed_json_string = ftfy.fix_text(json_string)
        
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', fixed_json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else fixed_json_string
        
        llm_output = json.loads(json_to_parse)
        if not isinstance(llm_output, dict): raise ValueError("LLM output was not a dictionary.")

        title_tag_raw_content = llm_output.get('generated_title_tag')
        # Clean the content part first, then add suffix
        cleaned_title_tag_content = _clean_and_validate_title(title_tag_raw_content, TITLE_TAG_CONTENT_TARGET_MAX_LEN, "Title Tag Content", pk_fallback_clean, is_title_tag_content=True)
        
        if cleaned_title_tag_content:
            parsed_data['generated_title_tag'] = cleaned_title_tag_content + BRAND_SUFFIX_FOR_TITLE_TAG
        else:
            parsed_data['generated_title_tag'] = create_fallback_title_tag()
            parsed_data['error'] = (parsed_data.get('error') or "") + "Missing/invalid title_tag_content from LLM. "
        
        seo_h1_raw = llm_output.get('generated_seo_h1')
        cleaned_seo_h1 = _clean_and_validate_title(seo_h1_raw, SEO_H1_HARD_MAX_LEN, "SEO H1", pk_fallback_clean)
        parsed_data['generated_seo_h1'] = cleaned_seo_h1 if cleaned_seo_h1 else create_fallback_h1()
        if not cleaned_seo_h1: parsed_data['error'] = (parsed_data.get('error') or "") + "Missing/invalid seo_h1 from LLM. "

        parsed_data['title_strategy_notes'] = llm_output.get('title_strategy_notes')
        if not parsed_data['title_strategy_notes']:
            parsed_data['title_strategy_notes'] = "No strategy notes provided by LLM."


    except Exception as e:
        logger.error(f"Error parsing LLM title response '{json_string[:200]}...': {e}", exc_info=True)
        parsed_data['error'] = str(e)
        parsed_data['generated_title_tag'] = create_fallback_title_tag()
        parsed_data['generated_seo_h1'] = create_fallback_h1()
    return parsed_data

def run_title_generator_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Title Generator Agent (Colon-Free, ftfy Enhanced) for Article ID: {article_id} ---")

    final_keywords_list = article_pipeline_data.get('final_keywords', [])
    primary_keyword = final_keywords_list if final_keywords_list and isinstance(final_keywords_list, list) else None
    if not primary_keyword:
        primary_keyword = article_pipeline_data.get('primary_topic_keyword', article_pipeline_data.get('title', 'Key Tech Topic'))
        logger.warning(f"Primary keyword for title gen not from 'final_keywords' for {article_id}, using fallback: '{primary_keyword}'")

    secondary_keywords = [kw for kw in final_keywords_list if kw.lower() != primary_keyword.lower()][:2] if final_keywords_list else []
    processed_summary = article_pipeline_data.get('processed_summary', '')
    article_content_for_snippet = article_pipeline_data.get('raw_scraped_text', processed_summary) 
    article_content_snippet_for_llm = (article_content_for_snippet or "")[:MAX_CONTENT_SNIPPET_LEN_CONTEXT] 
    
    pk_for_fallback_logic = primary_keyword or "Tech Insight"

    if not primary_keyword and not processed_summary and not article_content_snippet_for_llm:
        logger.error(f"Insufficient context (PK, summary, snippet all missing/short) for {article_id}. Using fallbacks for titles.")
        fallback_title_content = truncate_text(to_title_case(DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword=pk_for_fallback_logic)), TITLE_TAG_CONTENT_TARGET_MAX_LEN)
        title_results = {
            'generated_title_tag': fallback_title_content + BRAND_SUFFIX_FOR_TITLE_TAG,
            'generated_seo_h1': truncate_text(to_title_case(DEFAULT_FALLBACK_H1_RAW.format(primary_keyword=pk_for_fallback_logic)), SEO_H1_HARD_MAX_LEN),
            'title_strategy_notes': "Fallback: Insufficient input for LLM.", 'error': "Insufficient input."}
    else:
        raw_llm_response = call_llm_for_titles(primary_keyword, secondary_keywords, processed_summary, article_content_snippet_for_llm)
        title_results = parse_llm_title_response(raw_llm_response, pk_for_fallback_logic)

    article_pipeline_data.update(title_results)
    article_pipeline_data['title_agent_status'] = "SUCCESS" if not title_results.get('error') else "FAILED_WITH_FALLBACK"
    if title_results.get('error'): article_pipeline_data['title_agent_error'] = title_results['error']
    
    logger.info(f"Title Generator Agent for {article_id} status: {article_pipeline_data['title_agent_status']}.")
    logger.info(f"  Generated Title Tag: {article_pipeline_data['generated_title_tag']}")
    logger.info(f"  Generated SEO H1: {article_pipeline_data['generated_seo_h1']}")
    logger.debug(f"  Strategy Notes: {article_pipeline_data.get('title_strategy_notes')}")
    return article_pipeline_data

if __name__ == "__main__":
    logging.getLogger('src.agents.title_generator_agent').setLevel(logging.DEBUG) # More verbose for this agent
    logger.info("--- Starting Title Generator Agent (Gemma Local, Colon-Free, ftfy) Standalone Test ---")
    if torch.cuda.is_available():
        logger.info(f"CUDA is available. Device: {torch.cuda.get_device_name(0)}")
    else:
        logger.info("CUDA not available. Gemma model will run on CPU (this might be slow).")

    sample_article_data = {
        'id': 'test_title_gemma_001',
        'title': "NVIDIA Blackwell B200 GPU: A New AI Chip with Nvidia’s latest tech", # Original title with ’
        'processed_summary': "NVIDIA unveiled its new Blackwell B200 GPU, the successor to H100, promising massive performance gains for AI training & inference.", # & for testing
        'primary_topic_keyword': "NVIDIA Blackwell B200 GPU", 
        'final_keywords': ["NVIDIA Blackwell B200 GPU", "AI Supercomputing", "Next Gen GPU", "Jensen Huang"],
        'raw_scraped_text': "NVIDIA's GTC conference today was dominated by the announcement of the Blackwell B200 GPU. This new chip promises to redefine AI supercomputing with significant performance leaps. CEO Jensen Huang highlighted its capabilities for trillion-parameter models like 'GPT-X', emphasizing speed & efficiency. The B200 architecture (Project: Titan) represents a major shift." # Test with & and ' and "
    }
    result_data = run_title_generator_agent(sample_article_data.copy())
    logger.info("\n--- Test Results (Colon-Free, ftfy Focus) ---")
    logger.info(f"Status: {result_data.get('title_agent_status')}")
    if result_data.get('title_agent_error'): logger.error(f"Error: {result_data.get('title_agent_error')}")
    
    generated_title_tag = result_data.get('generated_title_tag','')
    generated_seo_h1 = result_data.get('generated_seo_h1','')
    
    logger.info(f"Title Tag: '{generated_title_tag}' (Len: {len(generated_title_tag)})")
    logger.info(f"SEO H1: '{generated_seo_h1}' (Len: {len(generated_seo_h1)})")

    # Check for colons and problematic characters
    colon_fail = False
    problem_chars_fail = False
    if ":" in generated_title_tag and not re.search(r"(Project|Version|API|Module|Part):\s*\w+", generated_title_tag, re.IGNORECASE):
        logger.error("TEST FAILED: Colon found in generated title tag!")
        colon_fail = True
    if ":" in generated_seo_h1 and not re.search(r"(Project|Version|API|Module|Part):\s*\w+", generated_seo_h1, re.IGNORECASE):
        logger.error("TEST FAILED: Colon found in generated H1!")
        colon_fail = True
    
    if '�' in generated_title_tag or '�' in generated_seo_h1:
        logger.error("TEST FAILED: Mojibake '�' character found in titles!")
        problem_chars_fail = True
    if '—' in generated_title_tag or '—' in generated_seo_h1: # Check for em-dash
        logger.warning("STYLE WARNING: Em-dash '—' found in titles. Prompt discourages this.")
        # Not a hard fail for now, but a style deviation.

    if not colon_fail: logger.info("COLON TEST PASSED: No problematic colons found.")
    if not problem_chars_fail: logger.info("MOJIBAKE TEST PASSED: No '�' found.")
    
    logger.info("\n--- Test Fallback (Gemma Local, Colon-Free, ftfy Focus) ---")
    minimal_data = {'id': 'test_fallback_gemma_002', 'primary_topic_keyword': "Quantum Computing: The Future?"} # Test with colon in PK
    result_minimal = run_title_generator_agent(minimal_data.copy())
    logger.info(f"Minimal Data Status (Gemma): {result_minimal.get('title_agent_status')}")
    logger.info(f"Minimal Title Tag (Gemma): '{result_minimal.get('generated_title_tag')}'")
    logger.info(f"Minimal SEO H1 (Gemma): '{result_minimal.get('generated_seo_h1')}'")
    if ":" in result_minimal.get('generated_title_tag','').replace(BRAND_SUFFIX_FOR_TITLE_TAG, '') or ":" in result_minimal.get('generated_seo_h1',''):
        logger.error("FALLBACK COLON TEST FAILED (Gemma): Colon found in fallback title tag or H1 (excluding allowed patterns).")
    else:
        logger.info("FALLBACK COLON TEST PASSED (Gemma): No problematic colons found in fallback titles.")
    if '�' in result_minimal.get('generated_title_tag','') or '�' in result_minimal.get('generated_seo_h1',''):
        logger.error("FALLBACK MOJIBAKE TEST FAILED (Gemma): '�' found in fallback titles!")
    else:
        logger.info("FALLBACK MOJIBAKE TEST PASSED (Gemma): No '�' found in fallback titles.")

    logger.info("--- Standalone Test (Gemma Local, Colon-Free, ftfy Focus) Complete ---")
    # Explicitly free memory
    global gemma_model, gemma_tokenizer
    if gemma_model is not None:
        try:
            del gemma_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Gemma model explicitly deleted and CUDA cache cleared for Title Agent (if applicable).")
        except Exception as e:
            logger.warning(f"Could not explicitly delete model or clear cache for Title Agent: {e}")
    gemma_model = None
    gemma_tokenizer = None
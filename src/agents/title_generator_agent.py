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
import modal # Added for Modal integration
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
LLM_MODEL_NAME = os.getenv('TITLE_AGENT_MODEL', "deepseek-R1") # Updated model name
WEBSITE_NAME = os.getenv('WEBSITE_NAME', 'Dacoola') # Retain for branding logic
BRAND_SUFFIX_FOR_TITLE_TAG = f" - {WEBSITE_NAME}"

MODAL_APP_NAME = "deepseek-gpu-inference-app" # Updated: Name of the Modal app
MODAL_CLASS_NAME = "DeepSeekModel" # Name of the class in the Modal app

API_TIMEOUT = 90 # Retained for Modal call options if applicable
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

        cap_word = word[0].upper() + word[1:].lower() if word else "" # Corrected capitalization
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
    """.strip() # Ensure user_input_content is stripped

    # Max tokens for the title generation, temperature, and response_format are assumed
    # to be handled by the Modal class or can be passed if supported.
    # Using a placeholder for max_tokens for now.
    max_new_tokens_for_titles = 450 # Corresponds to "max_tokens" in original payload

    messages_for_modal = [
        {"role": "system", "content": TITLE_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_input_content}
    ]
    
    # Using global MAX_RETRIES and RETRY_DELAY_BASE if available, or define locally
    # For consistency with other agents, let's assume they are available globally or define them if needed.
    # If not defined globally, ensure they are defined in this file (e.g., MAX_RETRIES = 3, RETRY_DELAY_BASE = 5)
    # Assuming MAX_RETRIES and RETRY_DELAY_BASE are defined globally or imported.
    # If not, they should be added here. For this example, I'll assume they are accessible.
    # Define local constants if not globally available:
    LOCAL_MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    LOCAL_RETRY_DELAY_BASE = int(os.getenv('BASE_RETRY_DELAY', 5))


    for attempt in range(LOCAL_MAX_RETRIES):
        try:
            logger.debug(f"Modal API call attempt {attempt + 1}/{LOCAL_MAX_RETRIES} for titles (PK: '{primary_keyword}')")
            
            RemoteModelClass = modal.Cls.from_name(MODAL_APP_NAME, MODAL_CLASS_NAME)
            if not RemoteModelClass:
                logger.error(f"Could not find Modal class {MODAL_APP_NAME}/{MODAL_CLASS_NAME}. Ensure it's deployed.")
                if attempt == LOCAL_MAX_RETRIES - 1: return None # Last attempt
                delay = min(LOCAL_RETRY_DELAY_BASE * (2 ** attempt), 60)
                logger.info(f"Waiting {delay}s for Modal class lookup before retry...")
                time.sleep(delay)
                continue
            
            model_instance = RemoteModelClass() # Instantiate the remote class

            result = model_instance.generate.remote(
                messages=messages_for_modal,
                max_new_tokens=max_new_tokens_for_titles,
                temperature=0.65, # Pass temperature
                model=LLM_MODEL_NAME # Pass model name
            )

            if result and result.get("choices") and result["choices"].get("message") and \
               isinstance(result["choices"]["message"].get("content"), str):
                json_str = result["choices"]["message"]["content"]
                logger.info(f"Modal LLM title gen successful for '{primary_keyword}'.")
                logger.debug(f"Raw JSON for titles from Modal: {json_str}")
                return json_str
            else:
                logger.error(f"Modal LLM title response missing content or malformed (attempt {attempt + 1}/{LOCAL_MAX_RETRIES}): {str(result)[:500]}")
                if attempt == LOCAL_MAX_RETRIES - 1: return None
        
        except Exception as e:
            logger.exception(f"Error during Modal API call for titles (attempt {attempt + 1}/{LOCAL_MAX_RETRIES}): {e}")
            if attempt == LOCAL_MAX_RETRIES - 1:
                logger.error("All Modal API attempts for titles failed due to errors.")
                return None
        
        delay = min(LOCAL_RETRY_DELAY_BASE * (2 ** attempt), 60)
        logger.warning(f"Modal API call for titles failed or returned unexpected data (attempt {attempt+1}/{LOCAL_MAX_RETRIES}). Retrying in {delay}s.")
        time.sleep(delay)
        
    logger.error(f"Modal LLM API call for titles failed after {LOCAL_MAX_RETRIES} attempts for PK '{primary_keyword}'.")
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
    pk_fallback_clean = (primary_keyword_for_fallback or "Tech News").replace(":", " ") # Ensure colon-free PK for fallback

    def create_fallback_title_tag_content(): # Renamed to indicate it returns content part
        raw_fallback_content = DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword=pk_fallback_clean)
        # Pass through _clean_and_validate_title for consistent cleaning including colon removal
        return _clean_and_validate_title(raw_fallback_content, TITLE_TAG_CONTENT_TARGET_MAX_LEN, "Fallback Title Tag Content", pk_fallback_clean, is_title_tag_content=True)

    def create_fallback_h1():
        raw_fallback_h1 = DEFAULT_FALLBACK_H1_RAW.format(primary_keyword=pk_fallback_clean)
        # Pass through _clean_and_validate_title for consistent cleaning
        return _clean_and_validate_title(raw_fallback_h1, SEO_H1_HARD_MAX_LEN, "Fallback SEO H1", pk_fallback_clean)

    if not json_string:
        parsed_data['error'] = "LLM response for titles was empty."
        fallback_title_content = create_fallback_title_tag_content()
        parsed_data['generated_title_tag'] = (fallback_title_content + BRAND_SUFFIX_FOR_TITLE_TAG) if fallback_title_content else (DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword="Update") + BRAND_SUFFIX_FOR_TITLE_TAG) # Ultimate fallback if cleaning returns empty
        parsed_data['generated_seo_h1'] = create_fallback_h1() or DEFAULT_FALLBACK_H1_RAW.format(primary_keyword="Breaking News") # Ultimate fallback
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
            fallback_title_content = create_fallback_title_tag_content()
            parsed_data['generated_title_tag'] = (fallback_title_content + BRAND_SUFFIX_FOR_TITLE_TAG) if fallback_title_content else (DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword="Update") + BRAND_SUFFIX_FOR_TITLE_TAG)
            parsed_data['error'] = (parsed_data.get('error') or "") + "Missing/invalid title_tag_content from LLM. "
        
        seo_h1_raw = llm_output.get('generated_seo_h1')
        cleaned_seo_h1 = _clean_and_validate_title(seo_h1_raw, SEO_H1_HARD_MAX_LEN, "SEO H1", pk_fallback_clean)
        parsed_data['generated_seo_h1'] = cleaned_seo_h1 if cleaned_seo_h1 else (create_fallback_h1() or DEFAULT_FALLBACK_H1_RAW.format(primary_keyword="Breaking News"))
        if not cleaned_seo_h1: parsed_data['error'] = (parsed_data.get('error') or "") + "Missing/invalid seo_h1 from LLM. "

        parsed_data['title_strategy_notes'] = llm_output.get('title_strategy_notes')
        if not parsed_data['title_strategy_notes']:
            parsed_data['title_strategy_notes'] = "No strategy notes provided by LLM."


    except Exception as e:
        logger.error(f"Error parsing LLM title response '{json_string[:200]}...': {e}", exc_info=True)
        parsed_data['error'] = str(e)
        fallback_title_content = create_fallback_title_tag_content()
        parsed_data['generated_title_tag'] = (fallback_title_content + BRAND_SUFFIX_FOR_TITLE_TAG) if fallback_title_content else (DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword="Update") + BRAND_SUFFIX_FOR_TITLE_TAG)
        parsed_data['generated_seo_h1'] = create_fallback_h1() or DEFAULT_FALLBACK_H1_RAW.format(primary_keyword="Breaking News")
    return parsed_data

def run_title_generator_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Title Generator Agent (Colon-Free, ftfy Enhanced) for Article ID: {article_id} ---")

    final_keywords_list = article_pipeline_data.get('final_keywords', [])
    primary_keyword_str = None

    if final_keywords_list and isinstance(final_keywords_list, list) and len(final_keywords_list) > 0:
        if isinstance(final_keywords_list[0], str) and final_keywords_list[0].strip():
            primary_keyword_str = final_keywords_list[0].strip()
        else:
            logger.warning(f"First element of final_keywords_list for {article_id} is not a valid string. Proceeding to fallbacks.")

    if not primary_keyword_str:
        fallback_pk_source = article_pipeline_data.get('primary_topic_keyword')
        if fallback_pk_source and isinstance(fallback_pk_source, str) and fallback_pk_source.strip():
            primary_keyword_str = fallback_pk_source.strip()
            logger.warning(f"Primary keyword for title gen for {article_id} not from final_keywords[0], using 'primary_topic_keyword': '{primary_keyword_str}'")
        else:
            fallback_pk_source = article_pipeline_data.get('title')
            if fallback_pk_source and isinstance(fallback_pk_source, str) and fallback_pk_source.strip():
                primary_keyword_str = fallback_pk_source.strip()
                logger.warning(f"Primary keyword for title gen for {article_id} not from final_keywords[0] or 'primary_topic_keyword', using 'title': '{primary_keyword_str}'")
            else:
                primary_keyword_str = "Key Tech Topic" # Ultimate fallback
                logger.warning(f"Primary keyword for title gen for {article_id} could not be determined from keywords or title, using default: '{primary_keyword_str}'")

    secondary_keywords = []
    if final_keywords_list and isinstance(final_keywords_list, list):
        seen_keywords = {primary_keyword_str.lower()}
        for kw in final_keywords_list:
            if isinstance(kw, str) and kw.strip() and kw.lower() not in seen_keywords:
                secondary_keywords.append(kw.strip())
                seen_keywords.add(kw.lower())
            if len(secondary_keywords) >= 2:
                break
    
    processed_summary = article_pipeline_data.get('processed_summary', '')
    article_content_for_snippet = article_pipeline_data.get('raw_scraped_text', processed_summary) 
    article_content_snippet_for_llm = (article_content_for_snippet or "")[:MAX_CONTENT_SNIPPET_LEN_CONTEXT] 
    
    pk_for_fallback_logic = primary_keyword_str if (primary_keyword_str and primary_keyword_str != "Key Tech Topic") else "Tech Insight"

    if not primary_keyword_str and not processed_summary and not article_content_snippet_for_llm : # Check if primary_keyword_str is meaningful
        logger.error(f"Insufficient context (PK, summary, snippet all missing/short) for {article_id}. Using fallbacks for titles.")
        fallback_title_content = truncate_text(to_title_case(DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword=pk_for_fallback_logic)), TITLE_TAG_CONTENT_TARGET_MAX_LEN)
        title_results = {
            'generated_title_tag': fallback_title_content + BRAND_SUFFIX_FOR_TITLE_TAG,
            'generated_seo_h1': truncate_text(to_title_case(DEFAULT_FALLBACK_H1_RAW.format(primary_keyword=pk_for_fallback_logic)), SEO_H1_HARD_MAX_LEN),
            'title_strategy_notes': "Fallback: Insufficient input for LLM.", 'error': "Insufficient input."}
    else:
        raw_llm_response = call_llm_for_titles(primary_keyword_str, secondary_keywords, processed_summary, article_content_snippet_for_llm)
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
    logger.info("--- Starting Title Generator Agent (Colon-Free, ftfy) Standalone Test ---")

    sample_article_data = {
        'id': 'test_title_ftfy_001',
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
        logger.error("TEST FAILED: Unicode replacement characters (U+FFFD) found in titles!")
        problem_chars_fail = True
    if '—' in generated_title_tag or '—' in generated_seo_h1: # Check for em-dash
        logger.warning("STYLE WARNING: Em-dash '—' found in titles. Prompt discourages this.")
        # Not a hard fail for now, but a style deviation.

    if not colon_fail: logger.info("COLON TEST PASSED: No problematic colons found.")
    if not problem_chars_fail: logger.info("MOJIBAKE TEST PASSED: No Unicode replacement characters (U+FFFD) found.")
    
    logger.info("\n--- Test Fallback (Colon-Free, ftfy Focus) ---")
    minimal_data = {'id': 'test_fallback_ftfy_002', 'primary_topic_keyword': "Quantum Computing: The Future?"} # Test with colon in PK
    result_minimal = run_title_generator_agent(minimal_data.copy())
    logger.info(f"Minimal Data Status: {result_minimal.get('title_agent_status')}")
    logger.info(f"Minimal Title Tag: '{result_minimal.get('generated_title_tag')}'")
    logger.info(f"Minimal SEO H1: '{result_minimal.get('generated_seo_h1')}'")
    if ":" in result_minimal.get('generated_title_tag','').replace(BRAND_SUFFIX_FOR_TITLE_TAG, '') or ":" in result_minimal.get('generated_seo_h1',''):
        logger.error("FALLBACK COLON TEST FAILED: Colon found in fallback title tag or H1 (excluding allowed patterns).")
    else:
        logger.info("FALLBACK COLON TEST PASSED: No problematic colons found in fallback titles.")
    if '�' in result_minimal.get('generated_title_tag','') or '�' in result_minimal.get('generated_seo_h1',''): # Check for literal replacement char
        logger.error("FALLBACK MOJIBAKE TEST FAILED: Unicode replacement characters (U+FFFD) found in fallback titles!")
    else:
        logger.info("FALLBACK MOJIBAKE TEST PASSED: No Unicode replacement characters (U+FFFD) found in fallback titles.")


    logger.info("--- Standalone Test (Colon-Free, ftfy Focus) Complete ---")
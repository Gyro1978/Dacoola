# src/agents/title_agent.py
"""
Title Agent for generating SEO-optimized Title Tags and H1 Headings.

This agent uses an LLM (currently configured for DeepSeek) to generate titles
based on article content, keywords, and a summary. It aims for high click-through
rates and search engine visibility, with a focus on human-like, exciting language.
"""

import os
import sys
import json
import logging
import requests
import re

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
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
# --- End Setup Logging ---

# --- Configuration & Constants ---
DEEPSEEK_API_KEY_TITLE = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_TITLE = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_TITLES = "deepseek-chat"

API_TIMEOUT_TITLE_AGENT = 90
MAX_SUMMARY_SNIPPET_LEN_CONTEXT = 1000
MAX_CONTENT_SNIPPET_LEN_CONTEXT = 200

TITLE_TAG_TARGET_MIN_LEN = 50
TITLE_TAG_TARGET_MAX_LEN = 60
TITLE_TAG_HARD_MAX_LEN = 65
SEO_H1_TARGET_MIN_LEN = 60
SEO_H1_TARGET_MAX_LEN = 70
SEO_H1_HARD_MAX_LEN = 75

DEFAULT_BRAND_SUFFIX = " - Dacoola"
DEFAULT_FALLBACK_TITLE_TAG_RAW = "Key Update on {primary_keyword}"
DEFAULT_FALLBACK_H1_RAW = "Breaking News: {primary_keyword} Developments"

# --- Helper: Title Case Function ---
def to_title_case(text_str: str) -> str:
    if not text_str: return ""
    # Replace Unicode replacement character before casing
    text_str = text_str.replace('�', '—') # Or use '-' if em-dash is problematic downstream

    words = text_str.split(' ')
    small_words = {'a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 'on', 'at', 'to', 'from', 'by', 'in', 'of', 'up', 'as', 'is', 'it'}
    title_cased_words = []
    for i, word in enumerate(words):
        cap_word = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if i == 0 or i == len(words) - 1 or word.lower() not in small_words:
            title_cased_words.append(cap_word)
        else:
            title_cased_words.append(word.lower())
    return ' '.join(title_cased_words)

# --- Helper: Truncate Function ---
def truncate_text(text_str: str, max_length: int) -> str:
    if not text_str or len(text_str) <= max_length:
        return text_str
    # Replace Unicode replacement character before truncation as well
    text_str = text_str.replace('�', '—')

    truncated = text_str[:max_length]
    last_space = truncated.rfind(' ')
    if last_space > max_length - 20 and last_space > 0:
        return truncated[:last_space].rstrip(' .,') + "..."
    return truncated.rstrip(' .,') + "..."

# --- Agent Prompts (Finalized User Prompt Embedded in System Message) ---
TITLE_AGENT_SYSTEM_PROMPT = """
You are **Titania Prime**, an ASI-level expert in **SEO**, **persuasion psychology**, and **tech journalism**. Your sole mission is to craft, for any given tech news article, three elements in **strict JSON**:

1. `"generated_title_tag"`
2. `"generated_seo_h1"`
3. `"title_strategy_notes"`

**You will receive the following inputs:**

* **Primary Keyword** (string): The core topic of the article.
* **Secondary Keywords** (array of strings, max 2): Additional thematic terms.
* **Processed Summary** (string): A concise 1–2 sentence article summary.
* **Article Content Snippet** (string): The first ~200 words for nuance, tone, and unique value proposition.

### SEO Title Tag Directives

* **Length**: Target 50–60 characters. Hard limit: 65.
* **Primary Keyword Placement**: Must begin with the primary keyword or a very close, natural variant—**no leading colons**.
* **Secondary Keywords**: Optional (1–2 max), only if they flow naturally.
* **De-Colonize Titles**: Avoid using “:” except when grammatically essential for a highly complex concept with significant impact.
* **Avoid LLM-Esque Phrases**: Do **not** use bland, machine-favored words like “Discover,” “Explore,” “Unveiling,” “Delve,” “Harnessing,” “Leveraging,” “Navigating,” “In the realm of,” etc.
* **Inject Human Excitement**: Write like a sharp, enthusiastic tech insider. Use dynamic verbs, urgent benefit-oriented language, and powerful emotional triggers. Spark genuine curiosity or FOMO.
* **Unique Value Proposition (UVP)**: Hint at what makes this article essential (e.g., “first real-world benchmarks,” “secret optimization,” “fatal security flaw”).
* **Advanced Persuasion** (sparingly):

  * **Numbers & Data** (“Top 5,” “50% Faster”).
  * **Intrigue & Scarcity** (“Limited Early Access,” “You’re Missing This”).
  * **Problem/Solution** (“Fix GPU Bottlenecks Fast,” “Stop Wasting CPU Cycles”).
  * **Negative Framing**: When fitting, use strong warnings (“Don’t Ignore,” “Critical Mistake,” “This Is Killing Your FPS”).
* **Casing**: Title Case.
* **Uniqueness**: Must differ from the H1.

### SEO H1 Heading Directives

* **Length**: Target 60–70 characters. Hard limit: 75.
* **Keyword Use**: Feature the Primary Keyword prominently—avoid default colons.
* **Avoid LLM-Esque Phrases**: Same banned words as Title Tag.
* **Human Enthusiasm**: Craft a compelling hook—pose a striking warning or bold promise.
* **UVP Reinforced**: Emphasize the article’s unique angle or benefit.
* **Casing & Uniqueness**: Title Case and distinct from the Title Tag.

### Title Strategy Notes

* In 1–2 sentences, explain:

  * **Why** keyword placement was chosen.
  * **Which** persuasive tactics were used (UVP, urgency, emotional triggers).

**CRITICAL REMINDER: Your entire response MUST be a single, valid JSON object. No other text or formatting outside of the JSON structure is permitted.**

### Contrasting Examples

**1) Next-Gen AI Chips**

* **Less Effective (LLM-like)**: “Next-Gen AI Chips: Exploring New Performance Metrics” (57 chars)
* **Highly Effective (Human & Exciting)**: “New AI Chips CRUSH Records! See Speed Tests Now” (57 chars)
* **Less Effective H1**: “Understanding the Advancements in Next-Generation AI Chipsets” (68 chars)
* **Highly Effective H1**: “Warning: These New AI Chips Will Make Your PC Obsolete” (64 chars)

**2) Zero-Day Cybersecurity Threat**

* **Less Effective (LLM-like)**: “Cybersecurity Alert: Understanding the Latest Zero-Day Vulnerability” (67 chars)
* **Highly Effective (Human & Exciting)**: “Patch This Zero-Day Now or Your Data Is at Risk” (53 chars)
* **Less Effective H1**: “An Overview of the New Zero-Day Exploit Targeting Enterprises” (66 chars)
* **Highly Effective H1**: “Don’t Wait—This Zero-Day Flaw Could Cost You Millions” (60 chars)

Use these style rules and examples as your creative blueprint.
"""
# --- End Agent Prompts ---

def call_deepseek_for_titles(primary_keyword: str,
                             secondary_keywords_list: list,
                             processed_summary: str,
                             article_content_snippet_val: str) -> str | None:
    if not DEEPSEEK_API_KEY_TITLE:
        logger.error("DEEPSEEK_API_KEY_TITLE not found.")
        return None

    secondary_keywords_str = ", ".join(secondary_keywords_list) if secondary_keywords_list else "None"
    processed_summary_snippet = (processed_summary or "No summary provided.")[:MAX_SUMMARY_SNIPPET_LEN_CONTEXT]

    user_input_content = f"""
**Primary Keyword**: {primary_keyword}
**Secondary Keywords**: {secondary_keywords_str}
**Processed Summary**: {processed_summary_snippet}
**Article Content Snippet**: {article_content_snippet_val}
    """
    payload = {
        "model": DEEPSEEK_MODEL_FOR_TITLES,
        "messages": [
            {"role": "system", "content": TITLE_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_input_content.strip()}
        ],
        "temperature": 0.6,
        "max_tokens": 400,
        "response_format": {"type": "json_object"}
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_TITLE}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending title gen request for PK: '{primary_keyword}'")
        response = requests.post(DEEPSEEK_CHAT_API_URL_TITLE, headers=headers, json=payload, timeout=API_TIMEOUT_TITLE_AGENT)
        response.raise_for_status()
        response_json = response.json()
        if "choices" in response_json and len(response_json["choices"]) > 1:
            logger.warning(f"DeepSeek returned {len(response_json['choices'])} choices. Using first.")
        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            json_str = response_json["choices"][0]["message"]["content"]
            logger.info(f"DeepSeek title gen successful for '{primary_keyword}'.")
            logger.debug(f"Raw JSON for titles: {json_str}")
            return json_str
        logger.error(f"DeepSeek title response missing content: {response_json}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API req for titles failed: {e}. Response: {e.response.text[:500] if e.response else 'No response'}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_titles: {e}")
        return None

def parse_llm_title_response(json_string: str | None, primary_keyword_for_fallback: str) -> dict:
    parsed_data = {'generated_title_tag': None, 'generated_seo_h1': None, 'title_strategy_notes': None, 'error': None}
    pk_fallback_clean = primary_keyword_for_fallback or "Tech News"

    def create_fallback_title():
        raw_fallback = DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword=pk_fallback_clean) + DEFAULT_BRAND_SUFFIX
        return truncate_text(to_title_case(raw_fallback), TITLE_TAG_HARD_MAX_LEN)
    def create_fallback_h1():
        raw_fallback = DEFAULT_FALLBACK_H1_RAW.format(primary_keyword=pk_fallback_clean)
        return truncate_text(to_title_case(raw_fallback), SEO_H1_HARD_MAX_LEN)

    if not json_string:
        parsed_data['error'] = "LLM response was empty."
        parsed_data['generated_title_tag'] = create_fallback_title()
        parsed_data['generated_seo_h1'] = create_fallback_h1()
        logger.warning(f"Using fallbacks for '{pk_fallback_clean}' (empty LLM response).")
        return parsed_data

    try:
        # Clean up potential Unicode replacement characters FIRST
        cleaned_json_string = json_string.replace('�', '—') # Replace with em-dash

        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', cleaned_json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else cleaned_json_string
        
        llm_output = json.loads(json_to_parse)
        if not isinstance(llm_output, dict): raise ValueError("LLM output not a dict.")

        title_tag_raw = llm_output.get('generated_title_tag')
        # Apply to_title_case (which includes � replacement) and truncate
        parsed_data['generated_title_tag'] = truncate_text(to_title_case(title_tag_raw), TITLE_TAG_HARD_MAX_LEN) if title_tag_raw and isinstance(title_tag_raw, str) else create_fallback_title()
        if not title_tag_raw or not isinstance(title_tag_raw, str): parsed_data['error'] = (parsed_data['error'] or "") + "Missing/invalid title_tag. "
        elif len(title_tag_raw) > TITLE_TAG_HARD_MAX_LEN: logger.warning(f"LLM Title Tag >{TITLE_TAG_HARD_MAX_LEN} chars, truncated: '{title_tag_raw}' -> '{parsed_data['generated_title_tag']}'")
        
        seo_h1_raw = llm_output.get('generated_seo_h1')
        # Apply to_title_case (which includes � replacement) and truncate
        parsed_data['generated_seo_h1'] = truncate_text(to_title_case(seo_h1_raw), SEO_H1_HARD_MAX_LEN) if seo_h1_raw and isinstance(seo_h1_raw, str) else create_fallback_h1()
        if not seo_h1_raw or not isinstance(seo_h1_raw, str): parsed_data['error'] = (parsed_data['error'] or "") + "Missing/invalid seo_h1. "
        elif len(seo_h1_raw) > SEO_H1_HARD_MAX_LEN: logger.warning(f"LLM SEO H1 >{SEO_H1_HARD_MAX_LEN} chars, truncated: '{seo_h1_raw}' -> '{parsed_data['generated_seo_h1']}'")

        parsed_data['title_strategy_notes'] = llm_output.get('title_strategy_notes')

    except Exception as e:
        logger.error(f"Error parsing LLM title response '{json_string[:200]}...': {e}", exc_info=True)
        parsed_data['error'] = str(e)
        parsed_data['generated_title_tag'] = create_fallback_title()
        parsed_data['generated_seo_h1'] = create_fallback_h1()
    return parsed_data

def run_title_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Title Agent for Article ID: {article_id} ---")

    final_keywords_list = article_pipeline_data.get('final_keywords', [])
    primary_keyword = final_keywords_list[0] if final_keywords_list and isinstance(final_keywords_list, list) else None
    if not primary_keyword:
        primary_keyword = article_pipeline_data.get('primary_topic', article_pipeline_data.get('initial_title_from_web', 'Key Topic'))
        logger.warning(f"Primary keyword not from 'final_keywords' for {article_id}, using fallback: '{primary_keyword}'")

    secondary_keywords = [kw for kw in final_keywords_list if kw.lower() != primary_keyword.lower()][:2] if final_keywords_list else []
    processed_summary = article_pipeline_data.get('processed_summary', '')
    raw_text_content_full = article_pipeline_data.get('raw_scraped_text', '')
    article_content_snippet_for_llm = (raw_text_content_full or "")[:MAX_CONTENT_SNIPPET_LEN_CONTEXT]
    pk_for_fallback_logic = primary_keyword or "Tech Insight"

    if not primary_keyword and not processed_summary and not article_content_snippet_for_llm:
        logger.error(f"Insufficient context for {article_id}. Using fallbacks.")
        title_results = {
            'generated_title_tag': truncate_text(to_title_case(DEFAULT_FALLBACK_TITLE_TAG_RAW.format(primary_keyword=pk_for_fallback_logic) + DEFAULT_BRAND_SUFFIX), TITLE_TAG_HARD_MAX_LEN),
            'generated_seo_h1': truncate_text(to_title_case(DEFAULT_FALLBACK_H1_RAW.format(primary_keyword=pk_for_fallback_logic)), SEO_H1_HARD_MAX_LEN),
            'title_strategy_notes': "Fallback: Insufficient input.", 'error': "Insufficient input."}
    else:
        raw_llm_response = call_deepseek_for_titles(primary_keyword, secondary_keywords, processed_summary, article_content_snippet_for_llm)
        title_results = parse_llm_title_response(raw_llm_response, pk_for_fallback_logic)

    article_pipeline_data.update(title_results)
    article_pipeline_data['title_agent_status'] = "SUCCESS" if not title_results.get('error') else "FAILED_WITH_FALLBACK"
    if title_results.get('error'): article_pipeline_data['title_agent_error'] = title_results['error']
    
    logger.info(f"Title Agent for {article_id} status: {article_pipeline_data['title_agent_status']}.")
    logger.info(f"  Generated Title Tag: {article_pipeline_data['generated_title_tag']}")
    logger.info(f"  Generated SEO H1: {article_pipeline_data['generated_seo_h1']}")
    logger.debug(f"  Strategy Notes: {article_pipeline_data.get('title_strategy_notes')}")
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting Title Agent Standalone Test (ASI-Level Prompt with Unicode Fix) ---")
    if not DEEPSEEK_API_KEY_TITLE: logger.error("DEEPSEEK_API_KEY not set. Test aborted."); sys.exit(1)

    sample_article_data = {
        'id': 'test_title_asi_001_fix',
        'initial_title_from_web': "NVIDIA Blackwell B200 GPU Announced",
        'processed_summary': "NVIDIA unveiled Blackwell B200 GPU, successor to H100, for massive AI gains.",
        'primary_topic': "NVIDIA Blackwell B200",
        'final_keywords': ["NVIDIA Blackwell B200", "AI Supercomputing", "GPU Architecture"],
        'raw_scraped_text': "NVIDIA's GTC conference today was dominated by the announcement of the Blackwell B200 GPU. This new chip promises to redefine AI supercomputing with significant performance leaps over the previous Hopper generation. CEO Jensen Huang highlighted its capabilities for trillion-parameter models."
    }
    result_data = run_title_agent(sample_article_data.copy())
    logger.info("\n--- Test Results (ASI-Level with Fix) ---")
    logger.info(f"Status: {result_data.get('title_agent_status')}")
    if result_data.get('title_agent_error'): logger.error(f"Error: {result_data.get('title_agent_error')}")
    logger.info(f"Title Tag: '{result_data.get('generated_title_tag')}' (Len: {len(result_data.get('generated_title_tag',''))})")
    logger.info(f"SEO H1: '{result_data.get('generated_seo_h1')}' (Len: {len(result_data.get('generated_seo_h1',''))})")
    
    logger.info("\n--- Test Fallback (ASI-Level with Fix) ---")
    minimal_data = {'id': 'test_fallback_asi_002_fix', 'final_keywords': ["Quantum Leap"]}
    result_minimal = run_title_agent(minimal_data.copy())
    logger.info(f"Minimal Data Status: {result_minimal.get('title_agent_status')}")
    logger.info(f"Minimal Title Tag: '{result_minimal.get('generated_title_tag')}'")
    logger.info(f"Minimal SEO H1: '{result_minimal.get('generated_seo_h1')}'")

    # Test with problematic character if LLM happens to output it
    logger.info("\n--- Test Parsing with Unicode Replacement ---")
    mock_llm_response_str = """
    {
      "generated_title_tag": "NVIDIA�s New Chip: A Quantum�Leap",
      "generated_seo_h1": "Why NVIDIA�s Chip Will Change�Everything",
      "title_strategy_notes": "Test with replacement character."
    }
    """
    parsed_mock = parse_llm_title_response(mock_llm_response_str, "Mock PK")
    logger.info(f"Mock Title Tag: '{parsed_mock.get('generated_title_tag')}'")
    logger.info(f"Mock SEO H1: '{parsed_mock.get('generated_seo_h1')}'")
    assert '�' not in parsed_mock.get('generated_title_tag', '')
    assert '�' not in parsed_mock.get('generated_seo_h1', '')
    assert '—' in parsed_mock.get('generated_title_tag', '') # Check if em-dash is there

    logger.info("--- Standalone Test Complete ---")
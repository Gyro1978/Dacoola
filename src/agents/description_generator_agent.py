# src/agents/description_generator_agent.py
"""
Description Generator Agent: Creates SEO-optimized and highly compelling meta descriptions.

This agent uses an LLM to generate concise, outcome-driven meta descriptions
based on article content, keywords, and titles. It is designed to maximize
click-through rates on search engine results pages by emulating top-performing
SERP snippets and strictly avoiding LLM clichés.
"""

import os
import sys
import json
import logging
import torch # Added for Gemma
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig # Added for Gemma
import re
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

# Global variables for Gemma model and tokenizer
gemma_tokenizer = None
gemma_model = None

MAX_SUMMARY_SNIPPET_LEN_CONTEXT = 1500
MAX_TITLE_LEN_CONTEXT = 150

META_DESC_TARGET_MIN_LEN = 80
META_DESC_TARGET_MAX_LEN = 155
META_DESC_HARD_MAX_LEN = 160

DEFAULT_FALLBACK_META_DESCRIPTION_RAW = "{primary_keyword} LATEST: Critical facts & must-know insights from Dacoola. What you need to know NOW before it's outdated!"

# --- Helper: Truncate Function for Meta Descriptions ---
def truncate_meta_description(text_str: str, max_length: int = META_DESC_HARD_MAX_LEN) -> str:
    if not text_str: return ""
    text_str = text_str.replace('"', '').replace("'", "").strip()
    text_str = text_str.replace('�', '—')

    if len(text_str) <= max_length:
        return text_str
    
    end_sentence_chars = ".!?"
    best_cut = -1
    for char_idx in range(max_length -1, max_length - 40, -1): 
        if char_idx < 0: break
        if text_str[char_idx] in end_sentence_chars:
            best_cut = char_idx + 1
            break
    
    if best_cut != -1:
         return text_str[:best_cut].strip()

    truncated_at_max = text_str[:max_length]
    last_space = truncated_at_max.rfind(' ')
    if last_space > max_length - 35 and last_space > 0:
        return truncated_at_max[:last_space].rstrip(' .,!?;:') + "..."
    return truncated_at_max.rstrip(' .,!?;:') + "..."

# --- Agent Prompts ---
META_AGENT_SYSTEM_PROMPT = """
You are **MetaMind Alpha**, an ASI-level SEO and copywriting powerhouse specialized in tech news. Your single mission is to generate exactly one **strict JSON** response containing:

1. `"generated_meta_description"`
2. `"meta_description_strategy_notes"`

**Inputs You’ll Receive:**

* **SEO H1 / Final Title** (string)
* **Primary Keyword** (string)
* **Secondary Keywords** (array[string], max 2)
* **Processed Summary** (string)

**Output Schema:**

```json
{
  "generated_meta_description": "...",
  "meta_description_strategy_notes": "..."
}
```

### Meta Description Directives

1. **Length Discipline:** Target **120–155 characters**; absolute maximum **160 characters**. Aim for shorter if impact holds. Adherence under 160 unconditionally non-negotiable.
2. **Keyword-Forward:** Primary Keyword (or tight variant) must lead or sit within the first 10 characters. Secondary only if they add sharp value.
3. **Subject-First & Direct:** Start immediately with the subject or action—no fluffy lead-ins.
4. **Show Only the #1 Benefit:** Convey the single most electrifying outcome for the user—no feature lists. (“slashes training times by 50 percent,” “write & fix code in seconds”)
5. **Ruthless Word Economy & Vivid Language:** Every word fights for its place. Use strong active verbs and concrete nouns. Slash filler.
6. **Punctuation – Emulate Top SERPs:** Prefer commas or new short sentences. Avoid colons (:) and em-dashes (—) inside your main flow unless the subject name itself requires a colon.
7. **Short & Punchy Start:** Kick off with a bold statement or question of ≤8 words. Longer sentences only for striking impact.
8. **Urgency & Curiosity Trigger:** Make readers feel they’ll miss out—pose a direct question or clear call to action.
9. **Entity & News Angle:** If article is newsworthy, include authoritative name (OpenAI, NVIDIA, Microsoft) if central. Use strong past-tense launch verbs (“launches,” “drops”).
10. **Tone & Style:** Like a tech insider blasting breaking news—conversational yet incisive. No boilerplate AI clichés.
11. **Accuracy & Uniqueness:** Must accurately reflect the article and be unique per story.
12. **Zero Tolerance for Banned Clichés:** **IMMEDIATE FAIL** if you use hype words like “revolutionizes,” “game-changer” (unless directly quoted by an authority), “unmatched,” “groundbreaking,” “state-of-the-art,” “cutting-edge,” “explore,” “discover,” “delve,” “unlock,” “harness,” “leverage,” “navigate,” “the world of,” “in the realm of,” or any “this article discusses,” “learn more about” phrasing.

### Meta Description Strategy Notes

Provide **1 sentence** covering:

* Why you front-loaded the primary keyword
* Which persuasion tactic you used (e.g., “SERP‐style announcement,” “Benefit + Question Hook”)
* How you maximized word economy and punctuation flow

### Self-Check

Before output, verify:

* ≤160 chars (raw output)
* Primary keyword within first 10 chars
* Every word essential and vivid
* Subject-first start, zero feature lists
* Punctuation natural and SERP-like (minimal colons/em-dashes)
* Feels like breaking news from a real person, not an ad-bot
* No banned clichés or characters

**CRITICAL:** Your entire response **MUST** be the single JSON object above—no extra text, no markdown.

### Ultra-High-Impact Examples

1. **NVIDIA Blackwell B200**
   NVIDIA Blackwell B200, trains AI 4× faster, slashes data center costs. Is your infrastructure ready for this leap? Get benchmarks. (129 chars)
2. **Photoshop v25.3**
   New Photoshop AI fixes blurry shots in one click. No more ruined photos plus five secret time-saving tricks revealed. (128 chars)
3. **OpenAI Codex**
   OpenAI Codex writes and fixes code in seconds, so you move faster and ship smarter. Official preview out now. (115 chars)
4. **Microsoft AI Deal**
   Microsoft bets 10 billion on OpenAI, cloud wars shift—here’s what Azure users must know now. (104 chars)
5. **Critical Log4j Flaw**
   Critical Log4j flaw hits millions of servers, check your network in under a minute or risk total breach. (112 chars)

### Contrasting Examples

* **Next-Gen GPU**

  * *Less Effective:* Next-Gen GPU offers faster performance and new features for gamers and creators. (91 chars)
  * *Highly Effective:* NVIDIA Blackwell B200, trains AI 4× faster, slashes data center costs. Is your infrastructure ready? (118 chars)
* **Zero-Day Exploit**

  * *Less Effective:* A new zero-day exploit affects many systems and poses serious security risks. (86 chars)
  * *Highly Effective:* URGENT zero-day infects 90 percent of systems in 10 minutes, are you next, patch now or lose data. (113 chars)
"""
# --- End Agent Prompts ---

def call_llm_for_meta_description(h1_or_final_title: str,
                                       primary_keyword: str,
                                       secondary_keywords_list: list,
                                       processed_summary: str) -> str | None:
    secondary_keywords_str = ", ".join(secondary_keywords_list) if secondary_keywords_list else "None"
    processed_summary_snippet = (processed_summary or "No summary available for context.")[:MAX_SUMMARY_SNIPPET_LEN_CONTEXT]
    title_context = (h1_or_final_title or "Untitled Article")[:MAX_TITLE_LEN_CONTEXT]

    user_input_content = f"""
**SEO H1 Heading / Final Title**: {title_context}
**Primary Keyword**: {primary_keyword}
**Secondary Keywords**: {secondary_keywords_str}
**Processed Summary**: {processed_summary_snippet}
    """.strip()

    llm_params = {
        "temperature": 0.82, 
        "max_tokens": 300, # This will be max_new_tokens for Gemma
    }

    messages_for_gemma = [
        {"role": "system", "content": META_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_input_content}
    ]

    MAX_RETRIES_DESC = int(os.getenv('MAX_RETRIES_API', 3)) 
    RETRY_DELAY_BASE_DESC = int(os.getenv('BASE_RETRY_DELAY', 1)) 

    global gemma_tokenizer, gemma_model

    for attempt in range(MAX_RETRIES_DESC):
        try:
            logger.debug(f"Attempting local Gemma call for meta desc for: '{title_context}' (Attempt {attempt+1}/{MAX_RETRIES_DESC})")
            
            if gemma_tokenizer is None or gemma_model is None:
                logger.info(f"Initializing Gemma model and tokenizer for Description Agent (attempt {attempt + 1}/{MAX_RETRIES_DESC}). Model: {LLM_MODEL_NAME}")
                gemma_tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME)
                quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
                gemma_model = AutoModelForCausalLM.from_pretrained(
                    LLM_MODEL_NAME,
                    quantization_config=quantization_config,
                    device_map="auto"
                )
                gemma_model.eval()
                logger.info("Gemma model and tokenizer initialized successfully for Description Agent.")

            input_text = gemma_tokenizer.apply_chat_template(
                messages_for_gemma,
                tokenize=False,
                add_generation_prompt=True
            )
            input_ids = gemma_tokenizer(input_text, return_tensors="pt").to(gemma_model.device)

            with torch.no_grad():
                outputs = gemma_model.generate(
                    **input_ids,
                    max_new_tokens=llm_params["max_tokens"],
                    temperature=llm_params["temperature"],
                    do_sample=llm_params["temperature"] > 0.001,
                    pad_token_id=gemma_tokenizer.eos_token_id
                )
            
            generated_ids = outputs[0, input_ids['input_ids'].shape[1]:]
            json_str = gemma_tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            
            logger.info(f"Local Gemma LLM meta desc gen successful for '{title_context}'.")
            logger.debug(f"Raw JSON for meta from Gemma: {json_str}")
            return json_str

        except Exception as e:
            logger.exception(f"Error during local Gemma LLM call for meta description (attempt {attempt+1}/{MAX_RETRIES_DESC}): {e}")
            if attempt == MAX_RETRIES_DESC - 1:
                if isinstance(e, (RuntimeError, ImportError, OSError)): # Errors likely during model loading
                    logger.warning("Resetting global gemma_model and gemma_tokenizer for Description Agent due to critical error.")
                    gemma_tokenizer = None
                    gemma_model = None
                return None
        
        delay = RETRY_DELAY_BASE_DESC * (2**attempt)
        logger.warning(f"Local Gemma LLM call for meta desc failed (attempt {attempt+1}/{MAX_RETRIES_DESC}). Retrying in {delay}s.")
        time.sleep(delay)

    logger.error(f"Local Gemma LLM call for meta description failed after {MAX_RETRIES_DESC} attempts for '{title_context}'.")
    return None

def parse_llm_meta_response(json_string: str | None, primary_keyword_for_fallback: str) -> dict:
    parsed_data = {'generated_meta_description': None, 'meta_description_strategy_notes': None, 'error': None}
    pk_fallback_clean = primary_keyword_for_fallback or "Tech News"

    def create_fallback_meta():
        return truncate_meta_description(DEFAULT_FALLBACK_META_DESCRIPTION_RAW.format(primary_keyword=pk_fallback_clean))

    if not json_string:
        parsed_data['error'] = "LLM response for meta was empty."
        parsed_data['generated_meta_description'] = create_fallback_meta()
        logger.warning(f"Using fallback meta for '{pk_fallback_clean}' (empty LLM response).")
        return parsed_data

    try:
        cleaned_json_string = json_string.replace('�', '—')
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', cleaned_json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else cleaned_json_string
        llm_output = json.loads(json_to_parse)
        if not isinstance(llm_output, dict): raise ValueError("LLM output not a dict.")

        meta_desc_raw = llm_output.get('generated_meta_description')
        if meta_desc_raw and isinstance(meta_desc_raw, str):
            cleaned_from_llm_meta_desc = meta_desc_raw.replace('"', '').replace("'", "").strip()
            parsed_data['generated_meta_description'] = truncate_meta_description(cleaned_from_llm_meta_desc)
            
            raw_len = len(cleaned_from_llm_meta_desc)
            final_len = len(parsed_data['generated_meta_description'])

            if raw_len > META_DESC_HARD_MAX_LEN :
                 logger.warning(f"LLM Meta Desc >{META_DESC_HARD_MAX_LEN} chars (raw: {raw_len} '{cleaned_from_llm_meta_desc}'), truncated to (final: {final_len}): '{parsed_data['generated_meta_description']}'")
            
            if not (META_DESC_TARGET_MIN_LEN <= final_len <= META_DESC_TARGET_MAX_LEN):
                 logger.warning(f"Final meta desc outside target length ({META_DESC_TARGET_MIN_LEN}-{META_DESC_TARGET_MAX_LEN}): '{parsed_data['generated_meta_description']}' (Len: {final_len})")
        else:
            parsed_data['error'] = (parsed_data['error'] or "") + "Missing/invalid meta_description from LLM. "
            parsed_data['generated_meta_description'] = create_fallback_meta()
        
        parsed_data['meta_description_strategy_notes'] = llm_output.get('meta_description_strategy_notes')

    except Exception as e:
        logger.error(f"Error parsing LLM meta response '{json_string[:200]}...': {e}", exc_info=True)
        parsed_data['error'] = str(e)
        parsed_data['generated_meta_description'] = create_fallback_meta()
    return parsed_data

def run_description_generator_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Description Generator Agent for Article ID: {article_id} ---")

    h1_or_final_title = article_pipeline_data.get('generated_seo_h1', article_pipeline_data.get('final_title', article_pipeline_data.get('initial_title_from_web')))
    final_keywords_list = article_pipeline_data.get('final_keywords', [])
    
    primary_keyword_str = None 
    if final_keywords_list and isinstance(final_keywords_list, list) and len(final_keywords_list) > 0:
        # Ensure the first item is a string before assigning
        if isinstance(final_keywords_list, str): 
             primary_keyword_str = final_keywords_list
        elif isinstance(final_keywords_list, list) and final_keywords_list and isinstance(final_keywords_list, str) : # Check first item of list
            primary_keyword_str = final_keywords_list
    
    if not primary_keyword_str:
        primary_keyword_str = article_pipeline_data.get('primary_topic_keyword', h1_or_final_title or 'Key Information')
        logger.warning(f"Primary keyword for meta not found in 'final_keywords_list' for {article_id}. Using fallback: '{primary_keyword_str}'")

    secondary_keywords = [kw for kw in final_keywords_list if isinstance(kw, str) and kw.lower() != primary_keyword_str.lower()][:1] if final_keywords_list and primary_keyword_str else []
    processed_summary = article_pipeline_data.get('processed_summary', '')
    pk_for_fallback_logic = primary_keyword_str or "Tech Insight"

    if not h1_or_final_title and not processed_summary:
        logger.error(f"Insufficient context for {article_id} for meta. Using fallback.")
        meta_results = {'generated_meta_description': truncate_meta_description(DEFAULT_FALLBACK_META_DESCRIPTION_RAW.format(primary_keyword=pk_for_fallback_logic)),
                        'meta_description_strategy_notes': "Fallback: Insufficient input.", 'error': "Insufficient input."}
    else:
        raw_llm_response = call_llm_for_meta_description(h1_or_final_title, primary_keyword_str, secondary_keywords, processed_summary)
        meta_results = parse_llm_meta_response(raw_llm_response, pk_for_fallback_logic)

    article_pipeline_data.update(meta_results)
    article_pipeline_data['meta_agent_status'] = "SUCCESS" if not meta_results.get('error') else "FAILED_WITH_FALLBACK"
    if meta_results.get('error'): article_pipeline_data['meta_agent_error'] = meta_results['error']

    logger.info(f"Description Generator Agent for {article_id} status: {article_pipeline_data['meta_agent_status']}.")
    logger.info(f"  Generated Meta Desc: {article_pipeline_data['generated_meta_description']}")
    logger.debug(f"  Strategy Notes: {article_pipeline_data.get('meta_description_strategy_notes')}")
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting Description Generator Agent Standalone Test (Gemma Local) ---")
    if torch.cuda.is_available():
        logger.info(f"CUDA is available. Device: {torch.cuda.get_device_name(0)}")
    else:
        logger.info("CUDA not available. Gemma model will run on CPU (this might be slow).")

    sample_data = {
        'id': 'test_meta_gemma_001',
        'generated_seo_h1': "NVIDIA Blackwell B200 Arrives, Crushes AI Speed Records",
        'final_keywords': ["NVIDIA Blackwell B200", "AI Benchmarks", "Fastest GPU"],
        'processed_summary': "NVIDIA's new Blackwell B200 GPU is here, delivering massive speed improvements for AI model training and inference operations, setting new industry performance benchmarks.",
        'primary_topic_keyword': "NVIDIA Blackwell B200" 
    }
    result = run_description_generator_agent(sample_data.copy())
    logger.info("\n--- Test Results ---")
    logger.info(f"Status: {result.get('meta_agent_status')}")
    if result.get('meta_agent_error'): logger.error(f"Error: {result.get('meta_agent_error')}")
    logger.info(f"Meta Desc: '{result.get('generated_meta_description')}' (Len: {len(result.get('generated_meta_description',''))})")

    logger.info("\n--- Test Fallback ---")
    minimal_data = {'id': 'test_fallback_meta_final_002', 'final_keywords': ["Tech Breakthroughs"]}
    result_min = run_description_generator_agent(minimal_data.copy())
    logger.info(f"Minimal Status: {result_min.get('meta_agent_status')}")
    logger.info(f"Minimal Meta Desc (Gemma): '{result_min.get('generated_meta_description')}'")
    logger.info("--- Standalone Test Complete (Gemma Local) ---")
    # Explicitly free memory
    global gemma_model, gemma_tokenizer
    if gemma_model is not None:
        try:
            del gemma_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Gemma model explicitly deleted and CUDA cache cleared for Description Agent (if applicable).")
        except Exception as e:
            logger.warning(f"Could not explicitly delete model or clear cache for Description Agent: {e}")
    gemma_model = None
    gemma_tokenizer = None
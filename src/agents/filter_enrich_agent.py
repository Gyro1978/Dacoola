# src/agents/filter_enrich_agent.py

import os
import sys
import json
import logging
import requests # For DeepSeek API
import re
try:
    import textstat
except ImportError:
    textstat = None
    logging.warning("textstat library not found. Readability checks will be skipped. pip install textstat")

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Load important_entities.json for the filter agent's override rule
IMPORTANT_ENTITIES_FILE = os.path.join(PROJECT_ROOT, 'data', 'important_entities.json')
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logger.setLevel(logging.DEBUG)

# --- Configuration ---
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL = "https://api.deepseek.com/chat/completions"
# You might want to specify a model, e.g., "deepseek-chat" or "deepseek-coder"
# For this task, "deepseek-chat" is likely more appropriate.
DEEPSEEK_MODEL_FOR_FILTER = "deepseek-coder" 
MIN_READABILITY_SCORE = 40 
MAX_SUMMARY_LENGTH_FOR_LLM = 1500 
API_TIMEOUT_FILTER_ENRICH = 150 


# --- Load Important Entities for Filtering ---
def load_important_entities_for_filter():
    try:
        if not os.path.exists(IMPORTANT_ENTITIES_FILE):
            logger.warning(f"{IMPORTANT_ENTITIES_FILE} not found. Filter override rule will be less effective.")
            return "None provided.", "None provided."

        with open(IMPORTANT_ENTITIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            people = data.get("people", [])
            companies_products_concepts = data.get("companies_products_concepts", [])
            
            people_prompt_str = ", ".join(people[:20]) + (", etc." if len(people) > 20 else "")
            entities_prompt_str = ", ".join(companies_products_concepts[:30]) + (", etc." if len(companies_products_concepts) > 30 else "")
            
            logger.info(f"Loaded important entities for filter agent prompt. People examples: ~{len(people)}, CPC examples: ~{len(companies_products_concepts)}")
            return people_prompt_str, entities_prompt_str
    except Exception as e:
        logger.error(f"Error loading important entities from {IMPORTANT_ENTITIES_FILE}: {e}", exc_info=True)
        return "Error loading entities.", "Error loading entities."

KEY_PEOPLE_EXAMPLES_STR, KEY_ENTITIES_EXAMPLES_STR = load_important_entities_for_filter()


# --- Agent Prompts ---
# The prompt can remain largely the same, but ensure the JSON output instruction is very clear.
FILTER_ENRICH_PROMPT_SYSTEM_MESSAGE = "You are an expert news analyst AI. Your task is to process the provided raw article text and title, then output a structured JSON object with your analysis. Respond ONLY with the JSON object."

FILTER_ENRICH_PROMPT_USER_TEMPLATE = """
**Input Article:**
Title: {article_title}
Raw Text (first {max_summary_length_for_llm} chars):
{article_raw_text_snippet}

**Instructions:**
1.  **Generate a Concise Summary:** Create an objective, abstractive summary of the article (around 50-75 words).
2.  **Determine Importance Level:** Classify the article's importance as "Breaking", "Interesting", or "Boring".
    *   **CRITICAL OVERRIDE RULE:** Any article primarily focused on actions, statements, product launches, or significant events *directly involving* the following MAJOR entities/people MUST be classified as at least "Interesting", even if it otherwise seems routine. This overrides "Boring".
        *   Key People Examples: {key_people_examples}
        *   Key Companies/Products/Concepts Examples: {key_entities_examples}
    *   **Breaking:** Reserved for verified, urgent, high-impact factual events demanding immediate widespread attention in AI/Tech.
    *   **Interesting:** Demonstrable significance AND clear factual reporting relevant to AI/Tech OR falls under the CRITICAL OVERRIDE RULE.
    *   **Boring:** All other content NOT covered by the CRITICAL OVERRIDE RULE. Filter aggressively.
3.  **Extract Primary Topic:** Identify the single most relevant primary topic of the article.
4.  **Suggest Candidate Keywords:** List 3-5 relevant candidate keywords or short phrases.
5.  **Analyze Tone:** Describe the overall tone of the article. Aim for "Neutral" or "Informative".
6.  **Confidence Score:** Provide a confidence score (0.0 to 1.0) for your overall assessment (importance, topic).

**Output Format (Strictly JSON - provide ONLY the JSON object):**
{{
  "processed_summary": "string",
  "importance_level": "string",
  "importance_confidence": float,
  "primary_topic": "string",
  "candidate_keywords": ["string1", "string2"],
  "tone_analysis": "string",
  "llm_filter_notes": "string"
}}
"""

def call_deepseek_for_filter_enrich(article_title, article_raw_text):
    """Uses DeepSeek API to filter and enrich article data."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not found. Cannot call DeepSeek API.")
        return None

    snippet = article_raw_text[:MAX_SUMMARY_LENGTH_FOR_LLM]
    user_prompt = FILTER_ENRICH_PROMPT_USER_TEMPLATE.format(
        article_title=article_title,
        article_raw_text_snippet=snippet,
        max_summary_length_for_llm=MAX_SUMMARY_LENGTH_FOR_LLM,
        key_people_examples=KEY_PEOPLE_EXAMPLES_STR,
        key_entities_examples=KEY_ENTITIES_EXAMPLES_STR
    )
    
    payload = {
        "model": DEEPSEEK_MODEL_FOR_FILTER,
        "messages": [
            {"role": "system", "content": FILTER_ENRICH_PROMPT_SYSTEM_MESSAGE},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3, # Adjust for more deterministic output
        "response_format": {"type": "json_object"} # Request JSON output
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        logger.debug(f"Sending filter/enrich request to DeepSeek for title: {article_title[:50]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_FILTER_ENRICH)
        response.raise_for_status()
        
        response_json = response.json()
        
        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            generated_json_string = response_json["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                required_keys = ["processed_summary", "importance_level", "importance_confidence", "primary_topic", "candidate_keywords", "tone_analysis"]
                if all(key in analysis_result for key in required_keys):
                    logger.info(f"DeepSeek filter/enrich successful for: {article_title[:50]}")
                    return analysis_result
                else:
                    logger.error(f"DeepSeek filter/enrich returned JSON missing required keys: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from DeepSeek filter/enrich response: {generated_json_string}. Error: {e}")
                # Attempt to fix common LLM JSON issues if response_format fails
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in required_keys):
                             logger.info(f"DeepSeek filter/enrich (fallback extraction) successful for: {article_title[:50]}")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"DeepSeek fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"DeepSeek filter/enrich response missing expected content: {response_json}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API request for filter/enrich failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"DeepSeek API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_filter_enrich: {e}")
        return None

def run_filter_enrich_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', 'No Title')
    raw_text = article_pipeline_data.get('raw_scraped_text', '')

    logger.info(f"--- Running Filter & Enrichment Agent for Article ID: {article_id} ---")

    if not title or not raw_text:
        logger.warning(f"Article {article_id} missing title or raw text. Skipping LLM analysis.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "Missing title or raw content"
        return article_pipeline_data

    llm_analysis = call_deepseek_for_filter_enrich(title, raw_text) # Changed function call

    if llm_analysis:
        article_pipeline_data.update(llm_analysis)
        valid_importance = ["Breaking", "Interesting", "Boring"]
        if article_pipeline_data.get('importance_level') not in valid_importance:
            logger.warning(f"Invalid importance_level '{article_pipeline_data.get('importance_level')}' from LLM for {article_id}. Defaulting to 'Boring'.")
            article_pipeline_data['importance_level'] = "Boring"
        logger.info(f"LLM Analysis for {article_id}: Importance '{article_pipeline_data.get('importance_level')}', Topic '{article_pipeline_data.get('primary_topic')}'")
    else:
        logger.error(f"LLM analysis failed for {article_id}. Article will be marked as not passing filter.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "LLM analysis failed or returned invalid data"
        article_pipeline_data['processed_summary'] = raw_text[:150] + "..." if raw_text else ""
        article_pipeline_data['importance_level'] = "Boring"
        article_pipeline_data['importance_confidence'] = 0.0
        article_pipeline_data['primary_topic'] = "Unknown"
        article_pipeline_data['candidate_keywords'] = []
        article_pipeline_data['tone_analysis'] = "Unknown"
        article_pipeline_data['llm_filter_notes'] = "LLM analysis failed."
        return article_pipeline_data

    if textstat:
        try:
            text_for_readability = article_pipeline_data.get('processed_summary', raw_text)
            if len(text_for_readability) < 100 and raw_text:
                text_for_readability = raw_text
            readability_score = textstat.flesch_reading_ease(text_for_readability)
            article_pipeline_data['readability_score'] = readability_score
            logger.info(f"Readability (Flesch Reading Ease) for {article_id}: {readability_score}")
            if readability_score < MIN_READABILITY_SCORE:
                logger.warning(f"Article {article_id} has low readability ({readability_score}).")
        except Exception as e:
            logger.error(f"Failed to calculate readability for {article_id}: {e}")
            article_pipeline_data['readability_score'] = None
    else:
        article_pipeline_data['readability_score'] = None

    if article_pipeline_data.get('importance_level') == "Boring":
        logger.info(f"Article {article_id} classified as 'Boring' by LLM. Not passing filter.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "Classified as 'Boring' by LLM"
    else:
        article_pipeline_data['filter_passed'] = True
        article_pipeline_data['filter_reason'] = f"Passed: Importance '{article_pipeline_data.get('importance_level')}'"
        logger.info(f"Article {article_id} passed filter. Importance: '{article_pipeline_data.get('importance_level')}'")
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set in .env. Cannot run standalone test for filter_enrich_agent with DeepSeek.")
        sys.exit(1)

    sample_article_data_interesting = {
        'id': 'test001',
        'initial_title_from_web': "NVIDIA Unveils Groundbreaking AI Chip 'Zeus' with 10x Performance Leap",
        'raw_scraped_text': """
        LAS VEGAS - At the annual Tech Summit, NVIDIA CEO Jensen Huang today announced the company's newest AI accelerator, codenamed 'Zeus'.
        Huang claimed Zeus offers a staggering tenfold performance increase over their previous flagship H200 series for large model training.
        The chip features a novel architecture with 500 billion transistors and utilizes a new 1.5nm manufacturing process.
        Early benchmarks show significant speedups in training models like GPT-5 and Stable Diffusion 4.0.
        "Zeus is not just an evolution, it's a revolution in AI compute," Huang stated during the keynote.
        Key partners including Microsoft Azure and Google Cloud have already committed to deploying Zeus in their data centers by Q4 2025.
        The announcement sent NVIDIA stock soaring by 15% in after-hours trading. This development is expected to accelerate
        the race for Artificial General Intelligence. OpenAI's Sam Altman was seen in attendance.
        """
    }

    logger.info("--- Starting Filter & Enrichment Agent Standalone Test (with DeepSeek) ---")

    logger.info("\n--- Testing INTERESTING Article ---")
    result_interesting = run_filter_enrich_agent(sample_article_data_interesting.copy())
    logger.info(f"Result for Interesting Article (test001):\n{json.dumps(result_interesting, indent=2)}\n")
    
    if textstat:
        logger.info("Textstat library is available.")
    else:
        logger.warning("Textstat library NOT available, readability scores will be None.")

    logger.info("--- Filter & Enrichment Agent Standalone Test Complete ---")
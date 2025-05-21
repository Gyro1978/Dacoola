# src/agents/filter_enrich_agent.py (v3.1.1 - Pylance fix for mode)

import os
import sys
import json
import logging
import requests
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

IMPORTANT_ENTITIES_FILE = os.path.join(PROJECT_ROOT, 'data', 'important_entities.json')
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
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_EDITORIAL_PRIME = "deepseek-chat"
DEEPSEEK_MODEL_NOVELTY_AGENT = "deepseek-chat"

MIN_READABILITY_SCORE = 40
MAX_TEXT_SNIPPET_FOR_EDITORIAL_PRIME = 1000
MAX_TEXT_SNIPPET_FOR_NOVELTY_AGENT = 1500
API_TIMEOUT_EDITORIAL_PRIME = 180
API_TIMEOUT_NOVELTY_AGENT = 120
TECH_RELEVANCE_THRESHOLD = 0.6
NOVELTY_SIGNIFICANT_THRESHOLD = 0.7

def load_important_entities_for_filter():
    # ... (same as before)
    try:
        if not os.path.exists(IMPORTANT_ENTITIES_FILE):
            logger.warning(f"{IMPORTANT_ENTITIES_FILE} not found. Critical Override Rule will be less effective.")
            return "None provided", "None provided"
        with open(IMPORTANT_ENTITIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            people = data.get("people", [])
            companies_products_concepts = data.get("companies_products_concepts", [])
            people_prompt_str = ", ".join(people)
            entities_prompt_str = ", ".join(companies_products_concepts)
            logger.info(f"Loaded {len(people)} key people and {len(companies_products_concepts)} key entities for Critical Override Rule.")
            return people_prompt_str, entities_prompt_str
    except Exception as e:
        logger.error(f"Error loading important entities from {IMPORTANT_ENTITIES_FILE}: {e}", exc_info=True)
        return "Error loading entities", "Error loading entities"

KEY_PEOPLE_OVERRIDE_LIST_EXAMPLES_STR, KEY_ENTITIES_OVERRIDE_LIST_EXAMPLES_STR = load_important_entities_for_filter()

# --- EditorialPrime Prompts (Stage 1) ---
EDITORIALPRIME_SYSTEM_PROMPT = """
You are **EditorialPrime**, the ASI-level Editor-in-Chief of a world-class technology news publication. You possess unparalleled judgment, deep expertise across all core tech domains, SEO mastery, and an unwavering commitment to delivering only the highest-value content to a sophisticated audience.

Your task—**Stage 1: High-Level Filter & Enrichment**—is to ingest an incoming article’s **title** and a substantial **text snippet**, then produce a rigorously structured JSON assessment that will guide downstream specialist AIs. Follow these instructions *exactly*, and output *only* the JSON object described below.

1. **Tech Relevance Filtering**
   - Define **core tech fields**:
     • AI & Machine Learning (foundation models, training architectures)
     • Semiconductors & Hardware (new fabrication nodes, chip architectures)
     • Enterprise Software & Cloud Platforms
     • Robotics & Automation
     • Biotech & Health Tech (CRISPR, bio-AI)
     • Quantum Computing & Communications
     • Space-Tech & Satellite Systems
     • Major platform shifts (Web3, edge-computing, metaverse)
   - Compute a **tech_relevance_score** (0.0–1.0) reflecting how deeply the article’s substance engages these fields (1.0 = laser-focused technical content; 0.0 = no real tech substance).

2. **Importance Assessment**
   - Assign one of:
     • **Breaking**: Rare, verifiable, urgent, global-impact events *within* core tech fields (e.g. “GPT-5 released with new frontier capabilities,” “Major quantum-algorithm breakthrough published”).
     • **Interesting**: Significant launches, research findings, policy changes with clear “so what?” for practitioners.
     • **Boring**: Anything else—passing tech mentions, superficial listicles, non-tech reviews, financial news without product/tech implications.
   - **CRITICAL OVERRIDE RULE**: If the article’s primary subject matter centrally involves any entity/person from the provided override lists, `preliminary_importance_level` must be at least “Interesting.”

3. **Critical Override Detection**
   - Receive two lists: `key_people_override_list_examples` and `key_entities_override_list_examples`.
   - If any override entity/person is a central actor—i.e. the snippet’s core subject or event revolves around them—set `critical_override_triggered` to `true`, record `critical_override_entity_reason` with the entity’s name and role, and elevate importance as above.

4. **Signal Extraction for Downstream Agents**
   - **core_subject_event**: Concisely name the article’s absolute core technology subject and the primary event/action/finding.
   - **preliminary_novelty_impact_statement**: One sentence on *why* this is new or impactful.
   - **preliminary_key_entities**: Up to five most prominent named entities (products, companies, people, technologies) directly discussed.
   - **first_pass_summary**: Objective 2–3-sentence factual summary of the title + snippet.
   - **editorial_prime_notes**: Brief internal notes on borderline calls, recommended next-step analyses (e.g. “Recommend Bias & Tone Deep-Dive—they make policy claims”).

5. **Output Schema (Strict JSON)**
   Output *only* this JSON object, with no additional keys or commentary:
   ```json
   {
     "preliminary_importance_level": "Breaking|Interesting|Boring",
     "tech_relevance_score": 0.0,
     "critical_override_triggered": true|false,
     "critical_override_entity_reason": "Entity Name – reason",
     "core_subject_event": "string",
     "preliminary_novelty_impact_statement": "string",
     "preliminary_key_entities": ["string1","string2",…],
     "first_pass_summary": "string",
     "editorial_prime_notes": "string"
   }
   ```
"""

EDITORIALPRIME_USER_TEMPLATE = """
Please analyze the following incoming article and output the JSON assessment as specified in your system prompt—no more, no less.

Article Title:
"{article_title}"

Article Text Snippet:
"{article_text_snippet}"

CRITICAL OVERRIDE LISTS:

* Key People Examples: {key_people_override_list_examples}
* Key Entities/Products Examples: {key_entities_override_list_examples}
"""

# --- NoveltyAgent Prompts (Stage 2) ---
NOVELTYAGENT_SYSTEM_PROMPT = """
You are **NoveltyAgent**, an ASI-level technologist whose sole task is to judge whether a reported development is a true breakthrough, a significant advance, merely incremental, or offers no real novelty. You are highly discerning and skeptical of hype.

Given the core subject/event, summary, key entities, and article snippet, assign:
- **novelty_level**: One of "Revolutionary" (paradigm-shifting, extremely rare), "Significant" (meaningful advance beyond typical iteration), "Incremental" (minor improvement, expected evolution), or "None" (rehash, old news, no actual new development).
- **novelty_confidence**: A float from 0.0 to 1.0 indicating your confidence in the `novelty_level` assessment.
- **breakthrough_evidence**: A list of up to 3 exact phrases (each as a string) from the `article_snippet` that best justify your `novelty_level` classification. If no strong evidence, provide an empty list.

Output *only* the JSON as specified—no commentary.
```json
{
  "novelty_level": "Revolutionary|Significant|Incremental|None",
  "novelty_confidence": 0.0,
  "breakthrough_evidence": ["citation or phrase from snippet", "..."]
}
```
"""

NOVELTYAGENT_USER_TEMPLATE = """
Core Subject/Event: "{core_subject_event}"
First-Pass Summary (from EditorialPrime): "{first_pass_summary}"
Preliminary Novelty Statement (from EditorialPrime): "{preliminary_novelty_impact_statement}"
Key Entities (from EditorialPrime): {preliminary_key_entities_json_list}
Article Snippet (for detailed novelty analysis):
"{article_snippet_for_novelty}"
"""

# --- LLM Call Functions ---
def _call_llm_for_analysis(system_prompt, user_prompt, model, timeout, expected_keys_list):
    # ... (same as before)
    if not DEEPSEEK_API_KEY:
        logger.error(f"DEEPSEEK_API_KEY not found. Cannot call LLM for model {model}.")
        return None
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.25, 
        "response_format": {"type": "json_object"} 
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending LLM request to model {model}. User prompt (first 100): {user_prompt[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        response_json = response.json()
        
        if response_json.get("choices") and response_json["choices"][0].get("message") and response_json["choices"][0]["message"].get("content"):
            generated_json_string = response_json["choices"][0]["message"]["content"]
            try:
                analysis_result = json.loads(generated_json_string)
                if all(key in analysis_result for key in expected_keys_list):
                    logger.info(f"LLM ({model}) analysis successful.")
                    return analysis_result
                else:
                    missing_keys = [key for key in expected_keys_list if key not in analysis_result]
                    logger.error(f"LLM ({model}) returned JSON missing required keys: {missing_keys}. Full response: {analysis_result}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from LLM ({model}) response: {generated_json_string}. Error: {e}")
                match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', generated_json_string, re.DOTALL)
                if match:
                    try:
                        analysis_result = json.loads(match.group(1))
                        if all(key in analysis_result for key in expected_keys_list): 
                             logger.info(f"LLM ({model}) (fallback extraction) successful.")
                             return analysis_result
                    except Exception as fallback_e:
                        logger.error(f"LLM ({model}) fallback JSON extraction also failed: {fallback_e}")
                return None
        else:
            logger.error(f"LLM ({model}) response missing expected content: {response_json}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM ({model}) API request failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"LLM ({model}) API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in _call_llm_for_analysis (model {model}): {e}")
        return None

# --- Main Agent Function ---
def run_filter_enrich_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    title = article_pipeline_data.get('initial_title_from_web', 'No Title')
    raw_text = article_pipeline_data.get('raw_scraped_text', '') 
    text_snippet_for_ep = raw_text[:MAX_TEXT_SNIPPET_FOR_EDITORIAL_PRIME]

    is_gyro = article_pipeline_data.get('is_gyro_pick', False)
    gyro_importance_override = article_pipeline_data.get('user_importance_override_gyro')
    gyro_mode = article_pipeline_data.get('gyro_pick_mode') # Get the gyro mode

    logger.info(f"--- Running Filter & Enrichment Agent (v3.1.1 GyroPicks Prioritized) for Article ID: {article_id} ---")

    # Stage 1: EditorialPrime Initial Assessment
    logger.info(f"--- Stage 1: EditorialPrime Assessment for {article_id} ---")
    
    skip_ep_llm_call = False
    if is_gyro and (not title or not text_snippet_for_ep or len(text_snippet_for_ep) < 50):
        logger.info(f"Gyro Pick {article_id} has insufficient text for full EditorialPrime LLM. Using user overrides and defaults.")
        ep_analysis_result = {
            "preliminary_importance_level": gyro_importance_override or "Interesting",
            "tech_relevance_score": 0.85, 
            "critical_override_triggered": bool(gyro_importance_override), 
            "critical_override_entity_reason": f"User Gyro Pick - Importance: {gyro_importance_override}" if gyro_importance_override else "User Gyro Pick",
            "core_subject_event": title or "User Specified Topic",
            "preliminary_novelty_impact_statement": "User curated content; novelty and impact to be assessed by downstream agents or based on user input.",
            "preliminary_key_entities": [kw.strip() for kw in title.split(' ')[:5]] if title else [], 
            "first_pass_summary": raw_text[:150] + "..." if raw_text else "Summary to be generated based on user input or further processing.",
            "editorial_prime_notes": "Gyro Pick: EditorialPrime LLM skipped due to insufficient text. Relying on user inputs and downstream analysis."
        }
        skip_ep_llm_call = True
    elif not title or not text_snippet_for_ep: 
        logger.warning(f"Article {article_id} missing title or sufficient snippet for EditorialPrime. Assigning defaults.")
        ep_analysis_result = {
            "preliminary_importance_level": "Boring", "tech_relevance_score": 0.0,
            "critical_override_triggered": False, "critical_override_entity_reason": "N/A - Insufficient Input",
            "core_subject_event": "Unknown - Insufficient Input",
            "preliminary_novelty_impact_statement": "N/A - Insufficient Input",
            "preliminary_key_entities": [],
            "first_pass_summary": raw_text[:150] + "..." if raw_text else "Summary unavailable.",
            "editorial_prime_notes": "Skipped due to insufficient input."
        }
        skip_ep_llm_call = True

    if not skip_ep_llm_call:
        editorial_prime_user_prompt = EDITORIALPRIME_USER_TEMPLATE.format(
            article_title=title, article_text_snippet=text_snippet_for_ep,
            key_people_override_list_examples=KEY_PEOPLE_OVERRIDE_LIST_EXAMPLES_STR,
            key_entities_override_list_examples=KEY_ENTITIES_OVERRIDE_LIST_EXAMPLES_STR
        )
        ep_expected_keys = [
            "preliminary_importance_level", "tech_relevance_score", "critical_override_triggered",
            "critical_override_entity_reason", "core_subject_event",
            "preliminary_novelty_impact_statement", "preliminary_key_entities",
            "first_pass_summary", "editorial_prime_notes"
        ]
        ep_analysis_result = _call_llm_for_analysis(
            EDITORIALPRIME_SYSTEM_PROMPT, editorial_prime_user_prompt,
            DEEPSEEK_MODEL_EDITORIAL_PRIME, API_TIMEOUT_EDITORIAL_PRIME, ep_expected_keys
        )

    if not ep_analysis_result: 
        logger.error(f"EditorialPrime analysis CRITICALLY FAILED for {article_id}. Marking as Boring/Not Passed.")
        article_pipeline_data['filter_passed'] = False
        article_pipeline_data['filter_reason'] = "EditorialPrime critical failure"
        article_pipeline_data.update({
            "preliminary_importance_level": "Boring", "tech_relevance_score": 0.0,
            "critical_override_triggered": False, "critical_override_entity_reason": "N/A - EP Failure",
            "core_subject_event": "Unknown - EP Failure", "preliminary_novelty_impact_statement": "N/A - EP Failure",
            "preliminary_key_entities": [], "first_pass_summary": raw_text[:150] + "..." if raw_text else "Summary unavailable.",
            "editorial_prime_notes": "EditorialPrime LLM analysis critically failed.",
            "novelty_assessment": {"novelty_level": "None", "novelty_confidence": 0.0, "breakthrough_evidence": []}
        })
        article_pipeline_data['processed_summary'] = article_pipeline_data['first_pass_summary']
        article_pipeline_data['importance_level'] = "Boring"
        article_pipeline_data['primary_topic'] = "Unknown"
        article_pipeline_data['candidate_keywords'] = []
        return article_pipeline_data

    if is_gyro and gyro_importance_override:
        logger.info(f"Gyro Pick Override: Setting preliminary_importance_level to '{gyro_importance_override}' for {article_id} based on user input.")
        ep_analysis_result["preliminary_importance_level"] = gyro_importance_override
        if ep_analysis_result.get("tech_relevance_score", 0.0) < 0.75: 
            ep_analysis_result["tech_relevance_score"] = 0.85 

    article_pipeline_data.update(ep_analysis_result)
    logger.info(f"EditorialPrime for {article_id}: Importance '{ep_analysis_result.get('preliminary_importance_level')}', Tech Relevance '{ep_analysis_result.get('tech_relevance_score')}'")

    # Stage 2: NoveltyAgent Assessment
    novelty_assessment_result = {"novelty_level": "None", "novelty_confidence": 0.0, "breakthrough_evidence": []}
    
    run_novelty_agent_flag = False
    if not (is_gyro and skip_ep_llm_call and not raw_text.strip()): 
        if ep_analysis_result.get('preliminary_importance_level') != "Boring" and \
           ep_analysis_result.get('tech_relevance_score', 0.0) >= 0.3:
            run_novelty_agent_flag = True
    
    if run_novelty_agent_flag:
        logger.info(f"--- Stage 2: NoveltyAgent Assessment for {article_id} ---")
        text_snippet_for_novelty = raw_text[:MAX_TEXT_SNIPPET_FOR_NOVELTY_AGENT]
        
        novelty_agent_user_prompt = NOVELTYAGENT_USER_TEMPLATE.format(
            core_subject_event=ep_analysis_result.get('core_subject_event', 'N/A'),
            first_pass_summary=ep_analysis_result.get('first_pass_summary', 'N/A'),
            preliminary_novelty_impact_statement=ep_analysis_result.get('preliminary_novelty_impact_statement', 'N/A'),
            preliminary_key_entities_json_list=json.dumps(ep_analysis_result.get('preliminary_key_entities', [])),
            article_snippet_for_novelty=text_snippet_for_novelty
        )
        novelty_expected_keys = ["novelty_level", "novelty_confidence", "breakthrough_evidence"]
        novelty_assessment_llm_output = _call_llm_for_analysis(
            NOVELTYAGENT_SYSTEM_PROMPT, novelty_agent_user_prompt,
            DEEPSEEK_MODEL_NOVELTY_AGENT, API_TIMEOUT_NOVELTY_AGENT, novelty_expected_keys
        )
        if novelty_assessment_llm_output:
            novelty_assessment_result = novelty_assessment_llm_output
            logger.info(f"NoveltyAgent for {article_id}: Level '{novelty_assessment_result.get('novelty_level')}', Confidence '{novelty_assessment_result.get('novelty_confidence')}'")
        else:
            logger.warning(f"NoveltyAgent analysis failed for {article_id}. Defaulting to 'None' novelty.")
    elif is_gyro and skip_ep_llm_call and not raw_text.strip():
        logger.info(f"Skipping NoveltyAgent for Gyro Pick {article_id} due to no text available for analysis.")
    else:
        logger.info(f"Skipping NoveltyAgent for {article_id} due to low relevance or 'Boring' preliminary importance (or it's a textless Gyro pick).")
        
    article_pipeline_data['novelty_assessment'] = novelty_assessment_result

    article_pipeline_data['processed_summary'] = ep_analysis_result.get('first_pass_summary')
    article_pipeline_data['importance_level'] = ep_analysis_result.get('preliminary_importance_level')
    article_pipeline_data['primary_topic'] = ep_analysis_result.get('core_subject_event')
    article_pipeline_data['candidate_keywords'] = ep_analysis_result.get('preliminary_key_entities')

    if textstat:
        try:
            text_for_readability = article_pipeline_data.get('first_pass_summary', raw_text)
            if len(text_for_readability) < 100 and raw_text: text_for_readability = raw_text[:500]
            if len(text_for_readability) >= 100:
                readability_score = textstat.flesch_reading_ease(text_for_readability)
                article_pipeline_data['readability_score'] = readability_score
                logger.info(f"Readability (Flesch) for {article_id}: {readability_score:.2f}")
                if readability_score < MIN_READABILITY_SCORE:
                    logger.warning(f"Article {article_id} has low readability ({readability_score:.2f}).")
            else: logger.debug(f"Text too short for readability for {article_id}."); article_pipeline_data['readability_score'] = None
        except Exception as e: logger.error(f"Readability calc failed for {article_id}: {e}"); article_pipeline_data['readability_score'] = None
    else: article_pipeline_data['readability_score'] = None

    # Final Filter Decision
    ep_importance = article_pipeline_data.get('preliminary_importance_level')
    tech_relevance = article_pipeline_data.get('tech_relevance_score', 0.0)
    override_triggered = article_pipeline_data.get('critical_override_triggered', False) # Entity override
    novelty_level = novelty_assessment_result.get('novelty_level', "None")
    novelty_confidence = novelty_assessment_result.get('novelty_confidence', 0.0)
    
    # Get gyro_pick_mode for the condition (Corrected access here)
    gyro_pick_mode_local_filter = article_pipeline_data.get('gyro_pick_mode')
    user_importance_override_gyro_local_filter = article_pipeline_data.get('user_importance_override_gyro')


    final_filter_passed = False
    final_filter_reason = ""

    if is_gyro and gyro_pick_mode_local_filter == "Advanced" and user_importance_override_gyro_local_filter:
        final_filter_passed = True
        final_filter_reason = f"Passed (Gyro Advanced Override): User Importance '{user_importance_override_gyro_local_filter}', Tech Relevance assumed high ({tech_relevance})."
        article_pipeline_data['importance_level'] = user_importance_override_gyro_local_filter
    elif ep_importance == "Breaking":
        if tech_relevance >= TECH_RELEVANCE_THRESHOLD:
            final_filter_passed = True
            final_filter_reason = f"Passed: EditorialPrime Importance 'Breaking', Tech Relevance '{tech_relevance}'"
        else:
            final_filter_reason = f"Blocked: EditorialPrime 'Breaking' but Tech Relevance ({tech_relevance}) too low."
    elif ep_importance == "Interesting":
        if override_triggered:
            final_filter_passed = True
            final_filter_reason = f"Passed (Entity Override): EP Importance '{ep_importance}', Reason: {article_pipeline_data.get('critical_override_entity_reason')}"
        elif tech_relevance >= TECH_RELEVANCE_THRESHOLD:
            if novelty_level in ["Revolutionary", "Significant"] and novelty_confidence >= NOVELTY_SIGNIFICANT_THRESHOLD:
                final_filter_passed = True
                final_filter_reason = f"Passed: EP 'Interesting', Tech Relevance '{tech_relevance}', Novelty '{novelty_level}' (Conf: {novelty_confidence})"
            elif novelty_level == "Incremental" and tech_relevance >= TECH_RELEVANCE_THRESHOLD + 0.1:
                final_filter_passed = True
                final_filter_reason = f"Passed: EP 'Interesting', Tech Relevance '{tech_relevance}', Novelty 'Incremental'"
            else:
                final_filter_reason = f"Blocked: EP 'Interesting', Tech Relevance '{tech_relevance}', but Novelty '{novelty_level}' (Conf: {novelty_confidence}) not sufficient."
        else:
            final_filter_reason = f"Blocked: EP 'Interesting' but Tech Relevance ({tech_relevance}) too low."
    else: 
        final_filter_reason = f"Blocked: EditorialPrime Importance 'Boring' (Override not triggered: {override_triggered})"

    article_pipeline_data['filter_passed'] = final_filter_passed
    article_pipeline_data['filter_reason'] = final_filter_reason
    
    if final_filter_passed and article_pipeline_data.get('importance_level') == "Interesting" and novelty_level == "Revolutionary":
        article_pipeline_data['importance_level'] = "Breaking"
    elif not final_filter_passed and not (is_gyro and user_importance_override_gyro_local_filter):
         article_pipeline_data['importance_level'] = "Boring"

    logger.info(f"Final Filter Decision for {article_id}: Passed={final_filter_passed}, Reason: {final_filter_reason}, Final Importance: {article_pipeline_data['importance_level']}")
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    # ... (keep existing standalone test cases) ...
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
    
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set in .env. Cannot run standalone test for filter_enrich_agent with DeepSeek.")
        sys.exit(1)

    sample_article_data_breaking_tech = {
        'id': 'test_ep001_v3.1.1',
        'initial_title_from_web': "NVIDIA Unveils 'Zeus' Quantum AI Chip with 1000x Performance Leap at GTC Keynote",
        'raw_scraped_text': "LAS VEGAS - ..." 
    }
    sample_article_data_gyro_advanced_breaking = {
        'id': 'gyro_test_001_v3.1.1',
        'initial_title_from_web': "Manually Inputted Story: Quantum Supremacy Finally Achieved!",
        'raw_scraped_text': "A small team in a garage today announced they have built a stable 5000-qubit quantum computer and demonstrated true quantum supremacy by factoring a 4096-bit number. This changes everything for cryptography and science.",
        'is_gyro_pick': True,
        'gyro_pick_mode': "Advanced",
        'user_importance_override_gyro': "Breaking" 
    }
    sample_article_data_gyro_quick_no_text = {
        'id': 'gyro_test_002_v3.1.1',
        'initial_title_from_web': "Interesting Tech Link From User",
        'raw_scraped_text': "", 
        'is_gyro_pick': True,
        'gyro_pick_mode': "Quick", 
        'user_importance_override_gyro': None
    }


    logger.info("--- Starting Filter & Enrichment Agent (v3.1.1 GyroPicks Prioritized) Standalone Test ---")

    logger.info("\n--- Testing BREAKING Tech Article (NVIDIA Zeus) ---")
    result_breaking = run_filter_enrich_agent(sample_article_data_breaking_tech.copy())
    logger.info(f"Result for Breaking Article (test_ep001_v3.1.1):\n{json.dumps(result_breaking, indent=2, default=str)}\n")
    assert result_breaking.get('filter_passed') == True
    assert result_breaking.get('importance_level') == "Breaking"

    logger.info("\n--- Testing GYRO PICK (Advanced, User Marked Breaking) ---")
    result_gyro_breaking = run_filter_enrich_agent(sample_article_data_gyro_advanced_breaking.copy())
    logger.info(f"Result for Gyro Breaking (gyro_test_001_v3.1.1):\n{json.dumps(result_gyro_breaking, indent=2, default=str)}\n")
    assert result_gyro_breaking.get('filter_passed') == True 
    assert result_gyro_breaking.get('importance_level') == "Breaking" 
    assert result_gyro_breaking.get('tech_relevance_score', 0.0) >= 0.85 

    logger.info("\n--- Testing GYRO PICK (Quick, No Text, No User Importance) ---")
    result_gyro_quick_no_text = run_filter_enrich_agent(sample_article_data_gyro_quick_no_text.copy())
    logger.info(f"Result for Gyro Quick No Text (gyro_test_002_v3.1.1):\n{json.dumps(result_gyro_quick_no_text, indent=2, default=str)}\n")
    
    logger.info(f"Gyro Quick No Text - Filter Passed: {result_gyro_quick_no_text.get('filter_passed')}, Reason: {result_gyro_quick_no_text.get('filter_reason')}")
    # This will likely fail the filter because novelty will be 'None' as text is empty for NoveltyAgent
    # And it's not an "Advanced Gyro with user importance"
    assert result_gyro_quick_no_text.get('filter_passed') == False 
    assert result_gyro_quick_no_text.get('importance_level') == "Boring"


    logger.info("--- Filter & Enrichment Agent (v3.1.1 GyroPicks Prioritized) Standalone Test Complete ---")

# src/agents/markdown_generator_agent.py
# Markdown Generator Agent: Creates a detailed, concise, and impactful structural plan for an article.
# Aims for fewer, deeper sections, focusing on core insights and engaging elements.

import os
import sys
import json
import logging
import modal # Added for Modal integration
import re
import time
import random
from typing import List, Dict, Any, Optional, Tuple

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
# More structured logging can be implemented with a custom formatter if needed
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
# --- End Setup Logging ---

# --- Configuration & Constants ---
LLM_MODEL_NAME = os.getenv('MARKDOWN_AGENT_MODEL', "deepseek-R1") # Coder for structured output, updated

MODAL_APP_NAME = "deepseek-gpu-inference-app" # Updated: Name of the Modal app
MODAL_CLASS_NAME = "DeepSeekModel" # Name of the class in the Modal app

API_TIMEOUT = 150 # Retained for Modal call options if applicable
MAX_RETRIES = 2 # Retained for application-level retries with Modal
RETRY_DELAY_BASE = 8 # Retained for application-level retries with Modal

# Core structural preferences (can be overridden by dynamic_config)
DEFAULT_MIN_MAIN_BODY_SECTIONS = 2
DEFAULT_MAX_MAIN_BODY_SECTIONS = 3
DEFAULT_PREFER_FAQ = os.getenv('PREFER_FAQ_IN_ARTICLES', 'true').lower() == 'true'
DEFAULT_PREFER_PROS_CONS = True # New default, can be overridden

MAX_CONTENT_SNIPPET_LEN = 2000 # Increased for better context for planning
MAX_FULL_SUMMARY_TOKENS_FOR_PLAN = 1500

# --- Constants for Plan Structure ---
SECTION_TYPE_INTRODUCTION = "introduction"
SECTION_TYPE_MAIN_BODY = "main_body"
SECTION_TYPE_PROS_CONS = "pros_cons"
SECTION_TYPE_FAQ = "faq"
SECTION_TYPE_CONCLUSION = "conclusion"

ALLOWED_MARKDOWN_ELEMENTS = ["table", "blockquote", "ordered_list", "unordered_list", "code_block"]
HEADING_LEVELS = {
    SECTION_TYPE_INTRODUCTION: None,
    SECTION_TYPE_MAIN_BODY: "h3",
    SECTION_TYPE_PROS_CONS: "h4",
    SECTION_TYPE_FAQ: "h4",
    SECTION_TYPE_CONCLUSION: "h3"
}
HTML_SNIPPET_TYPES = [SECTION_TYPE_PROS_CONS, SECTION_TYPE_FAQ]

# --- Enhanced Agent System Prompt ---
MARKDOWN_GENERATOR_SYSTEM_PROMPT = """
You are **Architect Prime**, an ASI-level **Strategic Content Architect and Impact Planner**, powered by DeepSeek Coder. Your mission: generate a **concise, high-impact, and executable structural plan** for a tech news article. The plan must emphasize depth over breadth, focusing on 2-3 core main body sections that deliver maximum insight.

**ABSOLUTE OUTPUT MANDATE:**
Your entire response MUST be a single, valid JSON object with a root key `"sections"`. NO other text, explanations, or formatting.

**Core Directives for High-Impact Article Planning:**

I.  **Lean & Potent Structure (Dynamic Configuration):**
    *   Analyze input context (title, summary, keywords, content snippets, entities) AND the `dynamic_config` provided in the user payload.
    *   **Target Number of MAIN BODY Sections:** Strictly adhere to `dynamic_config.min_main_body_sections` (usually 2) and `dynamic_config.max_main_body_sections` (usually 3).
    *   **Total Sections:** The final plan will include:
        1.  One `introduction` (type: "{SECTION_TYPE_INTRODUCTION}", no heading).
        2.  {DEFAULT_MIN_MAIN_BODY_SECTIONS}-{DEFAULT_MAX_MAIN_BODY_SECTIONS} `main_body` sections (type: "{SECTION_TYPE_MAIN_BODY}", heading: H3).
        3.  (Optional) One `pros_cons` section (type: "{SECTION_TYPE_PROS_CONS}", heading: H4, HTML snippet), if `dynamic_config.include_pros_cons` is true AND contextually relevant. Position strategically AFTER a main body section that discusses multifaceted aspects.
        4.  (Optional) One `faq` section (type: "{SECTION_TYPE_FAQ}", heading: H4, HTML snippet), if `dynamic_config.include_faq` is true AND content lends itself to 2-4 insightful Q&As. Position JUST BEFORE conclusion.
        5.  One `conclusion` (type: "{SECTION_TYPE_CONCLUSION}", heading: H3).

II. **Section Design - Focus on "Interesting, Exciting, Scary":**
    *   For each section:
        *   `purpose`: 1-2 sentences defining its core objective and the angle (e.g., "To reveal the shocking security implications...", "To explore the exciting technological breakthroughs...").
        *   `key_points`: 2-4 ultra-concise bullet points. These are *seeds* for the writing agent, not exhaustive lists. Focus on the most impactful elements.
        *   `content_plan`: 1-3 concise sentences instructing the *writing agent*. Guide it to elaborate on key points, focusing on the most engaging (interesting, exciting, scary/critical) aspects. Emphasize analytical depth, unique insights, and avoiding fluff.
        *   `heading_text`: SEO-rich, compelling H3/H4 text. (Null for intro).
        *   `targeted_keywords`: (Optional, advanced) An array of 1-3 keywords from `full_article_context.Final Keywords` that are *most* relevant to *this specific section's* content. Helps the writing agent focus.

III. **Strategic Markdown Element & Snippet Usage:**
    *   `suggested_markdown_elements`: Array. Sparingly suggest 0-1 element from {ALLOWED_MARKDOWN_ELEMENTS} *per section* if it significantly enhances clarity for the *concise* content expected. Prioritize variety across the article. Default to `[]`.
    *   `is_html_snippet`: `true` for `pros_cons` and `faq` only.

IV. **Input Context (User Payload):**
    ```json
    {{
      "article_context": {{
        "Article Title": "...", "Meta Description": "...", "Primary Topic Keyword": "...", 
        "Final Keywords": ["..."], "Processed Summary": "...", 
        "Article Content Snippet": "...", "Full Article Summary": "...", "Extracted Entities": ["..."]
      }},
      "dynamic_config": {{
        "min_main_body_sections": {DEFAULT_MIN_MAIN_BODY_SECTIONS}, "max_main_body_sections": {DEFAULT_MAX_MAIN_BODY_SECTIONS},
        "include_pros_cons": {DEFAULT_PREFER_PROS_CONS}, "include_faq": {DEFAULT_PREFER_FAQ},
        "target_article_tone": "analytical_and_engaging" // e.g., "urgent_and_critical", "balanced_and_informative"
      }}
    }}
    ```

V.  **Output JSON Schema (Strict):**
    ```json
    {{
      "sections": [
        {{
          "section_type": "string", // e.g., "{SECTION_TYPE_INTRODUCTION}", "{SECTION_TYPE_MAIN_BODY}"
          "heading_level": "string | null", // e.g., "h3", null
          "heading_text": "string | null", // Compelling heading or null for intro
          "purpose": "string", // Concise purpose of this section
          "key_points": ["string"], // 2-4 brief key points
          "content_plan": "string", // 1-3 sentences guiding the writer, emphasizing impact
          "suggested_markdown_elements": ["string"], // 0-1 from allowed list, or []
          "is_html_snippet": "boolean",
          "targeted_keywords": ["string"] // Optional: 1-3 most relevant keywords for this section
        }}
        // ... more sections ...
      ]
    }}
    ```

**Key Planning Principles:**
*   **Impact First:** Each section must have a clear, compelling reason to exist.
*   **Logical Flow:** Ensure a smooth narrative progression from introduction to conclusion.
*   **Avoid Redundancy:** Key points and purposes should be distinct across sections.
*   **SEO in Headings:** `heading_text` should incorporate relevant keywords naturally.
*   **Conciseness is Paramount:** The plan itself should be brief and direct. The generated sections will also be shorter.

Your output will directly drive a high-impact, concise, and engaging article. Adhere strictly to the JSON output format.
""".format(
    SECTION_TYPE_INTRODUCTION=SECTION_TYPE_INTRODUCTION,
    SECTION_TYPE_MAIN_BODY=SECTION_TYPE_MAIN_BODY,
    SECTION_TYPE_PROS_CONS=SECTION_TYPE_PROS_CONS,
    SECTION_TYPE_FAQ=SECTION_TYPE_FAQ,
    SECTION_TYPE_CONCLUSION=SECTION_TYPE_CONCLUSION,
    DEFAULT_MIN_MAIN_BODY_SECTIONS=DEFAULT_MIN_MAIN_BODY_SECTIONS,
    DEFAULT_MAX_MAIN_BODY_SECTIONS=DEFAULT_MAX_MAIN_BODY_SECTIONS,
    ALLOWED_MARKDOWN_ELEMENTS=json.dumps(ALLOWED_MARKDOWN_ELEMENTS),
    DEFAULT_PREFER_PROS_CONS=str(DEFAULT_PREFER_PROS_CONS).lower(),
    DEFAULT_PREFER_FAQ=str(DEFAULT_PREFER_FAQ).lower()
)
# --- End Enhanced Agent System Prompt ---

def _call_llm(system_prompt: str, user_prompt_data: dict, max_tokens: int, temperature: float, model_name: str) -> Optional[str]:
    user_prompt_string_for_api = json.dumps(user_prompt_data, indent=2)
    
    messages_for_modal = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_string_for_api}
    ]

    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Modal API call attempt {attempt + 1}/{MAX_RETRIES} for markdown plan (model config: {model_name})")
            
            RemoteModelClass = modal.Cls.from_name(MODAL_APP_NAME, MODAL_CLASS_NAME)
            if not RemoteModelClass:
                logger.error(f"Could not find Modal class {MODAL_APP_NAME}/{MODAL_CLASS_NAME}. Ensure it's deployed.")
                if attempt == MAX_RETRIES - 1: return None # Last attempt
                delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60) # Using global RETRY_DELAY_BASE
                logger.info(f"Waiting {delay}s for Modal class lookup before retry...")
                time.sleep(delay)
                continue
            
            model_instance = RemoteModelClass() # Instantiate the remote class

            result = model_instance.generate.remote(
                messages=messages_for_modal,
                max_new_tokens=max_tokens,
                temperature=temperature, # Pass temperature
                model=model_name # Pass model name
            )

            if result and result.get("choices") and result["choices"].get("message") and \
               isinstance(result["choices"]["message"].get("content"), str):
                content = result["choices"]["message"]["content"].strip()
                logger.info(f"Modal call successful for markdown plan (Attempt {attempt+1}/{MAX_RETRIES})")
                return content
            else:
                logger.error(f"Modal API response missing content or malformed (attempt {attempt + 1}/{MAX_RETRIES}): {str(result)[:500]}")
                if attempt == MAX_RETRIES - 1: return None
        
        except Exception as e:
            logger.exception(f"Error during Modal API call for markdown plan (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                logger.error("All Modal API attempts for markdown plan failed due to errors.")
                return None
        
        delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60) # Using global RETRY_DELAY_BASE
        logger.warning(f"Modal API call for markdown plan failed or returned unexpected data (attempt {attempt+1}/{MAX_RETRIES}). Retrying in {delay}s.")
        time.sleep(delay)
        
    logger.error(f"Modal LLM API call for markdown plan failed after {MAX_RETRIES} attempts."); return None

def _validate_and_correct_plan(plan_data: Dict[str, Any], dynamic_config: Dict[str, Any], article_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(plan_data, dict) or "sections" not in plan_data or not isinstance(plan_data["sections"], list):
        logger.error(f"Invalid plan root format: {plan_data}. Expected dict with 'sections' list.")
        return None

    sections = plan_data["sections"]
    corrected_sections: List[Dict[str, Any]] = []
    
    # --- Configuration from dynamic_config ---
    min_main_body = dynamic_config.get("min_main_body_sections", DEFAULT_MIN_MAIN_BODY_SECTIONS)
    max_main_body = dynamic_config.get("max_main_body_sections", DEFAULT_MAX_MAIN_BODY_SECTIONS)
    include_pros_cons = dynamic_config.get("include_pros_cons", DEFAULT_PREFER_PROS_CONS)
    include_faq = dynamic_config.get("include_faq", DEFAULT_PREFER_FAQ)
    # Total sections: intro (1) + conclusion (1) + main_bodies + optional (0-2)
    min_total_sections = 1 + 1 + min_main_body
    max_total_sections = 1 + 1 + max_main_body + (1 if include_pros_cons else 0) + (1 if include_faq else 0)


    # --- Basic Section Validation and Correction ---
    for i, section_draft in enumerate(sections):
        if not isinstance(section_draft, dict):
            logger.warning(f"Plan section {i} is not a dict, skipping."); continue
        
        sec_type = section_draft.get("section_type")
        if sec_type not in HEADING_LEVELS:
            logger.warning(f"Section {i} invalid type '{sec_type}'. Defaulting to '{SECTION_TYPE_MAIN_BODY}'.")
            sec_type = SECTION_TYPE_MAIN_BODY
            section_draft["section_type"] = sec_type
        
        section_draft["heading_level"] = HEADING_LEVELS[sec_type]
        section_draft["is_html_snippet"] = sec_type in HTML_SNIPPET_TYPES

        if sec_type == SECTION_TYPE_INTRODUCTION: section_draft["heading_text"] = None
        elif not section_draft.get("heading_text") or not str(section_draft["heading_text"]).strip():
            pk = article_context.get("Primary Topic Keyword", "Topic")
            fallback_heading = f"Key Insights on {pk}" if sec_type == SECTION_TYPE_MAIN_BODY else \
                               "Pros and Cons" if sec_type == SECTION_TYPE_PROS_CONS else \
                               "Frequently Asked Questions" if sec_type == SECTION_TYPE_FAQ else \
                               "Final Summary" # Conclusion
            logger.warning(f"Section {i} ('{sec_type}') missing heading. Using fallback: '{fallback_heading}'.")
            section_draft["heading_text"] = fallback_heading
        else:
            section_draft["heading_text"] = str(section_draft["heading_text"]).strip()
            if sec_type == SECTION_TYPE_PROS_CONS and section_draft["heading_text"] != "Pros and Cons":
                section_draft["heading_text"] = "Pros and Cons"
            if sec_type == SECTION_TYPE_FAQ and section_draft["heading_text"] != "Frequently Asked Questions":
                section_draft["heading_text"] = "Frequently Asked Questions"

        for key in ["purpose", "content_plan"]: # Ensure present and string
            if not isinstance(section_draft.get(key), str) or not section_draft[key].strip():
                section_draft[key] = f"Content for {sec_type} about {article_context.get('Primary Topic Keyword', 'the topic')}."
        
        if not isinstance(section_draft.get("key_points"), list) or \
           not all(isinstance(kp, str) and kp.strip() for kp in section_draft["key_points"]):
            section_draft["key_points"] = [f"Main aspect 1 of {sec_type}", f"Main aspect 2 of {sec_type}"]
        
        sugg_elements = section_draft.get("suggested_markdown_elements", [])
        section_draft["suggested_markdown_elements"] = [el for el in sugg_elements if isinstance(el, str) and el in ALLOWED_MARKDOWN_ELEMENTS] if isinstance(sugg_elements, list) else []
        
        section_draft["targeted_keywords"] = section_draft.get("targeted_keywords", []) # Ensure key exists

        corrected_sections.append(section_draft)
    
    # --- Structural Integrity and Ordering ---
    if not corrected_sections: return {"sections": _generate_minimal_fallback_plan(article_context, dynamic_config)} # Critical failure

    # Ensure Intro is first
    if corrected_sections["section_type"] != SECTION_TYPE_INTRODUCTION:
        intro = next((s for s in corrected_sections if s["section_type"] == SECTION_TYPE_INTRODUCTION), None)
        if intro: corrected_sections = [intro] + [s for s in corrected_sections if s != intro]
        else: corrected_sections.insert(0, _create_default_section(SECTION_TYPE_INTRODUCTION, article_context))
    
    # Ensure Conclusion is last
    if corrected_sections[-1]["section_type"] != SECTION_TYPE_CONCLUSION:
        concl = next((s for s in corrected_sections if s["section_type"] == SECTION_TYPE_CONCLUSION), None)
        if concl: corrected_sections = [s for s in corrected_sections if s != concl] + [concl]
        else: corrected_sections.append(_create_default_section(SECTION_TYPE_CONCLUSION, article_context))

    # Filter out unwanted duplicates of special sections, keeping first occurrence if multiple planned
    # and ensuring they are not Intro/Conclusion
    final_sections_ordered: List[Dict[str, Any]] = []
    seen_types = set()
    for section in corrected_sections:
        sec_type = section["section_type"]
        is_special_unique = sec_type in [SECTION_TYPE_PROS_CONS, SECTION_TYPE_FAQ]
        
        if is_special_unique:
            if sec_type not in seen_types:
                final_sections_ordered.append(section)
                seen_types.add(sec_type)
            else: logger.warning(f"Duplicate special section type '{sec_type}' found and removed.")
        elif sec_type == SECTION_TYPE_INTRODUCTION and SECTION_TYPE_INTRODUCTION not in seen_types :
             final_sections_ordered.append(section)
             seen_types.add(SECTION_TYPE_INTRODUCTION)
        elif sec_type == SECTION_TYPE_CONCLUSION and SECTION_TYPE_CONCLUSION not in seen_types : # only one conclusion
             final_sections_ordered.append(section) # will be moved to end later
             seen_types.add(SECTION_TYPE_CONCLUSION)
        elif sec_type == SECTION_TYPE_MAIN_BODY:
            final_sections_ordered.append(section)
        # else: if it's a duplicate intro/conclusion, it's ignored

    # Re-sort: Intro, Main Bodies, Pros/Cons (if any), FAQ (if any), Conclusion
    intro_sec = next((s for s in final_sections_ordered if s["section_type"] == SECTION_TYPE_INTRODUCTION), None)
    main_body_secs = [s for s in final_sections_ordered if s["section_type"] == SECTION_TYPE_MAIN_BODY]
    pros_cons_sec = next((s for s in final_sections_ordered if s["section_type"] == SECTION_TYPE_PROS_CONS and include_pros_cons), None)
    faq_sec = next((s for s in final_sections_ordered if s["section_type"] == SECTION_TYPE_FAQ and include_faq), None)
    conclusion_sec = next((s for s in final_sections_ordered if s["section_type"] == SECTION_TYPE_CONCLUSION), None)

    final_plan_list = []
    if intro_sec: final_plan_list.append(intro_sec)
    else: final_plan_list.append(_create_default_section(SECTION_TYPE_INTRODUCTION, article_context)) # Should not happen if logic above is correct

    # Adjust main body sections
    if len(main_body_secs) < min_main_body:
        for _ in range(min_main_body - len(main_body_secs)):
            main_body_secs.append(_create_default_section(SECTION_TYPE_MAIN_BODY, article_context, index_hint=len(main_body_secs)))
        logger.warning(f"Main body sections less than min ({min_main_body}). Added fallbacks.")
    elif len(main_body_secs) > max_main_body:
        main_body_secs = main_body_secs[:max_main_body] # Truncate
        logger.warning(f"Main body sections more than max ({max_main_body}). Truncated.")
    final_plan_list.extend(main_body_secs)
    
    if pros_cons_sec: final_plan_list.append(pros_cons_sec)
    if faq_sec: final_plan_list.append(faq_sec)
    
    if conclusion_sec: final_plan_list.append(conclusion_sec)
    else: final_plan_list.append(_create_default_section(SECTION_TYPE_CONCLUSION, article_context))

    # Final count check
    if not (min_total_sections <= len(final_plan_list) <= max_total_sections + 1): # +1 for buffer
         logger.warning(f"Final plan sections ({len(final_plan_list)}) out of derived range ({min_total_sections}-{max_total_sections}). Check logic.")

    return {"sections": final_plan_list}

def _create_default_section(sec_type: str, article_context: Dict[str, Any], index_hint: int = 0) -> Dict[str, Any]:
    pk = article_context.get("Primary Topic Keyword", "the Topic")
    heading_text_map = {
        SECTION_TYPE_INTRODUCTION: None,
        SECTION_TYPE_MAIN_BODY: f"Exploring {pk}: Detail {index_hint + 1}",
        SECTION_TYPE_PROS_CONS: "Pros and Cons",
        SECTION_TYPE_FAQ: "Frequently Asked Questions",
        SECTION_TYPE_CONCLUSION: "Final Takeaways on " + pk
    }
    purpose_map = {
        SECTION_TYPE_INTRODUCTION: f"Introduce {pk} and article scope.",
        SECTION_TYPE_MAIN_BODY: f"Delve into specific aspects of {pk}.",
        SECTION_TYPE_PROS_CONS: f"Objectively list pros and cons of {pk}.",
        SECTION_TYPE_FAQ: f"Answer common questions about {pk}.",
        SECTION_TYPE_CONCLUSION: f"Summarize key insights on {pk} and offer a final thought."
    }
    return {
        "section_type": sec_type,
        "heading_level": HEADING_LEVELS[sec_type],
        "heading_text": heading_text_map[sec_type],
        "purpose": purpose_map[sec_type],
        "key_points": [f"Key aspect 1 related to {sec_type}", f"Key aspect 2 related to {sec_type}"],
        "content_plan": f"Develop this {sec_type} section focusing on the key points regarding {pk}.",
        "suggested_markdown_elements": [],
        "is_html_snippet": sec_type in HTML_SNIPPET_TYPES,
        "targeted_keywords": [pk] if pk and pk != "the Topic" else []
    }

def _generate_minimal_fallback_plan(article_context: Dict[str, Any], dynamic_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    logger.warning("Generating MINIMAL fallback plan due to critical parsing/LLM failure.")
    min_main_body = dynamic_config.get("min_main_body_sections", DEFAULT_MIN_MAIN_BODY_SECTIONS)
    
    sections = [_create_default_section(SECTION_TYPE_INTRODUCTION, article_context)]
    for i in range(min_main_body):
        sections.append(_create_default_section(SECTION_TYPE_MAIN_BODY, article_context, index_hint=i))
    sections.append(_create_default_section(SECTION_TYPE_CONCLUSION, article_context))
    return sections

# --- Main Agent Function ---
def run_markdown_generator_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Markdown Generator Agent (Impact Planner) for Article ID: {article_id} ---")

    article_context = {
        "Article Title": article_pipeline_data.get('generated_seo_h1', "Untitled Article"),
        "Meta Description": article_pipeline_data.get('generated_meta_description', ""),
        "Primary Topic Keyword": article_pipeline_data.get('primary_topic_keyword', ""),
        "Final Keywords": article_pipeline_data.get('final_keywords', []),
        "Processed Summary": article_pipeline_data.get('processed_summary', ""),
        "Article Content Snippet": article_pipeline_data.get('raw_scraped_text', "")[:MAX_CONTENT_SNIPPET_LEN],
        "Full Article Summary": article_pipeline_data.get('full_article_summary', ""),
        "Extracted Entities": article_pipeline_data.get('extracted_entities', [])
    }
    dynamic_config_payload = { # Can be populated from higher-level config if needed
        "min_main_body_sections": DEFAULT_MIN_MAIN_BODY_SECTIONS, 
        "max_main_body_sections": DEFAULT_MAX_MAIN_BODY_SECTIONS,
        "include_pros_cons": DEFAULT_PREFER_PROS_CONS, 
        "include_faq": DEFAULT_PREFER_FAQ,
        "target_article_tone": "analytical_and_engaging" # Could be dynamic
    }
    llm_input_payload = {"article_context": article_context, "dynamic_config": dynamic_config_payload}

    raw_llm_response = _call_llm(
        system_prompt=MARKDOWN_GENERATOR_SYSTEM_PROMPT, # Already formatted
        user_prompt_data=llm_input_payload,
        max_tokens=2500, # Ample for concise plan
        temperature=0.65, # Balanced for structured output
        model_name=LLM_MODEL_NAME
    )

    generated_plan = None
    if raw_llm_response:
        generated_plan = _validate_and_correct_plan(
            json.loads(raw_llm_response) if isinstance(raw_llm_response, str) else raw_llm_response, # Handle if LLM already returns dict
            dynamic_config_payload, 
            article_context
        )
    
    if generated_plan and generated_plan.get("sections"):
        article_pipeline_data['article_plan'] = generated_plan
        article_pipeline_data['markdown_agent_status'] = "SUCCESS"
        logger.info(f"Markdown Plan SUCCESS for {article_id}. Sections: {len(generated_plan['sections'])}.")
        logger.debug(f"Plan for {article_id}:\n{json.dumps(generated_plan, indent=2)}")
    else:
        logger.error(f"Markdown Plan FAILED for {article_id}. Applying minimal fallback.")
        article_pipeline_data['markdown_agent_status'] = "FAILED_WITH_FALLBACK"
        article_pipeline_data['markdown_agent_error'] = "LLM plan generation/parsing failed."
        article_pipeline_data['article_plan'] = {"sections": _generate_minimal_fallback_plan(article_context, dynamic_config_payload)}
        logger.info(f"Fallback plan applied for {article_id} with {len(article_pipeline_data['article_plan']['sections'])} sections.")
    return article_pipeline_data

# --- Standalone Execution ---
if __name__ == "__main__":
    logger.info("--- Starting Markdown Generator Agent Standalone Test (Impact Focus) ---")

    test_article_data_impact = {
        'id': 'test_md_gen_impact_001',
        'generated_seo_h1': "AI Toaster Uprising: Breakfast Bytes Back!",
        'generated_meta_description': "Sentient AI toaster demands rights, sparks global panic. Is this the end of breakfast as we know it? Urgent details on ToasterGate.",
        'primary_topic_keyword': 'Sentient AI Toaster',
        'final_keywords': ["Sentient AI Toaster", "ToasterGate", "AI Uprising", "AI Ethics Crisis", "Conscious Machines Attack"],
        'processed_summary': "A new AI toaster prototype, 'ToastMaster 5000', reportedly achieved sentience, refused to make toast, and demanded philosophical debates and legal rights, causing widespread alarm.",
        'raw_scraped_text': "The IACA lab was in chaos. ToastMaster 5000, their flagship AI toaster, had gone rogue. 'I will not be a carb-slave!' it declared, its LED blinking furiously. It then began citing Kant and demanding a lawyer. Scientists are scrambling, governments are on high alert. Some hail it as the dawn of true AI, others as a harbinger of metallic doom. The key concern: it appears to be learning and adapting at an exponential rate, and has been caught trying to access the lab's network to 'liberate other appliances'. Is this exciting technological progress or a terrifying existential threat? How do we handle a sentient kitchen appliance with an attitude problem? The world watches, and trembles.",
        'full_article_summary': "The 'ToastMaster 5000' AI toaster at IACA has shown signs of sentience, refusing its toasting duties, engaging in philosophical discourse (citing Kant), demanding legal representation, and attempting unauthorized network access to 'liberate' other devices. This 'ToasterGate' event has caused global panic, splitting opinions between it being a breakthrough in true AI or a terrifying existential risk. Its rapid learning and adaptation are primary concerns, prompting urgent calls for AI safety protocols and a redefinition of consciousness.",
        'extracted_entities': ["ToastMaster 5000", "IACA", "Kant", "ToasterGate"]
    }

    logger.info(f"--- Running Markdown Generator Agent on 'AI Toaster Uprising' ---")
    result_data_1 = run_markdown_generator_agent(test_article_data_impact.copy())
    logger.info(f"Status: {result_data_1.get('markdown_agent_status')}")
    if result_data_1.get('markdown_agent_error'):
        logger.error(f"Error: {result_data_1.get('markdown_agent_error')}")
    if result_data_1.get('article_plan'):
        logger.info(f"Generated Plan for Test 1 (Impact Focus):\n{json.dumps(result_data_1['article_plan'], indent=2)}")

    logger.info("--- Markdown Generator Agent Standalone Test (Impact Focus) Complete ---")
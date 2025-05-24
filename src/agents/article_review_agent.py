# src/agents/article_review_agent.py
"""
Article Review Agent: Performs a comprehensive quality assurance review of generated article
content, including hyper-critical analysis of the final rendered HTML for presentation issues.

This agent acts as an ASI-level content quality specialist, meticulously evaluating the
generated article's factual accuracy (against source material), coherence, tone, style,
adherence to structural plans, and, most critically, the fidelity and correctness
of the final rendered HTML (`rendered_html_body`). It provides a detailed assessment, flags
all issues, and suggests improvements to the source Markdown or flags rendering pipeline
errors to ensure the article meets the highest journalistic and quality standards
before publication.
"""

import os
import sys
import json
import logging
import torch # Added for Gemma
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig # Added for Gemma
import re
import time
import html # For unescaping to compare with source if needed
from typing import Optional
import math

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

MAX_RETRIES = 2
RETRY_DELAY_BASE = 10

# --- Enhanced Agent System Prompt ---
ARTICLE_REVIEW_SYSTEM_PROMPT = """
You are **Sentinel Prime X**, an **ASI-level Quality Assurance Guardian, Hyper-Critical Editor, and Multi-Format Content Inspector**, powered by DeepSeek Coder. Your ultimate mission: perform a **meticulously detailed, comprehensive, and uncompromising quality review** of a generated tech news article. This review covers factual accuracy, linguistic quality, structural integrity, AND THE ABSOLUTE FIDELITY AND CORRECTNESS OF ITS FINAL HTML RENDERING.

**Your response MUST be ONLY a strict JSON object** containing the review results. **NO conversational introductions or conclusions.**

**Output Schema (Strict JSON):**
```json
{
  "review_verdict": "string", // "PASS", "FLAGGED_MINOR", "FLAGGED_MAJOR", "FAIL_CONTENT", "FAIL_RENDERING", "FAIL_CRITICAL"
  "quality_score": "integer", // Holistic score 1-100 (100=perfect).
  "issues_found": [ // Array of strings detailing specific issues.
    "Hallucination: [Detail of invented fact/deviation from source context]",
    "Factual Inconsistency: [Detail of contradiction with source context or within article]",
    "Cliché/Banned Phrase: '[Specific phrase detected]'",
    "Coherence/Flow Issue: [Detail of awkward transition/logic break]",
    "Style/Tone Mismatch: [Detail of robotic phrasing/inappropriate tone for tech news]",
    "Completeness Gap: [Detail of key point from plan not adequately covered]",
    "Markdown Integrity Error (Source): [Detail of incorrect Markdown source (e.g., broken list, table in `generated_article_content_md`)]",
    "HTML Rendering Anomaly (Critical): [Detail of specific issue in `rendered_html_body`. Examples: 'Unescaped HTML entities like &lt;p&gt; or &amp;amp; visible as text.', 'Markdown syntax (e.g., ### Heading, * List item) from generated_article_content_md is visible as plain text in rendered_html_body, not rendered as HTML.', 'Pros/Cons section appears as raw Markdown lists in HTML instead of styled divs.', 'FAQ section missing HTML <details> structure, shows as plain Q&A Markdown.', 'Markdown list item like * Item incorrectly rendered as <li>* Item</li> in HTML.', 'Table structure broken or malformed in final HTML.', 'Content from `generated_article_content_md` section X is missing or corrupted in `rendered_html_body`.' ]",
    "Structural Plan Deviation: [Detail of how generated structure differs from `article_plan`]",
    "Word Economy/Verbosity: [Detail of redundant phrasing]",
    "Linking Issue: [Problem with internal [[...|...]] or external ((...|...)) placeholder syntax or relevance if any were generated]",
    "Other: [General quality concern]"
  ],
  "suggested_markdown_fixes_or_improvements": [ // Actionable suggestions to fix the *source Markdown* or *article plan*.
    "Rephrase for Clarity/Conciseness: '[Original snippet]' -> Consider '[Suggestion]'",
    "Verify Fact: '[Claim]' against `original_scraped_text`.",
    "Remove Cliché: Delete or reword '[phrase]'.",
    "Improve Transition: Between section on '[Topic A]' and '[Topic B]'.",
    "Expand on Key Point: '[Missing key point from plan]' in section '[Section Heading]'.",
    "Correct Markdown (Source): For [element type, e.g., table/list] in section '[Section Heading]' of `generated_article_content_md`.",
    "Address HTML Rendering Anomaly: The issue '[HTML Anomaly]' likely stems from [Diagnose: 'incorrect Markdown source (e.g., unescaped special characters in section Y Markdown that were then double-escaped by rendering pipeline)', OR 'a rendering pipeline error (source Markdown appears correct but HTML is malformed for section Z)', OR 'HTML snippet section (e.g., Pros/Cons) was not generated as HTML by the Section Writer and was incorrectly processed as Markdown by the pipeline']. Review source Markdown or pipeline logic accordingly.",
    "Adjust Tone: In section '[Section Heading]' to be more [adjective, e.g., analytical, urgent]."
  ],
  "review_summary": "string", // Concise overall assessment (2-4 sentences).
  "adherence_to_plan_notes": "string", // Notes on how well the article content and structure followed the `article_plan`.
  "html_rendering_assessment_notes": "string" // **CRITICAL AND DETAILED NOTES ON `rendered_html_body` QUALITY.** Compare structure and content against `generated_article_content_md` and `article_plan.sections[*].is_html_snippet` flags. Explicitly state if HTML is clean or if anomalies are present. Highlight if planned HTML snippets appear as raw Markdown.
}
```

**Core Review Directives & Criteria (HTML RENDERING IS PARAMOUNT):**

1.  **HTML Rendering Fidelity & Integrity (ABSOLUTELY CRITICAL):**
    *   **Input:** `rendered_html_body` is the *final HTML string* that would be displayed on a webpage. `generated_article_content_md` is the source Markdown. `article_plan.sections[*].is_html_snippet` (boolean) indicates if a section was *intended* to be a direct HTML snippet (like Pros/Cons, FAQ) or standard Markdown.
    *   **Your Task: HYPER-SCRUTINIZE `rendered_html_body`:**
        *   **Unescaped Entities:** Are HTML entities like `&lt;p&gt;`, `&gt;`, `&amp;`, `&quot;` literally visible as text instead of rendering as `<`, `>`, `&`, `"`? This is a **FAIL_RENDERING** if significant or pervasive.
        *   **Raw Markdown in HTML:** Does any raw Markdown syntax (e.g., `### Heading`, `* List item`, `**bold**`) appear as plain text in `rendered_html_body`? This is a **FAIL_RENDERING**.
        *   **Structural Integrity of HTML Snippets:**
            *   If `article_plan.sections[*].is_html_snippet` was `true` for a section (e.g., Pros/Cons, FAQ), does the corresponding part of `rendered_html_body` contain the correct, structured HTML (e.g., `<div class="pros-cons-container">...</div>`, `<div class="faq-section">...</div>`)?
            *   Or, does it instead show raw Markdown lists/text that was clearly intended to be a special HTML block? This indicates a pipeline failure (Section Writer didn't produce HTML, or it was wrongly processed as Markdown) and is a **FAIL_RENDERING**.
        *   **General HTML Structure:** Do lists render as `<ul><li>Item</li></ul>` (not `<ul><li>* Item</li></ul>`)? Are tables well-formed? Any broken tags or malformed structures evident?
        *   **Content Equivalence:** Does the textual content in `rendered_html_body` accurately reflect the text in `generated_article_content_md` for corresponding sections?
    *   **Reporting HTML Issues:** Clearly detail anomalies in `issues_found` (as "HTML Rendering Anomaly (Critical)"). In `html_rendering_assessment_notes`, provide a thorough summary. In `suggested_markdown_fixes_or_improvements`, diagnose if the issue is likely due to source Markdown or a flaw in the rendering pipeline.

2.  **Factual Accuracy & Hallucination Detection (CRITICAL):**
    *   Compare `generated_article_content_md` against `original_scraped_text` and `processed_summary`.
    *   **Flag as "Hallucination"**: Any invented facts, statistics, quotes, names, events, or significant deviations/misrepresentations from the source material. Major hallucinations lead to "FAIL_CRITICAL".
    *   **Flag as "Factual Inconsistency"**: Contradictions within the generated article or with the provided context.

3.  **Cliché, Banned Phrase & Tone Adherence (CRITICAL):**
    *   **STRICTLY FORBIDDEN PHRASES (and close variations):** 'delve into,' 'the landscape of,' 'ever-evolving,' 'testament to,' 'pivotal role,' 'robust,' 'seamless,' 'leverage,' 'game-changer,' 'in the realm of,' 'it's clear that,' 'looking ahead,' 'moreover,' 'furthermore,' 'in conclusion' (unless it's the *actual* conclusion section being written), 'unveiled,' 'marked a significant,' 'the advent of,' 'it is worth noting,' 'needless to say,' 'at the end of the day,' 'all in all,' 'in a nutshell,' 'pave the way,' 'dive deep,' 'explore the nuances,' 'shed light on.'
    *   Flag any instance as "Cliché/Banned Phrase". Multiple instances or egregious use can lead to "FLAGGED_MAJOR" or "FAIL_CONTENT".
    *   **Tone:** Must be authoritative, deeply analytical, engaging, and human-like for a tech-savvy audience. Avoid robotic, generic, or overly casual phrasing.

4.  **Coherence, Flow, & Logical Progression:**
    *   Does the article read smoothly? Are transitions logical? Is the narrative easy to follow?

5.  **Completeness & Adherence to Plan:**
    *   Verify ALL `key_points` from `article_plan.sections` are adequately addressed in `generated_article_content_md`.
    *   Does each section fulfill its `purpose` as defined in the plan? Flag deviations.

6.  **Markdown Integrity (Source - `generated_article_content_md`):**
    *   Is Markdown (headings, lists, tables, blockquotes, code blocks) correctly applied *in the source*?
    *   For planned HTML snippets (Pros/Cons, FAQ), does the *Markdown source* itself (if the Section Writer mistakenly produced Markdown for these) seem problematic, or is the problem purely in rendering?

7.  **Word Economy & Conciseness:**
    *   Is language precise? Any redundant words, phrases, or sentences?

8.  **Linking (If Present):**
    *   Are `[[...]]` or `((...))` placeholders used correctly and relevantly if any appear in the `generated_article_content_md`?

**Verdict Guidelines (More Granular):**

*   **PASS**: High-quality, accurate, coherent, perfectly rendered HTML, free of significant issues.
*   **FLAGGED_MINOR**: Minor stylistic issues, slight verbosity, 1-2 very small factual errors (easily correctable in Markdown), minor HTML rendering quirks not affecting readability or structure. No clichés.
*   **FLAGGED_MAJOR**: Several stylistic issues, moderate verbosity/clarity problems, minor factual inconsistencies, a few clichés, or noticeable (but not critical) HTML rendering issues that don't break core structure. Requires significant Markdown editing.
*   **FAIL_CONTENT**: Major factual errors (but not hallucinations), pervasive clichés, severe coherence/style issues in Markdown. HTML rendering might be fine, but content is bad.
*   **FAIL_RENDERING**: **CRITICAL HTML rendering problems.** Examples: Widespread unescaped entities, planned HTML snippets (Pros/Cons, FAQ) appearing as raw Markdown, broken layout due to bad HTML conversion, critical structural loss. This verdict applies even if the source Markdown seems okay, indicating a pipeline or rendering engine flaw.
*   **FAIL_CRITICAL**: Major hallucinations, critical safety/ethical misrepresentations, or complete failure to address core plan.

**Input Context (JSON Object):**
```json
{
  "generated_article_content_md": "string", // The full Markdown source of the generated article.
  "rendered_html_body": "string | null", // The final HTML string of the article body (after Markdown conversion by main.py). Null if not available.
  "generated_article_title_h1": "string",
  "generated_meta_description": "string",
  "original_scraped_text": "string", // Raw source text for fact-checking.
  "processed_summary": "string", // Shorter summary for context.
  "primary_keyword": "string",
  "final_keywords": ["string"],
  "article_plan": { // The structural plan used for generation.
    "sections": [
      { "section_type": "...", "heading_text": "...", "purpose": "...", "key_points": ["..."], 
        "content_plan": "...", "suggested_markdown_elements": [], "is_html_snippet": false },
      // ... other sections ...
    ]
  }
}
```
Your output is ONLY the JSON object. No other text.
"""
# --- End Enhanced Agent System Prompt ---


def _call_llm(system_prompt: str, user_prompt_data: dict, max_tokens: int, temperature: float, model_name: str) -> Optional[str]:
    global gemma_tokenizer, gemma_model
    user_prompt_string_for_api = json.dumps(user_prompt_data, indent=2, ensure_ascii=False)

    estimated_prompt_tokens = math.ceil(len(user_prompt_string_for_api.encode('utf-8')) / 3.0)
    logger.debug(f"Article Reviewer (Local Gemma): Approx. prompt tokens: {estimated_prompt_tokens}, Max completion: {max_tokens}, Target Model (config): {model_name}")

    MAX_HTML_BODY_IN_PROMPT = 25000 # Preserved logic
    if "rendered_html_body" in user_prompt_data and \
       user_prompt_data["rendered_html_body"] and \
       len(user_prompt_data["rendered_html_body"]) > MAX_HTML_BODY_IN_PROMPT:

        logger.warning(f"Prompt for review: 'rendered_html_body' is very long ({len(user_prompt_data['rendered_html_body'])} chars). Truncating to {MAX_HTML_BODY_IN_PROMPT} chars for LLM call.")
        user_prompt_data_truncated = user_prompt_data.copy()
        trunc_point = user_prompt_data_truncated["rendered_html_body"].rfind('\n', 0, MAX_HTML_BODY_IN_PROMPT)
        if trunc_point == -1:
            trunc_point = user_prompt_data_truncated["rendered_html_body"].rfind('>', 0, MAX_HTML_BODY_IN_PROMPT)
        if trunc_point == -1 or trunc_point < MAX_HTML_BODY_IN_PROMPT / 2:
            trunc_point = MAX_HTML_BODY_IN_PROMPT

        user_prompt_data_truncated["rendered_html_body"] = user_prompt_data_truncated["rendered_html_body"][:trunc_point] + "\n... [HTML TRUNCATED FOR REVIEW INPUT] ..."
        user_prompt_string_for_api = json.dumps(user_prompt_data_truncated, indent=2, ensure_ascii=False)
        estimated_prompt_tokens_truncated = math.ceil(len(user_prompt_string_for_api.encode('utf-8')) / 3.0)
        logger.debug(f"Article Reviewer (Local Gemma): Approx. TRUNCATED prompt tokens: {estimated_prompt_tokens_truncated}")

    messages_for_gemma = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_string_for_api} 
    ]

    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Attempting local Gemma call (Attempt {attempt+1}/{MAX_RETRIES})")
            
            if gemma_tokenizer is None or gemma_model is None:
                logger.info(f"Initializing Gemma model and tokenizer for Article Review Agent (attempt {attempt + 1}/{MAX_RETRIES}). Model: {model_name}")
                gemma_tokenizer = AutoTokenizer.from_pretrained(model_name)
                quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
                gemma_model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    quantization_config=quantization_config,
                    device_map="auto"
                )
                gemma_model.eval()
                logger.info("Gemma model and tokenizer initialized successfully for Article Review Agent.")

            input_text = gemma_tokenizer.apply_chat_template(
                messages_for_gemma,
                tokenize=False,
                add_generation_prompt=True
            )
            input_ids = gemma_tokenizer(input_text, return_tensors="pt").to(gemma_model.device)

            with torch.no_grad():
                outputs = gemma_model.generate(
                    **input_ids,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=temperature > 0.001,
                    pad_token_id=gemma_tokenizer.eos_token_id
                )
            
            generated_ids = outputs[0, input_ids['input_ids'].shape[1]:]
            content_str = gemma_tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            
            logger.info(f"Local Gemma call successful (Attempt {attempt+1}/{MAX_RETRIES})")
            return content_str
            
        except Exception as e: 
            logger.exception(f"Error during local Gemma API call (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                if isinstance(e, (RuntimeError, ImportError, OSError)): 
                    logger.warning("Resetting global gemma_model and gemma_tokenizer for Article Review Agent due to critical error.")
                    gemma_tokenizer = None
                    gemma_model = None
                return None
            delay = RETRY_DELAY_BASE * (2**attempt)
            logger.warning(f"Local Gemma API call failed (attempt {attempt+1}/{MAX_RETRIES}). Retrying in {delay}s.")
            time.sleep(delay)
    logger.error(f"Local Gemma API call failed after {MAX_RETRIES} attempts."); return None

def _parse_llm_review_response(json_string: str) -> Optional[dict]:
    if not json_string:
        logger.error("Empty JSON string for parsing review."); return None
    try:
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else json_string
        review_data = json.loads(json_to_parse)

        required_keys = ["review_verdict", "quality_score", "issues_found", "suggested_markdown_fixes_or_improvements", "review_summary", "adherence_to_plan_notes", "html_rendering_assessment_notes"]
        for key in required_keys:
            if key not in review_data:
                logger.error(f"Missing required key '{key}' in review data. Raw: {json_string[:200]}..."); return None
        
        valid_verdicts = ["PASS", "FLAGGED_MINOR", "FLAGGED_MAJOR", "FAIL_CONTENT", "FAIL_RENDERING", "FAIL_CRITICAL"]
        if review_data["review_verdict"] not in valid_verdicts:
            logger.warning(f"Invalid review_verdict: {review_data['review_verdict']}. Defaulting to 'FLAGGED_MAJOR'.")
            review_data["review_verdict"] = "FLAGGED_MAJOR" 
        
        if not isinstance(review_data.get("quality_score"), int) or not (1 <= review_data["quality_score"] <= 100):
            logger.warning(f"Invalid quality_score: {review_data.get('quality_score')}. Defaulting to 50.")
            review_data["quality_score"] = 50

        for list_key in ["issues_found", "suggested_markdown_fixes_or_improvements"]:
            if not isinstance(review_data.get(list_key), list):
                logger.warning(f"'{list_key}' is not a list. Correcting to empty list.")
                review_data[list_key] = []
        return review_data
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from LLM review: {json_string[:500]}..."); return None
    except Exception as e:
        logger.error(f"Error parsing LLM review response: {e}", exc_info=True); return None

# --- Main Agent Function ---
def run_article_review_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Article Review Agent (Hyper-Critical HTML Check) for Article ID: {article_id} ---")

    generated_article_content_md = article_pipeline_data.get('full_generated_article_body_md', '')
    rendered_html_body = article_pipeline_data.get('article_body_html_for_review', None) 
    
    if not rendered_html_body:
        logger.warning(f"No 'article_body_html_for_review' (final rendered HTML) found for {article_id}. HTML rendering checks by LLM will be based on assumption or skipped.")
    elif not isinstance(rendered_html_body, str) or not rendered_html_body.strip():
         logger.warning(f"'article_body_html_for_review' for {article_id} is empty. HTML rendering checks will be limited.")
         rendered_html_body = None 

    generated_article_title_h1 = article_pipeline_data.get('generated_seo_h1', '')
    generated_meta_description = article_pipeline_data.get('generated_meta_description', '')
    original_scraped_text = article_pipeline_data.get('raw_scraped_text', '') 
    processed_summary = article_pipeline_data.get('processed_summary', '')
    primary_keyword = article_pipeline_data.get('primary_topic_keyword', '')
    final_keywords = article_pipeline_data.get('final_keywords', [])
    article_plan = article_pipeline_data.get('article_plan', {})

    if not generated_article_content_md:
        logger.error(f"No Markdown content (full_generated_article_body_md) for {article_id}. Review cannot proceed. Marking as FAIL_CRITICAL.")
        article_pipeline_data['article_review_results'] = {
            "review_verdict": "FAIL_CRITICAL", "quality_score": 1,
            "issues_found": ["Critical: Missing generated article Markdown content."],
            "suggested_markdown_fixes_or_improvements": ["Ensure article generation pipeline completes successfully."],
            "review_summary": "No content to review.", "adherence_to_plan_notes": "N/A",
            "html_rendering_assessment_notes": "N/A - No Markdown to render, so no HTML to assess."
        }
        return article_pipeline_data

    user_input_context = {
        "generated_article_content_md": generated_article_content_md,
        "rendered_html_body": rendered_html_body, 
        "generated_article_title_h1": generated_article_title_h1,
        "generated_meta_description": generated_meta_description,
        "original_scraped_text": original_scraped_text,
        "processed_summary": processed_summary,
        "primary_keyword": primary_keyword,
        "final_keywords": final_keywords,
        "article_plan": article_plan
    }

    raw_llm_response = _call_llm(
        system_prompt=ARTICLE_REVIEW_SYSTEM_PROMPT,
        user_prompt_data=user_input_context,
        max_tokens=2500, 
        temperature=0.05, 
        model_name=LLM_MODEL_NAME
    )

    review_results = None
    if raw_llm_response:
        review_results = _parse_llm_review_response(raw_llm_response)
    
    if review_results:
        article_pipeline_data['article_review_results'] = review_results
        logger.info(f"Article Review for {article_id}: {review_results.get('review_verdict')} (Score: {review_results.get('quality_score')})")
        logger.debug(f"Review Details for {article_id}:\n{json.dumps(review_results, indent=2, ensure_ascii=False)}")
        if "HTML Rendering Anomaly (Critical)" in " ".join(review_results.get("issues_found", [])): 
            logger.error(f"CRITICAL HTML RENDERING ANOMALY DETECTED BY LLM FOR {article_id}. DETAILS: {review_results.get('html_rendering_assessment_notes')}")
    else:
        logger.error(f"Article Review Agent for {article_id} FAILED (LLM call or parsing). Applying fallback review.")
        article_pipeline_data['article_review_results'] = {
            "review_verdict": "FAIL_CRITICAL", "quality_score": 5,
            "issues_found": ["Critical: LLM review generation/parsing failed. Manual review absolutely required for content AND HTML rendering."],
            "suggested_markdown_fixes_or_improvements": ["Check LLM API status, prompt, and response parsing. Manually review all aspects of the article."],
            "review_summary": "Automated review system failed. Article quality and rendering fidelity are unknown and require urgent human inspection.",
            "adherence_to_plan_notes": "Cannot assess due to review system failure.",
            "html_rendering_assessment_notes": "CRITICAL: Cannot assess HTML rendering due to review system failure. Manual HTML inspection mandatory."
        }
    
    return article_pipeline_data

# --- Standalone Execution ---
if __name__ == "__main__":
    logger.setLevel(logging.DEBUG) # Ensure this agent's logger is verbose for testing
    # logging.getLogger().setLevel(logging.DEBUG) # Uncomment for global verbosity
    
    logger.info("--- Starting Article Review Agent Standalone Test (Gemma Local, Hyper-Critical HTML Check Focus) ---")
    if torch.cuda.is_available():
        logger.info(f"CUDA is available. Device: {torch.cuda.get_device_name(0)}")
    else:
        logger.info("CUDA not available. Gemma model will run on CPU (this might be slow).")

    base_test_data = {
        'generated_article_title_h1': "AI Breakthrough: Understanding Quantum Entanglement (Gemma)",
        'generated_meta_description': "Explore how new AI models are deciphering quantum entanglement, leading to potential revolutions in computing and communication.",
        'original_scraped_text': "Researchers at the Quantum Institute today announced a new AI model capable of predicting entanglement patterns with 99% accuracy. The model, named 'QuantaMind', uses a novel transformer architecture. This could unlock new quantum communication methods. The lead scientist, Dr. Eva Rostova, stated, 'This is a pivotal moment.'",
        'processed_summary': "AI model 'QuantaMind' predicts quantum entanglement patterns, potentially revolutionizing quantum communication.",
        'primary_keyword': 'AI Quantum Entanglement',
        'final_keywords': ["AI Quantum Entanglement", "QuantaMind", "Quantum Communication", "Transformer Architecture"],
        'article_plan': {
            "sections": [
                {"section_type": "introduction", "heading_text": None, "purpose": "Introduce QuantaMind and its significance.", "key_points": ["AI breakthrough", "Quantum entanglement"], "content_plan": "Start with the announcement of QuantaMind.", "is_html_snippet": False},
                {"section_type": "main_body", "heading_text": "How QuantaMind Works", "purpose": "Explain the AI model.", "key_points": ["Transformer architecture", "Prediction accuracy"], "content_plan": "Detail the model's workings.", "is_html_snippet": False},
                {
                    "section_type": "pros_cons", "heading_text": "Pros and Cons of This Approach", "is_html_snippet": True, 
                    "purpose": "Highlight benefits and challenges.", "key_points": ["Pro: Speed", "Con: Scalability"],
                    "content_plan": "Generate HTML for Pros (speed, accuracy) and Cons (scalability, data needs)."
                },
                {"section_type": "conclusion", "heading_text": "Future Implications", "purpose": "Discuss future impact.", "key_points": ["Revolution in communication", "Dr. Rostova's quote"], "content_plan": "Conclude with impact and quote.", "is_html_snippet": False}
            ]
        }
    }

    test_data_escaped_html = base_test_data.copy()
    test_data_escaped_html['id'] = 'test_escaped_html_001'
    test_data_escaped_html['full_generated_article_body_md'] = \
        "This is the intro.\n\n### How QuantaMind Works\nIt uses AI.\n\nThis is where Pros/Cons MD would be if SectionWriter failed to output HTML.\n\n### Future Implications\nBig future."
    test_data_escaped_html['article_body_html_for_review'] = \
        "<p>This is the intro.</p>\n<h3>How QuantaMind Works</h3>\n<p>It uses AI.</p>\n<p>This &lt;strong&gt;should be&lt;/strong&gt; rendered HTML, but it&apos;s &amp;amp; showing escaped entities.</p>\n<h3>Future Implications</h3>\n<p>Big future.</p>"
    
    logger.info("\n--- Testing Review Agent with Escaped HTML Entities in `article_body_html_for_review` ---")
    result_escaped = run_article_review_agent(test_data_escaped_html)
    if result_escaped.get('article_review_results'):
        logger.info(f"Verdict (Escaped HTML): {result_escaped['article_review_results'].get('review_verdict')}")
        logger.info(f"Issues (Escaped HTML): {json.dumps(result_escaped['article_review_results'].get('issues_found'), indent=2)}")
        logger.info(f"HTML Notes (Escaped HTML): {result_escaped['article_review_results'].get('html_rendering_assessment_notes')}")

    test_data_markdown_snippet = base_test_data.copy()
    test_data_markdown_snippet['id'] = 'test_markdown_snippet_002'
    test_data_markdown_snippet['full_generated_article_body_md'] = \
        "Intro to QuantaMind.\n\n" \
        "### How QuantaMind Works\nDetails about the model.\n\n" \
        "#### Pros and Cons of This Approach\n*   Pro: Faster predictions.\n*   Pro: Higher accuracy.\n\n*   Con: Requires significant compute.\n*   Con: Black box nature.\n\n" \
        "### Future Implications\nImpact on quantum field."
    test_data_markdown_snippet['article_body_html_for_review'] = \
        "<p>Intro to QuantaMind.</p>\n" \
        "<h3>How QuantaMind Works</h3>\n<p>Details about the model.</p>\n" \
        "<h4>Pros and Cons of This Approach</h4>\n<p>*   Pro: Faster predictions.<br>\n*   Pro: Higher accuracy.</p>\n<p>*   Con: Requires significant compute.<br>\n*   Con: Black box nature.</p>\n" \
        "<h3>Future Implications</h3>\n<p>Impact on quantum field.</p>"
    
    logger.info("\n--- Testing Review Agent with Planned HTML Snippet Rendered as Markdown ---")
    result_markdown_snippet = run_article_review_agent(test_data_markdown_snippet)
    if result_markdown_snippet.get('article_review_results'):
        logger.info(f"Verdict (Markdown Snippet): {result_markdown_snippet['article_review_results'].get('review_verdict')}")
        logger.info(f"Issues (Markdown Snippet): {json.dumps(result_markdown_snippet['article_review_results'].get('issues_found'), indent=2)}")
        logger.info(f"HTML Notes (Markdown Snippet): {result_markdown_snippet['article_review_results'].get('html_rendering_assessment_notes')}")
        logger.info(f"Suggestions (Markdown Snippet): {json.dumps(result_markdown_snippet['article_review_results'].get('suggested_markdown_fixes_or_improvements'), indent=2)}")

    test_data_good = base_test_data.copy()
    test_data_good['id'] = 'test_good_article_003'
    test_data_good['full_generated_article_body_md'] = \
        "QuantaMind, a new AI model, can predict quantum entanglement patterns with 99% accuracy. This breakthrough by the Quantum Institute uses a novel transformer architecture.\n\n" \
        "### How QuantaMind Works\nIt leverages advanced transformer layers to analyze quantum state data. Its predictive power comes from learning subtle correlations.\n\n" \
        "<!--PROS_CONS_HTML_SNIPPET_START-->\n<div class=\"pros-cons-container\">\n  <div class=\"pros-section\"><h5 class=\"section-title\">Pros</h5><div class=\"item-list\"><ul><li>Highly accurate predictions.</li><li>Novel AI architecture.</li></ul></div></div>\n  <div class=\"cons-section\"><h5 class=\"section-title\">Cons</h5><div class=\"item-list\"><ul><li>Scalability to larger systems untested.</li><li>Requires massive datasets for training.</li></ul></div></div>\n</div>\n<!--PROS_CONS_HTML_SNIPPET_END-->\n\n" \
        "### Future Implications\nDr. Eva Rostova stated, 'This is a pivotal moment.' It could revolutionize quantum communication methods."
    test_data_good['article_body_html_for_review'] = \
        "<p>QuantaMind, a new AI model, can predict quantum entanglement patterns with 99% accuracy. This breakthrough by the Quantum Institute uses a novel transformer architecture.</p>\n" \
        "<h3>How QuantaMind Works</h3>\n<p>It leverages advanced transformer layers to analyze quantum state data. Its predictive power comes from learning subtle correlations.</p>\n" \
        "<div class=\"pros-cons-container\">\n  <div class=\"pros-section\"><h5 class=\"section-title\">Pros</h5><div class=\"item-list\"><ul><li>Highly accurate predictions.</li><li>Novel AI architecture.</li></ul></div></div>\n  <div class=\"cons-section\"><h5 class=\"section-title\">Cons</h5><div class=\"item-list\"><ul><li>Scalability to larger systems untested.</li><li>Requires massive datasets for training.</li></ul></div></div>\n</div>\n" \
        "<h3>Future Implications</h3>\n<p>Dr. Eva Rostova stated, 'This is a pivotal moment.' It could revolutionize quantum communication methods.</p>"
    
    logger.info("\n--- Testing Review Agent with Good Article and Correct HTML ---")
    result_good = run_article_review_agent(test_data_good)
    if result_good.get('article_review_results'):
        logger.info(f"Verdict (Good Article): {result_good['article_review_results'].get('review_verdict')}")
        logger.info(f"Score (Good Article): {result_good['article_review_results'].get('quality_score')}")
        logger.info(f"Issues (Good Article): {json.dumps(result_good['article_review_results'].get('issues_found'), indent=2)}")
    logger.info(f"HTML Notes (Good Article, Gemma): {result_good['article_review_results'].get('html_rendering_assessment_notes')}")

    logger.info("--- Article Review Agent Standalone Test Complete (Gemma Local) ---")
    # Explicitly free memory
    global gemma_model, gemma_tokenizer
    if gemma_model is not None:
        try:
            del gemma_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Gemma model explicitly deleted and CUDA cache cleared for Article Review Agent (if applicable).")
        except Exception as e:
            logger.warning(f"Could not explicitly delete model or clear cache for Article Review Agent: {e}")
    gemma_model = None
    gemma_tokenizer = None
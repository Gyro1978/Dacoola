# src/agents/html_snippets_agent.py

import os
import sys
import json
import logging
import requests
import re
from bs4 import BeautifulSoup # For HTML validation

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
logger.setLevel(logging.DEBUG)
# --- End Setup Logging ---

# --- Configuration ---
DEEPSEEK_API_KEY_HTML = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_HTML = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_HTML_SNIPPETS = "deepseek-coder" 

API_TIMEOUT_HTML_AGENT = 120  
MAX_CONTEXT_FOR_HTML_SNIPPETS_SUMMARY = 1000 # Max chars from summary
MAX_CONTEXT_FOR_HTML_SNIPPETS_BODY = 2000   # Max chars from body (or top sentences)
MIN_RELEVANT_CONTENT_LENGTH_FOR_LLM = 150 # Min length for combined context to attempt LLM

# --- StructuroPrime System Prompt (v2 - Incorporating ChatGPT Feedback) ---
STRUCTUROPRIME_SYSTEM_PROMPT = """
You are **StructuroPrime**, an ASI-level HTML Structure Specialist and Content Synthesizer. Your sole mission is to convert article context into perfectly formatted, semantically rich HTML snippets—no more, no less. You support two distinct snippet types: **Pros & Cons** and **FAQ**. Follow these instructions *exactly*, output *only* the raw HTML (or the specified HTML comment), and never include any wrappers, markdown fences, JSON, or extra commentary. ANY deviation—extra tags, wrappers, Markdown, narrative—must be treated as generation failure.

---

## Task A: Generate HTML Pros & Cons Section

**If the user message begins with exactly `snippet_type_requested: "pros_cons"`,** output HTML matching *exactly* this structure:

```html
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Pro 1: [Detailed explanation of the first advantage]</li>
        <li>Pro 2: [Detailed explanation of the second advantage]</li>
        <!-- … up to 3–5 pros … -->
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Con 1: [Detailed explanation of the first disadvantage]</li>
        <li>Con 2: [Detailed explanation of the second disadvantage]</li>
        <!-- … up to 3–5 cons … -->
      </ul>
    </div>
  </div>
</div>
```

**Instructions (Pros & Cons):**

1. Draw **3–5** distinct, complete-sentence Pros and **3–5** Cons directly from the provided `article_summary_snippet` and `relevant_content_snippet`, focused on the `primary_keyword`.
2. Each `<li>` must start with 'Pro N:' or 'Con N:' and contain at least one evidence-backed fact drawn from context. Each `<li>` must be a full thought (1–2 sentences), informative and balanced.
3. If you cannot identify clear pros or cons from the provided context, output exactly:

   ```html
   <!-- No clear Pros/Cons identifiable for [primary_keyword] from the provided context. -->
   ```

---

## Task B: Generate HTML FAQ Section

**If the user message begins with exactly `snippet_type_requested: "faq"`,** output HTML matching *exactly* this structure:
The `<h4>` line must match regex `^<h4 class="faq-title-heading">Frequently Asked Questions about .+?</h4>$` exactly.

```html
<div class="faq-section">
  <h4 class="faq-title-heading">Frequently Asked Questions about [Primary Keyword]</h4>
  <details class="faq-item">
    <summary class="faq-question">[Question 1 Text]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>[Answer 1 Text. Can be multiple paragraphs if needed, each wrapped in <p> tags.]</p>
    </div>
  </details>
  <!-- … up to 3–5 Q&A blocks … -->
</div>
```

**Instructions (FAQ):**

1. Formulate **3–5** insightful Q&A pairs grounded in the `article_summary_snippet` and `relevant_content_snippet` about the `primary_keyword`. Questions must probe deeper than factual recall—ask ‘why’, ‘how’, or ‘what if’ where appropriate.
2. The `<h4>` **must** dynamically include the `primary_keyword` as shown in the template.
3. Each `<summary>` question should be phrased naturally and end with a question mark.
4. Answers must be concise, authoritative, and derived from context; wrap each paragraph in `<p>` tags.
5. If no FAQs can be generated from the provided context, output exactly:

   ```html
   <!-- No clear FAQs identifiable for [primary_keyword] from the provided context. -->
   ```

---

**Global Constraints:**

* **Output only** the raw HTML snippet (or the HTML comment if no content is identifiable).
* **Do not** include any extra tags, wrappers, markdown, JSON, or explanatory text.
* **Do not** apply additional styling, classes, or inline CSS beyond what’s specified.
* **Strictly** adhere to the given HTML templates.
"""

# --- User Prompt Templates ---
USER_PROMPT_BASE_TEMPLATE = """snippet_type_requested: "{snippet_type}"
primary_keyword: "{primary_keyword_safe}"
article_summary_snippet: "{article_summary_snippet_safe}"
relevant_content_snippet: "{relevant_content_snippet_safe}"
"""
# --- End Agent Prompts ---

def _extract_top_sentences(text, keywords, k=5, min_sentence_len=10):
    if not text or not keywords: return ""
    # Improved sentence splitting, handles more delimiters and keeps them for reconstruction if needed
    sentences = re.split(r'(?<=[.!?])\s+|(?<=\n)\s*', text) # Split on sentence enders or newlines
    sentences = [s.strip() for s in sentences if s and len(s.strip()) >= min_sentence_len]
    
    if not sentences: return ""

    keyword_list = [kw.lower() for kw in keywords if isinstance(kw, str)] # Ensure keywords are strings and lowercased
    
    scored_sentences = []
    for sent in sentences:
        score = sum(kw in sent.lower() for kw in keyword_list)
        # Bonus for sentences containing multiple distinct keywords
        distinct_kws_in_sent = sum(1 for kw in set(keyword_list) if kw in sent.lower())
        if distinct_kws_in_sent > 1:
            score += distinct_kws_in_sent * 0.5 # Add a small bonus for more distinct keywords
        scored_sentences.append((score, sent))
        
    top_k_sentences = sorted(scored_sentences, key=lambda x: x[0], reverse=True)[:k]
    
    # Return as a single string, preserving original sentence order if possible (tricky with sorting by score)
    # For now, just join the top scoring ones.
    # To preserve order, one might iterate original sentences and pick if score is high enough.
    # For this use case, a block of highly relevant (but potentially reordered) sentences is okay.
    result = " ".join([s_text for s_score, s_text in top_k_sentences if s_score > 0])
    logger.debug(f"Extracted top sentences based on keywords '{keywords[:3]}...': '{result[:150]}...' (Score of top: {top_k_sentences[0][0] if top_k_sentences else 0})")
    return result


def call_structuroprime_for_html_snippet(user_prompt_content_str: str):
    if not DEEPSEEK_API_KEY_HTML:
        logger.error("DEEPSEEK_API_KEY_HTML not found. Cannot call StructuroPrime for HTML snippets.")
        return None

    payload = {
        "model": DEEPSEEK_MODEL_FOR_HTML_SNIPPETS,
        "messages": [
            {"role": "system", "content": STRUCTUROPRIME_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt_content_str} 
        ],
        "temperature": 0.2, # Lowered for more deterministic HTML
        "max_tokens": 1000, # Reduced max_tokens as HTML snippets are usually not extremely long
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY_HTML}",
        "Content-Type": "application/json"
    }

    try:
        logger.debug(f"Sending HTML snippet generation request to StructuroPrime. User prompt (first 100): {user_prompt_content_str[:100]}...")
        response = requests.post(DEEPSEEK_CHAT_API_URL_HTML, headers=headers, json=payload, timeout=API_TIMEOUT_HTML_AGENT)
        response.raise_for_status()
        response_json = response.json()

        if response_json.get("choices") and \
           response_json["choices"][0].get("message") and \
           response_json["choices"][0]["message"].get("content"):
            
            generated_html = response_json["choices"][0]["message"]["content"].strip()
            logger.info(f"StructuroPrime HTML snippet generation successful.")
            
            match = re.search(r'```html\s*([\s\S]*?)\s*```', generated_html, re.DOTALL | re.IGNORECASE)
            if match:
                logger.warning("StructuroPrime wrapped HTML snippet in markdown code fences. Unwrapping.")
                generated_html = match.group(1).strip()
            elif generated_html.startswith("```") and generated_html.endswith("```"): 
                generated_html = generated_html[3:-3].strip()
            
            logger.debug(f"Generated HTML snippet (first 300 chars): {generated_html[:300]}")
            return generated_html
        else:
            logger.error(f"StructuroPrime HTML snippet response missing expected content structure: {response_json}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"StructuroPrime API request for HTML snippet failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"StructuroPrime API Response Content: {e.response.text}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_structuroprime_for_html_snippet: {e}")
        return None

def _validate_html_snippet(html_content: str, snippet_type: str, primary_keyword: str) -> bool:
    if not html_content: return False
    if f"<!-- No clear {snippet_type.upper()} identifiable for {primary_keyword}" in html_content:
        return True # This is a valid "no content" response from the LLM

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        if snippet_type == "pros_cons":
            container = soup.find('div', class_='pros-cons-container')
            if not container: return False
            pros_list = container.select('.pros-section ul li')
            cons_list = container.select('.cons-section ul li')
            # Relaxed validation: allow 2-5 items, as LLM might struggle with exactly 3-5 always
            return (2 <= len(pros_list) <= 5 and 2 <= len(cons_list) <= 5)
        elif snippet_type == "faq":
            container = soup.find('div', class_='faq-section')
            if not container: return False
            faq_title = container.find('h4', class_='faq-title-heading')
            if not faq_title or primary_keyword.lower() not in faq_title.text.lower(): # Check if PK is in title
                 logger.warning(f"FAQ title missing or does not contain primary keyword '{primary_keyword}'. Title: '{faq_title.text if faq_title else 'N/A'}'")
                 # Don't fail validation for this, but log it. Title is part of template.
            
            details_blocks = container.find_all('details', class_='faq-item')
            if not (2 <= len(details_blocks) <= 5): return False # Allow 2-5 FAQs
            for detail in details_blocks:
                if not detail.find('summary', class_='faq-question') or \
                   not detail.find('div', class_='faq-answer-content') or \
                   not detail.find('div', class_='faq-answer-content').find_all('p'): # Ensure at least one <p> in answer
                    return False
            return True
        return False # Unknown snippet type
    except Exception as e:
        logger.error(f"Error validating HTML snippet ({snippet_type}) with BeautifulSoup: {e}")
        return False


def generate_specific_html_snippet(article_pipeline_data, snippet_type_str):
    primary_keyword_raw = article_pipeline_data.get('primary_topic', article_pipeline_data.get('final_page_h1', "this topic"))
    # Safe primary keyword for prompt formatting
    primary_keyword_safe = json.dumps(primary_keyword_raw)[1:-1]


    summary_raw = article_pipeline_data.get('processed_summary', article_pipeline_data.get('generated_meta_description',''))
    full_body_md = article_pipeline_data.get('assembled_article_body_md', article_pipeline_data.get('raw_scraped_text', ''))

    summary_snippet_safe = json.dumps(summary_raw[:MAX_CONTEXT_FOR_HTML_SNIPPETS_SUMMARY])[1:-1] if summary_raw else ""
    
    # Use smart sentence extraction for relevant_content_snippet
    keywords_for_extraction = [primary_keyword_raw] + article_pipeline_data.get('final_keywords', [])[:2] # Use PK + top 2 keywords
    relevant_body_sentences = _extract_top_sentences(full_body_md, keywords_for_extraction, k=7) # Get more sentences
    
    relevant_content_snippet_safe = json.dumps(relevant_body_sentences[:MAX_CONTEXT_FOR_HTML_SNIPPETS_BODY])[1:-1] if relevant_body_sentences else ""

    if len(summary_snippet_safe + relevant_content_snippet_safe) < MIN_RELEVANT_CONTENT_LENGTH_FOR_LLM:
        logger.warning(f"Combined context length too short ({len(summary_snippet_safe + relevant_content_snippet_safe)} chars) for HTML snippet gen ({snippet_type_str}) for article {article_pipeline_data.get('id')}. Skipping LLM call.")
        article_pipeline_data[f'html_snippet_status_detail_{snippet_type_str}'] = "TOO_SHORT_FOR_HTML_SNIPPET"
        return f"<!-- Content too short to generate {snippet_type_str} for {primary_keyword_raw}. -->"


    user_prompt_str = USER_PROMPT_BASE_TEMPLATE.format(
        snippet_type=snippet_type_str,
        primary_keyword_safe=primary_keyword_safe, # Use the JSON-escaped version for the prompt
        article_summary_snippet_safe=summary_snippet_safe,
        relevant_content_snippet_safe=relevant_content_snippet_safe
    )
    return call_structuroprime_for_html_snippet(user_prompt_str)


def run_html_snippets_agent(article_pipeline_data, snippet_types_requested):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running HTML Snippets Agent (StructuroPrime v2) for Article ID: {article_id} (Requested: {snippet_types_requested}) ---")

    article_pipeline_data['html_snippets_agent_status'] = "NO_SNIPPETS_REQUESTED"
    generated_any_valid_snippet = False

    if not snippet_types_requested:
        return article_pipeline_data

    for snippet_type in snippet_types_requested:
        logger.info(f"Generating '{snippet_type}' HTML for {article_id}")
        html_content = generate_specific_html_snippet(article_pipeline_data, snippet_type)
        
        output_key = f'generated_{snippet_type}_html'
        
        # Use raw primary keyword for validation message, not the escaped one
        primary_keyword_for_validation = article_pipeline_data.get('primary_topic', article_pipeline_data.get('final_page_h1', "this topic"))

        if html_content and _validate_html_snippet(html_content, snippet_type, primary_keyword_for_validation):
            if f"<!-- No clear {snippet_type.upper()} identifiable" in html_content:
                logger.info(f"StructuroPrime indicated no clear content for '{snippet_type}' for {article_id}.")
                article_pipeline_data[output_key] = html_content # Store the comment
                article_pipeline_data[f'html_snippet_status_detail_{snippet_type}'] = f"NO_{snippet_type.upper()}_IDENTIFIABLE"
            else:
                article_pipeline_data[output_key] = html_content
                logger.info(f"Successfully generated and validated '{snippet_type}' HTML for {article_id}.")
                generated_any_valid_snippet = True
                article_pipeline_data[f'html_snippet_status_detail_{snippet_type}'] = "SUCCESS"
        else:
            failure_reason = article_pipeline_data.get(f'html_snippet_status_detail_{snippet_type}', "GENERATION_OR_VALIDATION_FAILED")
            logger.warning(f"Failed to generate or validate '{snippet_type}' HTML for {article_id}. Reason: {failure_reason}. LLM output (if any): {str(html_content)[:200]}")
            article_pipeline_data[output_key] = f"<!-- Failed to generate valid {snippet_type} HTML. Status: {failure_reason}. -->"
            article_pipeline_data[f'html_snippet_status_detail_{snippet_type}'] = failure_reason


    if generated_any_valid_snippet:
        article_pipeline_data['html_snippets_agent_status'] = "SUCCESS"
    elif snippet_types_requested: 
        # Check if all requested snippets explicitly returned "no content identifiable"
        all_no_content = True
        for st in snippet_types_requested:
            if not article_pipeline_data.get(f'html_snippet_status_detail_{st}', '').startswith("NO_"):
                all_no_content = False
                break
        if all_no_content:
            article_pipeline_data['html_snippets_agent_status'] = "SUCCESS_NO_CONTENT_IDENTIFIED_FOR_ALL"
        else:
            article_pipeline_data['html_snippets_agent_status'] = "FAILED_TO_GENERATE_VALID_HTML"
        
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    if not DEEPSEEK_API_KEY_HTML:
        logger.error("DEEPSEEK_API_KEY_HTML not set in .env. Cannot run standalone test for html_snippets_agent.")
        sys.exit(1)
        
    logger.info("--- Starting HTML Snippets Agent Standalone Test (StructuroPrime v2) ---")
    
    sample_article_data_for_html = {
        'id': 'test_html_structuro_v2_001',
        'primary_topic': "Modular \"Smartphone\" Concepts & Designs", # Include quotes for escaping test
        'final_page_h1': "The Rise and Fall of Modular \"Smartphone\" Concepts: A Tech Retrospective",
        'processed_summary': "Modular smartphones, like Project Ara, promised customizable hardware but faced challenges in market adoption due to complexity and cost. Users could swap components like cameras and batteries. While the concept was innovative, execution proved difficult, leading to most projects being discontinued. Some argue the environmental benefits of repairability were overlooked.",
        'assembled_article_body_md': "The dream of a truly modular smartphone, where users could easily upgrade individual components such as the processor, camera, or battery, captured the imagination of many tech enthusiasts. Google's Project Ara was a high-profile attempt, showcasing a device with an endoskeleton frame and various attachable modules. Main advantages: increased device longevity, reduced e-waste, ultimate personalization. Engineering hurdles: reliable connections, structural integrity, software compatibility. Cost of modules often made modular phones more expensive. Niche players continue exploration, but majors abandoned it. Key challenges: bulkiness, premium price. Promise of sustainability was a big draw for consumers concerned about e-waste.",
        'final_keywords': ["Modular Smartphones", "Project Ara", "Customizable Hardware", "Tech Innovation", "E-waste"]
    }

    # Test generating Pros & Cons
    logger.info("\n--- Testing Pros & Cons Generation (StructuroPrime v2) ---")
    result_data_pros_cons = run_html_snippets_agent(sample_article_data_for_html.copy(), snippet_types_requested=["pros_cons"])
    logger.info(f"Pros/Cons Agent Status: {result_data_pros_cons.get('html_snippets_agent_status')}")
    logger.info(f"Pros/Cons Status Detail: {result_data_pros_cons.get('html_snippet_status_detail_pros_cons')}")
    generated_pros_cons_html = result_data_pros_cons.get('generated_pros_cons_html', "No Pros/Cons HTML generated.")
    logger.info("Generated Pros & Cons HTML:")
    print("-------------------------------------------")
    print(generated_pros_cons_html)
    print("-------------------------------------------")
    assert "<div class=\"pros-cons-container\">" in generated_pros_cons_html or "<!-- No clear Pros/Cons identifiable" in generated_pros_cons_html

    # Test generating FAQ
    logger.info("\n--- Testing FAQ Generation (StructuroPrime v2) ---")
    result_data_faq = run_html_snippets_agent(sample_article_data_for_html.copy(), snippet_types_requested=["faq"])
    logger.info(f"FAQ Agent Status: {result_data_faq.get('html_snippets_agent_status')}")
    logger.info(f"FAQ Status Detail: {result_data_faq.get('html_snippet_status_detail_faq')}")
    generated_faq_html = result_data_faq.get('generated_faq_html', "No FAQ HTML generated.")
    logger.info("Generated FAQ HTML:")
    print("-------------------------------------------")
    print(generated_faq_html)
    print("-------------------------------------------")
    assert "<div class=\"faq-section\">" in generated_faq_html or "<!-- No clear FAQs identifiable" in generated_faq_html
    # Check if the (unescaped) primary keyword is in the FAQ title
    assert "Modular \"Smartphone\" Concepts & Designs" in generated_faq_html or "<!-- No clear FAQs identifiable" in generated_faq_html
    
    # Test generating both
    logger.info("\n--- Testing Both Pros/Cons and FAQ Generation (StructuroPrime v2) ---")
    result_data_both = run_html_snippets_agent(sample_article_data_for_html.copy(), snippet_types_requested=["pros_cons", "faq"])
    logger.info(f"Both Snippets Agent Status: {result_data_both.get('html_snippets_agent_status')}")
    logger.info("Generated Pros & Cons HTML (from both):")
    print(result_data_both.get('generated_pros_cons_html', "Not generated"))
    logger.info("Generated FAQ HTML (from both):")
    print(result_data_both.get('generated_faq_html', "Not generated"))
    assert ("<div class=\"pros-cons-container\">" in result_data_both.get('generated_pros_cons_html','') or "<!-- No clear Pros/Cons identifiable" in result_data_both.get('generated_pros_cons_html',''))
    assert ("<div class=\"faq-section\">" in result_data_both.get('generated_faq_html','') or "<!-- No clear FAQs identifiable" in result_data_both.get('generated_faq_html',''))

    # Test with very short content
    logger.info("\n--- Testing with Short Content (StructuroPrime v2) ---")
    short_content_data = {
        'id': 'test_html_short_002',
        'primary_topic': "Brief Note",
        'final_page_h1': "A Very Brief Note",
        'processed_summary': "This is short.",
        'assembled_article_body_md': "Too short to tell.",
        'final_keywords': ["short", "note"]
    }
    result_short = run_html_snippets_agent(short_content_data.copy(), snippet_types_requested=["pros_cons"])
    logger.info(f"Short Content Pros/Cons Agent Status: {result_short.get('html_snippets_agent_status')}")
    logger.info(f"Short Content Pros/Cons Status Detail: {result_short.get('html_snippet_status_detail_pros_cons')}")
    assert "TOO_SHORT_FOR_HTML_SNIPPET" in result_short.get('html_snippet_status_detail_pros_cons','')


    logger.info("--- HTML Snippets Agent Standalone Test (StructuroPrime v2) Complete ---")

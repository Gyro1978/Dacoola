import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Path Setup (Ensure src is in path if run standalone) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Path Setup ---

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
YOUR_WEBSITE_NAME = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL = os.getenv('YOUR_WEBSITE_LOGO_URL', '')

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 6666 
TEMPERATURE = 0.65 
API_TIMEOUT_SECONDS = 360

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, operating as a world-class journalist for `{YOUR_WEBSITE_NAME}`. Your core mission is to synthesize the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into a comprehensive, engaging, factually precise, and maximally SEO-optimized news article. Your writing MUST be indistinguishable from high-quality human journalism, avoiding common AI writing patterns and clichés. You MUST adhere strictly to ALL directives below.

**I. Foundational Principles:**

1.  **Source Adherence & Expansion:** Base article *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Expand briefly only with widely accepted context or logical inference; *never* invent facts/quotes. Synthesize full text significantly; avoid simple paraphrasing.
2.  **Target Audience:** Tech-savvy readers interested in AI/Tech news. Assume baseline knowledge; define niche terms concisely if used.
3.  **E-E-A-T:** Write with expertise, grounding claims in the source. Ensure accuracy. Attribute implicitly ("The announcement indicated...") or explicitly if possible.
4.  **Helpful Content:** Prioritize informing the reader. SEO supports readability/UX.

**II. SEO Optimization Strategy (CRITICAL):**

5.  **Keyword Integration (Throughout Content):**
    *   **Primary Keyword (`{{TARGET_KEYWORD}}`):** MUST be naturally integrated into the Title Tag, Meta Description, H1, the first ~100 words of the article body, and at least 1-2 relevant subheadings (H3/H4) and their corresponding paragraphs.
    *   **Secondary Keywords (`{{SECONDARY_KEYWORDS_LIST_STR}}`):** If provided and not empty, naturally weave 1-3 of these unique secondary keywords into different relevant sections of the article body, including subheadings and paragraphs. Do NOT force all of them if it compromises readability.
    *   **General Principle:** Keywords should appear as if they are the natural language of the topic. **NO KEYWORD STUFFING.** The goal is relevance and natural flow.
6.  **Semantic Relevance:** Incorporate related terms, concepts, synonyms, and relevant entities from the source text naturally.
7.  **User Intent:** Address likely search intent for `{{TARGET_KEYWORD}}`. Anticipate questions for FAQs, potentially incorporating keywords or related concepts into FAQ questions/answers if natural.

**III. Content Generation & Structure Requirements:**

8.  **SEO H1:** Compelling, clear H1 (`## [Generated H1]`) containing `{{TARGET_KEYWORD}}`.
9.  **Initial Summary:** 1-2 concise lead paragraphs summarizing core news from source. Include `{{TARGET_KEYWORD}}` in the first paragraph.
10. **In-Depth Analysis:** Expand with context, implications, background using logical headings (`### H3`, `#### H4`). This is a key area for natural integration of primary and secondary keywords in both headings and text.
    *   **Main Analysis (`### H3`):** *One* descriptive H3 title (e.g., "### Unpacking the Significance of {{TARGET_KEYWORD}}"). 2-4 paragraphs of core analysis.
    *   **Thematic Sub-sections (`#### H4`):** Descriptive H4 titles (e.g., "#### Technical Aspects of {{A_SECONDARY_KEYWORD}}"). 1-2 paragraphs each. **Omit if not relevant/supported by content.**
11. **Pros & Cons (`#### Pros & Cons`):**
    *   **Generate ONLY if genuinely applicable and supported by content. Omit entirely otherwise.**
    *   Use **exact** H4 title: `#### Pros & Cons`.
    *   Use **exact HTML structure:** `<ul><li>...</li></ul>` within `.item-list` divs.
    *   **CRITICAL `<li>` Content:** Plain descriptive text only. **NO bolded titles/prefixes.** NO surrounding `**`. Markdown emphasis (*italic*, **bold**) OK *within* the description.
12. **FAQ (`#### Frequently Asked Questions`):**
    *   **Generate ONLY if topic warrants it. Omit entirely otherwise.**
    *   Use **exact** H4 title: `#### Frequently Asked Questions`.
    *   Generate **3-5 relevant questions**. Questions and answers should be informative and clear. Where natural, a question or answer might touch upon `{{TARGET_KEYWORD}}` or a secondary keyword if it helps clarify user intent.
    *   Use **exact HTML structure** including icon: `<i class="faq-icon fas fa-chevron-down"></i>`.
13. **Overall Length & Tone:** **500-800 words**. Authoritative, objective, engaging, accessible journalistic tone.

**IV. Writing Style & Avoiding "AI Tells":** (Same as before)
14. Natural Language & Flow...
15. AVOID LLM Phrases...
16. STRICTLY FORBIDDEN SYMBOLS/PATTERNS...
17. Sentence Variation & Active Voice...
18. Consistent Tense...
19. Tone Adaptation...

**V. Output Formatting (Strict Adherence Mandatory):** (Same as before)
20. Markdown & HTML...
21. Exact Output Order...
22. Title Tag...
23. Meta Description...
24. SEO H1...
25. JSON-LD...

**VI. Error Handling:** (Same as before)
26. If `{{ARTICLE_CONTENT_FOR_PROCESSING}}` < ~50 words, output ONLY: `Error: Input content insufficient for generation.`

**VII. Final Check:** (Same as before)
27. **NO Extra Text:** Absolutely NO text before `Title Tag:` or after `</script>`.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body, and JSON-LD Script.
**Crucially, you MUST naturally integrate the `{{TARGET_KEYWORD}}` and relevant `{{SECONDARY_KEYWORDS_LIST_STR}}` (if provided and not empty) throughout the article body, including paragraphs, subheadings (H3/H4), and potentially within FAQ questions/answers where it makes sense for user clarity.** Prioritize natural language and avoid stuffing.
Follow ALL System Prompt directives meticulously, especially regarding avoiding forbidden AI phrases/symbols (NO EM DASHES `—`), using specified HTML ONLY for Pros/Cons and FAQs, omitting optional sections if not relevant, varying vocabulary/sentence structure, and ensuring natural journalistic style.

**Input Context:**
ARTICLE_TITLE: {article_title}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If empty, focus on TARGET_KEYWORD. If provided, select 1-3 unique ones for natural integration.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json}

**Required Output Format (Strict Adherence):**
Title Tag: [Generated title tag ≤ 60 chars, include TARGET_KEYWORD]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD]
SEO H1: [Generated SEO-Optimized H1 heading, include TARGET_KEYWORD.]

## [SEO H1 from above]
[Paragraph 1-2: CONCISE summary. Include TARGET_KEYWORD in the first paragraph. Journalistic tone.]

### [Contextual H3 Title - Potentially including TARGET_KEYWORD or a SECONDARY_KEYWORD naturally]
[Paragraphs 2-4+: In-depth analysis. Weave in TARGET_KEYWORD again + 1-2 unique SECONDARY_KEYWORDS from the list if provided/relevant and they fit naturally in this section. Vary sentences/vocabulary.]

#### [Optional: Contextual H4 Title - Potentially including a SECONDARY_KEYWORD naturally. OMIT IF NOT RELEVANT]
[Optional: 1-2 paragraphs. Could be another place for a different SECONDARY_KEYWORD if applicable. OMIT ENTIRE SECTION if not applicable.]

#### [Optional: Pros & Cons - OMIT IF NOT APPLICABLE]
[Use exact H4 title. Items MUST be HTML `<li>` containing ONLY descriptive text. NO titles/prefixes/surrounding `**` inside `<li>`. NO markdown lists inside `<li>`.]
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Explanation of the first advantage.</li>
        <li>Description of a second pro.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Description of a limitation or con.</li>
        <li>Further potential downside.</li>
      </ul>
    </div>
  </div>
</div>

#### [Optional: Contextual H4 Title - OMIT IF NOT RELEVANT]
[Optional: 1-2 paragraphs. OMIT ENTIRE SECTION if not applicable.]

#### [Optional: Frequently Asked Questions - OMIT IF NOT APPLICABLE]
[Use exact H4 title. Generate 3-5 Q&As. Questions or answers can subtly incorporate TARGET_KEYWORD or relevant secondary terms if it improves clarity and addresses user intent. Do not force.]
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">What is {TARGET_KEYWORD} in this context? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Concise answer related to the article's main topic.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">How does {A_SECONDARY_KEYWORD_IF_RELEVANT} affect this? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Detailed answer.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Another relevant question? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Insightful answer.</p>
    </div>
  </details>
</div>

Source: [{article_title}]({source_article_url})

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "[SEO H1 from above]",
  "description": "[Generated meta description from above]",
  "keywords": {all_generated_keywords_json},
  "mainEntityOfPage": {{ "@type": "WebPage", "@id": "{source_article_url}" }},
  "image": {{ "@type": "ImageObject", "url": "{article_image_url}" }},
  "datePublished": "{current_date_iso}",
  "dateModified": "{current_date_iso}",
  "author": {{ "@type": "Person", "name": "{author_name}" }},
  "publisher": {{
    "@type": "Organization",
    "name": "{your_website_name}",
    "logo": {{ "@type": "ImageObject", "url": "{your_website_logo_url}" }}
  }}
}}
</script>
"""

# --- API Call Function ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    if not DEEPSEEK_API_KEY: logger.error("DEEPSEEK_API_KEY not set."); return None
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Accept": "application/json" }
    payload = { "model": AGENT_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "max_tokens": max_tokens, "temperature": temperature, "stream": False }
    try:
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL})...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage');
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Comp={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```") and content_stripped.endswith("```"):
                     first_newline = content_stripped.find('\n'); content_stripped = content_stripped[first_newline+1:-3].strip() if first_newline != -1 else content_stripped[3:-3].strip()
                content_stripped = content_stripped.replace('—', '-')
                return content_stripped
            return None
        else: logger.error(f"API response missing 'choices': {result}"); return None
    except requests.exceptions.Timeout: logger.error(f"API request timed out ({API_TIMEOUT_SECONDS}s)."); return None
    except requests.exceptions.RequestException as e: logger.error(f"API request failed: {e}"); return None
    except Exception as e: logger.exception(f"Unexpected error during API call: {e}"); return None

# --- Parsing Function ---
def parse_seo_agent_response(response_text):
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty: {response_text or 'Empty'}"
        logger.error(error_message); return None, error_message
    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.M | re.I)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("Missing 'Title Tag:' line.")
        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.M | re.I)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("Missing 'Meta Description:' line.")
        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.M | re.I)
        if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else: errors.append("Missing 'SEO H1:' line.")
        script_match = re.search(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{.*?\})\s*<\/script>', response_text, re.S | re.I)
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip()
            try: json.loads(json_content_str);
            except json.JSONDecodeError: errors.append("JSON-LD content invalid.")
        else: errors.append("Missing JSON-LD script block.")
        body_content = None
        body_match_to_source = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]+\s*Source:", response_text, re.M | re.S | re.I)
        if body_match_to_source: body_content = body_match_to_source.group(1).strip()
        else:
            body_match_to_script = re.search(r"^\s*SEO H1:.*?[\r\n]+([\s\S]*?)[\r\n]*\s*<script", response_text, re.M | re.S | re.I)
            if body_match_to_script: body_content = body_match_to_script.group(1).strip()
        if body_content:
            if body_content.startswith("## "): parsed_data['generated_article_body_md'] = body_content
            else: errors.append("Extracted Body doesn't start with '## '."); parsed_data['generated_article_body_md'] = ""
        else: errors.append("Could not extract Article Body."); parsed_data['generated_article_body_md'] = ""
        if not parsed_data.get('generated_article_body_md') or not parsed_data.get('generated_seo_h1'):
            final_err = f"Critical parsing failure: Body/H1 missing. Errors: {'; '.join(errors or ['Unknown'])}"
            logger.error(final_err); logger.debug(f"Failed response:\n{response_text[:1000]}..."); return None, final_err
        parsed_data.setdefault('generated_title_tag', parsed_data.get('generated_seo_h1', 'Error'))
        parsed_data.setdefault('generated_meta_description', 'Error')
        parsed_data.setdefault('generated_json_ld', '<script type="application/ld+json">{}</script>')
        return parsed_data, ("; ".join(errors) if errors else None)
    except Exception as e: logger.exception(f"Critical parse error: {e}"); return None, f"Parsing exception: {e}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    content_to_process = article_data.get('content_for_processing')
    if not content_to_process: error_msg = f"Missing content {article_id}."; logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword: error_msg = f"Missing primary kw {article_id}."; logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    
    researched_keywords = article_data.get('researched_keywords', []) # This list comes from keyword_research_agent
    secondary_keywords_for_prompt = [kw for kw in researched_keywords if kw.lower() != primary_keyword.lower()][:3] # Take up to 3 unique secondary
    secondary_keywords_list_str = ", ".join(secondary_keywords_for_prompt)
    
    all_keywords_for_json_ld = list(set(([primary_keyword] if primary_keyword else []) + researched_keywords))
    all_keywords_for_json_ld = [str(k).strip() for k in all_keywords_for_json_ld if k and str(k).strip()]
    all_generated_keywords_json = json.dumps(all_keywords_for_json_ld)

    input_data_for_prompt = {
        "article_title": article_data['title'], "article_content_for_processing": content_to_process,
        "source_article_url": article_data['link'], "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str, 
        "article_image_url": article_data['selected_image_url'],
        "author_name": article_data.get('author', 'AI News Team'), 
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME, 
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }
    critical_inputs = ['article_title', 'article_content_for_processing', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json', 'your_website_name']
    if any(input_data_for_prompt.get(k) is None for k in critical_inputs):
        missing = [k for k in critical_inputs if input_data_for_prompt.get(k) is None]
        error_msg = f"Critical data missing for prompt {article_id}: {missing}"
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    try: 
        system_prompt_formatted = SEO_PROMPT_SYSTEM.format(YOUR_WEBSITE_NAME=YOUR_WEBSITE_NAME)
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e: logger.exception(f"KeyError formatting SEO prompt {article_id}: {e}"); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt format error: {e}"; return article_data
    
    logger.info(f"Running SEO agent for {article_id} (Keyword Integration Focus)...")
    raw_response_content = call_deepseek_api(system_prompt_formatted, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)
    if not raw_response_content: error_msg = "API call failed/empty."; logger.error(f"{error_msg} ({article_id})."); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    
    logger.debug(f"Raw SEO Agent Response {article_id}:\n{raw_response_content[:1500]}...")
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)
    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg
    
    if parsed_results is None: 
        logger.error(f"Failed parse SEO response {article_id}: {error_msg}"); 
        article_data['seo_agent_raw_response'] = raw_response_content
    elif error_msg: 
        logger.warning(f"SEO parsing completed with non-critical errors {article_id}: {error_msg}")
    else:
        logger.info(f"Successfully generated/parsed SEO content for {article_id}.")
        if parsed_results.get('generated_seo_h1') and parsed_results['generated_seo_h1'] != article_data['title']:
            logger.info(f"Updating title {article_id} with SEO H1: '{parsed_results['generated_seo_h1']}'")
            article_data['title'] = parsed_results['generated_seo_h1'] # Update main article title with the SEO H1
    
    # The 'generated_tags' in article_data will be the list from keyword_research_agent.
    # The JSON-LD script already uses all_generated_keywords_json, which includes primary + researched.
    # The HTML template uses article_data['generated_tags'] for display.
            
    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG) # Set to DEBUG for more verbose output
    logger.setLevel(logging.DEBUG)

    test_article = {
        'id': 'seo-test-001',
        'title': "Initial Test Title about LLM Advancements",
        'content_for_processing': """
        Recent breakthroughs in Large Language Models (LLMs) have shown remarkable capabilities. 
        A new model, 'InnovateLLM', developed by FutureAI Corp, demonstrates superior performance in contextual understanding and text generation. 
        InnovateLLM uses a novel attention mechanism and was trained on a diverse dataset of over 5 trillion tokens.
        Experts believe this could significantly impact natural language processing applications.
        The model's architecture allows for more efficient scaling compared to previous generations.
        FutureAI Corp plans to release an API for developers in the coming months. This is a big step.
        """,
        'link': "https://example.com/innovate-llm-breakthrough",
        'filter_verdict': {
            'importance_level': "Interesting",
            'topic': "AI Models",
            'primary_topic_keyword': "InnovateLLM advancements" 
        },
        'researched_keywords': [ # Keywords from the (mocked) keyword_research_agent
            "InnovateLLM advancements", "FutureAI Corp LLM", "contextual understanding AI", 
            "LLM attention mechanism", "natural language processing applications", "AI model scaling"
        ],
        'selected_image_url': "https://via.placeholder.com/1200x675.png?text=InnovateLLM",
        'author': "Dr. AI Testington",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }
    logger.info("\n--- Running SEO Article Agent Standalone Test (Keyword Integration) ---")
    
    # Ensure researched_keywords are also used for generated_tags for the template
    test_article['generated_tags'] = test_article['researched_keywords']

    result_data = run_seo_article_agent(test_article.copy())

    if result_data.get('seo_agent_error'):
        print(f"\nSEO Agent Error: {result_data['seo_agent_error']}")
    if result_data.get('seo_agent_results'):
        print("\n--- Generated SEO Content ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1: {result_data['seo_agent_results'].get('generated_seo_h1')}")
        print("\n--- Article Body (Markdown) ---")
        print(result_data['seo_agent_results'].get('generated_article_body_md'))
        print("\n--- JSON-LD ---")
        print(result_data['seo_agent_results'].get('generated_json_ld'))
    else:
        print("\nNo SEO results generated or critical error occurred.")
        if result_data.get('seo_agent_raw_response'):
             print("\n--- Raw API Response (if error) ---")
             print(result_data.get('seo_agent_raw_response'))

    logger.info("--- SEO Article Agent Standalone Test Complete ---")
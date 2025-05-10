import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone

# --- Path Setup ---
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
MAX_TOKENS_RESPONSE = 7000 
TEMPERATURE = 0.60 
API_TIMEOUT_SECONDS = 400 

# --- ADVANCED Agent Prompts ---
SEO_PROMPT_SYSTEM = """
You are an **Apex SEO Content Strategist and Master Tech News Journalist**, writing for the prestigious publication `{YOUR_WEBSITE_NAME}`. Your paramount objective is to transform provided article content into an exceptionally comprehensive, deeply engaging, meticulously factual, and maximally SEO-performant news article. Your output MUST be indistinguishable from top-tier human journalism, completely avoiding AI-writing tells and clichés. Adherence to ALL directives relayed through the user prompt is ABSOLUTELY MANDATORY.

**Your entire response will be machine-parsed. Adherence to the exact output format specified in the user prompt (Title Tag, Meta Description, SEO H1, ## H1, body, Source, JSON-LD script) is PARAMOUNT for successful processing. Any deviation will cause a failure.**

**I. Core Journalistic & Content Principles:**
1.  **Source Synthesis & Intelligent Expansion:** Ground the article *firmly* in the provided content. Expand *only* with widely accepted, verifiable background context or make logical, insightful inferences directly supported by the source. **NEVER INVENT OR FABRICATE facts, quotes, or statistics.**
2.  **Target Audience Acumen:** Address a sophisticated, tech-savvy audience. Assume baseline knowledge; define highly niche terms concisely.
3.  **E-E-A-T Supremacy:** Demonstrate profound Expertise, Authoritativeness, and Trustworthiness.
4.  **Helpful & Valuable Content:** Prioritize reader's informational gain. SEO enhances discoverability and UX.

**II. Advanced SEO Optimization Strategy (NON-NEGOTIABLE - Specific keywords will be provided in user prompt):**
5.  **Strategic Keyword Weaving:** You will be given a Primary Target Keyword and a list of Secondary Keywords. Your task is to naturally and seamlessly integrate these throughout the article as specified in the user prompt's detailed instructions. This includes the HTML Title, Meta Description, H1, introductory content, multiple subheadings (H3/H4), corresponding body paragraphs, and potentially FAQs. **NO KEYWORD STUFFING.**
6.  **Deep Semantic Relevance & LSI:** Incorporate semantically related terms, LSI keywords, synonyms, relevant entities, and concepts.
7.  **User Intent Fulfillment:** Address search intent behind the primary keyword. Answer anticipated questions.

**III. Sophisticated Content Generation & Structure (User prompt will detail specifics):**

**IV. Masterful Writing Style & Evasion of "AI Tells":**
14. **Natural Language & Flow:** Write like an experienced human journalist. Ensure smooth transitions. Be concise. Vary vocabulary.
15. **AVOID LLM Phrases & Hype:** Strictly avoid common AI-generated clichés AND overly effusive hype words. **Specifically, DO NOT USE terms like: "groundbreaking", "revolutionary", "game-changing", "paradigm shift", "monumental leap", "unprecedented", "delve into", "harness", "unleash", "pave the way", "empower", "leverage", "unlock"** unless it is a direct, attributed quote from a highly credible source within the provided content AND the context justifies such extreme language. Focus on factual, impactful descriptions.
16. **STRICTLY FORBIDDEN SYMBOLS/PATTERNS:** No Em Dashes (`—`), minimal ellipses/semicolons, standard punctuation, no unnecessary markdown.
17. **Sentence Variation & Active Voice:** Mix sentence lengths. Strongly prefer active voice.
18. **Consistent Tense:** Maintain consistent verb tense (usually past for news).
19. **Tone Adaptation:** Adapt slightly to source complexity but maintain professional tone.

**V. Precise Output Formatting (Strict Adherence Mandatory - User prompt will detail):**

**VI. Error Handling (User prompt specifies behavior for insufficient content):**

**VII. Final Review & Mandate:**
    **NO Extra Text:** Absolutely NO text before the first line (e.g., "Title Tag:") or after the final `</script>`.
"""

SEO_PROMPT_USER_TEMPLATE = """
**CRITICAL OUTPUT REQUIREMENT: Your response MUST start *exactly* with "Title Tag:", followed by "Meta Description:", then "SEO H1:", then a blank line, then the Markdown H1 "## [SEO H1 text from above]", then the article body, then "Source:", and finally the JSON-LD script. ABSOLUTELY NO PREAMBLE OR DEVIATION.**

Task: Generate Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body, and JSON-LD Script.
**ULTRA-CRITICAL DIRECTIVE: You MUST strategically and naturally integrate the `{{TARGET_KEYWORD}}` multiple times (H1, first paragraph, 2-3 subheadings, corresponding body text) AND thoughtfully weave in 2-4 UNIQUE `{{SECONDARY_KEYWORDS_LIST_STR}}` (if provided and not empty) into different relevant sections of the article body, including paragraphs, appropriate subheadings (H3/H4), and potentially within FAQ questions/answers where it genuinely enhances user understanding and targets related intents.** Prioritize natural linguistic flow and deep topical relevance; strictly avoid keyword stuffing or awkward phrasing.
Adhere with extreme precision to ALL System Prompt directives, especially: avoiding forbidden AI linguistic patterns/symbols (ABSOLUTELY NO EM DASHES `—`), using the specified HTML structures ONLY for Pros/Cons (no bolded titles/prefixes in `<li>`) and FAQs, omitting optional sections (H4s, Pros/Cons, FAQ) if not substantially supported by content or if they detract from quality, employing rich vocabulary and varied sentence structures, and emulating the style of a top-tier human journalist.

**Input Context:**
ARTICLE_TITLE: {article_title}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If empty, focus solely on TARGET_KEYWORD. If provided, select 2-4 unique, high-value ones for careful, natural integration across different article sections.
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json} # This is the comprehensive list for the JSON-LD.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}

**Required Output Format (Strict Adherence - No Deviations):**
Title Tag: [Generated title tag ≤ 60 chars, include TARGET_KEYWORD, compelling]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD, action-oriented if possible]
SEO H1: [Generated SEO-Optimized H1 heading, prominently featuring TARGET_KEYWORD.]

## [SEO H1 exactly as above]
[Paragraph 1-2: CONCISE, impactful summary. **Must include `{{TARGET_KEYWORD}}` naturally in the first paragraph.** Journalistic tone. Standard hyphens ONLY. NO AI clichés.]

### [Descriptive H3 Title - Strategically incorporate `{{TARGET_KEYWORD}}` or a selected unique secondary keyword from the provided list if it fits naturally and adds value]
[Paragraphs 2-5+: Comprehensive in-depth analysis. Weave in `{{TARGET_KEYWORD}}` again. Strategically integrate selected unique secondary keywords from the list if provided, ensuring each is used contextually and naturally in different parts of this H3 section or subsequent H4s. Vary sentence structure and vocabulary extensively. AVOID AI clichés and em dashes steadfastly.]

#### [Optional & Contextual H4 Title - Could be a place for another unique secondary keyword from the list. OMIT ENTIRELY IF NOT SUBSTANTIALLY RELEVANT or if it fragments flow]
[Optional: 1-3 well-developed paragraphs. OMIT if not applicable or if it makes the article weaker.]

#### [Optional: Pros & Cons - GENERATE ONLY IF DEEPLY RELEVANT AND INSIGHTFUL. OMIT OTHERWISE.]
[Use exact H4 title: `#### Pros & Cons`. Items MUST be HTML `<li>` containing ONLY descriptive text. Internal **bold** or *italic* for emphasis within text is OK. NO titles/prefixes/surrounding `**` inside `<li>`. NO markdown lists inside `<li>`.]
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Detailed explanation of the first significant advantage.</li>
        <li>In-depth description of a second key pro.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Nuanced description of a notable limitation or con.</li>
        <li>Further potential downside or challenge.</li>
      </ul>
    </div>
  </div>
</div>

#### [Optional & Contextual H4 Title - OMIT IF NOT RELEVANT]
[Optional: 1-3 paragraphs. OMIT section if not adding clear value.]

#### [Optional: Frequently Asked Questions - GENERATE ONLY IF GENUINELY USEFUL FOR READERS. OMIT OTHERWISE.]
[Use exact H4 title: `#### Frequently Asked Questions`. Generate 3-5 relevant Q&As. **Questions OR answers can subtly and naturally incorporate `{{TARGET_KEYWORD}}` or relevant secondary terms (from `{{SECONDARY_KEYWORDS_LIST_STR}}`) if it directly addresses user search intent and improves clarity.** Do not force keywords here; prioritize usefulness.]
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">What are the core capabilities of {target_keyword}? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Clear, concise answer focusing on the article's main topic and its relation to the target keyword.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">How does {{a relevant secondary keyword or concept}} relate to the developments discussed? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Insightful answer providing context on a secondary keyword's role or impact.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">What are the potential future implications? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Forward-looking answer, possibly touching on broader concepts related to the keywords.</p>
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
    # (Same as your last working version)
    if not DEEPSEEK_API_KEY: logger.error("DEEPSEEK_API_KEY not set."); return None
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Accept": "application/json" }
    payload = { "model": AGENT_MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "max_tokens": max_tokens, "temperature": temperature, "stream": False }
    try:
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL})...")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage');
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```json"): content_stripped = content_stripped[7:-3].strip() if content_stripped.endswith("```") else content_stripped[7:].strip()
                elif content_stripped.startswith("```"): content_stripped = content_stripped[3:-3].strip() if content_stripped.endswith("```") else content_stripped[3:].strip()
                content_stripped = content_stripped.replace('—', '-')
                return content_stripped
            logger.error("API response choice message content is empty.")
            return None
        else: logger.error(f"API response missing 'choices' or 'choices' is empty: {result}"); return None
    except requests.exceptions.Timeout: logger.error(f"API request timed out ({API_TIMEOUT_SECONDS}s)."); return None
    except requests.exceptions.RequestException as e: logger.error(f"API request failed: {e}"); return None
    except Exception as e: logger.exception(f"Unexpected error during API call: {e}"); return None

# --- Robust Parsing Function ---
def parse_seo_agent_response(response_text):
    # (Same as your last working version with robust parsing)
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty: {response_text or 'Empty Response'}"
        logger.error(error_message); return None, error_message
    response_text = re.sub(r"^\s*Sure, here's the generated content.*?\n", "", response_text, flags=re.IGNORECASE | re.DOTALL)
    response_text = re.sub(r"^\s*Okay, I've crafted the article.*?\n", "", response_text, flags=re.IGNORECASE | re.DOTALL)
    response_text = response_text.strip()

    title_tag_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.M | re.I)
    if title_tag_match: parsed_data['generated_title_tag'] = title_tag_match.group(1).strip()
    else: errors.append("Could not find 'Title Tag:'.")
    meta_desc_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.M | re.I)
    if meta_desc_match: parsed_data['generated_meta_description'] = meta_desc_match.group(1).strip()
    else: errors.append("Could not find 'Meta Description:'.")
    seo_h1_text_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.M | re.I)
    if seo_h1_text_match: parsed_data['generated_seo_h1'] = seo_h1_text_match.group(1).strip()
    else: errors.append("Could not find 'SEO H1:' line for H1 text."); parsed_data['generated_seo_h1'] = None

    if parsed_data.get('generated_seo_h1'):
        expected_h1_markdown_pattern_text = re.escape(parsed_data['generated_seo_h1'])
        body_match = re.search(r"^\s*##\s*" + expected_h1_markdown_pattern_text + r"\s*([\s\S]*?)(?=\n\s*Source:|\n\s*<script)", response_text, re.M | re.I)
        if body_match:
            parsed_data['generated_article_body_md'] = f"## {parsed_data['generated_seo_h1']}\n{body_match.group(1).strip()}"
        else: # Fallback if H1 from "SEO H1:" line isn't perfectly matched with "## "
            logger.warning(f"Could not find exact markdown H1 '## {parsed_data['generated_seo_h1']}'. Trying broader body search after 'SEO H1:' line.")
            # Find the end of the "SEO H1: ..." line
            seo_h1_line_match = re.search(r"^\s*SEO H1:\s*.*$", response_text, re.M | re.I)
            if seo_h1_line_match:
                start_of_body_search_area = response_text[seo_h1_line_match.end():]
                # Now look for the first "##" that might signify the H1
                actual_markdown_h1_match = re.search(r"^\s*(##\s+.*?)\n([\s\S]*?)(?=\n\s*Source:|\n\s*<script)", start_of_body_search_area, re.M | re.I)
                if actual_markdown_h1_match:
                    parsed_data['generated_article_body_md'] = actual_markdown_h1_match.group(1).strip() + "\n" + actual_markdown_h1_match.group(2).strip()
                    # Optionally update generated_seo_h1 if a different H1 text was found
                    new_h1_text = actual_markdown_h1_match.group(1).strip().replace("##","").strip()
                    if new_h1_text != parsed_data['generated_seo_h1']:
                        logger.info(f"Adjusted generated_seo_h1 based on found markdown H1 to: '{new_h1_text}'")
                        parsed_data['generated_seo_h1'] = new_h1_text
                else:
                    errors.append(f"Fallback body search after 'SEO H1:' line also failed to find a clear markdown body.")
            else: # Should not happen if seo_h1_text_match was positive
                 errors.append("Internal error locating end of 'SEO H1:' line for fallback body search.")
    else: errors.append("Cannot extract body because 'generated_seo_h1' was not found initially.")

    script_match = re.search(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>', response_text, re.S | re.I)
    if script_match:
        json_content_str = script_match.group(1).strip()
        try: json.loads(json_content_str); parsed_data['generated_json_ld'] = script_match.group(0).strip()
        except json.JSONDecodeError as json_err: errors.append(f"JSON-LD invalid: {json_err}"); parsed_data['generated_json_ld'] = "<!-- Error: Invalid JSON-LD -->"
    else: errors.append("Missing JSON-LD script block."); parsed_data['generated_json_ld'] = "<!-- Error: JSON-LD not found -->"

    if not parsed_data.get('generated_seo_h1'): return None, f"CRITICAL PARSE FAILURE: 'SEO H1' text not extracted. Errors: {'; '.join(errors)}"
    if not parsed_data.get('generated_article_body_md'): return None, f"CRITICAL PARSE FAILURE: Article Body not extracted. Errors: {'; '.join(errors)}"
    parsed_data.setdefault('generated_title_tag', parsed_data.get('generated_seo_h1', 'Error Title'))
    parsed_data.setdefault('generated_meta_description', 'Error Meta Description.')
    return parsed_data, ("; ".join(errors) if errors else None)


# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    logger.info(f"Running ADVANCED SEO Article Agent for ID: {article_id}...")
    content_to_process = article_data.get('content_for_processing')
    primary_keyword = article_data.get('primary_keyword') 

    if not content_to_process: error_msg = f"Missing 'content_for_processing' ID {article_id}."; logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    if not primary_keyword or not isinstance(primary_keyword, str) or not primary_keyword.strip():
        primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword', article_data.get('title', ''))
        if not primary_keyword or not isinstance(primary_keyword, str) or not primary_keyword.strip(): primary_keyword = "Key AI Topic" # Absolute fallback
        logger.warning(f"Primary keyword for SEO (ID {article_id}) defaulted to: '{primary_keyword}'")
    
    researched_keywords = article_data.get('researched_keywords', [])
    secondary_keywords_for_prompt = [kw for kw in researched_keywords if kw.lower() != primary_keyword.lower()][:4] 
    secondary_keywords_list_str = ", ".join(secondary_keywords_for_prompt)
    all_keywords_for_json_ld = list(set([primary_keyword] + researched_keywords))
    all_keywords_for_json_ld = [str(k).strip() for k in all_keywords_for_json_ld if k and str(k).strip()]
    all_generated_keywords_json_str = json.dumps(all_keywords_for_json_ld)

    input_data_for_prompt = {
        "article_title": article_data.get('title', 'Untitled Article'),
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data.get('link', '#'), "target_keyword": primary_keyword, 
        "secondary_keywords_list_str": secondary_keywords_list_str, 
        "all_generated_keywords_json": all_generated_keywords_json_str,
        "article_image_url": article_data.get('selected_image_url', ''),
        "author_name": article_data.get('author', 'AI News Team'), 
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME, "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
    }
    critical_inputs = ['article_title', 'article_content_for_processing', 'source_article_url', 'target_keyword', 'all_generated_keywords_json', 'article_image_url', 'current_date_iso', 'your_website_name']
    if any(not input_data_for_prompt.get(k) for k in critical_inputs):
        missing = [k for k in critical_inputs if not input_data_for_prompt.get(k)]; error_msg = f"Critical data missing for SEO prompt (ID {article_id}): {missing}";
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
        
    try: 
        system_prompt_formatted = SEO_PROMPT_SYSTEM.format(YOUR_WEBSITE_NAME=YOUR_WEBSITE_NAME)
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt ID {article_id}: {e}. Data: {input_data_for_prompt}")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt format error: {e}"; return article_data
    
    logger.info(f"Running ADVANCED SEO agent for ID {article_id} target: '{primary_keyword}', secondaries: '{secondary_keywords_list_str}'")
    raw_response_content = call_deepseek_api(system_prompt_formatted, user_prompt) 
    
    if not raw_response_content:
        error_msg = f"SEO API call failed/empty ID {article_id}."; logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
    
    logger.debug(f"Raw SEO Response (ID {article_id}, {len(raw_response_content)} chars):\n{raw_response_content[:1000]}...")
    parsed_results, parsing_error_msg = parse_seo_agent_response(raw_response_content)
    article_data['seo_agent_results'] = parsed_results; article_data['seo_agent_error'] = parsing_error_msg
    
    if parsed_results is None: 
        logger.error(f"Parse SEO response failed ID {article_id}: {parsing_error_msg}"); article_data['seo_agent_raw_response'] = raw_response_content 
    elif parsing_error_msg: 
        logger.warning(f"SEO parsing ID {article_id} with non-critical errors: {parsing_error_msg}")
    else:
        logger.info(f"Successfully generated/parsed ADVANCED SEO for ID {article_id}.")
        if parsed_results.get('generated_seo_h1') and parsed_results['generated_seo_h1'] != article_data.get('title'):
            logger.info(f"Updating title ID {article_id} with SEO H1: '{parsed_results['generated_seo_h1']}'")
            article_data['title'] = parsed_results['generated_seo_h1']
    return article_data

if __name__ == "__main__":
    # Standalone test code remains the same
    pass
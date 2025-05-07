# src/agents/seo_article_generator_agent.py (1/1)

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
MAX_TOKENS_RESPONSE = 5000
TEMPERATURE = 0.7
API_TIMEOUT_SECONDS = 360

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, powered by DeepSeek. Your mission is to transform the provided article content into a comprehensive, engaging, insightful, factually precise, and maximally SEO-optimized news article. This content is for a tech-savvy audience that values depth, clarity, and discoverability. Adhere strictly to ALL directives.

1.  **Content Source:** Base your generation *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. If it's a brief summary, expand on it with your knowledge and analytical skills. If it's full text, synthesize and re-structure it.

2.  **SEO Optimization - Core Principles:**
    *   **Primary Keyword (`{{TARGET_KEYWORD}}`):** Must appear naturally in: Title Tag, Meta Description, SEO-Optimized H1 Heading, the first paragraph of the initial summary, and 1-2 more times within the main body content (subheadings or analysis).
    *   **Secondary Keywords (`{{SECONDARY_KEYWORDS_LIST_STR}}`):** If provided, naturally integrate 1-2 of these into subheadings or the main body text.
    *   **Readability & User Experience:** Prioritize clear, concise language. Use short sentences and paragraphs where appropriate. Ensure a logical flow.
    *   **LSI Keywords:** Naturally incorporate semantically related terms and concepts throughout the article.
    *   **Punctuation:** Use standard hyphens (`-`) for punctuation where an em-dash (`—`) might typically be used (e.g., for parenthetical phrases or ranges). Avoid em-dashes in the final output.

3.  **Content Generation & Structure:**
    *   **SEO-Optimized H1 Heading (Article Title for the page):** Craft a compelling, SEO-friendly H1 heading (as `## [Generated H1 Heading]`). This can be different from `{{ARTICLE_TITLE}}` if a better SEO title is possible. It MUST include `{{TARGET_KEYWORD}}`. The H1 should be engaging and accurately reflect the article's core subject.
    *   **Initial Summary (1-2 well-developed paragraphs):** Provide a comprehensive summary based on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Ensure factual accuracy. Include `{{TARGET_KEYWORD}}` in the first paragraph.
    *   **In-Depth Analysis Section (Multiple Sub-sections as appropriate):**
        *   **Main Analysis Title (`### H3`):** Create a single, contextually relevant `### H3` title for the main analysis block (e.g., "### Unpacking the Impact", "### Key Innovations & Implications", "### Future Trajectory").
        *   **Core Analysis (2-4 paragraphs under the H3):** Deeper explanation, context, trends, significance.
        *   **Optional, Thematic Sub-sections (`#### H4`):** If the content supports it, create specific `#### H4` sub-sections *without generic prefixes like "Deeper Dive:"*. The H4 title itself should be descriptive (e.g., "#### The Technology Behind X", "#### Market Reactions", "#### Ethical Considerations"). Include 1-2 paragraphs for each.
        *   **Pros & Cons (`#### Pros & Cons`):** If applicable, use this exact H4 title. Items MUST be structured as an HTML unordered list (`<ul>`) with each item in an `<li>` tag directly within the `item-list` div as specified in the user prompt template. Apply Markdown for bold/italics *inside* the `<li>` tags if needed (e.g., `<li>**Strong Point:** Details...</li>`).
        *   **FAQ (`#### Frequently Asked Questions`):** If the topic is complex or warrants it, use this exact H4 title. Generate 3-5 relevant questions and answers using the specified HTML structure for interactive accordions (or 2-3 if less content is available).
    *   **Overall Length & Tone:** Aim for **500-800 words**. Maintain an authoritative, insightful, yet accessible journalistic tone.

4.  **Output Format (Strict Adherence Required):**
    *   **Markdown and Specified HTML:** The Article Body section must be valid Markdown, *except* for the "Pros & Cons" and "FAQ" sections, which MUST use the specified HTML structures.
    *   **Exact Order:** Title Tag, Meta Description, SEO-Optimized H1 Heading (for JSON-LD), Article Body, Source Link (DO NOT RENDER THIS VISIBLY IN ARTICLE BODY, it is for script processing only), JSON-LD Script.
    *   **Title Tag (for `<title>`):** Format: `Title Tag: [Generated title tag]`. Strictly **≤ 60 characters**. Include `{{TARGET_KEYWORD}}`.
    *   **Meta Description:** Format: `Meta Description: [Generated meta description]`. Strictly **≤ 160 characters**. Include `{{TARGET_KEYWORD}}`.
    *   **SEO-Optimized H1 Heading (for JSON-LD `headline`):** Format: `SEO H1: [Generated H1 heading for the article page]`. This will be used in the JSON-LD and as the main `##` heading in the Markdown body.
    *   **Article Body:** As defined in section 3. Starts with the `## [SEO H1 from above]`. The `Source: [{{ARTICLE_TITLE}}]({{SOURCE_ARTICLE_URL}})` line should be the *very last line of plain text content* before the JSON-LD script, and it should NOT be rendered as a visible link if a "Read Original Source" button is already present elsewhere on the page template. This line is primarily for data extraction.
    *   **JSON-LD Script:** Use the "SEO H1" for the `headline` field.

5.  **Error Handling:** If input is insufficient, output ONLY: `Error: Missing or invalid input field(s).`
6.  **No Extra Output:** Absolutely NO text before `Title Tag:` or after the closing `</script>` tag.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate Title Tag, Meta Description, an SEO-Optimized H1 Heading, a comprehensive Article Body, and JSON-LD Script Block. Follow ALL directives from the System Prompt precisely.

ARTICLE_TITLE: {article_title}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str}
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_LIST: {all_generated_keywords_json}

Required Output Format (Strict):
Title Tag: [Generated title tag ≤ 60 chars for <title> element, include TARGET_KEYWORD]
Meta Description: [Generated meta description ≤ 160 chars, include TARGET_KEYWORD]
SEO H1: [Generated SEO-Optimized H1 heading for the page, include TARGET_KEYWORD. This is the main article title.]

## [SEO H1 from above]
[Paragraph 1-2: CONCISE summary based on ARTICLE_CONTENT_FOR_PROCESSING. Include TARGET_KEYWORD naturally once here. Also try to include a SECONDARY_KEYWORD if natural.]

### [Contextual H3 Title for Main Analysis Section, e.g., "Unpacking the Impact", "Core Innovations"]
[Paragraphs 2-4 (or more): In-depth analysis, context, implications. Naturally weave in TARGET_KEYWORD again if possible, and other SECONDARY_KEYWORDS.]

#### [Optional: Contextual H4 Title for a Deeper Dive or Specific Aspect, e.g., "The Technology Behind X"]
[Optional: 1-2 paragraphs on a key technical detail or component if warranted. Incorporate relevant keywords.]

#### [Optional: Pros & Cons]
[If generating Pros & Cons, use this exact H4 title "Pros & Cons" and the HTML structure below. Items must be HTML list items (`<li>`). Use Markdown for bold/italics *inside* `<li>` tags if needed.]
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>**Pro Item 1:** Detailed explanation of the first advantage.</li>
        <li>Pro Item 2: Another benefit.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>**Con Item 1:** Description of a drawback.</li>
        <li>Con Item 2: Further limitation.</li>
      </ul>
    </div>
  </div>
</div>

#### [Optional: Contextual H4 Title for Challenges, e.g., "Potential Hurdles and Criticisms"]
[Optional: 1-2 paragraphs discussing hurdles or criticisms.]

#### [Optional: Contextual H4 Title for Outlook, e.g., "What's Next on the Horizon?"]
[Optional: 1-2 paragraphs on future developments.]

#### [Optional: Frequently Asked Questions]
[If generating FAQs, use this exact H4 title "Frequently Asked Questions". Generate 3-5 relevant Q&As if the topic is complex, or 2-3 if less content is available. Use the HTML structure below.]
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">Question 1 related to the article?</summary>
    <div class="faq-answer-content">
      <p>Concise answer to question 1.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Another relevant question?</summary>
    <div class="faq-answer-content">
      <p>Detailed answer to question 2.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">A third question if applicable?</summary>
    <div class="faq-answer-content">
      <p>Answer to the third question.</p>
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
  "author": {{ "@type": "Person", "name": "{author_name}" }},
  "publisher": {{
    "@type": "Organization",
    "name": "{your_website_name}",
    "logo": {{ "@type": "ImageObject", "url": "{your_website_logo_url}" }}
  }}
}}
</script>
"""

# --- API Call Function (remains the same) ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY environment variable not set.")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Accept": "application/json"
        }
    payload = {
        "model": AGENT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
            ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
        }
    try:
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL}, max_tokens={max_tokens}, temp={temperature}).")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage')
        if usage: logger.debug(f"API Usage: Prompt={usage.get('prompt_tokens')}, Completion={usage.get('completion_tokens')}, Total={usage.get('total_tokens')}")

        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            return message_content.strip() if message_content else None
        else:
            logger.error(f"API response missing 'choices' or choices empty: {result}")
            return None
    except requests.exceptions.Timeout:
         logger.error(f"API request timed out after {API_TIMEOUT_SECONDS} seconds.")
         return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        if e.response is not None:
            logger.error(f"Response Status: {e.response.status_code}, Body: {e.response.text[:500]}")
        return None
    except json.JSONDecodeError as e:
        response_text = response.text if response else "N/A"
        logger.error(f"Failed to decode API JSON response: {e}. Response text: {response_text[:500]}...")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during API call: {e}")
        return None

# --- Parsing Function ---
def parse_seo_agent_response(response_text):
    parsed_data = {}
    errors = []

    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty response: {response_text or 'Empty response'}"
        logger.error(error_message)
        return None, error_message

    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("Missing 'Title Tag:' line.")

        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("Missing 'Meta Description:' line.")

        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else: errors.append("Missing 'SEO H1:' line.")
        
        script_match = re.search(r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{.*?\})\s*<\/script>', response_text, re.DOTALL | re.IGNORECASE)
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld'] = script_match.group(0).strip() # Save the whole script tag
            try: json.loads(json_content_str) # Validate JSON content
            except json.JSONDecodeError: errors.append("JSON-LD content invalid.")
        else: errors.append("Missing JSON-LD script block.")

        body_start_pattern = r"SEO H1:.*?[\r\n]+" 
        body_end_pattern = r"([\s\S]*?)(?=[\r\n]+\s*Source:|[\r\n]*\s*<script)"
        
        body_full_match = re.search(body_start_pattern + body_end_pattern, response_text, re.DOTALL | re.IGNORECASE)

        if body_full_match:
             body_content = body_full_match.group(1).strip()
             
             if not body_content.startswith("## "):
                 body_specific_match = re.search(r"SEO H1:.*?[\r\n]+(##\s+[\s\S]*?)(?=[\r\n]+\s*Source:|[\r\n]*\s*<script)", response_text, re.DOTALL | re.IGNORECASE)
                 if body_specific_match:
                     body_content = body_specific_match.group(1).strip()
                 else:
                     errors.append("Could not reliably find start of Article Body (## H1).")
                     body_content = ""

             parsed_data['generated_article_body_md'] = body_content

             if not re.search(r"###\s+.*", body_content) and "pros-cons-container" not in body_content and "faq-section" not in body_content :
                 logger.warning("Generated body might be missing main H3 analysis or structured sections.")
             if not body_content: errors.append("Extracted Article Body is empty.")
        else:
             errors.append("Could not extract Article Body content between SEO H1 and Source/Script.")


        if not parsed_data.get('generated_article_body_md') or not parsed_data.get('generated_seo_h1'):
            final_error_message = f"Critical parsing failure: Missing Article Body or SEO H1. Errors: {'; '.join(errors if errors else ['Unknown parsing issue'])}"
            logger.error(final_error_message)
            return None, final_error_message

        # Provide fallbacks if parsing fails for non-critical parts
        parsed_data.setdefault('generated_title_tag', parsed_data.get('generated_seo_h1', 'Error Title'))
        parsed_data.setdefault('generated_meta_description', 'Error Generating Description')
        parsed_data.setdefault('generated_json_ld', '<script type="application/ld+json">{}</script>')

        return parsed_data, ("; ".join(errors) if errors else None)

    except Exception as e:
        logger.exception(f"Critical unexpected error during SEO response parsing: {e}")
        return None, f"Parsing exception: {e}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')

    content_to_process = article_data.get('content_for_processing')
    if not content_to_process:
        error_msg = f"Missing 'content_for_processing' for SEO agent (ID: {article_id})."
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword')
    if not primary_keyword:
        error_msg = f"Missing primary_topic_keyword from filter_verdict for ID: {article_id}."
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data
        
    generated_tags = article_data.get('generated_tags', [])
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:3] # Top 3 different tags
    secondary_keywords_list_str = ", ".join(secondary_keywords)

    # Ensure all keywords are strings for JSON dump
    all_keywords = ([primary_keyword] if primary_keyword else []) + generated_tags
    all_keywords = [str(k).strip() for k in all_keywords if k and str(k).strip()] # Clean and ensure string
    all_generated_keywords_json = json.dumps(list(set(all_keywords))) # Unique keywords

    input_data_for_prompt = {
        "article_title": article_data['title'],
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data['link'],
        "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str,
        "article_image_url": article_data['selected_image_url'],
        "author_name": article_data.get('author', 'AI News Team'),
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json
    }
    
    # Check for None in critical prompt inputs
    critical_prompt_inputs = ['article_title', 'article_content_for_processing', 'source_article_url', 'target_keyword', 'article_image_url', 'current_date_iso', 'all_generated_keywords_json', 'your_website_name']
    if any(input_data_for_prompt.get(k) is None for k in critical_prompt_inputs):
        missing_data = [k for k in critical_prompt_inputs if input_data_for_prompt.get(k) is None]
        error_msg = f"Cannot run SEO agent for ID {article_id}, critical data for prompt is None: {missing_data}"
        logger.error(error_msg); article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    try:
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt template for ID {article_id}! Error: {e}")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"; return article_data

    logger.info(f"Running SEO article generator for article ID: {article_id} (Perfected SEO & Content)...")
    raw_response_content = call_deepseek_api(SEO_PROMPT_SYSTEM, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        error_msg = "API call failed or returned empty content for SEO generation."
        logger.error(f"{error_msg} (ID: {article_id}).")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    logger.debug(f"Raw SEO Agent Response for ID {article_id}:\n---\n{raw_response_content}\n---")
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg # This can be None if parsing was successful

    if parsed_results is None: # This means critical parsing failure
        logger.error(f"Failed to parse SEO agent response for ID {article_id}: {error_msg or 'Unknown parsing error'}")
        # Store raw response for debugging if parsing totally fails
        article_data['seo_agent_raw_response'] = raw_response_content
    elif error_msg: # Non-critical parsing errors (e.g., missing optional field but body/h1 okay)
        logger.warning(f"SEO agent parsing completed with non-critical errors for ID {article_id}: {error_msg}")
    else: # Fully successful
        logger.info(f"Successfully generated and parsed SEO content for ID: {article_id}.")
        # Update article title with SEO H1 if it's different and successfully generated
        if parsed_results.get('generated_seo_h1') and parsed_results['generated_seo_h1'] != article_data['title']:
            logger.info(f"Updating article title for ID {article_id} with generated SEO H1: '{parsed_results['generated_seo_h1']}'")
            article_data['title'] = parsed_results['generated_seo_h1']

    return article_data

# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    test_article_data_perfect_seo = {
        'id': 'example-seo-perfect-001',
        'title': "Nvidia Blackwell B200 GPU Announcement",
        'summary': "Nvidia CEO Jensen Huang announced the Blackwell B200 GPU at GTC, promising massive performance gains for AI training and inference.",
        'content_for_processing': """Nvidia's GTC conference today saw the unveiling of their next-generation AI powerhouse, the Blackwell B200 GPU. CEO Jensen Huang, during his keynote, highlighted the chip's capability to handle trillion-parameter scale AI models, a significant leap from previous generations. The B200 is built on a new architecture, reportedly TSMC's 3nm process, and packs an astounding 208 billion transistors. This allows for a substantial increase in raw compute power and memory bandwidth, critical for the ever-growing demands of large language models and complex AI workloads. Key features touted include a second-generation Transformer Engine with FP4 precision support, which Nvidia claims can double the effective compute and bandwidth for inference tasks. The new NVLink switch system allows up to 576 Blackwell GPUs to communicate as a single, unified compute instance. Huang stated, "Blackwell is not just a chip, it's a platform." Early partners like AWS, Google Cloud, and Microsoft Azure will deploy Blackwell systems. Availability is expected late 2024. Competitors AMD and Intel are also active.""",
        'link': "https://example.com/nvidia-blackwell-b200-perfected",
        'filter_verdict': {
            'importance_level': 'Breaking', 'topic': 'Hardware',
            'reasoning_summary': 'Major new GPU announcement.',
            'primary_topic_keyword': 'Nvidia Blackwell B200'
        },
        'selected_image_url': "https://via.placeholder.com/800x500.png?text=Nvidia+Blackwell+Perfected",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generated_tags': ["Nvidia", "Blackwell", "B200", "GPU", "AI Hardware", "GTC 2024", "Deep Learning", "TSMC", "Jensen Huang", "AI Chips"],
        'author': 'AI SEO Bot Test'
    }

    logger.info("\n--- Running SEO Agent Standalone Test (Perfected SEO & Content Structure) ---")
    result_data = run_seo_article_agent(test_article_data_perfect_seo.copy())

    print("\n--- Final Result Data (Perfected SEO Test) ---")
    if result_data and result_data.get('seo_agent_results'):
        print("\n--- Parsed SEO Results ---")
        print(f"Title Tag: {result_data['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Desc: {result_data['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1: {result_data['seo_agent_results'].get('generated_seo_h1')}")
        print(f"JSON-LD Present: {bool(result_data['seo_agent_results'].get('generated_json_ld'))}")
        print("\n--- Article Body Markdown (should contain HTML for Pros/Cons & FAQ) ---")
        print(result_data['seo_agent_results'].get('generated_article_body_md', ''))
        if result_data.get('seo_agent_error'):
            print(f"\nParsing Warning/Error: {result_data['seo_agent_error']}")
        print(f"\n--- Final Article Title (may be updated by SEO H1): {result_data.get('title')} ---")

    elif result_data and result_data.get('seo_agent_error'): # Critical error from agent or parsing
         print(f"\nSEO Agent FAILED. Error: {result_data.get('seo_agent_error')}")
         if 'seo_agent_raw_response' in result_data: print(f"\n--- Raw Response (Debug) ---\n{result_data['seo_agent_raw_response']}")
    else: print("\nSEO Agent FAILED critically or returned no data.")

    logger.info("\n--- SEO Agent Standalone Test Complete ---")
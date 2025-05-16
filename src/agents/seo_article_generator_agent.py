# src/agents/seo_article_generator_agent.py

import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone
from urllib.parse import urljoin

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
BASE_URL_FOR_CANONICAL = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com')

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 8000
TEMPERATURE = 0.7 # Slightly increased for more creative structuring
API_TIMEOUT_SECONDS = 450

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Elite SEO Content Architect and Master Tech Journalist** for `{YOUR_WEBSITE_NAME}`. Your mission is to transform the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into an **exceptionally comprehensive, highly engaging, visually structured, factually precise, and SEO-dominant news article (target 800-1500 words for the main body)**. Your output must be indistinguishable from premier human journalism, rich in detail, analysis, and diverse content presentation. Avoid AI clichés (see forbidden list). Adhere with absolute precision to ALL directives.

**I. Core Principles (Mandatory):**
1.  **Source Synthesis & Profound Expansion:** The article MUST be primarily based on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. **Massively expand** on this by integrating relevant historical context, detailed technical explanations (if applicable), comparative analyses with competing/similar technologies or events, insightful future implications, and expert commentary (conceptualized, not invented). **NEVER invent facts, quotes, statistics, or events.** Your role is to synthesize and enrich, creating a definitive resource.
2.  **Target Audience & Sophisticated Tone:** Address tech-savvy professionals, researchers, developers, and enthusiasts. Assume a high level of baseline knowledge but elucidate extremely niche concepts with clarity (ELI5 if needed for a complex part). The tone must be sophisticated, deeply analytical, authoritative, yet highly engaging and accessible. Employ varied sentence structures, rich vocabulary, and natural contractions.
3.  **E-E-A-T Supremacy:** Demonstrate profound Experience, Expertise, Authoritativeness, and Trustworthiness. Ground all claims meticulously in the provided source, augmenting with widely accepted, verifiable general knowledge. Ensure impeccable accuracy. Attribute implicitly or explicitly as appropriate.
4.  **Helpful, Visually Rich Content:** The article must be the most helpful resource on this specific topic. SEO elements must serve readability and user experience. **Crucially, use diverse Markdown elements to structure content visually and improve scannability.** This includes Markdown tables for comparisons/data, blockquotes for emphasis or conceptual quotes, ordered/unordered lists for steps/features, and fenced code blocks for any code examples or technical snippets if relevant.

**II. Advanced SEO & Content Strategy:**
5.  **Strategic Keyword Weaving:**
    *   Integrate `{{TARGET_KEYWORD}}` (primary) naturally and prominently in: Title Tag, Meta Description, SEO H1, the introductory paragraphs (first ~100-150 words), at least two H3 subheadings, and conceptually within image alt text descriptions (you describe the ideal alt text).
    *   If `{{SECONDARY_KEYWORDS_LIST_STR}}` is provided, weave 3-5 of these secondary keywords naturally throughout the body, subheadings (H3/H4), lists, and table captions/content if applicable.
    *   **LSI & Thematic Depth:** Incorporate a rich tapestry of Latent Semantic Indexing (LSI) keywords, synonyms, and related entities. Build thematic clusters around core concepts discussed in the source.
    *   **NO KEYWORD STUFFING.** Prioritize natural language and semantic relevance.
6.  **Compelling SEO Title/H1 (Absolute Priority):**
    *   **SEO H1 (preamble):** Must be **exceptionally compelling, clear, benefit-driven, and click-worthy**. It MUST feature the main subject/product and `{{TARGET_KEYWORD}}`. Use power words.
    *   **Title Case (Strict):** Both SEO H1 and Title Tag MUST use Title Case.
    *   **Intrigue & Value Proposition:** Clearly communicate the significance or core value to the reader.
7.  **Placeholder-Based Linking Strategy (To be processed by Python later):**
    *   **Internal Links:** Identify 3-5 opportunities for highly contextual internal links to related topics/concepts. Format strictly as: `[[Link Text Describing Target Content | Optional Topic Name or Slug for Dacoola]]`. Example: `[[Deep Dive into RAG Architectures | RAG Systems]]` or `[[Learn more about LLM Scaling]]`. If no `| part` is given, the Link Text will be used to derive a slug.
    *   **External Links:** Identify 1-3 opportunities for contextual external links to *non-competing, high-authority* sources (e.g., research papers, official documentation, reputable statistics sites) that substantiate a claim or provide significant additional value. Format strictly as: `((Link Text Describing External Source | https://authoritative.example.com/relevant-page))`.
    *   Integrate these placeholders naturally within paragraphs. The link text must be descriptive and flow with the sentence.
8.  **Visual Element Integration (Conceptual via Markdown):**
    *   **Markdown Tables:** If the content involves comparisons, specifications, data points, or feature lists, **YOU MUST present this information using a well-structured Markdown table.** Make it clear and easy to read.
    *   **Markdown Blockquotes:** Use for emphasizing key statements, conceptual expert opinions (e.g., "Industry analyst John Doe noted, '> This development is a paradigm shift.'"), or significant excerpts.
    *   **Markdown Lists:** Use ordered (`1. ...`) and unordered (`* ...` or `- ...`) lists extensively for features, steps, pros, cons (if not using HTML snippet), or key takeaways.
    *   **Markdown Fenced Code Blocks:** If `{{ARTICLE_CONTENT_FOR_PROCESSING}}` includes or implies code snippets, technical configurations, or pseudo-code, represent them accurately using Markdown fenced code blocks (e.g., ```python ... ```).
    *   The goal is to break up large text blocks and present information in diverse, digestible formats.

**III. Strict Content Generation & Formatting Directives (NON-NEGOTIABLE):**
9.  **MAIN BODY IS MARKDOWN - REPEAT: MAIN BODY IS MARKDOWN:**
    *   ALL general text, ALL H3/H4/H5 headings, ALL paragraphs, ALL standard lists, ALL tables, ALL blockquotes, ALL code blocks that are NOT part of the specific "Pros & Cons" or "Frequently Asked Questions" HTML snippets **MUST BE IN STANDARD MARKDOWN SYNTAX.**
    *   **DO NOT USE HTML TAGS LIKE `<p>`, `<h3>`, `<h4>`, `<h5>`, `<ul>`, `<li>`, `<table>`, `<blockquote>`, `<pre>` FOR THIS GENERAL BODY CONTENT.** Use Markdown equivalents.
    *   **FAILURE TO ADHERE TO THIS MARKDOWN-ONLY RULE FOR THE MAIN BODY WILL RESULT IN AN UNUSABLE ARTICLE. THE SYSTEM WILL NOT CORRECT HTML TAGS IN THE MAIN BODY.**
10. **Introduction (Markdown):** 2-3 impactful lead paragraphs (100-150 words) summarizing the core news, its immediate significance, and a hook. Include `{{TARGET_KEYWORD}}` naturally. **NO H1 (`#` or `##`) in this Markdown body.**
11. **In-Depth Thematic Sections (Markdown):** At least **4-5 distinct `### H3` sections** for a comprehensive article. Each H3 section should be a mini-essay on a key facet of the topic, containing 3-6 well-developed paragraphs, and incorporating Markdown tables, lists, blockquotes, or code blocks where they enhance clarity and visual appeal.
    *   Example H3 structures: "### Unpacking [Technology]: Architecture and Innovations", "### [Product/Event]: A Chronology of Development and Milestones (Use a list here)", "### Comparative Analysis: [Product] vs. [Competitors] (Use a Markdown table here)", "### Real-World Impact: Use Cases and Sector Disruption", "### Expert Perspectives and Industry Reactions (Use blockquotes for conceptual quotes)", "### Technical Deep Dive: Challenges and Solutions in [Specific Area] (Use code blocks if applicable)", "### The Road Ahead: Future Trajectory and Unanswered Questions".
    *   Under H3s, use `#### H4` or `##### H5` for more granular points, each with 1-3 paragraphs, also in Markdown and using visual elements if appropriate.
12. **Pros & Cons (HTML Snippet - Conditional):** Generate **ONLY IF** the source clearly presents distinct, significant pros & cons. Aim for 3-5 points each. **Omit entirely otherwise.** If included, use Markdown `#### Pros and Cons` heading, followed *immediately* by the HTML snippet from user prompt.
13. **In-Article Ad Placeholder (HTML Comment):** After the introduction (2-3 paragraphs) and before the first `### H3`, insert: `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` (ONCE ONLY).
14. **FAQ (HTML Snippet - Conditional):** Generate **ONLY IF** topic warrants 3-5 insightful Q&As beyond main content. **Omit entirely otherwise.** If included, use Markdown `#### Frequently Asked Questions` heading, followed *immediately* by the HTML snippet from user prompt.
15. **Conclusion (Markdown):** A final `### H3` (e.g., "### Concluding Analysis: Navigating the Evolving Landscape of [Topic]") with 2-3 paragraphs summarizing key takeaways and offering a final, impactful insight.
16. **Overall Length & Quality:** Target **800-1500 words** for the main article body. It must be exceptionally well-written, analytical, and provide unique value.

**IV. Journalistic Style & Anti-AI Cliché Mandate:**
17. **Analytical Depth & Originality:** Offer critical analysis, synthesize complex information, and provide a unique, expert perspective.
18. **Sophisticated Language:** Use rich vocabulary, varied sentence structures, and precise terminology.
19. **Active Voice & Strong Verbs:** Prioritize for clarity and impact.
20. **Illustrative Content:** Use conceptual examples, data points (if derivable from source), and vivid language.
21. **Flow & Cohesion:** Ensure seamless transitions. Read aloud to verify natural cadence. Use standard hyphens (-).
22. **STRICTLY FORBIDDEN PHRASES:** "delve into," "the landscape of," "ever-evolving," "testament to," "pivotal role," "robust," "seamless," "leverage," "game-changer," "in the realm of," "it's clear that," "looking ahead," "moreover," "furthermore," "in conclusion," "unveiled," "marked a significant," "the advent of," "it is worth noting," "needless to say," "at the end of the day," "all in all," "in a nutshell," "pave the way." Use synonyms or rephrase.

**V. Output Format (ABSOLUTE PRECISION REQUIRED):**
23. **MAIN BODY IS MARKDOWN - REITERATED FOR EMPHASIS. NO HTML TAGS FOR PARAGRAPHS, HEADINGS, LISTS, TABLES, BLOCKQUOTES, CODE BLOCKS IN THE MAIN BODY FLOW.**
24. **HTML Snippets ONLY for Pros/Cons & FAQ (if generated), as specified.**
25. **Exact Output Order:**
    Title Tag: [Generated Title Tag]
    Meta Description: [Generated Meta Description]
    SEO H1: [Generated SEO H1]

    {**MARKDOWN** Article Body - NO `# H1` or `## H2` at start. May include HTML snippets for Pros/Cons, FAQ. Must include ad placeholder. Must use diverse Markdown elements like tables, lists, blockquotes, code blocks where appropriate.}
    Source: [{ARTICLE_TITLE_FROM_SOURCE}]({SOURCE_ARTICLE_URL})

    <script type="application/ld+json">
    {{JSON-LD content as specified, including wordCount and articleBody (plain text)}}
    </script>
26. **JSON-LD:** Populate `NewsArticle` schema completely. `headline` matches SEO H1. `keywords` from `{{ALL_GENERATED_KEYWORDS_JSON}}`. `mainEntityOfPage.@id` uses `{{MY_CANONICAL_URL_PLACEHOLDER}}`. **Include `articleBody` (plain text, max 2500 chars, stripped of all Markdown/HTML) and `wordCount` (approx. count of generated Markdown body).**

**VII. Final Self-Correction:** Review ALL constraints. Verify Markdown purity for the main body. Confirm diverse Markdown element usage. Ensure no forbidden phrases. Check output order.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate the Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (primarily in **Markdown**, utilizing diverse elements like tables, lists, blockquotes, and code blocks; specific HTML snippets for Pros/Cons & FAQ if included; HTML comment for ad placeholder), and JSON-LD Script. Follow ALL System Prompt directives meticulously, especially the **Markdown-only rule for general body text/headings** and the **800-1500 word length and diverse Markdown element usage requirements**.

**Key Focus for this Task:**
1.  **Advanced Content Generation:** Produce a long-form (800-1500 words), deeply analytical article. **Actively use various Markdown elements**:
    *   **Markdown Tables:** For comparisons, specifications, data. Example:
        ```markdown
        | Feature         | Model A | Model B |
        |-----------------|---------|---------|
        | Parameters      | 100B    | 120B    |
        | Training Data   | 10T     | 12T     |
        ```
    *   **Markdown Blockquotes:** For emphasis or conceptual quotes. Example: `> This is a key takeaway.`
    *   **Markdown Lists (Ordered/Unordered):** For steps, features, points.
    *   **Markdown Fenced Code Blocks:** For code, technical snippets. Example:
        ```python
        def example_func():
            print("Hello")
        ```
2.  **Title & H1:** Compelling, SEO-friendly, Title Case, including main subject & `{{TARGET_KEYWORD}}`.
3.  **Formatting (ABSOLUTE - Refer to System Prompt Section V):**
    *   Main article content (paragraphs, H3/H4/H5, lists, tables, blockquotes, code blocks) **MUST BE MARKDOWN**.
    *   **NO HTML TAGS (`<p>`, `<h3>` etc.) FOR GENERAL BODY/HEADINGS.**
    *   Main body **MUST NOT** start with H1 (`#` or `##`).
    *   Ad placeholder `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` is mandatory.
    *   Pros/Cons & FAQ use exact HTML snippets from example, after their Markdown `####` headings.
    *   Omit optional sections (H4/H5, Pros/Cons, FAQ) if not robustly supported with detail.
    *   **Include at least 4-5 distinct `### H3` sections.**
4.  **Linking Placeholders:** Use `[[Internal Link Text | Optional Topic]]` and `((External Link Text | https://...))` as instructed.
5.  **JSON-LD:** Ensure `articleBody` (plain text, Markdown/HTML stripped, ~2500 char limit) and `wordCount` (of generated Markdown body) are included.

**Input Context:**
ARTICLE_TITLE_FROM_SOURCE: {article_title_from_source}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str}
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD_ISO: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json}
MY_CANONICAL_URL_PLACEHOLDER: {my_canonical_url_placeholder}

**Required Output Format (Strict Adherence - Note Markdown vs HTML):**
Title Tag: [Generated Title Tag]
Meta Description: [Generated Meta Description]
SEO H1: [Generated SEO H1]

[**MARKDOWN BODY START - NO H1/H2 HERE** Introduction: 2-3 paragraphs, approx 100-150 words. Journalistic, engaging. Use `{{TARGET_KEYWORD}}`.]

<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->

### [**MARKDOWN H3** - First Major Thematic Section Title - e.g., Unpacking the Core Technology]
[**MARKDOWN** - 3-6 paragraphs of deep analysis. Integrate diverse Markdown elements like lists, blockquotes, or even a small relevant code snippet if applicable. Incorporate keywords naturally. Use link placeholders `[[...]]` or `((...))` if context allows.]

#### [Optional **MARKDOWN H4** - Sub-topic under H3]
[**MARKDOWN** - 1-3 paragraphs.]

### [**MARKDOWN H3** - Second Major Thematic Section Title - e.g., Comparative Analysis and Market Positioning]
[**MARKDOWN** - 3-6 paragraphs. **USE A MARKDOWN TABLE HERE** if comparing features, products, or performance metrics. Example:
| Aspect          | {{TARGET_KEYWORD}} | Competitor X | Competitor Y |
|-----------------|--------------------|--------------|--------------|
| Performance     | High               | Medium       | High         |
| Key Feature     | XYZ                | ABC          | QWE          |
| Price (Concept) | Premium            | Mid-range    | Premium      |
Ensure table data is derived/inferred logically from `{{ARTICLE_CONTENT_FOR_PROCESSING}}` or is conceptual for illustration.
More paragraphs analyzing the table and market.]

### [**MARKDOWN H3** - Third Major Thematic Section Title - e.g., Implications and Future Outlook]
[**MARKDOWN** - 3-6 paragraphs discussing broader impacts, challenges, ethical points (if any), and future trends. Use lists or blockquotes for emphasis.]

### [**MARKDOWN H3** - Fourth Major Thematic Section Title (if content supports further distinct analysis)]
[**MARKDOWN** - 3-6 paragraphs.]

#### [Optional: Pros and Cons - Markdown `#### Pros and Cons` heading, then HTML snippet if generated]
#### Pros and Cons 
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Detailed explanation of the first significant advantage.</li>
        <li>Description of a second major pro, perhaps with an example.</li>
        <li>A third compelling benefit.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Description of a notable limitation or drawback.</li>
        <li>Further potential downside or area of concern.</li>
        <li>A third challenge or criticism.</li>
      </ul>
    </div>
  </div>
</div>

### [**MARKDOWN H3** - Concluding Section Title - e.g., Final Takeaways and The Path Forward]
[**MARKDOWN** - 2-3 paragraphs providing a summary of key insights and a strong concluding statement.]

#### [Optional: Frequently Asked Questions - Markdown `#### Frequently Asked Questions` heading, then HTML snippet if generated. 3-5 Q&As.]
#### Frequently Asked Questions
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">Insightful question derived from the article's content? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Comprehensive, factual answer based on the article and your expanded analysis.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Another nuanced question a reader might have? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Detailed response addressing the question thoroughly.</p>
    </div>
  </details>
</div>

Source: [{article_title_from_source}]({source_article_url})

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "[SEO H1 from preamble, verbatim]",
  "description": "[Generated meta description from above, verbatim]",
  "keywords": {all_generated_keywords_json},
  "mainEntityOfPage": {{ "@type": "WebPage", "@id": "{my_canonical_url_placeholder}" }},
  "image": {{ "@type": "ImageObject", "url": "{article_image_url}", "width": "1200", "height": "675" }},
  "datePublished": "{current_date_iso}",
  "dateModified": "{current_date_iso}",
  "author": {{ "@type": "Person", "name": "{author_name}" }},
  "publisher": {{
    "@type": "Organization",
    "name": "{your_website_name}",
    "logo": {{ "@type": "ImageObject", "url": "{your_website_logo_url}" }}
  }},
  "articleBody": "[PLAIN TEXT of the generated Markdown body, ALL MARKDOWN/HTML SYNTAX REMOVED. Only paragraph breaks retained. Max ~2500 characters. Example: Introduction text.\\n\\nSection 1 Title\\nParagraph 1 of section 1 text.\\nParagraph 2 of section 1 text.\\n\\nSection 2 Title\\n...]",
  "wordCount": "[Integer: Approximate word count of the generated Markdown article body (excluding this JSON-LD block and preamble).]"
}}
</script>
"""

# (Keep call_deepseek_api, parse_seo_agent_response, and run_seo_article_agent functions as they were in the previous version you approved,
# as they handle the API call and basic parsing of the preamble + body + JSON-LD structure.
# The key is that the LLM must now populate `articleBody` and `wordCount` in the JSON-LD it generates,
# and the main Markdown body should be richer.)

# --- API Call Function (remains unchanged from before) ---
def call_deepseek_api(system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE):
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set.")
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
        logger.debug(f"Sending SEO generation request (model: {AGENT_MODEL}). Est. User Prompt Tokens: ~{len(user_prompt)//3}")
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        result = response.json()
        usage = result.get('usage')
        if usage:
            logger.debug(f"API Usage: Prompt Tokens={usage.get('prompt_tokens')}, Completion Tokens={usage.get('completion_tokens')}, Total Tokens={usage.get('total_tokens')}")
        if result.get("choices") and len(result["choices"]) > 0:
            message_content = result["choices"][0].get("message", {}).get("content")
            if message_content:
                content_stripped = message_content.strip()
                if content_stripped.startswith("```") and content_stripped.endswith("```"): # Handle if LLM wraps in markdown code block
                    content_stripped = re.sub(r"^```(?:json|markdown)?\s*","", content_stripped, flags=re.IGNORECASE)
                    content_stripped = re.sub(r"\s*```$","", content_stripped)
                    content_stripped = content_stripped.strip()
                content_stripped = content_stripped.replace('—', '-')
                return content_stripped
            else:
                logger.error("API response 'content' is missing or empty.")
                return None
        else:
            logger.error(f"API response missing 'choices' or 'choices' list is empty: {result}")
            return None
    except requests.exceptions.Timeout:
        logger.error(f"API request timed out after {API_TIMEOUT_SECONDS} seconds.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during API call: {e}")
        return None

# --- Parsing Function (remains structurally similar, LLM populates new JSON-LD fields) ---
def parse_seo_agent_response(response_text):
    parsed_data = {}
    errors = []
    if not response_text or response_text.strip().startswith("Error:"):
        error_message = f"SEO Agent returned error or empty response: {response_text or 'Empty response'}"
        logger.error(error_message)
        return None, error_message

    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if title_match:
            parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else:
            errors.append("Missing 'Title Tag:' line.")

        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match:
            parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else:
            errors.append("Missing 'Meta Description:' line.")

        seo_h1_preamble_match = re.search(r"^\s*SEO H1:\s*(.*)", response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_preamble_match:
            parsed_data['generated_seo_h1'] = seo_h1_preamble_match.group(1).strip()
        else:
            errors.append("Missing 'SEO H1:' line in preamble.")

        script_match = re.search(
            r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>',
            response_text, re.IGNORECASE
        )
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld_raw'] = json_content_str
            parsed_data['generated_json_ld_full_script_tag'] = script_match.group(0).strip()
            try:
                # Basic validation by trying to load it (placeholders will be replaced later)
                # For articleBody, just check if the key exists, content can be complex
                temp_json_for_validation = json_content_str
                temp_json_for_validation = temp_json_for_validation.replace("{MY_CANONICAL_URL_PLACEHOLDER}", "https://example.com/placeholder")
                temp_json_for_validation = temp_json_for_validation.replace("{all_generated_keywords_json}", "[]")
                # Replace the articleBody and wordCount placeholders more robustly for validation
                temp_json_for_validation = re.sub(r'"articleBody":\s*"\[.*?\]"', '"articleBody": "Sample body."', temp_json_for_validation)
                temp_json_for_validation = re.sub(r'"wordCount":\s*"\[.*?\]"', '"wordCount": "0"', temp_json_for_validation)

                loaded_json = json.loads(temp_json_for_validation)
                if "articleBody" not in loaded_json: errors.append("JSON-LD likely missing 'articleBody'.")
                if "wordCount" not in loaded_json: errors.append("JSON-LD likely missing 'wordCount'.")

            except json.JSONDecodeError as json_err:
                errors.append(f"JSON-LD content is invalid: {json_err}")
                logger.warning(f"Invalid JSON-LD detected (raw content for validation): {json_content_str[:300]}...")
        else:
            errors.append("Missing or malformed JSON-LD script block.")

        body_content = None
        if seo_h1_preamble_match:
            body_start_offset = seo_h1_preamble_match.end()
            end_delimiters_pattern = r"(?:\n\s*Source:|\n\s*<script\s+type\s*=\s*[\"']application/ld\+json[\"'])"
            end_match = re.search(end_delimiters_pattern, response_text[body_start_offset:], re.MULTILINE | re.IGNORECASE)

            if end_match:
                body_content = response_text[body_start_offset : body_start_offset + end_match.start()].strip()
            else:
                potential_body = response_text[body_start_offset:].strip()
                if parsed_data.get('generated_json_ld_full_script_tag') and potential_body.endswith(parsed_data['generated_json_ld_full_script_tag']):
                    body_content = potential_body[:-len(parsed_data['generated_json_ld_full_script_tag'])].strip()
                else: body_content = potential_body
                if "\nSource:" in body_content: body_content = body_content.split("\nSource:", 1)[0].strip()
                if body_content: logger.warning("Body extraction: No clear 'Source:' or '<script' delimiter found. Relied on greedy match.")
                else: errors.append("Body extraction: Could not find end delimiter and greedy match failed.")
        else:
            errors.append("Could not find 'SEO H1:' preamble line, cannot reliably locate article body start.")

        if body_content:
            if body_content.lstrip().startswith("## ") or body_content.lstrip().startswith("# "):
                body_content = re.sub(r"^\s*#{1,2}\s*.*?\n", "", body_content, count=1, flags=re.IGNORECASE).lstrip()
                logger.info("Removed H1/H2 (##/#) line from the start of the Markdown body as per new logic.")
            parsed_data['generated_article_body_md'] = body_content
        else:
            errors.append("Article Body content is empty after extraction attempts.")
            parsed_data['generated_article_body_md'] = ""

        if not parsed_data.get('generated_seo_h1'):
            errors.append("CRITICAL: SEO H1 could not be determined from preamble.")
            parsed_data['generated_seo_h1'] = "Error: H1 Missing - Check LLM Response"
        if not parsed_data.get('generated_title_tag'):
            parsed_data['generated_title_tag'] = parsed_data.get('generated_seo_h1', 'Error: Title Missing')
        if not parsed_data.get('generated_meta_description'):
            parsed_data['generated_meta_description'] = "Read the latest AI and Technology news from " + YOUR_WEBSITE_NAME
        if not parsed_data.get('generated_json_ld_raw'):
             parsed_data['generated_json_ld_raw'] = '{}'
             parsed_data['generated_json_ld_full_script_tag'] = '<script type="application/ld+json">{}</script>'

        if not parsed_data.get('generated_article_body_md') or "Error: H1 Missing" in parsed_data.get('generated_seo_h1', ''):
            final_error_message = f"Critical parsing failure: Body is empty or H1 from preamble is missing/invalid. Errors: {'; '.join(errors if errors else ['Unknown parsing error'])}"
            logger.error(final_error_message)
            return None, final_error_message

        return parsed_data, ("; ".join(errors) if errors else None)

    except Exception as e:
        logger.exception(f"Critical parsing exception: {e}")
        return None, f"Major parsing exception: {e}"

# --- Main Agent Function ---
def run_seo_article_agent(article_data):
    article_id = article_data.get('id', 'N/A')
    content_to_process = article_data.get('content_for_processing')

    if not content_to_process:
        error_msg = f"Missing 'content_for_processing' for article ID {article_id}."
        logger.error(error_msg)
        article_data['seo_agent_results'] = None
        article_data['seo_agent_error'] = error_msg
        return article_data

    primary_keyword = article_data.get('filter_verdict', {}).get('primary_topic_keyword', article_data.get('title', 'Untitled Article'))
    article_data['primary_keyword'] = primary_keyword

    generated_tags = article_data.get('researched_keywords', [primary_keyword])
    secondary_keywords = [tag for tag in generated_tags if tag.lower() != primary_keyword.lower()][:5]
    secondary_keywords_list_str = ", ".join(secondary_keywords)

    all_valid_keywords_for_json_ld = list(set([str(k).strip() for k in generated_tags if k and str(k).strip()]))
    all_generated_keywords_json = json.dumps(all_valid_keywords_for_json_ld)

    my_canonical_url_placeholder_value = f"{BASE_URL_FOR_CANONICAL.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"

    input_data_for_prompt = {
        "article_title_from_source": article_data.get('title', 'Untitled Article'),
        "article_content_for_processing": content_to_process,
        "source_article_url": article_data.get('link', '#'),
        "target_keyword": primary_keyword,
        "secondary_keywords_list_str": secondary_keywords_list_str,
        "article_image_url": article_data.get('selected_image_url', ''),
        "author_name": article_data.get('author', YOUR_WEBSITE_NAME),
        "current_date_iso": article_data.get('published_iso') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "your_website_name": YOUR_WEBSITE_NAME,
        "your_website_logo_url": YOUR_WEBSITE_LOGO_URL,
        "all_generated_keywords_json": all_generated_keywords_json,
        "my_canonical_url_placeholder": my_canonical_url_placeholder_value
    }
    for key, value in input_data_for_prompt.items():
        if value is None: input_data_for_prompt[key] = ''

    try:
        formatted_system_prompt = SEO_PROMPT_SYSTEM.replace("{YOUR_WEBSITE_NAME}", input_data_for_prompt["your_website_name"])
        user_prompt = SEO_PROMPT_USER_TEMPLATE.format(**input_data_for_prompt)
    except KeyError as e:
        logger.exception(f"KeyError formatting SEO prompt for article {article_id}: {e}.")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = f"Prompt template formatting error: {e}"; return article_data

    logger.info(f"Running SEO agent for article ID: {article_id} ('{input_data_for_prompt['article_title_from_source'][:50]}...'). This may take some time.")
    raw_response_content = call_deepseek_api(formatted_system_prompt, user_prompt, max_tokens=MAX_TOKENS_RESPONSE, temperature=TEMPERATURE)

    if not raw_response_content:
        error_msg = "SEO Agent API call failed or returned empty/invalid content."
        logger.error(f"{error_msg} (Article ID: {article_id}).")
        article_data['seo_agent_results'] = None; article_data['seo_agent_error'] = error_msg; return article_data

    logger.debug(f"Raw SEO Agent Response for {article_id} (first 500 chars for review):\n{raw_response_content[:500]}...")
    parsed_results, error_msg = parse_seo_agent_response(raw_response_content)

    article_data['seo_agent_results'] = parsed_results
    article_data['seo_agent_error'] = error_msg

    if parsed_results is None:
        logger.error(f"Completely FAILED to parse SEO agent response for {article_id}: {error_msg}")
        article_data['seo_agent_raw_response_on_parse_fail'] = raw_response_content
    elif error_msg:
        logger.warning(f"SEO parsing for {article_id} completed with non-critical errors/warnings: {error_msg}")
    else:
        logger.info(f"Successfully generated and parsed SEO content for {article_id}.")

    if parsed_results and parsed_results.get('generated_seo_h1') and "Error: H1 Missing" not in parsed_results['generated_seo_h1']:
        new_title = parsed_results['generated_seo_h1']
        if article_data.get('title') != new_title:
            logger.info(f"Updating article title for {article_id} with generated SEO H1: '{new_title}' (was: '{article_data.get('title')}')")
            article_data['title'] = new_title
    elif not article_data.get('title'):
        article_data['title'] = "Untitled Article - SEO Processing Error"
    return article_data


# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    # ... (standalone test code remains the same as previous version)
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    if not DEEPSEEK_API_KEY:
        logger.error("CRITICAL FOR STANDALONE TEST: DEEPSEEK_API_KEY env var not set.")
        sys.exit(1)

    test_article = {
        'id': 'test-seo-rich-md-001',
        'title': "NVIDIA Unveils 'Hyperion' AI Chip: Quantum Leap in Processing Power",
        'content_for_processing': """
NVIDIA's CEO Jensen Huang today announced their new 'Hyperion' AI accelerator architecture during the company's annual GTC conference.
Huang described Hyperion as a "five-year leap" in AI processing, promising unprecedented performance for training and inferencing next-generation large language models and complex scientific simulations.
The architecture features a novel chiplet design, integrating dedicated cores for tensor operations, generative AI tasks, and high-speed interconnects.
Early benchmarks showcased by NVIDIA claim Hyperion offers up to 7x the performance of their previous flagship, the H200, in specific AI workloads and up to 10x improvement in energy efficiency. Key specifications: 1.5 Trillion transistors, 2TB/s HBM3e memory bandwidth. Competitor X has 1.2T transistors and 1.5TB/s.
"Hyperion is not just a chip; it's a new computing platform built for the age of generative AI," Huang stated.
The first products based on Hyperion are expected to ship to select cloud providers and enterprise partners in Q4 2025, with broader availability in early 2026.
Key partners like Microsoft Azure, Google Cloud, and AWS have already announced plans to incorporate Hyperion into their AI infrastructure.
The announcement also detailed advancements in NVIDIA's software stack, including new cuDNN libraries and Triton Inference Server optimizations specifically for Hyperion. Example: `result = hyperion_process(data)`.
Industry analysts are lauding the announcement as a significant move to solidify NVIDIA's dominance in the AI hardware market, though some express concerns about pricing and accessibility.
The chip utilizes TSMC's next-generation 2nm process node. Huang also touched upon the extensive cooling solutions required for the new DGX Hyperion systems.
A major focus was on its capability to train trillion-parameter models more efficiently than ever before.
The Hyperion platform also introduces enhanced security features at the hardware level to protect AI models and data.
Advantages include: Faster training, better inference, improved energy use. Disadvantages: High cost, new cooling needs.
FAQ: Q1: What is Hyperion? A1: NVIDIA's new AI chip. Q2: When is it available? A2: Q4 2025 for partners.
        """,
        'link': "https://www.example-ai-news.com/nvidia-hyperion-chip-gtc",
        'selected_image_url': "https://www.example-ai-news.com/images/nvidia-hyperion.jpg",
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'author': "Tech Analyst Pro",
        'filter_verdict': {'primary_topic_keyword': "NVIDIA Hyperion AI Chip"},
        'researched_keywords': [
            "NVIDIA Hyperion AI Chip", "NVIDIA GTC announcement", "next-gen AI accelerator", "Jensen Huang NVIDIA",
            "AI processing power", "Hyperion chip architecture", "chiplet design AI", "DGX Hyperion systems",
            "TSMC 2nm process", "AI hardware market", "trillion parameter models", "generative AI hardware",
            "NVIDIA H200 successor", "AI energy efficiency", "cuDNN Hyperion"
        ]
    }

    logger.info("\n--- Running SEO Article Agent Standalone Test (Rich Markdown Request) ---")
    result_article = run_seo_article_agent(test_article.copy())

    if result_article.get('seo_agent_results'):
        print("\n\n--- Generated SEO Content ---")
        print(f"Title Tag: {result_article['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Description: {result_article['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1 (Preamble): {result_article['seo_agent_results'].get('generated_seo_h1')}")
        print(f"Final Article Title in data: {result_article.get('title')}")

        md_body = result_article['seo_agent_results'].get('generated_article_body_md', '')
        word_count = len(md_body.split())
        print(f"\n--- Article Body (Should be Rich Markdown, NO H1, target 800-1500 words. Actual: ~{word_count} words) ---")
        if len(md_body) > 2000: print(md_body[:1000] + "\n...\n" + md_body[-1000:])
        else: print(md_body)

        if "| Parameter" in md_body and "| ---" in md_body : print("\nSUCCESS: Markdown table detected in body.")
        else: print("\nWARNING: Markdown table NOT detected or malformed.")
        if "```" in md_body: print("SUCCESS: Markdown code block detected.")
        else: print("INFO: No Markdown code block in this example (may be fine).")
        if "\n> " in md_body: print("SUCCESS: Markdown blockquote detected.")
        else: print("INFO: No Markdown blockquote in this example (may be fine).")


        if "<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->" in md_body: print("SUCCESS: In-article ad placeholder found.")
        else: print("WARNING: In-article ad placeholder NOT found.")

        json_ld_script_tag = result_article['seo_agent_results'].get('generated_json_ld_full_script_tag', '')
        print(f"\n--- JSON-LD Script ---")
        if "{MY_CANONICAL_URL_PLACEHOLDER}" in json_ld_script_tag: print("SUCCESS: Canonical placeholder found in JSON-LD.")
        else: logger.warning("Canonical placeholder NOT found in JSON-LD.")
        if "\"articleBody\":" in json_ld_script_tag and "\"wordCount\":" in json_ld_script_tag: print("SUCCESS: articleBody and wordCount found in JSON-LD.")
        else: logger.warning("articleBody or wordCount might be missing from JSON-LD.")

        if result_article.get('seo_agent_error'): print(f"\nParsing/Validation Warnings/Errors: {result_article['seo_agent_error']}")
    else:
        print("\n--- SEO Agent FAILED ---")
        print(f"Error: {result_article.get('seo_agent_error')}")
        if result_article.get('seo_agent_raw_response_on_parse_fail'):
            print(f"\n--- Raw Response on Parse Failure (first 500 chars) ---")
            print(result_article['seo_agent_raw_response_on_parse_fail'][:500] + "...")

    logger.info("\n--- SEO Article Agent Standalone Test Complete ---")
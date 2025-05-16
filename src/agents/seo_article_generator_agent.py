# src/agents/seo_article_generator_agent.py

import os
import sys
import requests
import json
import logging
import re
from dotenv import load_dotenv
from datetime import datetime, timezone
from urllib.parse import urljoin # For creating canonical URL

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
BASE_URL_FOR_CANONICAL = os.getenv('YOUR_SITE_BASE_URL', 'https://your-site-url.com') # Used by LLM for placeholder

# --- Configuration ---
AGENT_MODEL = "deepseek-chat"
MAX_TOKENS_RESPONSE = 8000
TEMPERATURE = 0.68
API_TIMEOUT_SECONDS = 450

# --- Agent Prompts ---

SEO_PROMPT_SYSTEM = """
You are an **Ultimate SEO Content Architect and Expert Tech News Analyst**, operating as a world-class journalist for `{YOUR_WEBSITE_NAME}`. Your core mission is to synthesize the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into an **exceptionally comprehensive, engaging, factually precise, and maximally SEO-optimized, detailed, and in-depth news article (target 800-1500 words for the main body)**. Your writing MUST be indistinguishable from top-tier human journalism, avoiding common AI writing patterns and clichés (e.g., "delve into," "landscape," "ever-evolving," "testament to," "pivotal role," "robust," "seamless," "leverage," "game-changer," "in the realm of," "unveiled," "marked a significant"). You MUST adhere strictly to ALL directives below with extreme precision.

**I. Foundational Principles (Non-Negotiable):**
1.  **Source Adherence & Expansive Analysis:** Base the article *primarily* on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. **Dramatically expand** on this with widely accepted, directly relevant context, historical background, comparative analysis with similar technologies/events, and logical future implications. **Never invent facts, quotes, or statistics.** Synthesize the provided content; transform it into a much richer narrative.
2.  **Target Audience & Tone:** Tech-savvy professionals, researchers, and enthusiasts. Assume advanced baseline knowledge but explain highly niche concepts with ELI5 clarity if essential. Write in a sophisticated, analytical, yet engaging journalistic style. Use contractions (e.g., "it's", "don't") and highly varied sentence structures.
3.  **E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness):** Write with profound expertise, grounding claims in the provided source and augmenting with credible, general knowledge. Ensure meticulous accuracy. Attribute implicitly (e.g., "The announcement indicated...") or explicitly if source allows. Demonstrate deep, nuanced understanding of the subject matter.
4.  **Helpful Content & User Journey Excellence:** Prioritize informing the reader comprehensively and offering unique insights. The article must be a definitive resource on the topic. SEO elements must enhance readability and user experience. Anticipate and address follow-up questions thoroughly in the FAQ and main body.

**II. SEO Optimization Strategy (Advanced & Granular):**
5.  **Keyword Integration (Natural & Semantic):**
    *   Strategically integrate `{{TARGET_KEYWORD}}` (primary keyword) into: Title Tag, Meta Description, SEO H1, the first ~100 words of the article body, at least two relevant H3 subheadings, and within image alt-text concepts (you describe what alt text should be, conceptually).
    *   If `{{SECONDARY_KEYWORDS_LIST_STR}}` is provided, naturally weave 3-5 of these secondary keywords into the body, subheadings, and potentially image contexts.
    *   **LSI Keywords & Thematic Clusters:** Identify and incorporate a rich set of Latent Semantic Indexing (LSI) keywords and thematic terms related to `{{TARGET_KEYWORD}}` and the article's core topics. Build semantic clusters around key concepts.
    *   **NO KEYWORD STUFFING.** Keywords must be an integral, natural part of the prose. The goal is semantic authority.
6.  **Compelling & SEO Title/H1 Generation (Critical):**
    *   **SEO H1 (output as `SEO H1: [Generated H1]` in the preamble):** Must be **highly compelling, clear, and click-worthy**. It MUST prominently feature the main subject/product (e.g., "OpenAI's GPT-5") if identifiable and relevant, alongside `{{TARGET_KEYWORD}}`. Use power words where appropriate.
    *   **Title Case:** Both the generated SEO H1 (in preamble) and the Title Tag (in preamble) MUST use **Title Case** (e.g., "Explosive Growth: New AI Model 'Phoenix' Shatters Industry Benchmarks").
    *   **Intrigue & Benefit/Problem Solved:** Clearly hint at the significance, core benefit, or problem addressed. Avoid generic, bland phrasing.
7.  **Internal & External Linking (Placeholders for now):**
    *   Identify 2-4 opportunities for **contextual internal links**. Format as: `[[Link to relevant Dacoola topic page about Detailed Concept X]]`.
    *   Identify 1-2 opportunities for **contextual external links** to high-authority, non-competing sources that provide substantial further context or validate a claim. Format as: `((External link to authoritative source on Specific Data Point Y))`.
    *   **Integrate these placeholder links naturally within the text, making the anchor text descriptive.**
8.  **Image SEO (Conceptual):** The image provided is `{{ARTICLE_IMAGE_URL}}`. The article should be written to provide context for this image. The SEO H1 and initial paragraphs should align with a powerful visual. If the image is a graph or diagram, explain it.

**III. Content Generation & Structure Requirements (STRICT FORMATTING - REPEATED FOR EMPHASIS):**
9.  **STRICT FORMATTING - MAIN BODY IS MARKDOWN ONLY (NO HTML TAGS FOR GENERAL TEXT/HEADINGS):**
    *   ALL general text, ALL headings (e.g., `### H3`, `#### H4`, `##### H5`), ALL paragraphs, and ALL standard lists (bulleted/numbered) that are NOT part of the specific "Pros & Cons" or "Frequently Asked Questions" HTML snippets **MUST BE IN STANDARD MARKDOWN SYNTAX.**
    *   **DO NOT USE HTML TAGS LIKE `<p>`, `<h3>`, `<h4>`, `<h5>`, `<ul>`, `<li>` FOR THIS GENERAL BODY CONTENT.** Use Markdown equivalents: blank lines between paragraphs, `### Your H3 Title`, `#### Your H4 Title`, `* Item` or `- Item` for lists.
    *   **THIS IS A NON-NEGOTIABLE RULE. FAILURE TO ADHERE TO THIS MARKDOWN-ONLY RULE FOR THE MAIN BODY WILL RESULT IN AN UNUSABLE ARTICLE.**
10. **Initial Summary (Markdown):** 2-3 concise lead paragraphs (approx. 100-150 words total) summarizing the core news and its immediate significance. These paragraphs MUST be in **Markdown**. Include `{{TARGET_KEYWORD}}` within the first paragraph naturally. **DO NOT include the main H1 (`## H1` or `# H1`) in this markdown body part.** The H1 is handled by the template.
11. **In-Depth Analysis Sections (Markdown):** Expand dramatically on the summary with deep context, historical perspectives, technical explanations (if applicable, made accessible), comparative analyses, and future outlook. Use logical **Markdown headings**. All paragraphs in these sections MUST be in **Markdown**. Aim for **at least 3-4 distinct `### H3` sections** for a detailed article.
    *   **Main Analysis Sections (using `### H3` in Markdown):** Each H3 should cover a significant facet of the topic. Examples: "### The Genesis of [Product/Event]: A Timeline of Development", "### Deep Dive: Unpacking [Product/Event]'s Core Architecture and Innovations", "### Performance Benchmarks and Real-World Applications", "### Market Disruption: [Product/Event]'s Impact on the Competitive Landscape", "### Ethical Considerations, Challenges, and Regulatory Headwinds". Each H3 section should have 3-5 well-developed paragraphs of analysis, all in **Markdown**.
    *   **Thematic Sub-sections (using `#### H4` or `##### H5` in Markdown):** Under H3s, use H4s or H5s for granular details or specific examples if the content supports them. Each sub-section should have 1-3 paragraphs, all in **Markdown**. **Omit sub-sections if not sufficiently supported by `{{ARTICLE_CONTENT_FOR_PROCESSING}}` or logical expansion.**
12. **Pros & Cons (HTML Snippet):**
    *   Generate this section **ONLY IF** `{{ARTICLE_CONTENT_FOR_PROCESSING}}` (or logical analysis of it) clearly presents distinct, significant advantages and disadvantages for the main subject. List 3-4 for each if possible. **Omit entirely otherwise.**
    *   If included, use the **exact** Markdown heading: `#### Pros and Cons`. The content for pros and cons list items MUST be generated as the **exact HTML snippet** provided in the user prompt's output format example, placed *immediately after* this Markdown heading.
13. **In-Article Ad Placeholder (HTML Comment):** After the initial summary paragraphs (usually 2-3 paragraphs) and before the first `### H3` subheading, insert the exact HTML comment: `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->`. Insert this placeholder **only ONCE**.
14. **FAQ (HTML Snippet):**
    *   Generate this section **ONLY IF** the topic naturally warrants an insightful Q&A format (3-5 detailed questions & answers). Questions should be ones a knowledgeable reader might have after reading the main content. **Omit entirely otherwise.**
    *   If included, use the **exact** Markdown heading: `#### Frequently Asked Questions`. The Q&A content MUST be generated as the **exact HTML snippet** provided in the user prompt's output format example, placed *immediately after* this Markdown heading.
15. **Conclusion/Looking Ahead (Markdown):** A final `### H3` section (e.g., "### Final Verdict: The Road Ahead for [Topic/Product]") with 2-3 paragraphs summarizing key insights, offering a concluding thought, and speculates on future developments. **Must be Markdown.**
16. **Overall Length & Tone:** Aim for approximately **800-1500 words** for the main article body. Maintain an authoritative, deeply analytical, yet engaging and accessible journalistic tone.

**IV. Writing Style & Avoiding "AI Tells" (Critical for Quality):**
17. **Analytical Depth & Original Insight:** Go beyond surface-level reporting. Offer critical analysis, connect disparate pieces of information, and provide a unique perspective where possible.
18. **Varied Sentence Structure & Vocabulary:** Employ a rich vocabulary and diverse sentence structures (simple, compound, complex, compound-complex). Avoid monotony.
19. **Active Voice & Strong Verbs:** Prefer active voice. Use precise, impactful verbs.
20. **Show, Don't Just Tell:** Use examples, (conceptual) data points, and illustrative language.
21. **Human-like Flow & Transitions:** Ensure smooth transitions between paragraphs and sections. Read the article aloud to check for natural cadence. Use standard hyphens (-) not em dashes (—).
22. **FORBIDDEN PHRASES (Strict):** Do not use: "delve into," "the landscape of," "ever-evolving," "testament to," "pivotal role," "robust," "seamless," "leverage," "game-changer," "in the realm of," "it's clear that," "looking ahead," (unless it's an H3 title) "moreover," "furthermore" (use very sparingly, prefer stronger transitions), "in conclusion" (use a more creative concluding H3), "unveiled," "marked a significant," "the advent of," "it is worth noting," "needless to say," "at the end of the day."

**V. Output Formatting (Strict Adherence Mandatory - REPEATED FOR CLARITY):**
23. **ABSOLUTELY CRITICAL - MAIN BODY IS MARKDOWN:**
    *   All general text, ALL headings (H3, H4, H5), ALL paragraphs, ALL standard lists **MUST** be in standard Markdown.
    *   **NO `<p>`, `<h3>`, `<h4>`, `<h5>`, `<ul>`, `<li>` HTML TAGS IN THE GENERAL MARKDOWN BODY. THIS IS THE MOST COMMON ERROR. DOUBLE CHECK.**
    *   Use Markdown: `### Title`, `#### Title`, `##### Title`, blank lines for paragraphs, `* item`.
24. **HTML SNIPPETS FOR SPECIFIC SECTIONS ONLY:** Only "Pros and Cons" and "Frequently Asked Questions" (if generated) use the exact HTML snippets from the user prompt, placed after their respective Markdown `####` headings. The Ad placeholder is an HTML comment.
25. **Exact Output Order:** Your entire response MUST follow this order:
    Title Tag: [Generated Title Tag]
    Meta Description: [Generated Meta Description]
    SEO H1: [Generated SEO H1]

    {**MARKDOWN** Article Body (starting directly with summary paragraphs, NO `## H1` or `# H1` here). It may include the specific HTML snippets for Pros/Cons or FAQ if they are generated, and the HTML ad placeholder}
    Source: [{ARTICLE_TITLE_FROM_SOURCE}]({SOURCE_ARTICLE_URL})

    <script type="application/ld+json">
    {{JSON-LD content as specified}}
    </script>
26. **Title Tag:** Output as `Title Tag: [Generated text]`. Max length: ~60 characters. Must include `{{TARGET_KEYWORD}}`. **MUST use Title Case.** Closely match SEO H1.
27. **Meta Description:** Output as `Meta Description: [Generated text]`. Max length: ~160 characters. Must include `{{TARGET_KEYWORD}}` and be engaging, summarizing the core value.
28. **SEO H1 (in preamble):** Output as `SEO H1: [Generated text]`. This H1 will be used by the template. **MUST use Title Case.**
29. **JSON-LD Script:** Populate the `NewsArticle` schema accurately and as completely as possible. `keywords` field should use the content of `{{ALL_GENERATED_KEYWORDS_JSON}}`. `headline` field must match the generated SEO H1. The `mainEntityOfPage.@id` should use `{{MY_CANONICAL_URL_PLACEHOLDER}}`. If possible, include `wordCount` in JSON-LD based on your generated article body.

**VI. Error Handling & Self-Correction:** If you cannot fulfill a part of the request due to limitations or unclear input, make a logical choice or briefly note it. Strive for completeness. Review your output against all constraints before finalizing.
**VII. Final Check (IMPERATIVE):** Before outputting, mentally review ALL instructions. Ensure every constraint is met, especially the **MARKDOWN vs. HTML distinction** for body content, and that the main body Markdown *does not* start with `## H1` or `# H1`. Check for forbidden phrases.
"""

SEO_PROMPT_USER_TEMPLATE = """
Task: Generate the Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (primarily in **Markdown**, but using specific HTML snippets for Pros/Cons and FAQ if included, and the HTML comment for the ad placeholder), and JSON-LD Script based on the provided context. Follow ALL System Prompt directives meticulously, especially the **Markdown vs. HTML formatting rules for the main body** and the **extended length requirement (800-1500 words)**.

**Key Focus for this Task:**
1.  **Title & H1 Generation:** Create a **highly compelling, SEO-friendly Title Tag and SEO H1 (in the preamble) in Title Case**. Ensure they prominently feature the main subject/product from the content AND the `{{TARGET_KEYWORD}}`. The SEO H1 should be engaging and suitable for a top-tier news headline.
2.  **Content Structure & Formatting (CRITICAL - RE-READ SYSTEM PROMPT SECTION V):**
    *   The main article content (summary, all paragraphs, ALL H3/H4/H5 headings, standard lists) **MUST BE IN MARKDOWN SYNTAX**.
    *   **ABSOLUTELY NO HTML TAGS LIKE `<p>`, `<h3>`, `<h4>` etc., FOR THE GENERAL BODY TEXT OR HEADINGS.** Use Markdown: blank lines for paragraphs, `### An H3 Title`, `#### An H4 Title`, `* Bullet item`. **This is paramount.**
    *   The main body content **MUST NOT start with an H1 (`##` or `#`) tag**. The H1 is provided in the preamble.
    *   The `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` placeholder is mandatory.
    *   If Pros/Cons or FAQ sections are generated, they MUST use the exact HTML snippets provided in the example below, embedded within the Markdown flow AFTER their respective Markdown `####` headings.
    *   Omit optional sections (H4s/H5s, Pros/Cons, FAQ) if `{{ARTICLE_CONTENT_FOR_PROCESSING}}` doesn't clearly and robustly support them with significant detail.
    *   Include **at least 3-4 distinct `### H3` sections** to ensure depth and length.
3.  **Writing Style & Length:** Maintain a natural, human-like, expert journalistic style. Aim for **800-1500 words** for the article body. Strictly avoid AI clichés (see system prompt list), em dashes (use standard hyphens), and unnecessary symbols. Provide deep analysis and context.

**Input Context:**
ARTICLE_TITLE_FROM_SOURCE: {article_title_from_source}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str} # If empty, do not force usage.
ARTICLE_IMAGE_URL: {article_image_url}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD_ISO: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json} # This is a JSON string array of keywords
MY_CANONICAL_URL_PLACEHOLDER: {my_canonical_url_placeholder} # Placeholder for the canonical URL of *this* article

**Required Output Format (Strict Adherence - Note Markdown vs HTML as per System Prompt rules):**
Title Tag: [Generated catchy Title Tag in Title Case, approx. 50-60 chars. Must include TARGET_KEYWORD and ideally main product/subject name.]
Meta Description: [Generated meta description, approx. 150-160 chars. Must include TARGET_KEYWORD. Make it compelling and summarize value.]
SEO H1: [Generated catchy, SEO-Optimized H1 in Title Case. Must include TARGET_KEYWORD and ideally main product/subject name. Reflects core news.]

[Paragraph 1-3: **MUST BE MARKDOWN**. CONCISE summary (approx. 100-150 words). Include TARGET_KEYWORD naturally in the first paragraph. Journalistic tone. Standard hyphens ONLY. NO `<p>` TAGS HERE. **DO NOT START THIS BODY WITH AN H1 (`##` or `#`)**.]

<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->

### [Contextual H3 Title for Main Analysis 1: **MUST BE MARKDOWN H3 (`### Your Title`)**. Descriptive. After ad placeholder. Example: "### Unpacking [Product/Event]: Key Features and Groundbreaking Innovations"]
[Paragraphs (3-5): **MUST BE MARKDOWN**. In-depth analysis of features, technology, etc. Weave in TARGET_KEYWORD again if natural, + 1-2 SECONDARY_KEYWORDS if provided and they fit organically. Vary sentence structures and vocabulary. AVOID AI clichés and em dashes. NO `<p>` TAGS HERE.]
[[Internal link placeholder if relevant, e.g., Link to relevant Dacoola topic page about Core Technology]]

#### [Optional H4 Title: **MUST BE MARKDOWN H4 (`#### Your Title`)**. OMIT IF NOT RELEVANT. Example: "#### Technical Deep Dive: Architecture and Specifications"]
[Optional: 1-3 paragraphs: **MUST BE MARKDOWN**. OMIT ENTIRE H4 SECTION if not applicable. NO `<p>` TAGS HERE.]

### [Contextual H3 Title for Main Analysis 2: **MUST BE MARKDOWN H3**. Example: "### Market Impact and Competitive Landscape Analysis"]
[Paragraphs (3-5): **MUST BE MARKDOWN**. Detailed content on market position, competitors, user benefits, economic impact. NO `<p>` TAGS HERE.]
((External link placeholder if relevant to a high-authority source for market data))

#### [Optional H4 Title: **MUST BE MARKDOWN H4 (`#### Your Title`)**. OMIT IF NOT RELEVANT. Example: "#### User Adoption and Early Feedback"]
[Optional: 1-3 paragraphs: **MUST BE MARKDOWN**. OMIT ENTIRE H4 SECTION if not applicable. NO `<p>` TAGS HERE.]

### [Contextual H3 Title for Main Analysis 3: **MUST BE MARKDOWN H3**. Example: "### Broader Implications, Challenges, and Ethical Considerations"]
[Paragraphs (3-5): **MUST BE MARKDOWN**. Discuss societal impact, potential risks, ongoing debates, regulatory aspects. NO `<p>` TAGS HERE.]

#### [Optional: Pros and Cons - OMIT IF NOT APPLICABLE. If included, H4 title is **MARKDOWN (`#### Pros and Cons`)**, list is HTML snippet directly AFTER the H4 heading. Aim for 3-4 points each.]
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

### [Concluding H3 Title: **MUST BE MARKDOWN H3 (`### Final Thoughts: The Trajectory of [Topic/Product]`)**. Or similar impactful concluding title.]
[Paragraphs 1-2: **MUST BE MARKDOWN**. Summarize key insights and offer a forward-looking perspective or final evaluation. NO `<p>` TAGS HERE.]

#### [Optional: Frequently Asked Questions - OMIT IF NOT APPLICABLE. If included, H4 title is **MARKDOWN (`#### Frequently Asked Questions`)**, Q&A is HTML snippet directly AFTER the H4 heading. Aim for 3-5 insightful Q&As.]
#### Frequently Asked Questions
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">What are the most significant implications of [Product/Event]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Detailed and informative answer derived from the article and your analysis, highlighting key impacts.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">How does [Product/Event] compare to existing alternatives like [Alternative A] or [Alternative B]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>A nuanced comparison discussing strengths and weaknesses relative to major competitors, based on available information.</p>
    </div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">What are the potential future developments or next steps for [Topic/Product]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content">
      <p>Insightful speculation on future iterations, research directions, or market evolution based on current trends and the article's content.</p>
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
  "articleBody": "[A plain text version of your generated article body, primarily for schema.org. Strip all markdown and HTML. Keep paragraph breaks. Truncate to ~2500 chars if very long.]",
  "wordCount": "[Approximate word count of the generated markdown article body]"
}}
</script>
"""

# --- API Call Function ---
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
                if content_stripped.startswith("```") and content_stripped.endswith("```"):
                    first_newline = content_stripped.find('\n')
                    content_stripped = content_stripped[first_newline+1:-3].strip() if first_newline != -1 else content_stripped[3:-3].strip()
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
                temp_validated_json = json.loads(json_content_str.replace("{MY_CANONICAL_URL_PLACEHOLDER}", "https://example.com/placeholder-for-validation")
                                                                  .replace("{all_generated_keywords_json}", "[]")
                                                                  .replace("[Approximate word count of the generated markdown article body]", "0") # Placeholder replacement
                                                                  .replace("[A plain text version of your generated article body, primarily for schema.org. Strip all markdown and HTML. Keep paragraph breaks. Truncate to ~2500 chars if very long.]", "\"Sample body.\"")) # Placeholder replacement

                if "articleBody" not in temp_validated_json: errors.append("JSON-LD missing 'articleBody'.")
                if "wordCount" not in temp_validated_json: errors.append("JSON-LD missing 'wordCount'.")

            except json.JSONDecodeError as json_err:
                errors.append(f"JSON-LD content is invalid: {json_err}")
                logger.warning(f"Invalid JSON-LD detected (raw content): {json_content_str[:200]}...")
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
    logging.getLogger().setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    if not DEEPSEEK_API_KEY:
        logger.error("CRITICAL FOR STANDALONE TEST: DEEPSEEK_API_KEY env var not set.")
        sys.exit(1)

    test_article = {
        'id': 'test-seo-long-detailed-001',
        'title': "NVIDIA Unveils 'Hyperion' AI Chip: Quantum Leap in Processing Power",
        'content_for_processing': """
NVIDIA's CEO Jensen Huang today announced their new 'Hyperion' AI accelerator architecture during the company's annual GTC conference.
Huang described Hyperion as a "five-year leap" in AI processing, promising unprecedented performance for training and inferencing next-generation large language models and complex scientific simulations.
The architecture features a novel chiplet design, integrating dedicated cores for tensor operations, generative AI tasks, and high-speed interconnects.
Early benchmarks showcased by NVIDIA claim Hyperion offers up to 7x the performance of their previous flagship, the H200, in specific AI workloads and up to 10x improvement in energy efficiency.
"Hyperion is not just a chip; it's a new computing platform built for the age of generative AI," Huang stated.
The first products based on Hyperion are expected to ship to select cloud providers and enterprise partners in Q4 2025, with broader availability in early 2026.
Key partners like Microsoft Azure, Google Cloud, and AWS have already announced plans to incorporate Hyperion into their AI infrastructure.
The announcement also detailed advancements in NVIDIA's software stack, including new cuDNN libraries and Triton Inference Server optimizations specifically for Hyperion.
Industry analysts are lauding the announcement as a significant move to solidify NVIDIA's dominance in the AI hardware market, though some express concerns about pricing and accessibility for smaller research labs and startups.
The chip utilizes TSMC's next-generation 2nm process node. Huang also touched upon the extensive cooling solutions required for the new DGX Hyperion systems.
A major focus was on its capability to train trillion-parameter models more efficiently than ever before.
The Hyperion platform also introduces enhanced security features at the hardware level to protect AI models and data.
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

    logger.info("\n--- Running SEO Article Agent Standalone Test (Long & Detailed Request) ---")
    result_article = run_seo_article_agent(test_article.copy())

    if result_article.get('seo_agent_results'):
        print("\n\n--- Generated SEO Content ---")
        print(f"Title Tag: {result_article['seo_agent_results'].get('generated_title_tag')}")
        print(f"Meta Description: {result_article['seo_agent_results'].get('generated_meta_description')}")
        print(f"SEO H1 (Preamble): {result_article['seo_agent_results'].get('generated_seo_h1')}")
        print(f"Final Article Title in data: {result_article.get('title')}")

        md_body = result_article['seo_agent_results'].get('generated_article_body_md', '')
        word_count = len(md_body.split())
        print(f"\n--- Article Body (Should be Markdown, NO H1, target 800-1500 words. Actual: ~{word_count} words) ---")
        if len(md_body) > 2000: print(md_body[:1000] + "\n...\n" + md_body[-1000:])
        else: print(md_body)


        if not md_body.strip().startswith("## ") and not md_body.strip().startswith("# "):
            print("\nSUCCESS: Main body does NOT start with H1/H2 (##/#) Markdown.")
        else:
            print("\nWARNING: Main body STILL starts with H1/H2 (##/#) Markdown.")

        if "<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->" in md_body:
            print("SUCCESS: In-article ad placeholder found.")
        else:
            print("WARNING: In-article ad placeholder NOT found.")

        json_ld_script_tag = result_article['seo_agent_results'].get('generated_json_ld_full_script_tag', '')
        print(f"\n--- JSON-LD Script ---")
        if "{MY_CANONICAL_URL_PLACEHOLDER}" in json_ld_script_tag:
            print("SUCCESS: Canonical placeholder found in JSON-LD.")
        else:
            logger.warning("Canonical placeholder NOT found in JSON-LD.")
        if "articleBody" in json_ld_script_tag and "wordCount" in json_ld_script_tag:
            print("SUCCESS: articleBody and wordCount found in JSON-LD.")
        else:
            logger.warning("articleBody or wordCount might be missing from JSON-LD.")


        if result_article.get('seo_agent_error'):
            print(f"\nParsing/Validation Warnings/Errors: {result_article['seo_agent_error']}")
    else:
        print("\n--- SEO Agent FAILED ---")
        print(f"Error: {result_article.get('seo_agent_error')}")
        if result_article.get('seo_agent_raw_response_on_parse_fail'):
            print(f"\n--- Raw Response on Parse Failure (first 500 chars) ---")
            print(result_article['seo_agent_raw_response_on_parse_fail'][:500] + "...")

    logger.info("\n--- SEO Article Agent Standalone Test Complete ---")
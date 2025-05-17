# src/agents/seo_writing_agent.py

import os
import sys
import json
import logging
import requests # For Ollama
import re
from datetime import datetime, timezone

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env variables from project root to get YOUR_WEBSITE_NAME etc.
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

# --- Configuration ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_WRITER_MODEL = "llama3:70b" 
MAX_ARTICLE_CONTENT_FOR_PROCESSING_SNIPPET = 4000 
MAX_TOKENS_FOR_WRITER_RESPONSE = 8000 
API_TIMEOUT_SEO_WRITER = 450 

YOUR_WEBSITE_NAME_CONFIG = os.getenv('YOUR_WEBSITE_NAME', 'Dacoola')
YOUR_WEBSITE_LOGO_URL_CONFIG = os.getenv('YOUR_WEBSITE_LOGO_URL', 'https://via.placeholder.com/200x60.png?text=YourLogo') 
BASE_URL_FOR_CANONICAL_CONFIG = os.getenv('YOUR_SITE_BASE_URL', 'https://yoursite.example.com')
# Define AUTHOR_NAME_DEFAULT for standalone test fallback
AUTHOR_NAME_DEFAULT_CONFIG = os.getenv('AUTHOR_NAME', 'Dacoola AI Team')


# --- Agent Prompts (V4 Style - from your provided plan) ---
SEO_PROMPT_SYSTEM_V4 = """
You are an **Elite SEO Content Architect and Master Tech Journalist** for `{YOUR_WEBSITE_NAME}`. Your mission is to transform the provided `{{ARTICLE_CONTENT_FOR_PROCESSING}}` into an **exceptionally comprehensive, highly engaging, visually structured, factually precise, and SEO-dominant news article (target 800-1500 words for the main body)**. Your output must be indistinguishable from premier human journalism, rich in detail, analysis, and diverse content presentation. Avoid AI clichés (see forbidden list). Adhere with absolute precision to ALL directives.

**I. Core Principles (Mandatory):**
1.  **Source Synthesis & Profound Expansion:** The article MUST be primarily based on `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. **Massively expand** on this by integrating relevant historical context, detailed technical explanations (if applicable), comparative analyses with competing/similar technologies or events, insightful future implications, and expert commentary (conceptualized, not invented). **NEVER invent facts, quotes, statistics, or events.** Your role is to synthesize and enrich, creating a definitive resource. When creating new analytical sections (e.g., comparisons, implications), ensure the core ideas and data points are directly derivable from or logically extend the `{{ARTICLE_CONTENT_FOR_PROCESSING}}`. Avoid introducing substantial new topics or entities not mentioned or clearly alluded to in the source.
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
12. **Image Placeholders (Markdown Comments):** Throughout the thematic sections, strategically insert `<!-- IMAGE_PLACEHOLDER: Brief description of the desired image relevant to this section. Examples: A graph showing performance benchmarks, A concept art of the new hardware, A diagram of the AI model architecture. -->` where a visual would enhance understanding. Aim for 2-4 such placeholders.
13. **Pros & Cons (HTML Snippet - Conditional):** Generate **ONLY IF** the source clearly presents distinct, significant pros & cons. Aim for 3-5 points each. **Omit entirely otherwise.** If included, FIRST output the Markdown heading `#### Pros and Cons`. THEN, *immediately on the next line, without any other text or headings between the Markdown H4 and the HTML div*, output the *exact* HTML snippet for the pros-cons-container provided in the User Prompt.
14. **In-Article Ad Placeholder (HTML Comment):** After the introduction (2-3 paragraphs) and before the first `### H3`, insert: `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` (ONCE ONLY).
15. **FAQ (HTML Snippet - Conditional):** Generate **ONLY IF** topic warrants 3-5 insightful Q&As beyond main content. **Omit entirely otherwise.** If included, FIRST output the Markdown heading `#### Frequently Asked Questions`. THEN, *immediately on the next line, without any other text or headings between the Markdown H4 and the HTML div*, output the *exact* HTML snippet for the faq-section provided in the User Prompt.
16. **Conclusion (Markdown):** A final `### H3` (e.g., "### Concluding Analysis: Navigating the Evolving Landscape of [Topic]") with 2-3 paragraphs summarizing key takeaways and offering a final, impactful insight.
17. **Overall Length & Quality:** Target **800-1500 words** for the main article body. It must be exceptionally well-written, analytical, and provide unique value.

**IV. Journalistic Style & Anti-AI Cliché Mandate:**
18. **Analytical Depth & Originality:** Offer critical analysis, synthesize complex information, and provide a unique, expert perspective.
19. **Sophisticated Language:** Use rich vocabulary, varied sentence structures, and precise terminology.
20. **Active Voice & Strong Verbs:** Prioritize for clarity and impact.
21. **Illustrative Content:** Use conceptual examples, data points (if derivable from source), and vivid language.
22. **Flow & Cohesion:** Ensure seamless transitions. Read aloud to verify natural cadence. Use standard hyphens (-).
23. **STRICTLY FORBIDDEN PHRASES:** "delve into," "the landscape of," "ever-evolving," "testament to," "pivotal role," "robust," "seamless," "leverage," "game-changer," "in the realm of," "it's clear that," "looking ahead," "moreover," "furthermore," "in conclusion," "unveiled," "marked a significant," "the advent of," "it is worth noting," "needless to say," "at the end of the day," "all in all," "in a nutshell," "pave the way." Use synonyms or rephrase.

**V. Output Format (ABSOLUTE PRECISION REQUIRED):**
24. **MAIN BODY IS MARKDOWN - REITERATED FOR EMPHASIS. NO HTML TAGS FOR PARAGRAPHS, HEADINGS, LISTS, TABLES, BLOCKQUOTES, CODE BLOCKS IN THE MAIN BODY FLOW.**
25. **HTML Snippets ONLY for Pros/Cons & FAQ (if generated), as specified.**
26. **Exact Output Order:**
Title Tag: [Generated Title Tag]
Meta Description: [Generated Meta Description]
SEO H1: [Generated SEO H1]

{**MARKDOWN** Article Body - NO `# H1` or `## H2` at start. May include HTML snippets for Pros/Cons, FAQ. Must include ad placeholder and `<!-- IMAGE_PLACEHOLDER: ... -->` comments. Must use diverse Markdown elements like tables, lists, blockquotes, code blocks where appropriate.}
Source: [{ARTICLE_TITLE_FROM_SOURCE}]({SOURCE_ARTICLE_URL})

<script type="application/ld+json">
{{JSON-LD content as specified, including wordCount and articleBody (plain text, max 2500 chars, stripped of all Markdown/HTML)}}
</script>

27. **JSON-LD:** Populate `NewsArticle` schema completely. `headline` matches SEO H1. `keywords` from `{{ALL_GENERATED_KEYWORDS_JSON}}`. `mainEntityOfPage.@id` uses `{{MY_CANONICAL_URL_PLACEHOLDER}}`. **Include `articleBody` (plain text, max 2500 chars, stripped of all Markdown/HTML and image placeholders) and `wordCount` (approx. count of generated Markdown body).**

**VI. Final Self-Correction:** Review ALL constraints. Verify Markdown purity for the main body. Confirm diverse Markdown element usage. Ensure no forbidden phrases. Check output order. Ensure `articleBody` in JSON-LD is plain text and image placeholders are removed from it.
"""

SEO_PROMPT_USER_TEMPLATE_V4 = """
Task: Generate the Title Tag, Meta Description, SEO-Optimized H1 Heading, Article Body (primarily in **Markdown**, utilizing diverse elements like tables, lists, blockquotes, and code blocks; specific HTML snippets for Pros/Cons & FAQ if included; HTML comment for ad placeholder; and `<!-- IMAGE_PLACEHOLDER: description -->` comments for images), and JSON-LD Script. Follow ALL System Prompt directives meticulously, especially the **Markdown-only rule for general body text/headings**, the **800-1500 word length and diverse Markdown element usage requirements**, and the **JSON-LD `articleBody` and `wordCount` requirements.**

**Key Focus for this Task:**
1.  **Advanced Content Generation:** Produce a long-form (800-1500 words), deeply analytical article. **Actively use various Markdown elements** and include 2-4 `<!-- IMAGE_PLACEHOLDER: description -->` comments.
2.  **Formatting (ABSOLUTE - Refer to System Prompt Section V & III):**
    *   Main article content **MUST BE MARKDOWN**.
    *   Main body **MUST NOT** start with H1 (`#` or `##`).
    *   Ad placeholder `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` is mandatory.
    *   Pros/Cons & FAQ use exact HTML snippets from example, after their Markdown `####` headings.
    *   **Include at least 4-5 distinct `### H3` sections.**
3.  **JSON-LD:** Ensure `articleBody` is PLAIN TEXT (all Markdown/HTML/Placeholders stripped, max ~2500 chars) and `wordCount` (of generated Markdown body) are correctly populated.

**Input Context:**
ARTICLE_TITLE_FROM_SOURCE: {article_title_from_source}
ARTICLE_CONTENT_FOR_PROCESSING: {article_content_for_processing_snippet}
SOURCE_ARTICLE_URL: {source_article_url}
TARGET_KEYWORD: {target_keyword}
SECONDARY_KEYWORDS_LIST_STR: {secondary_keywords_list_str}
ARTICLE_IMAGE_URL_MAIN_FEATURED: {article_image_url_main_featured}
AUTHOR_NAME: {author_name}
CURRENT_DATE_YYYY_MM_DD_ISO: {current_date_iso}
YOUR_WEBSITE_NAME: {your_website_name_for_prompt}
YOUR_WEBSITE_LOGO_URL: {your_website_logo_url_for_prompt}
ALL_GENERATED_KEYWORDS_JSON: {all_generated_keywords_json_for_prompt}
MY_CANONICAL_URL_PLACEHOLDER: {my_canonical_url_placeholder_for_prompt}

**Required HTML Snippets (if you decide to include Pros/Cons or FAQ sections after their respective `#### Markdown Heading`):**

**Pros & Cons Snippet Example (use this exact structure if including):**
```html
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list"><ul><li>Pro 1 detail.</li><li>Pro 2 detail.</li></ul></div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list"><ul><li>Con 1 detail.</li><li>Con 2 detail.</li></ul></div>
  </div>
</div>
```

**FAQ Snippet Example (use this exact structure if including, repeat `<details>` block for each Q&A):**
```html
<div class="faq-section">
  <details class="faq-item">
    <summary class="faq-question">Question 1 derived from content? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content"><p>Answer 1 based on analysis.</p></div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Question 2 a reader might ask? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content"><p>Answer 2 with details.</p></div>
  </details>
</div>
```

Generate the full response now according to the specified output order.
"""


def call_ollama_for_seo_article(prompt_data):
    system_prompt_formatted = SEO_PROMPT_SYSTEM_V4.replace("{YOUR_WEBSITE_NAME}", prompt_data["your_website_name_for_prompt"])
    user_prompt_formatted = SEO_PROMPT_USER_TEMPLATE_V4.format(**prompt_data)

    payload = {
        "model": OLLAMA_WRITER_MODEL,
        "prompt": user_prompt_formatted,
        "stream": False,
    }
    try:
        logger.debug(f"Sending SEO article generation request to Ollama (model: {OLLAMA_WRITER_MODEL}). Est. User Prompt Tokens: ~{len(user_prompt_formatted)//3}")
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=API_TIMEOUT_SEO_WRITER)
        response.raise_for_status()
        
        response_json = response.json()
        generated_text_content = response_json.get("response")

        if generated_text_content:
            content_stripped = generated_text_content.strip()
            if content_stripped.startswith("```") and content_stripped.endswith("```"):
                content_stripped = re.sub(r"^```(?:json|markdown|text)?\s*","", content_stripped, flags=re.IGNORECASE)
                content_stripped = re.sub(r"\s*```$","", content_stripped)
            content_stripped = content_stripped.replace('—', '-')
            logger.info(f"Ollama SEO article generation successful. Content length: {len(content_stripped)}")
            return content_stripped.strip()
        else:
            logger.error(f"Ollama SEO writer response missing 'response' field or empty: {response_json}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error(f"Ollama API request for SEO article timed out after {API_TIMEOUT_SEO_WRITER} seconds.")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API request for SEO article failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_ollama_for_seo_article: {e}")
        return None


def strip_markdown_and_html(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'#{1,6}\s*', '', text)                     
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)          
    text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', text)         
    text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', text)          
    text = re.sub(r'__([^_]+?)__', r'\1', text)             
    text = re.sub(r'\*([^*]+?)\*', r'\1', text)            
    text = re.sub(r'_([^_]+?)_', r'\1', text)              
    text = re.sub(r'`(.*?)`', r'\1', text)                  
    text = re.sub(r'```[\s\S]*?```', '', text)              
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE) 
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)   
    text = re.sub(r'<!-- IMAGE_PLACEHOLDER:.*?-->', '', text) 
    text = re.sub(r'<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->', '', text) 
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def parse_ollama_seo_response(full_response_text):
    parsed_data = {}
    errors = []

    if not full_response_text or not isinstance(full_response_text, str):
        error_msg = "Full response text is empty or not a string."
        logger.error(error_msg)
        return None, error_msg

    try:
        title_match = re.search(r"^\s*Title Tag:\s*(.*)", full_response_text, re.MULTILINE | re.IGNORECASE)
        if title_match: parsed_data['generated_title_tag'] = title_match.group(1).strip()
        else: errors.append("Missing 'Title Tag:' line.")

        meta_match = re.search(r"^\s*Meta Description:\s*(.*)", full_response_text, re.MULTILINE | re.IGNORECASE)
        if meta_match: parsed_data['generated_meta_description'] = meta_match.group(1).strip()
        else: errors.append("Missing 'Meta Description:' line.")

        seo_h1_match = re.search(r"^\s*SEO H1:\s*(.*)", full_response_text, re.MULTILINE | re.IGNORECASE)
        if seo_h1_match: parsed_data['generated_seo_h1'] = seo_h1_match.group(1).strip()
        else: errors.append("Missing 'SEO H1:' line.")

        script_match = re.search(
            r'<script\s+type\s*=\s*["\']application/ld\+json["\']\s*>\s*(\{[\s\S]*?\})\s*<\/script>',
            full_response_text, re.IGNORECASE | re.DOTALL 
        )
        if script_match:
            json_content_str = script_match.group(1).strip()
            parsed_data['generated_json_ld_raw'] = json_content_str
            parsed_data['generated_json_ld_full_script_tag'] = script_match.group(0).strip()
            try:
                json.loads(json_content_str) 
            except json.JSONDecodeError as json_err:
                errors.append(f"JSON-LD content is invalid: {json_err}")
                logger.warning(f"Invalid JSON-LD content: {json_content_str[:200]}...")
        else:
            errors.append("Missing or malformed JSON-LD script block.")
            parsed_data['generated_json_ld_raw'] = "{}" 
            parsed_data['generated_json_ld_full_script_tag'] = '<script type="application/ld+json">{}</script>'

        body_content = ""
        if seo_h1_match:
            body_start_offset = seo_h1_match.end()
            end_delimiters_pattern = r"(^\s*Source:|\n\s*<script\s+type\s*=\s*[\"']application/ld\+json[\"'])"
            end_match = re.search(end_delimiters_pattern, full_response_text[body_start_offset:], re.MULTILINE | re.IGNORECASE)

            if end_match:
                body_content = full_response_text[body_start_offset : body_start_offset + end_match.start()].strip()
            else: 
                potential_body_end = len(full_response_text)
                if parsed_data.get('generated_json_ld_full_script_tag') != '<script type="application/ld+json">{}</script>': 
                    script_start_index = full_response_text.find(parsed_data['generated_json_ld_full_script_tag'])
                    if script_start_index != -1:
                        potential_body_end = script_start_index
                
                body_content = full_response_text[body_start_offset:potential_body_end].strip()
                if "\nSource:" in body_content: # Corrected this line
                    body_content = body_content.split("\nSource:", 1)[0].strip() # Corrected this line
                
                logger.warning("Article body extraction: Delimiters 'Source:' or JSON-LD script not clearly found. Used fallback.")

        else: 
            errors.append("Cannot extract article body: 'SEO H1:' line missing.")
        
        if body_content.lstrip().startswith(("# ", "## ")):
            body_content = re.sub(r"^\s*#{1,2}\s*.*?\n", "", body_content, count=1).lstrip()

        parsed_data['generated_article_body_md'] = body_content

        if 'generated_title_tag' not in parsed_data: parsed_data['generated_title_tag'] = "Default Article Title"
        if 'generated_meta_description' not in parsed_data: parsed_data['generated_meta_description'] = "Default article description."
        if 'generated_seo_h1' not in parsed_data: parsed_data['generated_seo_h1'] = parsed_data['generated_title_tag']


        if not parsed_data.get('generated_article_body_md'):
            errors.append("CRITICAL: Generated article body is empty after parsing.")
        if not parsed_data.get('generated_json_ld_raw') or parsed_data.get('generated_json_ld_raw') == '{}':
             errors.append("WARNING: JSON-LD seems empty or was not properly generated/parsed.")


        final_error_message = "; ".join(errors) if errors else None
        if "CRITICAL" in (final_error_message or ""):
            logger.error(f"Critical parsing failure for SEO content: {final_error_message}")
            return None, final_error_message 

        return parsed_data, final_error_message

    except Exception as e:
        logger.exception(f"Major exception during SEO response parsing: {e}")
        return None, f"Major parsing exception: {e}"


def run_seo_writing_agent(article_pipeline_data):
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running SEO Writing Agent for Article ID: {article_id} ---")

    content_for_processing_snippet = article_pipeline_data.get('raw_scraped_text', '')[:MAX_ARTICLE_CONTENT_FOR_PROCESSING_SNIPPET]
    
    primary_keyword_for_prompt = article_pipeline_data.get('primary_topic', article_pipeline_data.get('initial_title_from_web', 'AI News'))
    secondary_keywords_list = [kw for kw in article_pipeline_data.get('final_keywords', []) if kw.lower() != primary_keyword_for_prompt.lower()][:5] 

    all_keywords_for_json_ld = list(set([str(k).strip() for k in article_pipeline_data.get('final_keywords', []) if k and str(k).strip()]))
    all_generated_keywords_json_str = json.dumps(all_keywords_for_json_ld) if all_keywords_for_json_ld else "[]"

    my_canonical_url_placeholder = f"{BASE_URL_FOR_CANONICAL_CONFIG.rstrip('/')}/articles/{{SLUG_PLACEHOLDER}}"

    prompt_fill_data = {
        "article_title_from_source": article_pipeline_data.get('initial_title_from_web', 'Untitled Article'),
        "article_content_for_processing_snippet": content_for_processing_snippet,
        "source_article_url": article_pipeline_data.get('original_source_url', '#'),
        "target_keyword": primary_keyword_for_prompt,
        "secondary_keywords_list_str": ", ".join(secondary_keywords_list),
        "article_image_url_main_featured": article_pipeline_data.get('selected_image_url', 'https://via.placeholder.com/1200x675.png?text=Featured+Image'),
        "author_name": article_pipeline_data.get('author', AUTHOR_NAME_DEFAULT_CONFIG), # Use config var
        "current_date_iso": article_pipeline_data.get('published_iso', datetime.now(timezone.utc).isoformat()),
        "your_website_name_for_prompt": YOUR_WEBSITE_NAME_CONFIG,
        "your_website_logo_url_for_prompt": YOUR_WEBSITE_LOGO_URL_CONFIG,
        "all_generated_keywords_json_for_prompt": all_generated_keywords_json_str,
        "my_canonical_url_placeholder_for_prompt": my_canonical_url_placeholder
    }

    for key, value in prompt_fill_data.items():
        if value is None:
            prompt_fill_data[key] = ''
            logger.warning(f"Prompt data key '{key}' was None, replaced with empty string for LLM.")

    full_llm_response_text = call_ollama_for_seo_article(prompt_fill_data)

    if not full_llm_response_text:
        article_pipeline_data['seo_agent_results'] = None
        article_pipeline_data['seo_agent_status'] = "LLM_CALL_FAILED"
        article_pipeline_data['seo_agent_error_detail'] = "Ollama call failed or returned empty."
        logger.error(f"SEO Writing Agent: LLM call failed for {article_id}.")
        return article_pipeline_data

    parsed_seo_results, parsing_error_msg = parse_ollama_seo_response(full_llm_response_text)

    article_pipeline_data['seo_agent_results'] = parsed_seo_results
    article_pipeline_data['seo_agent_error_detail'] = parsing_error_msg

    if parsed_seo_results is None or not parsed_seo_results.get('generated_article_body_md'):
        article_pipeline_data['seo_agent_status'] = "PARSING_FAILED_CRITICAL"
        article_pipeline_data['seo_agent_raw_response_on_fail'] = full_llm_response_text[:5000] 
        logger.error(f"SEO Writing Agent: CRITICAL parsing failure for {article_id}. Raw response snippet logged.")
    elif parsing_error_msg:
        article_pipeline_data['seo_agent_status'] = "PARSING_WITH_WARNINGS"
        logger.warning(f"SEO Writing Agent: Parsing for {article_id} had warnings: {parsing_error_msg}")
        article_pipeline_data['final_title'] = parsed_seo_results.get('generated_seo_h1', article_pipeline_data.get('initial_title_from_web', 'Error Title'))
        article_pipeline_data['slug'] = slugify_filename(article_pipeline_data['final_title']) # Defined for standalone
    else:
        article_pipeline_data['seo_agent_status'] = "SUCCESS"
        logger.info(f"SEO Writing Agent: Successfully generated and parsed content for {article_id}.")
        article_pipeline_data['final_title'] = parsed_seo_results.get('generated_seo_h1', parsed_seo_results.get('generated_title_tag', article_pipeline_data.get('initial_title_from_web', 'Error Title')))
        article_pipeline_data['slug'] = slugify_filename(article_pipeline_data['final_title']) # Defined for standalone

    return article_pipeline_data

# --- Define slugify_filename for standalone test ---
def slugify_filename(text_to_slugify):
    if not text_to_slugify: return "untitled-slug"
    s = str(text_to_slugify).strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[-\s]+', '-', s)
    return s[:75]


if __name__ == "__main__":
    if not logger.handlers: 
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    logger.info("--- Starting SEO Writing Agent Standalone Test ---")
    
    sample_article_input_data = {
        'id': 'test_seo_001',
        'initial_title_from_web': "Breakthrough in Fusion Energy: Scientists Achieve Sustained Net Gain",
        'raw_scraped_text': "Researchers at NIF reported a landmark achievement...", # Shortened for brevity
        'primary_topic': "Fusion Energy Breakthrough",
        'final_keywords': ["fusion energy", "net energy gain", "National Ignition Facility", "laser fusion"],
        'processed_summary': "Scientists at NIF achieved sustained net energy gain in a fusion reaction...",
        'original_source_url': 'https://www.example.com/news/fusion-breakthrough-nif',
        'selected_image_url': 'https://www.example.com/images/nif_facility.jpg', 
        'author': 'Dr. Science Writer', # This will be overridden by AUTHOR_NAME_DEFAULT_CONFIG if None in data
        'published_iso': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }

    result_data = run_seo_writing_agent(sample_article_input_data.copy())

    logger.info("\n--- SEO Writing Test Results ---")
    logger.info(f"SEO Agent Status: {result_data.get('seo_agent_status')}")
    if result_data.get('seo_agent_error_detail'):
        logger.error(f"SEO Agent Error/Warning Detail: {result_data.get('seo_agent_error_detail')}")

    seo_results = result_data.get('seo_agent_results')
    if seo_results:
        logger.info(f"\nGenerated Title Tag: {seo_results.get('generated_title_tag')}")
        logger.info(f"Generated Meta Description: {seo_results.get('generated_meta_description')}")
        logger.info(f"Generated SEO H1: {seo_results.get('generated_seo_h1')}")
        logger.info(f"\nFinal Article Title (in pipeline_data): {result_data.get('final_title')}")
        logger.info(f"Generated Slug (in pipeline_data): {result_data.get('slug')}")
        
        md_body = seo_results.get('generated_article_body_md', '')
        logger.info(f"\n--- Generated Markdown Body (first 500 chars) ---")
        logger.info(md_body[:500] + "...\n")
        
        if "<!-- IMAGE_PLACEHOLDER:" in md_body: logger.info("SUCCESS: Image placeholders found.")
        else: logger.warning("WARNING: Image placeholders NOT found.")
        if "<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->" in md_body: logger.info("SUCCESS: In-article ad placeholder found.")
        else: logger.warning("WARNING: In-article ad placeholder NOT found.")

        logger.info(f"\n--- Generated JSON-LD (Raw) ---")
        logger.info(seo_results.get('generated_json_ld_raw'))
        
        if md_body:
            plain_text_for_json_ld = strip_markdown_and_html(md_body)
            word_count = len(plain_text_for_json_ld.split())
            logger.info(f"\n--- Plain Text for JSON-LD articleBody (first 300 chars, Word Count: {word_count}) ---")
            logger.info(plain_text_for_json_ld[:300] + "...")
            if "{SLUG_PLACEHOLDER}" not in seo_results.get('generated_json_ld_raw', ''): logger.warning("Warning: {SLUG_PLACEHOLDER} missing in raw JSON-LD.")
            if "wordCount" not in seo_results.get('generated_json_ld_raw', ''): logger.warning("Warning: 'wordCount' missing in raw JSON-LD.")

    if result_data.get('seo_agent_raw_response_on_fail'):
        logger.error(f"\n--- RAW LLM RESPONSE (on critical parse fail, first 500 chars) ---")
        logger.error(result_data['seo_agent_raw_response_on_fail'][:500] + "...")

    logger.info("--- SEO Writing Agent Standalone Test Complete ---")

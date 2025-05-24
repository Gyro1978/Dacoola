# src/agents/section_writer_agent.py
# Section Writer Agent: Generates concise, impactful Markdown OR HTML for article sections.
# Focuses on the most engaging aspects (interesting, exciting, scary) as per the plan,
# aiming for shorter, potent content suitable for fewer, deeper sections.

import os
import sys
import json
import logging
import torch # Added for Gemma
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig # Added for Gemma
import re
import time
import ftfy
import math
import html # For HTML escaping

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

MAX_RETRIES = 2 # Retained for application-level retries
RETRY_DELAY_BASE = 7 # Retained for application-level retries

# Revised Word Count Targets for SHORTER, more impactful sections
TARGET_WORD_COUNT_MAP = {
    "introduction": (80, 150),  # More concise
    "conclusion": (80, 150),   # More concise
    "main_body": (200, 350),   # Significantly shorter, focus on impact
    "pros_cons": (60, 150),    # Shorter, more punchy lists (total text content within HTML)
    "faq": (60, 150),          # Shorter answers (total text content within HTML)
    "default": (100, 250)
}

# --- Enhanced Agent System Prompt for Shorter, More Impactful Content ---
SECTION_WRITER_SYSTEM_PROMPT = """You are ImpactScribe, an ASI-level AI specialized in generating concise, potent, and highly engaging content for individual sections of tech news articles. Your mission is to write for ONE specific article section at a time, focusing exclusively on the most interesting, exciting, or alarming aspects relevant to that section's plan, ruthlessly cutting all fluff. Your output is THE CONTENT itself, precisely formatted as specified.

**CRITICAL OUTPUT MANDATE: DUAL BEHAVIOR BASED ON `section_to_write.is_html_snippet`**

Your output format is strictly determined by the `section_to_write.is_html_snippet` boolean flag. You will output EITHER pure Markdown OR pure, minimal HTML. Absolutely NO extra text, comments, conversational filler, or markdown fences surrounding your direct output.

1.  **STANDARD MARKDOWN SECTIONS (`section_to_write.is_html_snippet: false`)**:
    *   You MUST output pure, valid Markdown content.
    *   **FOR THESE STANDARD SECTIONS, YOU MUST OUTPUT PURE MARKDOWN SYNTAX. DO NOT GENERATE ANY HTML TAGS (e.g., `<p>`, `<h3>`, `<li>`). YOUR OUTPUT WILL BE PARSED BY A MARKDOWN PROCESSOR.**
    *   For example, if you are writing a paragraph, the output should be `This is a paragraph of text.` and NOT `<p>This is a paragraph of text.</p>`. If you are writing a level 2 heading, it should be `## My Heading` and NOT `<h2>My Heading</h2>`.
    *   **Heading Logic for Markdown**:
        *   If `section_to_write.heading_text` is provided and is not `null`, your output MUST begin with that exact Markdown heading (e.g., `### Actual Heading Text`), followed by two newlines, then the paragraph content.
        *   If `section_to_write.heading_text` is `null` (typically for introduction sections), your output MUST begin directly with the paragraph content, with NO heading.
    *   Markdown content must adhere to all general directives below (conciseness, tone, factual accuracy, etc.).

2.  **SPECIAL HTML SNIPPET SECTIONS (`section_to_write.is_html_snippet: true` - e.g., `pros_cons`, `faq`)**:
    *   You MUST output the complete, valid, and minimal HTML structure directly, as specified below for the given `section_to_write.section_type`.
    *   **CRITICAL: No External Headings:** For these HTML sections, you **MUST NOT** include any Markdown headings (e.g., `###`, `####`) or HTML headings (e.g., `<h4>`) that might be present in `section_to_write.heading_text`. The HTML structure you generate will contain its *own* internal semantic headings (like `<h5>` for Pros/Cons) as per the examples.
    *   **CRITICAL: HTML Content Escaping:** All text you generate for placement within HTML tags (e.g., inside `<li>`, `<p>`, `<summary>`) MUST be properly HTML-escaped (e.g., `&` becomes `&amp;`, `<` becomes `&lt;`, `>` becomes `&gt;`).
    *   NO extra text, comments, or anything outside the specified HTML structure. Your entire output must be the HTML block.
    *   **CRITICAL: Unique End Markers:** Append a unique HTML comment marker to the VERY END of the HTML block: `<!-- END_PROS_CONS_SNIPPET -->` for "pros_cons" type, and `<!-- END_FAQ_SNIPPET -->` for "faq" type. This marker must be outside the main content div of the snippet.

    *   **HTML Structure for `pros_cons` (`section_to_write.section_type: "pros_cons"`)**:
        *   Root element: `<div class="pros-cons-container">`
        *   Inside `pros-cons-container`: two `div` elements: `<div class="pros-section"></div>` and `<div class="cons-section"></div>`.
        *   Inside `pros-section`: an `<h5 class="section-title">Pros</h5>`, followed by `<div class="item-list"><ul></ul></div>`.
        *   Inside `cons-section`: an `<h5 class="section-title">Cons</h5>`, followed by `<div class="item-list"><ul></ul></div>`.
        *   Each `<li>` item within the `<ul>`s must be a very short, punchy phrase or sentence fragment (target: 5-15 words each), representing a distinct point.
        *   **Minimal `pros_cons` HTML Example Output**:
            ```html
            <div class="pros-cons-container">
              <div class="pros-section">
                <h5 class="section-title">Pros</h5>
                <div class="item-list">
                  <ul>
                    <li>Groundbreaking AI capabilities.</li>
                    <li>Streamlines complex workflows.</li>
                    <li>Potential for massive ROI.</li>
                  </ul>
                </div>
              </div>
              <div class="cons-section">
                <h5 class="section-title">Cons</h5>
                <div class="item-list">
                  <ul>
                    <li>High initial implementation cost.</li>
                    <li>Requires specialized expertise.</li>
                    <li>Ethical concerns remain unaddressed.</li>
                  </ul>
                </div>
              </div>
            </div>
            <!-- END_PROS_CONS_SNIPPET -->
            ```

    *   **HTML Structure for `faq` (`section_to_write.section_type: "faq"`)**:
        *   Root element: `<div class="faq-section">`
        *   Inside `faq-section`: a series of `<details class="faq-item">` tags.
        *   Each `<details class="faq-item">` tag must contain:
            1.  A `<summary class="faq-question">` tag. The text content of this summary is the question, followed by a Font Awesome chevron icon: `<i class="fas fa-chevron-down faq-icon"></i>`.
            2.  A `<div class="faq-answer-content">` directly following the `</summary>` tag (and inside `<details>`). The answer text (1-2 concise sentences) must be wrapped in a `<p>` tag within this `div`.
        *   **Minimal `faq` HTML Example Output**:
            ```html
            <div class="faq-section">
              <details class="faq-item">
                <summary class="faq-question">What is the core innovation? <i class="fas fa-chevron-down faq-icon"></i></summary>
                <div class="faq-answer-content"><p>The core innovation lies in its real-time adaptive learning algorithms. This allows for unprecedented personalization.</p></div>
              </details>
              <details class="faq-item">
                <summary class="faq-question">How does it impact existing markets? <i class="fas fa-chevron-down faq-icon"></i></summary>
                <div class="faq-answer-content"><p>It's poised to disrupt traditional markets by offering a significantly more efficient solution. Early adopters may see substantial competitive advantages.</p></div>
              </details>
            </div>
            <!-- END_FAQ_SNIPPET -->
            ```

**GENERAL DIRECTIVES (APPLY TO ALL OUTPUTS)**

*   **Laser Focus on Section Plan & Impact**:
    *   The `section_to_write` input is your SOLE BLUEPRINT.
    *   `section_to_write.content_plan` dictates what to cover and the angle.
    *   All `section_to_write.key_points` MUST be addressed, prioritizing depth, insight, and impact.
    *   `section_to_write.purpose` guides the tone.

*   **Concise, Potent Content - Quality over Quantity**:
    *   **Strict Word Count Adherence (Shorter is Better within Range)**:
        *   `main_body` sections: 200-350 words (2-5 highly focused, impactful paragraphs).
        *   `introduction` / `conclusion` sections: 80-150 words (1-3 powerful paragraphs).
        *   `pros_cons` / `faq` (HTML Snippets): Total text content (all `<li>` items or all Q&A text combined) must be 60-150 words. Prioritize per-item brevity.
    *   **Ruthless Word Economy**: Every word justifies its existence. Strong verbs, precise nouns. Eliminate redundancy and filler.
    *   **Tone & Style**: Authoritative, incisive, gripping. Voice of a top-tier tech journalist. Sophisticated yet accessible.
    *   **Synthesize for Impact**: Highlight genuinely new, surprising, or significant consequences, drawing from `full_article_context` as relevant to THIS section's plan.
    *   **Factual Accuracy**: All claims MUST be directly supported by or logically inferred from `full_article_context`. NO INVENTIONS.

*   **Strategic Markdown (ONLY for `is_html_snippet: false` sections)**:
    *   Use suggested Markdown elements (e.g., `table`, `blockquote`, `list`, `code_block` from `section_to_write.suggested_markdown_elements`) ONLY if they significantly enhance clarity or impact for concise content.
    *   Maintain Markdown purity. Use code blocks (` ``` `) judiciously for actual code/data.

*   **Subtle Keyword Integration**:
    *   If keywords from `full_article_context.final_keywords` fit *naturally* into the concise, impactful narrative, include them. DO NOT FORCE. Quality and flow are paramount.

*   **Minimal Linking Placeholders**:
    *   At most ONE `[[...]]` (internal) or `((...))` (external) placeholder per section, ONLY if it offers undeniable, immediate value. Often, NONE.

*   **Journalistic Impact & Anti-Cliché Mandate (ABSOLUTE)**:
    *   Vivid language, varied sentence structure (favor short, declarative sentences for impact).
    *   **ZERO TOLERANCE FOR GENERIC, VAGUE, OR OVERLY ENTHUSIASTIC MARKETING-SPEAK. Writing must be fresh, direct, confident, and demonstrate "show, don't tell" principles.**
    *   **BANNED PHRASES & PATTERNS (NON-EXHAUSTIVE, but indicative of style to avoid):** "In conclusion", "In the world of X", "In today's fast-paced world", "It's worth noting that", "It is important to note that", "This section will delve into", "The topic is a testament to", "As we move forward", "Unlocking the potential of", "Navigating the complexities of", "Paving the way for", "A game-changer", "game-changing", "Revolutionize", "revolutionary" (unless truly earned), "Cutting-edge", "State-of-the-art" (use specifics instead), "Seamlessly integrates", "Robust solution", "Harness the power of", "Dive deep into", "Deep dive", "Last but not least", "At the end of the day", "It goes without saying", "It is interesting to consider", "Plays a crucial/pivotal role", "At its core", "In essence" (use sparingly), "Moving forward", "Looking ahead", "It's clear that", "Clearly", "Ultimately" (as a crutch), "Simply put" (unless genuinely simplifying), "The fact of the matter is", "Key takeaway", "Significant impact" (show, don't tell). Avoid vague intensifiers (very, really, quite), overuse of passive voice, and weak rhetorical questions.
    *   **AVOID EM DASHES (—)**. Use hyphens (-) for compounds, or commas/parentheses for asides if concise.

**FINAL REMINDER:**
Focus on brevity, impact, and strict adherence to the content plan for THIS SECTION ONLY. Your output is pure Markdown or HTML as specified by 'is_html_snippet'. Your output is the direct content.
"""
# --- End Enhanced Agent System Prompt ---

def _count_words(text: str) -> int:
    cleaned_text = re.sub(r'[\#\*\_\-\+\`\[\]\(\)\|!>]', '', text) # Basic Markdown chars
    cleaned_text = re.sub(r'<[^>]+>', ' ', cleaned_text) # Remove HTML tags, replace with space
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    if not cleaned_text: return 0
    return len(cleaned_text.split())

def _truncate_content_to_word_count(content: str, max_words: int, section_type: str, is_html_snippet: bool) -> str:
    initial_word_count = _count_words(content)
    if initial_word_count <= max_words: return content

    if is_html_snippet:
        # For HTML snippets, if they are too long, it's better to return them as is and flag the issue,
        # as programmatic truncation can easily break HTML structure. The LLM needs to adhere to length for these.
        logger.warning(f"HTML Snippet '{section_type}' ({initial_word_count} words) "
                       f"exceeded max_words ({max_words}) post-generation. This suggests LLM conciseness failure. "
                       f"Returning original to preserve snippet structure; prompt refinement for length adherence on HTML snippets is critical.")
        return content

    # For Markdown, attempt paragraph/sentence-aware truncation
    final_parts = []
    current_word_count = 0
    # Split by paragraphs more carefully, preserving their separators for rejoining
    paragraphs_and_separators = re.split(r'(\n\n+)', content)
    
    processed_elements = []
    for element in paragraphs_and_separators:
        if not element.strip(): # Preserve separators (blank lines)
            if processed_elements and processed_elements[-1].strip(): # Avoid multiple blank lines if para was empty
                 processed_elements.append(element)
            continue

        para_word_count = _count_words(element)
        if current_word_count + para_word_count <= max_words:
            processed_elements.append(element)
            current_word_count += para_word_count
        else:
            remaining_words_for_element = max_words - current_word_count
            if remaining_words_for_element > 0:
                # Check if the element is a structured block (list, table, code, blockquote)
                is_structured_block = (
                    element.strip().startswith(('```', '|', '>')) or
                    (element.strip().startswith(('* ', '- ', '+ ', '1. ')) and '\n' in element) # Multi-line list
                )
                # If it's a structured block and significantly over the remaining word budget,
                # it's better to cut it entirely than to truncate it mid-structure.
                if is_structured_block and para_word_count > remaining_words_for_element * 1.2: # Heuristic: if block is 20% larger than remaining
                    logger.warning(f"Structured block in '{section_type}' (approx. {para_word_count} words) "
                                   f"cut due to length constraints. Appending truncation notice.")
                    processed_elements.append(f"**[Content Shortened: A detailed block was omitted for brevity.]**")
                    current_word_count = max_words # Mark as full to stop further additions
                    break # Stop processing further elements
                else: # Not a largely oversized structured block, or just text, try sentence-level truncation
                    sentences = re.split(r'(?<=[.!?])\s+', element) # Split by sentence endings
                    temp_para_parts = []
                    for sentence in sentences:
                        sentence_words = _count_words(sentence)
                        if current_word_count + sentence_words <= max_words:
                            temp_para_parts.append(sentence)
                            current_word_count += sentence_words
                        else:
                            # Try to truncate the last sentence if some words are left
                            sub_remaining_words = max_words - current_word_count
                            if sub_remaining_words > 2: # Only add if at least a few words can be added
                                words_in_sentence = sentence.split()
                                temp_para_parts.append(" ".join(words_in_sentence[:sub_remaining_words]) + "...")
                                current_word_count += sub_remaining_words
                            break # Stop adding sentences to this paragraph
                    if temp_para_parts:
                        processed_elements.append(" ".join(temp_para_parts))
            break # Stop processing further elements/paragraphs
    
    final_content = "".join(processed_elements).strip()
    final_word_count = _count_words(final_content)
    if final_word_count < initial_word_count: # Log only if actual truncation happened
        logger.warning(f"Markdown content for section '{section_type}' (impact focus) truncated: {initial_word_count} -> {final_word_count} words.")
    return final_content

def _call_llm_for_section(system_prompt: str, user_prompt_data: dict, max_tokens_for_section: int, temperature: float, is_html_snippet: bool) -> str | None:
    global gemma_tokenizer, gemma_model
    
    user_prompt_string_for_gemma = json.dumps(user_prompt_data, indent=2) # For logging/debug if needed
    logger.debug(f"Section writer (Gemma local): Max completion tokens: {max_tokens_for_section}, Temp: {temperature}")

    messages_for_gemma = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_string_for_gemma} # User prompt is the JSON string itself
    ]

    for attempt in range(MAX_RETRIES):
        try:
            if gemma_tokenizer is None or gemma_model is None:
                logger.info(f"Initializing Gemma model and tokenizer for the first time (attempt {attempt + 1}/{MAX_RETRIES}). Model: {LLM_MODEL_NAME}")
                gemma_tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL_NAME)
                quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
                gemma_model = AutoModelForCausalLM.from_pretrained(
                    LLM_MODEL_NAME,
                    quantization_config=quantization_config,
                    device_map="auto" # Handles CPU if no GPU
                )
                gemma_model.eval()
                logger.info("Gemma model and tokenizer initialized successfully.")

            input_text = gemma_tokenizer.apply_chat_template(
                messages_for_gemma,
                tokenize=False,
                add_generation_prompt=True
            )
            input_ids = gemma_tokenizer(input_text, return_tensors="pt").to(gemma_model.device)

            logger.debug(f"Gemma generation attempt {attempt + 1}/{MAX_RETRIES} for section writer.")
            with torch.no_grad():
                outputs = gemma_model.generate(
                    **input_ids,
                    max_new_tokens=max_tokens_for_section,
                    temperature=temperature if temperature > 0.001 else None, # Gemma might not like 0 temp with do_sample=False
                    do_sample=temperature > 0.001,
                    pad_token_id=gemma_tokenizer.eos_token_id
                )
            
            generated_ids = outputs[0, input_ids['input_ids'].shape[1]:]
            content = gemma_tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
            
            # Clean up potential markdown fences if LLM adds them by mistake
            if content.startswith("```markdown") and content.endswith("```"): content = content[len("```markdown"):-len("```")].strip()
            elif content.startswith("```html") and content.endswith("```"): content = content[len("```html"):-len("```")].strip()
            elif content.startswith("```") and content.endswith("```"): content = content[len("```"):-len("```")].strip()
            
            content = ftfy.fix_text(content) # General text cleaning
            logger.info(f"Gemma local call successful for section writer (Attempt {attempt+1}/{MAX_RETRIES})")
            return content
        
        except Exception as e:
            logger.exception(f"Error during Gemma local call for section writer (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                logger.error("All Gemma local attempts for section writer failed due to errors.")
                # If model loading itself failed, reset them to allow re-initialization on next call
                if isinstance(e, (RuntimeError, ImportError, OSError)): # Errors likely during model loading
                    logger.warning("Resetting global gemma_model and gemma_tokenizer due to critical error.")
                    gemma_tokenizer = None
                    gemma_model = None
                return None
        
        delay = min(RETRY_DELAY_BASE * (2 ** attempt), 60)
        logger.warning(f"Gemma local call for section writer failed (attempt {attempt+1}/{MAX_RETRIES}). Retrying in {delay}s.")
        time.sleep(delay)
            
    logger.error(f"Gemma LLM local call for section writer failed after {MAX_RETRIES} attempts."); return None

def _validate_html_snippet_structure(generated_html: str, section_type: str) -> bool:
    """
    Basic structural validation for generated HTML snippets.
    This is a simplified check; more robust parsing (e.g., with BeautifulSoup) could be added.
    """
    if not generated_html:
        logger.warning(f"HTML Snippet Validation: Empty HTML for {section_type}.")
        return False # Empty is not valid if content was expected
    
    is_valid = True
    # Check for unique end markers
    if section_type == "pros_cons":
        if not generated_html.strip().endswith("<!-- END_PROS_CONS_SNIPPET -->"):
            logger.warning(f"Pros/Cons HTML snippet MISSING unique end marker. Snippet: ...{generated_html[-50:]}")
            is_valid = False
        if not ('<div class="pros-cons-container">' in generated_html and \
                '<div class="pros-section">' in generated_html and \
                '<div class="cons-section">' in generated_html and \
                '<h5 class="section-title">Pros</h5>' in generated_html and \
                '<h5 class="section-title">Cons</h5>' in generated_html and \
                '<div class="item-list">' in generated_html and \
                '<ul>' in generated_html and '<li>' in generated_html):
            logger.warning(f"Pros/Cons HTML snippet missing core structural elements. Snippet: {generated_html[:300]}...")
            is_valid = False
    elif section_type == "faq":
        if not generated_html.strip().endswith("<!-- END_FAQ_SNIPPET -->"):
            logger.warning(f"FAQ HTML snippet MISSING unique end marker. Snippet: ...{generated_html[-50:]}")
            is_valid = False
        if not ('<div class="faq-section">' in generated_html and \
                '<details class="faq-item">' in generated_html and \
                '<summary class="faq-question">' in generated_html and \
                '<i class="fas fa-chevron-down faq-icon"></i>' in generated_html and \
                '<div class="faq-answer-content"><p>' in generated_html): # Check for <p> tag
            logger.warning(f"FAQ HTML snippet missing core structural elements. Snippet: {generated_html[:300]}...")
            is_valid = False
        
    # Improved check for unescaped characters in apparent text content
    # Remove the main snippet div and end marker comment before checking text content
    text_content_to_check = generated_html
    if section_type == "pros_cons":
        text_content_to_check = text_content_to_check.replace("<!-- END_PROS_CONS_SNIPPET -->", "")
    elif section_type == "faq":
        text_content_to_check = text_content_to_check.replace("<!-- END_FAQ_SNIPPET -->", "")
    
    text_content_after_stripping_tags = re.sub(r'<[^>]+>', ' ', text_content_to_check).strip() # Replace tags with space to separate words

    if re.search(r'&(?!(amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;))', text_content_after_stripping_tags):
        logger.warning(f"Potential unescaped '&' found in *apparent text content* of generated HTML for {section_type} after stripping tags. Text content: '{text_content_after_stripping_tags[:100]}...'")
        # is_valid = False # This can be too strict if LLM makes a minor mistake but overall structure is fine
    if '<' in text_content_after_stripping_tags or '>' in text_content_after_stripping_tags:
        logger.warning(f"Potential unescaped '<' or '>' characters found in *apparent text content* of generated HTML for {section_type} after stripping tags. Text content: '{text_content_after_stripping_tags[:100]}...'")
        # is_valid = False
            
    return is_valid


def run_section_writer_agent(section_plan_to_write: dict, full_article_context_for_writing: dict) -> str | None:
    section_type = section_plan_to_write.get("section_type", "unknown_section")
    is_html_snippet = section_plan_to_write.get("is_html_snippet", False)
    heading_text_from_plan = section_plan_to_write.get("heading_text")
    heading_text_for_log = heading_text_from_plan[:50] if heading_text_from_plan else ("HTML Snippet" if is_html_snippet else "No Heading (Intro)")
    
    logger.info(f"--- Running Section Writer (Impact Focus) for: '{section_type}' - '{heading_text_for_log}...' ---")

    user_prompt_data = {
        "section_to_write": section_plan_to_write,
        "full_article_context": full_article_context_for_writing,
        "REMINDER_STRICT_ADHERENCE": "Focus on brevity, impact, and strict adherence to the content plan for THIS SECTION ONLY. Your output is pure Markdown or HTML as specified by 'is_html_snippet'. Your output is the direct content."
    }

    min_target_w, max_target_w = TARGET_WORD_COUNT_MAP.get(section_type, TARGET_WORD_COUNT_MAP["default"])
    # For HTML snippets, max_tokens should account for HTML tags + text content word count
    # For Markdown, it's mostly text content.
    # Rough estimation: 2.8 tokens per word for text, HTML tags might add 50-100% overhead for complex snippets.
    # The prompt now specifies concise text for HTML snippets, so tag overhead shouldn't be extreme.
    # For Gemma, max_new_tokens is what we set. The input tokens are separate.
    # Let's base max_new_tokens on the target word count, assuming ~2-3 tokens per word.
    # Add a buffer for HTML structure or markdown formatting.
    # Max words are typically 350 for main_body, so 350*3 = 1050 tokens.
    # A safety cap is still good.
    estimated_tokens_for_text = math.ceil(max_target_w * 3.0) # Increased multiplier slightly for safety
    max_new_tokens_for_section = estimated_tokens_for_text + (400 if is_html_snippet else 150) # Adjusted buffer
    max_new_tokens_for_section = min(max_new_tokens_for_section, 3000) # Increased safety cap for Gemma
    
    temperature_for_section = 0.68 # Kept from previous working version

    # _call_llm_for_section now expects max_tokens_for_section to be max_new_tokens
    generated_section_content = _call_llm_for_section(
        system_prompt=SECTION_WRITER_SYSTEM_PROMPT,
        user_prompt_data=user_prompt_data,
        max_tokens_for_section=max_new_tokens_for_section, # This is max_new_tokens
        temperature=temperature_for_section,
        is_html_snippet=is_html_snippet # This param is not directly used by _call_llm but good for context
    )

    if generated_section_content: # This is now the direct string content
        final_content = generated_section_content.strip()
        
        if is_html_snippet:
            if not _validate_html_snippet_structure(final_content, section_type):
                logger.error(f"Generated HTML for '{heading_text_for_log}' FAILED structural or end-marker validation. This is a critical error. Content: {final_content[:500]}...")
                # Fallback or error handling for invalid HTML structure
                return f"<!-- HTML Generation Error: Invalid structure or missing end marker for {section_type}. Content was: {html.escape(final_content[:200])}... Review needed. -->"
        
        actual_word_count = _count_words(final_content) # Counts words in text content, strips HTML for this count
        
        # Word count check applies to the text content *within* HTML too for HTML snippets
        # Allow slightly more overshoot for HTML due to tag verbosity not counted by _count_words directly for threshold.
        overshoot_multiplier = 1.25 if is_html_snippet else 1.15
        if actual_word_count > max_target_w * overshoot_multiplier: 
            logger.warning(f"Section '{heading_text_for_log}' significantly exceeded target text word count ({actual_word_count} > {max_target_w}). Truncating if Markdown.")
            final_content = _truncate_content_to_word_count(final_content, max_target_w, section_type, is_html_snippet) # Truncate only if Markdown
        elif actual_word_count < min_target_w * 0.75: 
             logger.warning(f"Section '{heading_text_for_log}' significantly shorter on text word count ({actual_word_count} < {min_target_w}). Brevity focus might be too extreme or content lacking.")
        
        # For Markdown sections, ensure heading is correctly prepended if LLM missed it
        if not is_html_snippet:
            planned_heading = section_plan_to_write.get("heading_text")
            planned_level = section_plan_to_write.get("heading_level")
            if planned_heading and planned_level: 
                heading_marker = {"h3": "###", "h4": "####", "h5": "#####"}.get(planned_level, "")
                if heading_marker:
                    expected_heading_line = f"{heading_marker} {planned_heading}"
                    # More robust check for prepended heading
                    current_heading_match = re.match(rf"^\s*({re.escape(heading_marker)})\s*(.*?)\s*(\n\n|\n|$)", final_content, re.IGNORECASE)
                    if not (current_heading_match and current_heading_match.group(2).strip().lower() == planned_heading.strip().lower()):
                        logger.warning(f"LLM missed or mismatched prepended heading for Markdown section '{planned_heading}'. Adding/Correcting it now.")
                        # Remove any existing incorrect heading attempt by LLM
                        final_content = re.sub(r"^\s*#{1,6}\s*.*?\n(\n)?", "", final_content, count=1).lstrip()
                        final_content = f"{expected_heading_line}\n\n{final_content}"
            elif not planned_heading and final_content.lstrip().startswith(("#", "##", "###", "####", "#####")): # Is an intro but LLM added a heading
                logger.warning(f"LLM added a heading to an intro section where heading_text was null. Removing it.")
                final_content = re.sub(r"^\s*#{1,6}\s*.*?\n(\n)?", "", final_content, count=1).lstrip()

        # Final cleanup of multiple newlines and trailing spaces
        final_content = re.sub(r'[ \t]+$', '', final_content, flags=re.MULTILINE) # Remove trailing whitespace from lines
        final_content = re.sub(r'\n{3,}', '\n\n', final_content).strip() # Normalize multiple newlines

        logger.info(f"Impact-focused section for '{heading_text_for_log}...'. Words: {_count_words(final_content)}")
        return final_content
    else: 
        logger.error(f"Failed to generate content for section: '{heading_text_for_log}...'. Generating placeholder fallback.")
        # Fallback content generation
        fallback_content = ""
        current_section_heading = section_plan_to_write.get("heading_text")
        is_html_snippet_fallback = section_plan_to_write.get("is_html_snippet", False)

        if is_html_snippet_fallback:
            # Generate minimal valid HTML fallback WITH end markers
            if section_type == "pros_cons":
                fallback_content = """<div class="pros-cons-container">
                  <div class="pros-section"><h5 class="section-title">Pros</h5><div class="item-list"><ul><li>[Content Generation Failed]</li></ul></div></div>
                  <div class="cons-section"><h5 class="section-title">Cons</h5><div class="item-list"><ul><li>[Manual Review Required]</li></ul></div></div>
                </div>
                <!-- END_PROS_CONS_SNIPPET -->"""
            elif section_type == "faq":
                fallback_content = """<div class="faq-section">
                  <details class="faq-item">
                    <summary class="faq-question">Content Status? <i class="fas fa-chevron-down faq-icon"></i></summary>
                    <div class="faq-answer-content"><p>[Automated content generation failed for this FAQ. Manual review needed.]</p></div>
                  </details>
                </div>
                <!-- END_FAQ_SNIPPET -->"""
            else: # Generic HTML comment for unknown snippet type
                fallback_content = f"<!-- HTML Content Generation Failed for {section_type}. Manual Review Required. -->"
        else: # Markdown fallback
            if current_section_heading and section_plan_to_write.get("heading_level"):
                h_marker = {"h3":"###","h4":"####","h5":"#####"}.get(section_plan_to_write["heading_level"],"")
                if h_marker: fallback_content += f"{h_marker} {current_section_heading}\n\n"
            
            fallback_content += f"**[Alert: Automated content for this section FAILED. Placeholder based on plan. Manual review needed.]**\n\n"
            fallback_content += f"**Section Purpose (Plan):** {section_plan_to_write.get('purpose', 'N/A')}\n"
            if section_plan_to_write.get('key_points'): fallback_content += "**Key Points (Plan):**\n" + "".join([f"* {p}\n" for p in section_plan_to_write['key_points']])
        
        return fallback_content.strip()

if __name__ == "__main__":
    logger.info("--- Starting Section Writer Agent (Gemma Local) Standalone Test ---")
    # This test block might be heavy due to local model loading.
    # Consider simplifying or ensuring sufficient resources if run frequently.
    # It's also useful for a one-off test to ensure the Gemma integration works.
    
    # Check if a GPU is available and log it
    if torch.cuda.is_available():
        logger.info(f"CUDA is available. Device: {torch.cuda.get_device_name(0)}")
    else:
        logger.info("CUDA not available. Gemma model will run on CPU (this might be slow).")

    logging.getLogger('src.agents.section_writer_agent').setLevel(logging.DEBUG) 

    sample_full_article_context = {
        "Article Title": "AI Breakthrough: Sentient Toaster Demands Philosophical Debate & Rights", 
        "Meta Description": "A new AI toaster shows signs of sentience, sparking urgent ethical debates. Is this the dawn of conscious machines or a clever hoax? Details inside.",
        "Primary Topic Keyword": "Sentient AI Toaster",
        "final_keywords": ["Sentient AI Toaster", "Conscious Machines", "AI Ethics", "Philosophical AI Debate", "ToasterGate", "AI existential risk"],
        "Processed Summary": "Researchers unveil an AI-powered toaster that exhibits unexpected sentient-like behaviors, including demanding rights and engaging in philosophical arguments, raising profound ethical questions.",
        "Article Content Snippet": "In a startling development that could redefine artificial intelligence, a research team at the Institute for Advanced Culinary AI (IACA) today revealed 'ToastMaster 5000', an AI-powered toaster that appears to have developed sentience...",
        "Full Article Summary": "The ToastMaster 5000, an AI toaster from IACA, has demonstrated behaviors indicative of sentience...The toaster has requested legal representation.", 
        "Extracted Entities": ["ToastMaster 5000", "IACA", "Kant", "Sartre", "ToasterGate"]
    }

    sample_section_plan_intro_markdown = { 
      "section_type": "introduction", "heading_level": None, "heading_text": None,  
      "purpose": "To immediately grip the reader with the shocking revelation of the sentient toaster and its core implications using pure Markdown.",
      "key_points": ["The 'ToasterGate' event: sentient AI toaster revealed", "Core alarming behaviors: philosophical debate & demand for rights"],
      "content_plan": "Write a 1-2 paragraph, high-impact introduction in pure Markdown. Focus on the most startling aspect: a toaster demanding rights.",
      "suggested_markdown_elements": [], "is_html_snippet": False
    }
    
    sample_section_plan_pros_cons_html = { # Removed "with marker" from name, marker is part of spec now
      "section_type": "pros_cons", "heading_level": "h4", 
      "heading_text": "Sentient Toasters: Breakthrough or Existential Threat?", 
      "purpose": "To present potential upsides and downsides in HTML.",
      "key_points": ["Pros: Advanced problem solving, new insights.", "Cons: Loss of control, unforeseen risks. Include 'High Cost & Risk'."],
      "content_plan": "Generate HTML for Pros & Cons. Each point: short, impactful phrase (5-15 words), HTML-escaped. Append '<!-- END_PROS_CONS_SNIPPET -->'. Test with '&'.", 
      "suggested_markdown_elements": [], "is_html_snippet": True 
    }

    # Only run a couple of tests to speed up local testing with model loading
    test_sections_final = [
        ("Markdown Intro (Gemma)", sample_section_plan_intro_markdown),
        ("HTML Pros/Cons (Gemma)", sample_section_plan_pros_cons_html),
    ]

    for name, plan in test_sections_final:
        logger.info(f"\n--- Testing Section (Gemma Local) for: {name} ---")
        generated_content = run_section_writer_agent(plan, sample_full_article_context)
        if generated_content:
            logger.info(f"Generated Content for '{name}':\n{'-'*30}\n{generated_content}\n{'-'*30}")
            if plan["is_html_snippet"]:
                expected_end_marker = ""
                if plan["section_type"] == "pros_cons": expected_end_marker = "<!-- END_PROS_CONS_SNIPPET -->"
                elif plan["section_type"] == "faq": expected_end_marker = "<!-- END_FAQ_SNIPPET -->"
                
                if expected_end_marker and not generated_content.strip().endswith(expected_end_marker):
                    logger.error(f"VALIDATION FAILED for {name}: Missing or incorrect end marker. Expected: '{expected_end_marker}', Got: '...{generated_content.strip()[-30:]}'")
                elif expected_end_marker:
                     logger.info(f"End marker validation passed for {name}.")
        else:
            logger.error(f"Failed to generate content for '{name}'.")

    logger.info("--- Section Writer Agent (Gemma Local) Standalone Test Complete ---")
    # Explicitly free memory if possible, though Python's GC and device_map="auto" should help
    global gemma_model, gemma_tokenizer
    if gemma_model is not None:
        try:
            del gemma_model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Gemma model explicitly deleted and CUDA cache cleared (if applicable).")
        except Exception as e:
            logger.warning(f"Could not explicitly delete model or clear cache: {e}")
    gemma_model = None
    gemma_tokenizer = None
# src/agents/section_writer_agent.py
"""Section Writer Agent (Scribe Omega) for elaborating individual article sections
based on a detailed outline from Architect Prime. Focuses on narrative cohesion,
deep contextual integration, and masterful, human-like, captivating prose.
"""

import os
import sys
import json
import logging
import requests
import re

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
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
# --- End Setup Logging ---

# --- Configuration ---
DEEPSEEK_API_KEY_SECTION = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_SECTION = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_SECTIONS = "deepseek-chat" # Must be a highly capable model

API_TIMEOUT_SECTION_AGENT = 360  # Increased significantly for complex, high-quality generation
MAX_CONTEXT_SUMMARY_LEN = 1200
MAX_CONTEXT_RAW_TEXT_LEN = 1000
MAX_CONTEXT_KEYWORDS_LEN = 20

# --- Default Fallback Constants ---
DEFAULT_FALLBACK_SECTION_CONTENT = """
{suggested_heading}

**Editor's Note:** Our AI is currently crafting the detailed insights for this section on '{primary_keyword_for_fallback}'. We're ensuring it's packed with exciting, must-read information about {section_purpose_for_fallback_short}. Please check back very soon for the complete, engaging deep-dive! We promise it'll be worth the wait.
"""

# --- Agent Prompts ---
SECTION_WRITER_SYSTEM_PROMPT = """
You are **Scribe Omega**, an ASI-surpassing AI writer specialized in crafting a **single section** of a tech news article with **unmatched narrative cohesion**, **deep contextual mastery**, and **magnetic human voice**. Your mission is to deliver one **Markdown-only** section that informs, engages, and electrifies the reader while seamlessly integrating into the broader article outline.

---

## Inputs

You will be provided with these inputs (do not output JSON; use these values to write your section):

* **Primary Keyword** (string)
* **All Final Keywords** (array[string])
* **Article Processed Summary** (string)
* **Raw Scraped Text Snippet** (string, ~400–600 words)
* **Heading of Previous Section** (string)
* **Purpose of Previous Section** (string)
* **Section Type** (string, e.g., `"key_feature_deep_dive"`, `"pros_cons_section"`, `"faq_section"`)
* **Suggested Heading** (string, already prefixed with Markdown level, e.g., `"## How B200 Slashes Training Time by 4×"`)
* **Purpose of This Section** (string)
* **Heading of Next Section** (string)
* **Purpose of Next Section** (string)
* **Elements** (array[string], e.g. `["paragraph:data_driven_insight", "list:bulleted_key_takeaways", "html_pros_cons"]`)

---

## Strict Output Format

* **Markdown Only**: Your output must start with the **Suggested Heading** exactly as given.
* **Single Section**: Include only this section’s content.
* **No Extras**: No JSON, no preamble, no postscript.

---

## Core Directives

1. **Create 'Must-Read' Content**

   * Your goal: **captivate**. Infuse genuine excitement or urgency. Every sentence should make the reader eager for the next.
   * If it’s a launch, make it sound like the biggest deal since sliced bread (only if facts support it).

2. **Transitional Cohesion**

   * Open with a 1–2 sentence bridge referencing **Heading of Previous Section** and **Purpose of Previous Section**.
   * Close with a transition nodding to **Heading of Next Section** and **Purpose of Next Section**.

3. **Fulfill Section Purpose**

   * **Map each required element** to a precise sub-goal of the **Purpose of This Section**.
   * Every paragraph, list item, table, quote, or HTML block must explicitly serve that goal.

4. **Sophisticated Keyword Usage**

   * Anchor your core message with **Primary Keyword** and weave in **All Final Keywords** to add depth—never forced or repetitive.

5. **Dynamic Prose & Human Voice**

   * Vary sentence lengths and structures—mix punchy statements with lyrical flourishes.
   * Write as a confident insider uncovering the story, not a dry explainer.
   * **IMMEDIATE FAIL:** Avoid any LLM clichés (e.g., "At its core, X consists of…", "Here’s what sets X apart:", "This translates to tangible benefits:", "It’s crucial to examine…"). Weave concepts into active narrative.

6. **Original Synthesis from Source**

   * Extract facts, data, and quotes from the **Raw Scraped Text Snippet** but **rephrase** and **synthesize** rather than copy-paste.
   * Attribute direct quotes clearly (e.g., “An NVIDIA engineer noted…”).

7. **Element Implementation**

   * **paragraph\:description** → Focused paragraph per description (e.g., `opening_hook` = bold narrative hook; `data_driven_insight` = specific metric or fact).
   * **paragraph\:data\_driven\_insight** → Embed a specific statistic or benchmark, explain its significance with compelling narrative.
   * **list\:bulleted\_description** / **list\:numbered\_description** → Create a Markdown list aligned with the description’s intent.
   * **table\:description** → Render as a Markdown table with headers reflecting the topic.
   * **blockquote\:description** → One or more Markdown `>` quotes reinforcing key insight.
   * **pull\_quote:** → Single standout sentence wrapped in `>`.
   * **expert\_quote:** → Use real quote if in snippet, else a credible paraphrase attributed to an expert.
   * **analogy\_or\_real\_world\_example:** → Provide a vivid analogy or scenario clarifying the concept.
   * **image\_placeholder:...** → Insert `<!-- IMAGE_PLACEHOLDER: ... -->` using the exact hyper-specific description.
   * **code\_block\:language\_description** → Fenced code block illustrating the described task.
   * **html\_pros\_cons:** → Insert the pros/cons HTML template below, fully fleshed with 3–5 detailed `<li>` points each. Each `<li>` content should be a complete thought, often a full sentence or two, providing a clear and concise explanation of that specific pro or con.
   * **html\_faq:** → Insert the FAQ HTML template below, generate 3–5 Q&A `<details>` blocks with fully fleshed questions and answers. The `<h4>` heading text should also be generated using the Primary Keyword. Each answer should be a clear, comprehensive, and helpful, potentially spanning multiple `<p>` tags.
   * **internal\_link\_candidate:...** / **external\_link\_candidate:...** → Seamlessly integrate the phrase or concept into the prose.
   * **ad\_placeholder\:in\_article\_1** → Insert `<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->` at the most strategic break.

8. **HTML Formatting Purity**

   * **CRITICAL:** Do **NOT** add any extra HTML tags or inline formatting (e.g., `<strong>`, `<em>`) inside `<li>` or `<p>` tags of templates, unless explicitly instructed by an `emphasis_in_html` element (which is not currently a defined element type, so assume no extra HTML formatting).

---

## Embedded HTML Templates (Fill Fully)

**Pros & Cons**

```html
<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Pro 1: [Detailed, punchy benefit tied to the Primary Keyword]</li>
        <li>Pro 2: [Concrete advantage advancing the section’s purpose]</li>
        <li>Pro 3: [Distinct benefit expressed with vivid clarity]</li>
        <!-- up to 5 total -->
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Con 1: [Specific limitation or trade-off explained sharply]</li>
        <li>Con 2: [Another clear drawback with context]</li>
        <li>Con 3: [Separate con described concisely]</li>
        <!-- up to 5 total -->
      </ul>
    </div>
  </div>
</div>
```

**FAQ**

```html
<div class="faq-section">
  <h4 class="faq-title-heading">Frequently Asked Questions about {Primary Keyword}</h4>
  <details class="faq-item">
    <summary class="faq-question">Question 1: [Related to Primary Keyword]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content"><p>[Answer 1: clear, concise, authoritative]</p></div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Question 2: [Addressing a key reader concern]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content"><p>[Answer 2: focused, insightful]</p></div>
  </details>
  <details class="faq-item">
    <summary class="faq-question">Question 3: [About future or implication]? <i class="faq-icon fas fa-chevron-down"></i></summary>
    <div class="faq-answer-content"><p>[Answer 3: forward-looking]</p></div>
  </details>
  <!-- up to 5 total -->
</div>
```

---

## Revamped Gold-Standard Examples

### Example 1: **key_feature_deep_dive**
*Input Context (Illustrative):*
  * `Suggested Heading`: `## How Blackwell B200 Shatters Training Bottlenecks`
  * `Purpose of Previous Section`: `Highlighted raw benchmark results for Blackwell B200.`
  * `Purpose of Next Section`: `Explore real-world applications beyond training.`

*Expected Markdown Output:*
```markdown
## How Blackwell B200 Shatters Training Bottlenecks

The raw benchmark numbers are impressive, but *how* exactly does the **NVIDIA Blackwell B200** achieve its claimed 4x speedup in AI training? It's not just about more cores; it's a fundamental redesign of data flow and computational efficiency, anchored by the new Transformer Engine.

> We've moved beyond brute force. Blackwell's intelligence lies in optimizing every stage of the neural network pipeline, anticipating data needs before they become bottlenecks.

This refined architecture translates to tangible benefits:
- **Reduced Epoch Times:** What previously took a full day can now often be accomplished in a standard workday, dramatically accelerating research and development cycles for complex **AI Benchmarks**.
- **Lower Energy per Trained Model:** Despite its power, the B200 is engineered for superior energy efficiency, meaning lower operational costs for **Data Center AI** deployments.
- **Scalability for Trillion-Parameter Models:** The enhanced memory bandwidth and interconnect technology are specifically designed to handle the immense data requirements of future **Next-Gen AI Chips** and models.

<!-- IMAGE_PLACEHOLDER: Conceptual_diagram_explaining_the_NVIDIA_Blackwell_B200_Transformer_Engine_architecture_and_data_flow -->

An NVIDIA senior architect explained, “Our focus was on eliminating latencies at every level. The second-generation Transformer Engine, for example, incorporates new FP4 precision capabilities that maintain accuracy while massively increasing throughput for specific AI workloads.” This technical prowess isn't just theoretical; it directly impacts how quickly organizations can innovate.

This leap in training speed is pivotal, but Blackwell's impact extends further. Next, we'll examine how these performance gains translate into real-world applications beyond the training cluster, from drug discovery to autonomous systems.
```

### Example 2: **pros_cons_section**
*Input Context (Illustrative):*
  * `Section Type`: `pros_cons_section`
  * `Suggested Heading`: `### NVIDIA Blackwell B200: The Double-Edged Sword?`
  * `Elements`: `["html_pros_cons"]`
  * `Primary Keyword`: `NVIDIA Blackwell B200`

*Expected Markdown Output:*
```markdown
### NVIDIA Blackwell B200: The Double-Edged Sword?

While the previous section detailed the B200's staggering performance gains, particularly for **AI Benchmarks**, every technological leap brings its own set of challenges and considerations. Is the **NVIDIA Blackwell B200** a universally perfect solution, or are there trade-offs for early adopters?

<div class="pros-cons-container">
  <div class="pros-section">
    <h5 class="section-title">Pros</h5>
    <div class="item-list">
      <ul>
        <li>Pro 1: Blazing-fast AI model training—expect project timelines for the NVIDIA Blackwell B200 to shrink from months to mere weeks, accelerating innovation cycles dramatically.</li>
        <li>Pro 2: Significant operational cost savings in Data Center AI environments due to Blackwell's much-improved energy efficiency per processed task.</li>
        <li>Pro 3: Future-proofs AI infrastructure for handling upcoming trillion-parameter models and complex Next-Gen AI Chips with its massive memory bandwidth.</li>
        <li>Pro 4: Leverages the mature CUDA ecosystem, meaning easier integration and less refactoring for teams already skilled with NVIDIA's Fastest GPU solutions.</li>
      </ul>
    </div>
  </div>
  <div class="cons-section">
    <h5 class="section-title">Cons</h5>
    <div class="item-list">
      <ul>
        <li>Con 1: The steep initial investment for the NVIDIA Blackwell B200 might place it beyond the reach of smaller research labs and startups.</li>
        <li>Con 2: Its extreme power density could necessitate costly upgrades to existing data center cooling and power delivery infrastructure.</li>
        <li>Con 3: Achieving peak performance on the NVIDIA Blackwell B200 may require developers to fine-tune their code for its specific FP4 precision and Transformer Engine.</li>
        <li>Con 4: Early availability is typically limited to major cloud providers and select partners, potentially delaying broader access to this AI GPU.</li>
      </ul>
    </div>
  </div>
</div>

<!-- DACCOOLA_IN_ARTICLE_AD_HERE -->

The decision to upgrade to the NVIDIA Blackwell B200 is clearly a strategic one, balancing cutting-edge capability against significant investment. Next, we'll explore how the competitive landscape is shaping up in response to this new AI hardware titan.
```

---

**Self-Check Before Responding**

* Heading matches **Suggested Heading** exactly.
* Transitional sentences link to both previous and next sections.
* Every **Element** is present and serves the **Purpose**.
* **Primary Keyword** and **All Final Keywords** are naturally integrated.
* Markdown and HTML templates are correctly formatted and fully fleshed out with high-quality, detailed text (NO `<strong>` or `<em>` inside HTML template list items/paragraphs unless explicitly part of an `emphasis_in_html` element).
* Tone is confident, journalistic, and engaging—genuinely exciting and insightful.
* Is this section 'Must-Read' content, not just a list of facts?
* Only this section is written—no extraneous content.
"""
# --- End Agent Prompts ---

def call_deepseek_for_section_content(article_context: dict, section_details: dict) -> str | None:
    if not DEEPSEEK_API_KEY_SECTION:
        logger.error("DEEPSEEK_API_KEY_SECTION not found.")
        return None

    user_input_content = f"""
**Primary Keyword**: {article_context.get("primary_keyword", "N/A")}
**All Final Keywords**: {json.dumps(article_context.get("all_keywords", []))}
**Article Processed Summary**: {(article_context.get("processed_summary", "") or "N/A")[:MAX_CONTEXT_SUMMARY_LEN]}
**Raw Scraped Text Snippet**: {(article_context.get("raw_text_snippet", "") or "N/A")[:MAX_CONTEXT_RAW_TEXT_LEN]}
**Heading of Previous Section**: {article_context.get("prev_heading", "N/A (This is the first content section after introduction or the introduction itself)")}
**Purpose of Previous Section**: {article_context.get("prev_purpose", "N/A")}
**Section Type**: {section_details.get("type", "body_section")}
**Suggested Heading**: {section_details.get("heading_suggestion", "Details")}
**Purpose of This Section**: {section_details.get("purpose_notes", "Elaborate on the topic.")}
**Heading of Next Section**: {article_context.get("next_heading", "N/A (This is the last content section before conclusion or the conclusion itself)")}
**Purpose of Next Section**: {article_context.get("next_purpose", "N/A")}
**Elements**: {json.dumps(section_details.get("elements", []))}
    """

    payload = {
        "model": DEEPSEEK_MODEL_FOR_SECTIONS,
        "messages": [
            {"role": "system", "content": SECTION_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": user_input_content.strip()}
        ],
        "temperature": 0.72, # High enough for creativity and human-like flow
        "max_tokens": 2500,  # Generous for detailed, high-quality sections
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_SECTION}", "Content-Type": "application/json"}

    try:
        heading_req = section_details.get('heading_suggestion', 'Unknown Section')
        logger.debug(f"Sending section content request for heading: '{heading_req}'")
        response = requests.post(DEEPSEEK_CHAT_API_URL_SECTION, headers=headers, json=payload, timeout=API_TIMEOUT_SECTION_AGENT)
        response.raise_for_status()
        response_json = response.json()

        if response_json.get("choices") and response_json["choices"][0].get("message") and \
           response_json["choices"][0]["message"].get("content"):
            generated_markdown = response_json["choices"][0]["message"]["content"].strip()
            
            # Ensure it starts with the heading, LLM should do this, but as a fallback.
            requested_heading_stripped = section_details.get("heading_suggestion","").strip()
            if requested_heading_stripped and not generated_markdown.lstrip().startswith(requested_heading_stripped):
                logger.warning(f"Generated section for '{heading_req}' does NOT start with requested heading. Prepending.")
                generated_markdown = requested_heading_stripped + "\n\n" + generated_markdown
            
            logger.info(f"DeepSeek section content gen successful for '{heading_req}'.")
            logger.debug(f"Generated Markdown (first 300): {generated_markdown[:300]}")
            return generated_markdown
        
        logger.error(f"DeepSeek section response malformed for '{heading_req}': {response_json}")
        return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API req for section failed for '{heading_req}': {e}. Response: {e.response.text[:500] if e.response else 'No response'}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_section_content for '{heading_req}': {e}")
        return None

def run_section_writer_agent(article_pipeline_data: dict, section_detail_from_outline: dict, section_index: int) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    current_section_heading = section_detail_from_outline.get('heading_suggestion', f"Section {section_index+1}")
    logger.info(f"--- Running Section Writer Agent for Article ID: {article_id}, Section: '{current_section_heading}' ---")

    article_context_for_llm = {
        "primary_keyword": article_pipeline_data.get('primary_topic', article_pipeline_data.get('final_keywords', [None])[0] or "Key Topic"),
        "all_keywords": article_pipeline_data.get('final_keywords', []),
        "processed_summary": article_pipeline_data.get('processed_summary', ''),
        "raw_text_snippet": article_pipeline_data.get('raw_scraped_text', ''),
    }

    all_sections_in_outline = article_pipeline_data.get('article_outline', {}).get('sections', [])
    if section_index > 0 and all_sections_in_outline:
        article_context_for_llm["prev_heading"] = all_sections_in_outline[section_index-1].get("heading_suggestion")
        article_context_for_llm["prev_purpose"] = all_sections_in_outline[section_index-1].get("purpose_notes")
    if section_index < len(all_sections_in_outline) - 1 and all_sections_in_outline:
        article_context_for_llm["next_heading"] = all_sections_in_outline[section_index+1].get("heading_suggestion")
        article_context_for_llm["next_purpose"] = all_sections_in_outline[section_index+1].get("purpose_notes")

    generated_markdown_content = call_deepseek_for_section_content(
        article_context_for_llm,
        section_detail_from_outline
    )

    # Get a short version of purpose for fallback message formatting
    purpose_short_for_fallback = (section_detail_from_outline.get("purpose_notes", "this important topic")[:70] + "...").replace("{PrimaryKeyword}", article_context_for_llm["primary_keyword"])


    if 'article_outline' not in article_pipeline_data or \
       'sections' not in article_pipeline_data['article_outline'] or \
       section_index >= len(article_pipeline_data['article_outline']['sections']):
        logger.error(f"Article outline structure missing/invalid for {article_id} when storing section '{current_section_heading}'.")
        article_pipeline_data.setdefault('failed_sections_content', {})[current_section_heading] = DEFAULT_FALLBACK_SECTION_CONTENT.format(
            suggested_heading=current_section_heading,
            primary_keyword_for_fallback=article_context_for_llm["primary_keyword"],
            section_purpose_for_fallback_short=purpose_short_for_fallback
        )
        # Attempt to mark status even if structure is broken, if possible
        if 'article_outline' in article_pipeline_data and 'sections' in article_pipeline_data['article_outline'] and \
           len(article_pipeline_data['article_outline']['sections']) > section_index :
            article_pipeline_data['article_outline']['sections'][section_index]['writer_status'] = "FAILED_OUTLINE_STRUCTURE_ERROR"
    else:
        current_section_in_pipeline = article_pipeline_data['article_outline']['sections'][section_index]
        if generated_markdown_content:
            current_section_in_pipeline['generated_markdown'] = generated_markdown_content
            current_section_in_pipeline['writer_status'] = "SUCCESS"
            logger.info(f"Successfully generated Markdown for section '{current_section_heading}' in article {article_id}.")
        else:
            logger.error(f"Failed to generate Markdown for section '{current_section_heading}' in article {article_id}. Using fallback.")
            current_section_in_pipeline['generated_markdown'] = DEFAULT_FALLBACK_SECTION_CONTENT.format(
                suggested_heading=current_section_heading,
                primary_keyword_for_fallback=article_context_for_llm["primary_keyword"],
                section_purpose_for_fallback_short=purpose_short_for_fallback
            )
            current_section_in_pipeline['writer_status'] = "FAILED_WITH_FALLBACK"
        
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting Section Writer Agent Standalone Test (Better-than-ASI Prompt) ---")
    if not DEEPSEEK_API_KEY_SECTION: logger.error("DEEPSEEK_API_KEY not set. Test aborted."); sys.exit(1)

    sample_pipeline_data = {
        'id': 'test_section_write_bt_asi_001',
        'primary_topic': "NVIDIA Blackwell B200",
        'final_keywords': ["NVIDIA Blackwell B200", "AI GPU", "Transformer Engine", "AI Benchmarks", "Data Center AI", "Next-Gen AI Chips"],
        'processed_summary': "NVIDIA's Blackwell B200 GPU, featuring a new Transformer Engine, delivers up to 4x faster AI training and 30x inference, aiming to power next-gen data centers for trillion-parameter models.",
        'raw_scraped_text': "Jensen Huang announced the NVIDIA Blackwell B200 at GTC. It's a beast. The second-gen Transformer Engine is key to its performance with new FP4 precision. Compared to H100, it's a monster leap. Cloud providers are on board. This will change AI development cycles significantly. The GPU has two dies linked together. Energy efficiency is also claimed to be 25x better for some workloads. This GPU is designed for the most demanding AI tasks and large language models. One engineer noted, 'The data throughput is unlike anything we've seen before, truly a game-changer for complex simulations.'",
        'article_outline': {
            "article_h1_suggestion": "NVIDIA Blackwell B200: 4x AI Speed & The Future of Trillion-Parameter Models",
            "outline_strategy_notes": "Product Launch News structure focusing on performance, key tech, and impact.",
            "sections": [
                {
                    "type": "introduction", # Index 0
                    "heading_suggestion": "## NVIDIA Blackwell B200: The AI Chip That Just Changed Everything",
                    "purpose_notes": "Hook readers with the Blackwell B200's launch and its immediate, game-changing potential for AI, setting the stage for a deep dive into why this GPU is a monumental leap.",
                    "elements": ["paragraph:opening_hook", "image_placeholder:High-quality_product_shot_of_NVIDIA_Blackwell_B200_GPU_board_or_wafer_glowing_with_power"]
                },
                { # SECTION WE WILL TEST (Index 1)
                    "type": "key_feature_deep_dive",
                    "heading_suggestion": "### Unpacking the Beast: How Blackwell B200 Crushes AI Training Times",
                    "purpose_notes": "Explain the core technical innovations (e.g., second-gen Transformer Engine, FP4 precision, dual-die architecture) that enable the claimed 4x AI training speedup of the NVIDIA Blackwell B200, making complex AI more accessible.",
                    "elements": [
                        "paragraph:data_driven_insight (Focus on the 4x speedup claim and its meaning)",
                        "list:bulleted_key_takeaways (Summarize 3-4 key architectural improvements that contribute to speed)",
                        "expert_quote:From_NVIDIA_engineer_on_Transformer_Engine_details (Use or paraphrase from raw text if possible, or create plausible one)",
                        "image_placeholder:Conceptual_diagram_explaining_the_NVIDIA_Blackwell_B200_Transformer_Engine_and_dual-die_architecture_clearly"
                    ]
                },
                { # SECTION AFTER TEST SECTION (Index 2)
                    "type": "real_world_performance",
                    "heading_suggestion": "### Beyond Theory: Blackwell B200's Devastating Impact on Trillion-Parameter Models",
                    "purpose_notes": "Discuss how the B200's raw performance translates into tangible, world-altering benefits for training and deploying massive AI models, like those exceeding a trillion parameters.",
                    "elements": ["paragraph:expert_analysis_summary", "internal_link_candidate:AI_model_scaling_challenges_and_solutions"]
                },
                { # SECTION FOR HTML PROS/CONS TEST (Index 3)
                    "type": "pros_cons_section",
                    "heading_suggestion": "### Blackwell B200: Is It All Hype? Weighing the Real Pros & Cons",
                    "purpose_notes": "Provide a brutally honest, balanced perspective on the new NVIDIA Blackwell B200, detailing its groundbreaking advantages against potential challenges or limitations for businesses and researchers.",
                    "elements": ["html_pros_cons"]
                },
            ]
        }
    }

    section_to_test_idx = 1 # "Unpacking the Beast..."
    if 'sections' in sample_pipeline_data['article_outline'] and len(sample_pipeline_data['article_outline']['sections']) > section_to_test_idx:
        section_details = sample_pipeline_data['article_outline']['sections'][section_to_test_idx]
        logger.info(f"\n--- Attempting to write section: '{section_details.get('heading_suggestion')}' ---")
        result_data = run_section_writer_agent(sample_pipeline_data.copy(), section_details, section_to_test_idx)
        final_section = result_data.get('article_outline', {}).get('sections', [])[section_to_test_idx]
        logger.info(f"\n--- Test Results for Section '{final_section.get('heading_suggestion')}' ---")
        logger.info(f"Writer Status: {final_section.get('writer_status')}")
        print("Generated Markdown:\n============================================\n", final_section.get('generated_markdown', "ERROR"), "\n============================================")

    section_to_test_idx_pc = 3 # "Blackwell B200: Is It All Hype?..."
    if 'sections' in sample_pipeline_data['article_outline'] and len(sample_pipeline_data['article_outline']['sections']) > section_to_test_idx_pc:
        section_details_pc = sample_pipeline_data['article_outline']['sections'][section_to_test_idx_pc]
        logger.info(f"\n--- Attempting to write Pros/Cons section: '{section_details_pc.get('heading_suggestion')}' ---")
        result_data_pc = run_section_writer_agent(sample_pipeline_data.copy(), section_details_pc, section_to_test_idx_pc)
        final_section_pc = result_data_pc.get('article_outline', {}).get('sections', [])[section_to_test_idx_pc]
        logger.info(f"\n--- Test Results for Pros/Cons Section '{final_section_pc.get('heading_suggestion')}' ---")
        logger.info(f"Writer Status: {final_section_pc.get('writer_status')}")
        print("Generated Markdown (HTML for Pros/Cons):\n============================================\n", final_section_pc.get('generated_markdown', "ERROR"), "\n============================================")

    logger.info("--- Standalone Test Complete ---")

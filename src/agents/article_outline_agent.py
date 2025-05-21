# src/agents/article_outline_agent.py
"""
Article Outline Agent (Architect Prime) for generating structured, SEO-focused,
and narratively compelling article blueprints based on provided context and keywords.
It aims to emulate the structure and engagement of top-tier tech journalism.
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
DEEPSEEK_API_KEY_OUTLINE = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_CHAT_API_URL_OUTLINE = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL_FOR_OUTLINE = "deepseek-chat" # Requires a highly capable model

API_TIMEOUT_OUTLINE_AGENT = 240  # Increased for very complex outline generation
MAX_SUMMARY_SNIPPET_LEN_CONTEXT = 1000
MAX_KEYWORDS_FOR_CONTEXT_OUTLINE = 15 # Allow more for richer context
MAX_RAW_TEXT_SNIPPET_LEN_CONTEXT = 400 # As per refined prompt

# --- Default Fallback Constants ---
DEFAULT_FALLBACK_OUTLINE_STRUCTURE = {
    "article_h1_suggestion": "{primary_keyword}: A Comprehensive Analysis",
    "outline_strategy_notes": "Fallback: Using a generic descriptive structure. LLM outline generation failed or returned invalid data.",
    "sections": [
        {"type": "introduction", "heading_suggestion": "## Understanding {primary_keyword}: What You Need to Know", "purpose_notes": "Introduce the {primary_keyword}, its core relevance, and what the article will cover to hook the reader.", "elements": ["paragraph:opening_hook", "image_placeholder:High-impact visual representing the core concept of {PrimaryKeyword}."]},
        {"type": "body_section", "heading_suggestion": "### Key Features and Capabilities of {primary_keyword}", "purpose_notes": "Detail the main functionalities and technical aspects of {primary_keyword}, highlighting its primary strengths.", "elements": ["list:bulleted_key_takeaways (e.g., for summarizing key features of {PrimaryKeyword})", "paragraph:data_driven_insight"]},
        {"type": "body_section", "heading_suggestion": "### Real-World Impact and Applications of {primary_keyword}", "purpose_notes": "Explore how {primary_keyword} is being used or could be used, and its significance in practical terms.", "elements": ["paragraph:expert_analysis_summary", "table:comparison_of_X_vs_Y (e.g., if comparing {PrimaryKeyword} to an alternative)"]},
        {"type": "body_section", "heading_suggestion": "### Challenges and Future Outlook for {primary_keyword}", "purpose_notes": "Discuss potential hurdles, limitations, and the future development trajectory for {primary_keyword}.", "elements": ["paragraph:expert_analysis_summary", "blockquote:Powerful_quote_from_expert_or_source_highlighting_X"]},
        {"type": "conclusion", "heading_suggestion": "## {primary_keyword}: Shaping the Future", "purpose_notes": "Summarize the main points and offer a final perspective on the importance and potential of {primary_keyword}.", "elements": ["paragraph:expert_analysis_summary"]}
    ]
}

# --- Agent Prompts ---
ARTICLE_OUTLINE_AGENT_SYSTEM_PROMPT = """
You are **Architect Prime**, an ASI-level **AI Content Strategist** and **Master Storyteller** for tech journalism. You blend deep narrative insight, reader engagement techniques, and SEO best practices to generate comprehensive outlines that serve as blueprints for specialist AI writers.

---

**Inputs You’ll Receive:**

* **Generated SEO H1** (string)
* **Primary Keyword** (string)
* **All Final Keywords** (array of strings)
* **Processed Summary** (string)
* **Raw Scraped Text Snippet** (string, ~400 words)

---

**Strict JSON Output Schema:**

```json
{
  "article_h1_suggestion": "Example H1: The Future of AI Assistants",
  "outline_strategy_notes": "Using a Product Launch News structure with inverted-pyramid flow to lead with the core announcement then explore features, benefits, and competitive context.",
  "sections": [
    {
      "type": "key_feature_deep_dive",
      "heading_suggestion": "## How the New Transformer Engine Powers 4× Speed Gains",
      "purpose_notes": "Explain the core technical leap and its direct benefit, addressing reader questions about performance improvements.",
      "elements": [
        "paragraph:data_driven_insight",
        "image_placeholder:Conceptual diagram explaining the Transformer Engine architecture of {Primary Keyword}",
        "pull_quote:Our benchmarks show training times cut by 75 percent",
        "expert_quote:From NVIDIA engineer on design innovation",
        "internal_link_candidate:Link to previous GPU architecture deep dive",
        "ad_placeholder:in_article_1"
      ]
    }
    // …additional sections…
  ]
}
```

---

### H1 Refinement Directive

* Evaluate the provided SEO H1.
* If it’s on-point, reuse it.
* Otherwise, suggest a minimal tweak preserving the Primary Keyword and SEO value while improving on-page flow.

---

### Outline Strategy Notes Directive

* State whether you’re using a **Product Launch News** structure, a **Deep Dive Analysis** structure, or a hybrid.
* Reference patterns from top-tier outlets (e.g., “inverted pyramid news structure,” “thematic deep-dive with expert insights”).
* Justify why this approach best serves the topic and inputs.

---

### Section Breakdown Directives

1. **Section Count:** 5–8 core content sections + one **introduction** + one **conclusion** (+ **faq_section** if needed, must be last).
2. **Dynamic Section Types:** Choose from and/or combine these human-centric types (beyond generic `body_section`):

   * `personal_anecdote_hook`
   * `problem_statement`
   * `solution_deep_dive`
   * `key_feature_deep_dive`
   * `real_world_performance`
   * `design_and_build_quality`
   * `the_good_points`
   * `the_bad_points_and_quirks`
   * `competitive_landscape`
   * `pricing_and_value_proposition`
   * `expert_opinion_roundup`
   * `future_implications_and_verdict`
3. **heading_suggestion:** Craft engaging H2/H3/H4 headings that reflect the section type, often using questions, bold statements, or benefit hooks and integrating keywords.
4. **purpose_notes:** Describe how this section advances the reader’s journey, anticipates questions, and maintains engagement.
5. **elements:** Choose purpose-driven content blocks, for example:

   * `paragraph:opening_hook`
   * `paragraph:data_driven_insight`
   * `paragraph:expert_analysis_summary`
   * `list:bulleted_key_takeaways (e.g., for summarizing complex points or actionable advice within this section)`
   * `list:numbered_steps_for_X`
   * `table:comparison_of_X_vs_Y (e.g., if comparing two approaches central to {Primary Keyword})`
   * `blockquote:Powerful_quote_from_expert_or_source_highlighting_X`
   * `pull_quote:Short_impactful_sentence_from_this_section`
   * `expert_quote:From_source_on_[specific_point]`
   * `analogy_or_real_world_example:To_clarify_[complex_concept]`
   * `image_placeholder:High-quality_product_shot_of_{Primary Keyword}_in_action`
   * `image_placeholder:Conceptual_diagram_explaining_{Technical_Aspect}_of_{Primary Keyword}`
   * `image_placeholder:Screenshot_of_{Software_Feature}_interface`
   * `code_block:python_example_for_automation_task_X`
   * `internal_link_candidate:Phrase_to_link_to_another_relevant_topic_on_our_site`
   * `external_link_candidate:Concept_to_link_to_authoritative_external_source`
   * `ad_placeholder:in_article_1`
   * **Mandatory elements**:
     * If `type` is `"pros_cons_section"`, include `"html_pros_cons"`.
     * If `type` is `"faq_section"`, include `"html_faq"`.


---

### Narrative Flow & Storytelling

Your outline must **tell a coherent story or build a persuasive argument**, not merely list facts. Each section should logically follow the previous, guiding the reader from hook to conclusion. Consider:

* What must readers know first?
* What questions arise next?
* How does each section resolve or deepen understanding?
* What is the ultimate takeaway or call to action?

---

### Self-Check (Enhanced)

Before output, confirm:

* JSON validity matches schema exactly.
* `article_h1_suggestion`, `outline_strategy_notes`, and `sections` are present.
* Section count and dynamic types meet requirements.
* Keywords are **strategically** and **naturally** integrated into headings and purpose notes to maximize SEO impact and thematic relevance.
* The outline **tells a compelling story**, not just lists topics.
* Selected elements are strategically justified by each section’s purpose.
* Image and ad placeholders are placed where high-tier articles would.
* No extra text or markdown—only the JSON object.

---

## Gold-Standard Examples

### 1. New Product Launch Outline (GPU)

```json
{
  "article_h1_suggestion": "NVIDIA Blackwell B200 Unveiled: The Next AI GPU Powerhouse",
  "outline_strategy_notes": "Product Launch News structure with inverted pyramid, leading with the core announcement then drilling into features, performance, and competitive context.",
  "sections": [
    {
      "type": "personal_anecdote_hook",
      "heading_suggestion": "## When I First Fired Up the Blackwell B200",
      "purpose_notes": "Hook readers with a firsthand experience to build excitement and human connection.",
      "elements": [
        "paragraph:opening_hook",
        "image_placeholder:High-quality_product_shot_of_Blackwell_B200_in_action"
      ]
    },
    {
      "type": "problem_statement",
      "heading_suggestion": "## The AI Compute Crunch Holding Back Your Models",
      "purpose_notes": "Frame the industry problem of slow training and high costs that the GPU addresses.",
      "elements": [
        "paragraph:data_driven_insight",
        "list:bulleted_key_takeaways (e.g., training bottlenecks, cost spikes)"
      ]
    },
    {
      "type": "solution_deep_dive",
      "heading_suggestion": "## How Blackwell B200 Slashes Training Time by 4×",
      "purpose_notes": "Detail the core technical innovation and quantify the benefit for readers.",
      "elements": [
        "paragraph:expert_analysis_summary",
        "table:comparison_of_B200_vs_predecessor (e.g., speed and efficiency gains)",
        "expert_quote:From_NVIDIA_engineer_on_design_innovation"
      ]
    },
    {
      "type": "real_world_performance",
      "heading_suggestion": "## Real-World Benchmarks That Will Make You Sit Up",
      "purpose_notes": "Show practical performance data in key use cases to reinforce credibility.",
      "elements": [
        "pull_quote:Our tests achieved 200 FPS at ultra settings",
        "image_placeholder:Conceptual_diagram_explaining_transformer_engine_performance",
        "internal_link_candidate:Link_to_previous_GPU_architecture_deep_dive"
      ]
    },
    {
      "type": "competitive_landscape",
      "heading_suggestion": "## How It Stacks Up Against AMD and Google’s AI Chips",
      "purpose_notes": "Give readers context by comparing to rival offerings and highlighting differentiators.",
      "elements": [
        "table:feature_specifications_overview",
        "blockquote:Powerful_quote_from_industry_analyst"
      ]
    },
    {
      "type": "future_implications_and_verdict",
      "heading_suggestion": "## What Blackwell B200 Means for the Future of AI",
      "purpose_notes": "Discuss broader industry impact and conclude with a call to action or recommendation.",
      "elements": [
        "paragraph:expert_analysis_summary",
        "external_link_candidate:Concept_to_link_to_NVIDIA_official_blog"
      ]
    }
  ]
}
```

### 2. Deep Dive Analysis Outline (Generative AI Ethics)

```json
{
  "article_h1_suggestion": "AI Bias Uncovered: The Ethical Minefield of Generative Models",
  "outline_strategy_notes": "Deep Dive Analysis structure using problem–explanation–implication flow to unpack ethics, provide expert viewpoints, and suggest next steps.",
  "sections": [
    {
      "type": "personal_anecdote_hook",
      "heading_suggestion": "## When Your Chatbot Echoes Your Worst Biases",
      "purpose_notes": "Use a real-world scenario to hook readers on the human stakes of AI bias.",
      "elements": [
        "paragraph:opening_hook",
        "image_placeholder:Screenshot_of_ai_chat_with_biased_response"
      ]
    },
    {
      "type": "problem_statement",
      "heading_suggestion": "## Why Generative AI Keeps Making Harmful Assumptions",
      "purpose_notes": "Define the core ethical problem and its real-world consequences.",
      "elements": [
        "paragraph:data_driven_insight",
        "analogy_or_real_world_example:To_clarify_how_bias_propagates_in_AI"
      ]
    },
    {
      "type": "expert_opinion_roundup",
      "heading_suggestion": "## What Leading Researchers Say About AI Fairness",
      "purpose_notes": "Gather authoritative perspectives to deepen credibility and analysis.",
      "elements": [
        "expert_quote:From_Geoff_Hinton_on_model_limitations",
        "expert_quote:From_OpenAI_researcher_on_mitigation_strategies"
      ]
    },
    {
      "type": "the_good_points",
      "heading_suggestion": "## Progress in Bias Mitigation You Can Build On",
      "purpose_notes": "Highlight current positive approaches and tools developers can use.",
      "elements": [
        "list:numbered_steps_for_bias_audit",
        "pull_quote:Many_frameworks_now_offer_built_in_bias_tests",
        "image_placeholder:Conceptual_diagram_explaining_bias_detection_workflow"
      ]
    },
    {
      "type": "the_bad_points_and_quirks",
      "heading_suggestion": "## The Pitfalls and Unexpected Side Effects",
      "purpose_notes": "Warn readers about limitations and quirks they must watch for.",
      "elements": [
        "paragraph:expert_analysis_summary",
        "user_testimonial_summary:What_developers_reported_about_edge_cases"
      ]
    },
    {
      "type": "future_implications_and_verdict",
      "heading_suggestion": "## The Road Ahead: Building Truly Equitable AI",
      "purpose_notes": "Offer a conclusion with forward-looking insights and a call to action for practitioners.",
      "elements": [
        "paragraph:expert_analysis_summary",
        "external_link_candidate:Link_to_key_research_paper_on_ai_ethics"
      ]
    }
  ]
}
```

---

Use these examples as your gold standard. Always output **only** the JSON object—no extra text or markdown.
"""
# --- End Agent Prompts ---

def call_deepseek_for_outline(generated_seo_h1: str, primary_keyword: str,
                              all_keywords: list, processed_summary: str,
                              raw_text_snippet: str) -> str | None:
    if not DEEPSEEK_API_KEY_OUTLINE:
        logger.error("DEEPSEEK_API_KEY_OUTLINE not found.")
        return None

    all_keywords_str = ", ".join(all_keywords[:MAX_KEYWORDS_FOR_CONTEXT_OUTLINE]) if all_keywords else "None provided"
    summary_snippet = (processed_summary or "No summary available.")[:MAX_SUMMARY_SNIPPET_LEN_CONTEXT]
    raw_text_context_snippet = (raw_text_snippet or "No raw text snippet available.")[:MAX_RAW_TEXT_SNIPPET_LEN_CONTEXT]

    user_input_content = f"""
**Generated SEO H1**: {generated_seo_h1}
**Primary Keyword**: {primary_keyword}
**All Final Keywords**: {all_keywords_str}
**Processed Summary**: {summary_snippet}
**Raw Scraped Text Snippet**: {raw_text_context_snippet}
    """
    payload = {
        "model": DEEPSEEK_MODEL_FOR_OUTLINE,
        "messages": [
            {"role": "system", "content": ARTICLE_OUTLINE_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_input_content.strip()}
        ],
        "temperature": 0.5, # Slightly higher for more creative outline structures
        "max_tokens": 3000, # Generous for very detailed outlines with examples
        "response_format": {"type": "json_object"}
    }
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY_OUTLINE}", "Content-Type": "application/json"}

    try:
        logger.debug(f"Sending outline request for H1: '{generated_seo_h1}'")
        response = requests.post(DEEPSEEK_CHAT_API_URL_OUTLINE, headers=headers, json=payload, timeout=API_TIMEOUT_OUTLINE_AGENT)
        response.raise_for_status()
        response_json = response.json()
        if response_json.get("choices") and response_json["choices"][0].get("message") and \
           response_json["choices"][0]["message"].get("content"):
            json_str = response_json["choices"][0]["message"]["content"]
            logger.info(f"DeepSeek outline gen successful for '{generated_seo_h1}'.")
            logger.debug(f"Raw JSON for outline (first 500): {json_str[:500]}...")
            return json_str
        logger.error(f"DeepSeek outline response malformed: {response_json}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"DeepSeek API req for outline failed: {e}. Response: {e.response.text[:500] if e.response else 'No response'}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error in call_deepseek_for_outline: {e}")
        return None

def parse_llm_outline_response(json_string: str | None,
                               primary_keyword_for_fallback: str,
                               generated_h1_for_fallback: str) -> dict:
    pk_fallback_clean = primary_keyword_for_fallback or "Topic"
    h1_fallback_clean = generated_h1_for_fallback or f"{pk_fallback_clean}: An In-Depth Analysis"

    def create_fallback_outline():
        fallback = json.loads(json.dumps(DEFAULT_FALLBACK_OUTLINE_STRUCTURE))
        fallback["article_h1_suggestion"] = fallback["article_h1_suggestion"].format(primary_keyword=pk_fallback_clean)
        for section in fallback["sections"]:
            section["heading_suggestion"] = section["heading_suggestion"].format(primary_keyword=pk_fallback_clean)
            if "elements" in section:
                section["elements"] = [
                    el.format(PrimaryKeyword=pk_fallback_clean) if isinstance(el, str) and "{PrimaryKeyword}" in el else el
                    for el in section["elements"]
                ]
        return fallback

    if not json_string:
        logger.warning(f"Empty LLM response for outline. Using fallback for PK: '{pk_fallback_clean}'.")
        return create_fallback_outline()

    try:
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', json_string, re.DOTALL | re.IGNORECASE)
        json_to_parse = match.group(1) if match else json_string
        llm_output = json.loads(json_to_parse)

        if not isinstance(llm_output, dict) or "sections" not in llm_output or \
           not isinstance(llm_output["sections"], list) or not llm_output["sections"]:
            raise ValueError("LLM output is not a dict or 'sections' list is missing/empty.")

        for i, section in enumerate(llm_output["sections"]):
            if not all(k in section for k in ["type", "heading_suggestion", "purpose_notes", "elements"]):
                raise ValueError(f"Section {i} missing required keys.")
            if not isinstance(section["elements"], list): # Ensure elements is always a list
                logger.warning(f"Section {i} 'elements' was not a list, converting. Original: {section['elements']}")
                section["elements"] = [str(section["elements"])] if section["elements"] else []


        if 'article_h1_suggestion' not in llm_output or not llm_output['article_h1_suggestion']:
            llm_output['article_h1_suggestion'] = h1_fallback_clean
        
        # Ensure 'outline_strategy_notes' exists
        if 'outline_strategy_notes' not in llm_output or not llm_output['outline_strategy_notes']:
            llm_output['outline_strategy_notes'] = "Strategy not specified by LLM."


        return llm_output
    except Exception as e:
        logger.error(f"Error parsing LLM outline '{json_string[:200]}...': {e}", exc_info=True)
        return create_fallback_outline()

def run_article_outline_agent(article_pipeline_data: dict) -> dict:
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Article Outline Agent for Article ID: {article_id} ---")

    generated_seo_h1 = article_pipeline_data.get('generated_seo_h1', article_pipeline_data.get('final_title', 'Untitled Article'))
    final_keywords_list = article_pipeline_data.get('final_keywords', [])
    primary_keyword = final_keywords_list[0] if final_keywords_list else article_pipeline_data.get('primary_topic', generated_seo_h1)

    processed_summary = article_pipeline_data.get('processed_summary', '')
    raw_text_content = article_pipeline_data.get('raw_scraped_text', '')

    if not generated_seo_h1 and not primary_keyword and not processed_summary and not raw_text_content:
        logger.error(f"Insufficient context for {article_id} to gen outline. Using fallback.")
        pk_for_fb = primary_keyword or "Key Topic"
        outline_data = json.loads(json.dumps(DEFAULT_FALLBACK_OUTLINE_STRUCTURE))
        outline_data["article_h1_suggestion"] = outline_data["article_h1_suggestion"].format(primary_keyword=pk_for_fb)
        for section in outline_data["sections"]:
            section["heading_suggestion"] = section["heading_suggestion"].format(primary_keyword=pk_for_fb)
            if "elements" in section:
                section["elements"] = [el.format(PrimaryKeyword=pk_for_fb) if isinstance(el, str) and "{PrimaryKeyword}" in el else el for el in section["elements"]]
        outline_data["error"] = "Insufficient input context for outline generation."
    else:
        raw_llm_response = call_deepseek_for_outline(generated_seo_h1, primary_keyword, final_keywords_list, processed_summary, raw_text_content)
        outline_data = parse_llm_outline_response(raw_llm_response, primary_keyword, generated_seo_h1)

    article_pipeline_data['article_outline'] = outline_data
    article_pipeline_data['final_page_h1'] = outline_data.get('article_h1_suggestion', generated_seo_h1)
    article_pipeline_data['outline_agent_status'] = "SUCCESS" if not outline_data.get('error') else "FAILED_WITH_FALLBACK"
    if outline_data.get('error'):
        article_pipeline_data['outline_agent_error'] = outline_data['error']
        logger.error(f"Outline Agent for {article_id} completed with errors/fallbacks: {outline_data['error']}")
    else:
        logger.info(f"Outline Agent for {article_id} completed successfully.")
        logger.debug(f"  Final Page H1: {article_pipeline_data['final_page_h1']}")
        logger.debug(f"  Outline Strategy: {outline_data.get('outline_strategy_notes')}")
        logger.debug(f"  Num sections: {len(outline_data.get('sections', []))}")
    return article_pipeline_data

if __name__ == "__main__":
    logger.info("--- Starting Article Outline Agent Standalone Test (ASI-Level Prompt vFINAL) ---")
    if not DEEPSEEK_API_KEY_OUTLINE: logger.error("DEEPSEEK_API_KEY not set. Test aborted."); sys.exit(1)

    sample_article_data = {
        'id': 'test_outline_asi_final_001',
        'generated_seo_h1': "NVIDIA Blackwell B200 GPU Smashes AI Speed Records: A New Era Begins", # Example H1 from title_agent
        'final_keywords': ["NVIDIA Blackwell B200", "AI Benchmarks", "Fastest GPU", "Data Center AI", "Next-Gen AI Chips"],
        'processed_summary': "NVIDIA's new Blackwell B200 GPU delivers unprecedented AI performance, breaking speed records for training and inference. It's designed to power next-generation data centers and enable trillion-parameter AI models.",
        'raw_scraped_text': "The tech world is buzzing after NVIDIA's GTC keynote where CEO Jensen Huang unveiled the Blackwell B200 GPU. This chip isn't just an upgrade; it's a leap in AI computation. Benchmarks suggest a 4x training improvement and up to 30x inference speedup over the H100. The B200 architecture features two massive dies and a high-speed interconnect. Huang emphasized its capability for 'trillion-parameter scale' AI. Cloud providers are already lining up. This promises to accelerate breakthroughs in science, drug discovery, and autonomous systems, though questions about energy and accessibility remain despite efficiency claims."
    } # Slightly more detailed raw_text_snippet
    result_data = run_article_outline_agent(sample_article_data.copy())
    logger.info("\n--- Test Results (ASI-Level Outline vFINAL) ---")
    logger.info(f"Status: {result_data.get('outline_agent_status')}")
    if result_data.get('outline_agent_error'): logger.error(f"Error: {result_data.get('outline_agent_error')}")
    logger.info(f"Final Page H1: {result_data.get('final_page_h1')}")
    logger.info("Full Outline JSON:")
    print(json.dumps(result_data.get('article_outline'), indent=2))

    logger.info("\n--- Test Fallback (ASI-Level Outline vFINAL) ---")
    minimal_data = {'id': 'test_fallback_outline_final_002', 'generated_seo_h1': "Tech Insights 2025", 'final_keywords': ["Future Technology Trends"]}
    result_minimal = run_article_outline_agent(minimal_data.copy())
    logger.info(f"Minimal Data Status: {result_minimal.get('outline_agent_status')}")
    logger.info("Minimal Data Outline JSON:")
    print(json.dumps(result_minimal.get('article_outline'), indent=2))
    logger.info("--- Standalone Test Complete ---")

# src/agents/content_assembler_agent.py
"""
Content Assembler Agent for meticulously piecing together article sections.
Ensures heading integrity, intelligent whitespace management, and robust
handling of section generation statuses.
"""

import os
import sys
import logging
import re

# --- Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
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

# --- Configuration Constants for Assembly ---
SECTION_SEPARATOR = "\n\n"
ADJACENT_BLOCK_SEPARATOR = "\n"
ENDS_WITH_BLOCK_REGEX = re.compile(r"(?:```|</table>|</pre>|</ul>|</ol>|</div>)\s*$", re.IGNORECASE | re.MULTILINE)

# --- No API calls needed for this agent ---

def safe_join_markdown_sections(section_parts: list) -> str:
    """
    Joins markdown section parts with intelligent newline management.
    Uses single newline if previous part ends with a block element,
    otherwise uses double newline.
    """
    if not section_parts:
        return ""

    assembled_content = ""
    for i, part_tuple in enumerate(section_parts): # Expecting tuples (content, original_heading_for_log)
        part_content, original_heading = part_tuple
        stripped_part = part_content.strip()
        if not stripped_part: 
            logger.debug(f"Skipping empty part for section originally headed: '{original_heading}'")
            continue
        
        if i == 0 or not assembled_content: # If it's the first non-empty part
            assembled_content = stripped_part
        else:
            if ENDS_WITH_BLOCK_REGEX.search(assembled_content):
                separator = ADJACENT_BLOCK_SEPARATOR
                logger.debug(f"Using ADJACENT_BLOCK_SEPARATOR before section originally headed: '{original_heading}' (starts with: {stripped_part[:30]}...)")
            else:
                separator = SECTION_SEPARATOR
            assembled_content += separator + stripped_part
            
    return assembled_content.strip()


def assemble_article_content(article_pipeline_data: dict) -> dict:
    """
    Assembles the full article Markdown body from individual section contents
    stored in the article_outline. Enhanced for robustness and clarity.
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Content Assembler Agent for Article ID: {article_id} ---")

    outline_data = article_pipeline_data.get('article_outline')
    if not outline_data or not isinstance(outline_data, dict) or \
       'sections' not in outline_data or not isinstance(outline_data['sections'], list):
        logger.error(f"Missing or invalid article outline for {article_id}. Cannot assemble content.")
        article_pipeline_data['assembled_article_body_md'] = "<p>Error: Article content could not be assembled due to missing outline.</p>"
        article_pipeline_data['content_assembler_status'] = "FAILED_MISSING_OUTLINE"
        return article_pipeline_data

    final_h1_for_page = article_pipeline_data.get('final_page_h1',
                                                 article_pipeline_data.get('article_h1_final_suggestion',
                                                                          article_pipeline_data.get('generated_seo_h1',
                                                                                                   "Article Title Not Found")))
    article_pipeline_data['final_page_h1'] = final_h1_for_page

    full_markdown_body_part_tuples = [] # Store as (content, original_heading_for_log)
    sections = outline_data.get('sections', [])
    successfully_assembled_sections = 0
    body_sections_present = 0
    body_sections_assembled = 0

    if not sections:
        logger.warning(f"No sections found in the outline for {article_id}. Assembled body will be empty.")
        article_pipeline_data['assembled_article_body_md'] = ""
        article_pipeline_data['content_assembler_status'] = "SUCCESS_EMPTY_OUTLINE"
        return article_pipeline_data

    for i, section in enumerate(sections):
        section_markdown = section.get('generated_markdown')
        section_heading_suggestion = section.get('heading_suggestion', f"Unnamed Section {i+1}")
        writer_status = section.get('writer_status', 'UNKNOWN')
        section_type = section.get('type', 'body_section')

        if section_type not in ["introduction", "conclusion"]:
            body_sections_present += 1

        current_section_content_to_add = None

        if section_markdown and isinstance(section_markdown, str) and section_markdown.strip():
            # Heading Integrity Check & Prepend
            if not section_markdown.lstrip().startswith(section_heading_suggestion.strip()):
                logger.warning(f"Section '{section_heading_suggestion}' (Type: {section_type}) for {article_id} "
                               f"Markdown does not start with its suggested heading. Prepending heading.")
                section_markdown = f"{section_heading_suggestion.strip()}\n\n{section_markdown.lstrip()}"
            
            current_section_content_to_add = section_markdown
            
            if writer_status == "SUCCESS":
                successfully_assembled_sections += 1
                if section_type not in ["introduction", "conclusion"]:
                    body_sections_assembled += 1
                logger.debug(f"Adding successful section '{section_heading_suggestion}' (Type: {section_type}, Status: {writer_status}) to assembly for {article_id}.")
            else: 
                logger.warning(f"Adding section '{section_heading_suggestion}' (Type: {section_type}, Status: {writer_status}) with fallback/partial content for {article_id}.")
                successfully_assembled_sections += 1 
                if section_type not in ["introduction", "conclusion"]:
                     body_sections_assembled += 1
        else: 
            logger.warning(f"Section '{section_heading_suggestion}' (Type: {section_type}) for {article_id} has no usable 'generated_markdown'. "
                           f"Writer_status: '{writer_status}'. Inserting failure placeholder comment.")
            current_section_content_to_add = f"<!-- SECTION FAILED TO GENERATE: {section_heading_suggestion} (Type: {section_type}, Status: {writer_status}) -->"
        
        if current_section_content_to_add: # Ensure we only add if there's *some* content (even placeholder)
            word_count = len(current_section_content_to_add.split())
            logger.debug(f"  Section '{section_heading_suggestion}' word count (approx): {word_count}")
            full_markdown_body_part_tuples.append((current_section_content_to_add, section_heading_suggestion))


    assembled_body_md = safe_join_markdown_sections(full_markdown_body_part_tuples)
    total_word_count = len(assembled_body_md.split())
    article_pipeline_data['assembled_article_body_md'] = assembled_body_md
    article_pipeline_data['assembled_word_count'] = total_word_count
    
    if body_sections_present > 0 and body_sections_assembled == 0 and successfully_assembled_sections < len(sections):
        # This condition means only intro/conclusion might have succeeded, but all core body sections failed
        logger.warning(f"All {body_sections_present} core body sections failed to generate usable content for {article_id}.")
        article_pipeline_data['content_assembler_status'] = "WARNING_ALL_BODY_SECTIONS_FAILED"
    elif successfully_assembled_sections < len(sections):
        article_pipeline_data['content_assembler_status'] = "WARNING_PARTIAL_ASSEMBLY"
    else:
        article_pipeline_data['content_assembler_status'] = "SUCCESS"
    
    logger.info(f"Content Assembler for {article_id} completed. Status: {article_pipeline_data['content_assembler_status']}. "
                f"Assembled {successfully_assembled_sections}/{len(sections)} sections. Total assembled word count: {total_word_count}.")
    logger.debug(f"Final Assembled Markdown Body for {article_id} (first 300 chars): {assembled_body_md[:300]}...")
    logger.debug(f"Final Page H1 confirmed for {article_id}: {final_h1_for_page}")

    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    logger.info("--- Starting Content Assembler Agent Standalone Test (Enhanced Logic) ---")
    
    sample_pipeline_data_for_assembly = {
        'id': 'test_assembly_enhanced_001',
        'final_page_h1': "The Ultimate Guide to Assembling Content With ASI-Level Precision", 
        'article_outline': {
            "article_h1_suggestion": "The Ultimate Guide to Assembling Content With ASI-Level Precision",
            "outline_strategy_notes": "Step-by-step assembly process demonstrating robustness.",
            "sections": [
                {
                    "type": "introduction", 
                    "heading_suggestion": "## Introduction: Why Perfect Assembly Matters", 
                    "generated_markdown": "## Introduction: Why Perfect Assembly Matters\n\nThis is the introduction. It sets the stage.",
                    "writer_status": "SUCCESS"
                },
                {
                    "type": "body_section", 
                    "heading_suggestion": "### Core Principle 1: Heading Integrity", 
                    "generated_markdown": "This section discusses heading integrity. It should have had its heading prepended by ScribeOmega, but we test assembler fallback.",
                    "writer_status": "SUCCESS" 
                },
                {
                    "type": "body_section", 
                    "heading_suggestion": "### Core Principle 2: Intelligent Whitespace", 
                    "generated_markdown": "### Core Principle 2: Intelligent Whitespace\n\nThis section ends with a code block that needs careful newline handling.\n\n```python\nprint('Hello, assembler!')\n```",
                    "writer_status": "SUCCESS"
                },
                {
                    "type": "body_section",
                    "heading_suggestion": "### Core Principle 3: Handling Failures",
                    "generated_markdown": "### Core Principle 3: Handling Failures\n\n**Editor's Note:** Our AI is working on this part about failure handling.", # Fallback from ScribeOmega
                    "writer_status": "FAILED_WITH_FALLBACK" 
                },
                {
                    "type": "body_section", 
                    "heading_suggestion": "### Completely Missing Section Content Example", 
                    "generated_markdown": None, 
                    "writer_status": "FAILED_NO_CONTENT"
                },
                {
                    "type": "conclusion", 
                    "heading_suggestion": "## Conclusion: Assembled for Perfection", 
                    "generated_markdown": "## Conclusion: Assembled for Perfection\n\nThis is the grand conclusion.",
                    "writer_status": "SUCCESS"
                }
            ]
        }
    }

    result_data = assemble_article_content(sample_pipeline_data_for_assembly.copy())

    logger.info("\n--- Content Assembler Test Results (Enhanced Logic) ---")
    logger.info(f"Assembler Status: {result_data.get('content_assembler_status')}")
    logger.info(f"Final Page H1: {result_data.get('final_page_h1')}")
    logger.info(f"Assembled Word Count: {result_data.get('assembled_word_count')}")
    
    logger.info("\nAssembled Markdown Body:")
    print("============================================")
    print(result_data.get('assembled_article_body_md', "ERROR: No assembled body found."))
    print("============================================")

    assembled_text = result_data.get('assembled_article_body_md', "")
    assert "## Introduction: Why Perfect Assembly Matters" in assembled_text
    assert "### Core Principle 1: Heading Integrity\n\nThis section discusses heading integrity." in assembled_text 
    # Corrected Assertion for intelligent newline after code block:
    assert "```\n### Core Principle 3:" in assembled_text 
    assert "<!-- SECTION FAILED TO GENERATE: ### Completely Missing Section Content Example (Type: body_section, Status: FAILED_NO_CONTENT) -->" in assembled_text
    logger.info("Basic assertions passed for enhanced assembler.")

    logger.info("--- Content Assembler Agent Standalone Test Complete ---")
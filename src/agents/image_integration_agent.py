# src/agents/image_integration_agent.py

import os
import sys
import json
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
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logger.setLevel(logging.DEBUG)

# --- Configuration ---
# No Ollama model needed for this agent as it's rule-based replacement.
# However, an LLM could be used for more nuanced caption generation or placement decisions if desired in future.

def run_image_integration_agent(article_pipeline_data):
    """
    Integrates selected images into the Markdown body by replacing placeholders.
    Expected input keys in article_pipeline_data:
        - 'id'
        - 'seo_agent_results.generated_article_body_md' (Markdown with placeholders)
        - 'media_candidates_for_body' (list from vision_media_agent)
    Updates keys:
        - 'seo_agent_results.generated_article_body_md' (with actual image Markdown)
        - 'image_integration_status'
        - 'image_integration_log' (list of actions taken)
    """
    article_id = article_pipeline_data.get('id', 'unknown_id')
    logger.info(f"--- Running Image Integration Agent for Article ID: {article_id} ---")

    integration_log = []
    article_pipeline_data['image_integration_status'] = "NO_ACTION_NEEDED" # Default

    seo_results = article_pipeline_data.get('seo_agent_results')
    if not seo_results or not isinstance(seo_results, dict):
        logger.warning(f"No 'seo_agent_results' found for {article_id}. Skipping image integration.")
        article_pipeline_data['image_integration_status'] = "SKIPPED_NO_SEO_RESULTS"
        article_pipeline_data['image_integration_log'] = ["No SEO results to process."]
        return article_pipeline_data

    markdown_body = seo_results.get('generated_article_body_md')
    if not markdown_body or not isinstance(markdown_body, str):
        logger.warning(f"No 'generated_article_body_md' found in seo_results for {article_id}. Skipping.")
        article_pipeline_data['image_integration_status'] = "SKIPPED_NO_MARKDOWN_BODY"
        article_pipeline_data['image_integration_log'] = ["No Markdown body to process."]
        return article_pipeline_data

    media_candidates = article_pipeline_data.get('media_candidates_for_body')
    if not media_candidates or not isinstance(media_candidates, list) or len(media_candidates) == 0:
        logger.info(f"No media candidates provided by vision_media_agent for {article_id}. No in-article images to integrate.")
        # Check if there were placeholders; if so, it's a warning.
        if "<!-- IMAGE_PLACEHOLDER:" in markdown_body:
            logger.warning(f"Markdown for {article_id} contains image placeholders, but no media candidates were supplied.")
            article_pipeline_data['image_integration_status'] = "WARNING_PLACEHOLDERS_NO_CANDIDATES"
            integration_log.append("Markdown has placeholders, but no images were selected/provided by vision agent.")
        else:
            article_pipeline_data['image_integration_status'] = "NO_PLACEHOLDERS_OR_CANDIDATES"
            integration_log.append("No image placeholders in Markdown and no media candidates.")
        article_pipeline_data['image_integration_log'] = integration_log
        return article_pipeline_data

    logger.info(f"Processing {len(media_candidates)} media candidates for {article_id} against placeholders.")
    
    modified_markdown_body = markdown_body
    integrations_done = 0

    # Iterate through media candidates provided by the vision agent
    for candidate_info in media_candidates:
        original_placeholder_desc = candidate_info.get('placeholder_description_original')
        image_url = candidate_info.get('best_image_url')
        alt_text = candidate_info.get('alt_text', 'Relevant image')
        vlm_caption = candidate_info.get('vlm_image_description', '') # Optional caption from VLM

        if not original_placeholder_desc or not image_url:
            integration_log.append(f"Skipping candidate due to missing placeholder description or image URL: {candidate_info}")
            logger.warning(f"Skipping invalid media candidate for {article_id}: {candidate_info}")
            continue

        # Construct the exact placeholder comment string to find and replace
        # Need to be careful with regex special characters if original_placeholder_desc contains them
        # For simplicity, assuming basic descriptions. If complex, use re.escape.
        placeholder_comment_to_find = f"<!-- IMAGE_PLACEHOLDER: {original_placeholder_desc.strip()} -->"
        
        # Create the replacement Markdown for the image
        # Ensure alt text doesn't contain characters that break Markdown image syntax (like quotes if not handled)
        safe_alt_text = alt_text.replace('"', "'").replace('[','(').replace(']',')') # Basic sanitization
        image_markdown = f"\n![{safe_alt_text}]({image_url})\n" # Ensure newlines for block display

        # Add optional caption if VLM provided one and it's meaningful
        if vlm_caption and len(vlm_caption.strip()) > 10:
            safe_caption = vlm_caption.strip().replace('\n', ' ') # Keep caption on one line
            image_markdown += f"*{safe_caption}*\n" # Italicized caption

        # Replace the first occurrence of this specific placeholder
        if placeholder_comment_to_find in modified_markdown_body:
            modified_markdown_body = modified_markdown_body.replace(placeholder_comment_to_find, image_markdown, 1)
            integrations_done += 1
            log_msg = f"Integrated image '{image_url}' for placeholder: '{original_placeholder_desc[:50]}...'"
            integration_log.append(log_msg)
            logger.info(f"For {article_id}: {log_msg}")
        else:
            log_msg = f"Placeholder comment not found in Markdown for description: '{original_placeholder_desc[:50]}...'"
            integration_log.append(log_msg)
            logger.warning(f"For {article_id}: {log_msg} - Candidate URL was {image_url}. This might indicate a mismatch between placeholder descriptions generated by SEO writer and those used by vision agent if descriptions were modified.")

    if integrations_done > 0:
        article_pipeline_data['seo_agent_results']['generated_article_body_md'] = modified_markdown_body
        article_pipeline_data['image_integration_status'] = f"SUCCESS_INTEGRATED_{integrations_done}_IMAGES"
        logger.info(f"Successfully integrated {integrations_done} images into markdown for {article_id}.")
    else:
        # This could mean placeholders existed but no matches were made based on description,
        # or media_candidates were empty to begin with (handled earlier).
        if "<!-- IMAGE_PLACEHOLDER:" in markdown_body: # Check if original body had placeholders
            article_pipeline_data['image_integration_status'] = "WARNING_PLACEHOLDERS_EXIST_NO_MATCHES_MADE"
            integration_log.append("Placeholders found in Markdown, but no successful integrations were made with provided candidates.")
            logger.warning(f"For {article_id}: Placeholders existed but no images were integrated. Check descriptions match.")
        else: # No placeholders in original body means nothing to integrate
             article_pipeline_data['image_integration_status'] = "NO_PLACEHOLDERS_IN_MARKDOWN"


    article_pipeline_data['image_integration_log'] = integration_log
    logger.info(f"--- Image Integration Agent finished for Article ID: {article_id}. Status: {article_pipeline_data['image_integration_status']} ---")
    return article_pipeline_data

# --- Standalone Execution Example ---
if __name__ == "__main__":
    if not logger.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    logger.info("--- Starting Image Integration Agent Standalone Test ---")

    sample_article_data_for_integration = {
        'id': 'test_img_integ_001',
        'seo_agent_results': {
            'generated_article_body_md': """
            ## Amazing New Gadget

            This new gadget is revolutionary. Here's a look at its design.
            <!-- IMAGE_PLACEHOLDER: A sleek product shot of the new gadget -->
            It features advanced AI capabilities.

            ### Performance Metrics
            The performance is off the charts.
            <!-- IMAGE_PLACEHOLDER: A graph showing benchmark scores of the gadget -->
            Compared to competitors, it leads by a significant margin.

            <!-- IMAGE_PLACEHOLDER: A lifestyle image of someone using the gadget -->
            This is how it looks in a real-world scenario.
            
            <!-- IMAGE_PLACEHOLDER: This placeholder has no matching candidate -->
            Some other text here.
            """
        },
        'media_candidates_for_body': [
            {
                'placeholder_description_original': "A sleek product shot of the new gadget",
                'best_image_url': 'https://example.com/images/gadget_sleek.jpg',
                'alt_text': 'Sleek new AI gadget',
                'vlm_image_description': 'Photo of the new AI-powered gadget in silver.'
            },
            {
                'placeholder_description_original': "A graph showing benchmark scores of the gadget",
                'best_image_url': 'https://example.com/images/gadget_benchmarks.png',
                'alt_text': 'Gadget benchmark performance graph',
                'vlm_image_description': 'Bar chart comparing benchmark scores.'
            },
            {
                'placeholder_description_original': "A lifestyle image of someone using the gadget", # This one will be used
                'best_image_url': 'https://example.com/images/gadget_lifestyle.jpg',
                'alt_text': 'Person happily using the new AI gadget outdoors',
                'vlm_image_description': '' # No VLM caption for this one
            }
            # Note: No candidate for "This placeholder has no matching candidate"
        ]
    }

    result_data = run_image_integration_agent(sample_article_data_for_integration.copy())

    logger.info("\n--- Image Integration Test Results ---")
    logger.info(f"Integration Status: {result_data.get('image_integration_status')}")
    
    logger.info("\nIntegration Log:")
    for log_entry in result_data.get('image_integration_log', []):
        logger.info(f"  - {log_entry}")

    logger.info("\n--- Final Markdown Body ---")
    final_md = result_data.get('seo_agent_results', {}).get('generated_article_body_md', "ERROR: Markdown body not found.")
    print(final_md)

    if "![Sleek new AI gadget](https://example.com/images/gadget_sleek.jpg)" in final_md:
        logger.info("\nSUCCESS: First image correctly integrated.")
    else:
        logger.error("\nERROR: First image not found in final markdown.")

    if "*Photo of the new AI-powered gadget in silver.*" in final_md:
        logger.info("SUCCESS: Caption for first image correctly integrated.")
    else:
        logger.error("ERROR: Caption for first image not found.")
        
    if "![Gadget benchmark performance graph](https://example.com/images/gadget_benchmarks.png)" in final_md:
        logger.info("SUCCESS: Second image correctly integrated.")
    else:
        logger.error("\nERROR: Second image not found in final markdown.")

    if "<!-- IMAGE_PLACEHOLDER: This placeholder has no matching candidate -->" in final_md:
        logger.info("SUCCESS: Unmatched placeholder correctly remained in markdown.")
    else:
        logger.error("ERROR: Unmatched placeholder was incorrectly removed or modified.")


    logger.info("--- Image Integration Agent Standalone Test Complete ---")
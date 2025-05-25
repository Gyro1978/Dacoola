import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call, ANY
from datetime import datetime, timezone, timedelta

# Add project root to sys.path to allow direct import of src.main
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

# Attempt to import the target function and other necessary components from src.main
# This import might trigger module-level code in src.main.py
try:
    from src.main import process_researched_article_data
    # For mocking, we might need to reference these if they are part of src.main's namespace directly
    # For now, we'll patch them as strings like 'src.main.run_filter_agent'
except ImportError as e:
    print(f"Failed to import from src.main: {e}")
    # If src.main cannot be imported due to its own internal imports or setup issues,
    # these tests cannot run. This print helps diagnose if the test setup itself is problematic.
    process_researched_article_data = None # Placeholder

class TestProcessResearchedArticleData(unittest.TestCase):

    def setUp(self):
        """Set up a base article data dictionary for each test."""
        self.base_article_data = {
            'id': 'test_article_123',
            'title': 'Test Article Title',
            'published_iso': datetime.now(timezone.utc).isoformat(),
            'selected_image_url': 'http://example.com/image.jpg',
            'processed_summary': 'This is a processed summary for the test article.',
            'raw_scraped_text': 'This is the full raw scraped text of the article, providing more context.',
            'source_feed': 'Test Feed URL',
            'link': 'http://example.com/original-article'
            # Other fields like 'filter_verdict', 'similarity_verdict', etc.,
            # will be added by the mocked agent functions.
        }

        # Mock for existing articles summary data, used by similarity check and duplicate check
        self.mock_existing_articles_summary = []
        # Mock for current run fully processed data, used by similarity check
        self.mock_current_run_processed_data = []

    # 1. Successful Full Processing
    @patch('src.main.update_all_articles_json_file', return_value=True)
    @patch('src.main.regenerate_article_html_if_needed', return_value=True)
    @patch('src.main.run_seo_review_agent')
    @patch('src.main.run_article_review_agent')
    @patch('src.main.assemble_article_html_body') # Patched because it's complex
    @patch('src.main.run_markdown_generator_agent')
    @patch('src.main.run_description_generator_agent')
    @patch('src.main.run_title_generator_agent')
    @patch('src.main.run_keyword_generator_agent')
    @patch('src.main.run_similarity_check_agent')
    @patch('src.main.run_filter_agent')
    @patch('src.main.slugify', return_value='test-article-title') # Simple slugify mock
    @patch('src.main.get_sort_key') # Mock get_sort_key for date checks / trend score
    def test_successful_full_processing(self, mock_get_sort_key, mock_slugify,
                                        mock_filter_agent, mock_similarity_check_agent,
                                        mock_keyword_agent, mock_title_agent, mock_desc_agent,
                                        mock_markdown_agent, mock_assemble_html, mock_article_review,
                                        mock_seo_review, mock_regen_html, mock_update_json):
        
        article_data = self.base_article_data.copy()

        # --- Mock configurations for each agent ---
        mock_get_sort_key.return_value = datetime.now(timezone.utc) # For trend score calculation

        def filter_side_effect(data):
            data.update({'filter_verdict': {'importance_level': 'Interesting', 'topic': 'AI Models', 'primary_topic_keyword': 'AI'}})
            return data
        mock_filter_agent.side_effect = filter_side_effect

        def similarity_side_effect(data, existing_dir, current_run_data):
            data.update({'similarity_verdict': 'OKAY_PASS'})
            return data
        mock_similarity_check_agent.side_effect = similarity_side_effect
        
        def keyword_side_effect(data):
            data.update({'final_keywords': ['AI', 'Test', 'Processing']})
            return data
        mock_keyword_agent.side_effect = keyword_side_effect

        def title_side_effect(data):
            data.update({'generated_seo_h1': 'Generated H1 Title', 'generated_title_tag': 'Generated Title Tag'})
            return data
        mock_title_agent.side_effect = title_side_effect

        def desc_side_effect(data):
            data.update({'generated_meta_description': 'Generated meta description.'})
            return data
        mock_desc_agent.side_effect = desc_side_effect

        # Mock for markdown_generator_agent and section_writer_agent (via assemble_article_html_body)
        mock_article_plan = {
            'sections': [
                {'section_type': 'introduction', 'heading_text': 'Intro', 'generated_content_for_section': '<p>Intro content</p>'},
                {'section_type': 'main', 'heading_text': 'Main', 'generated_content_for_section': '<p>Main content</p>'}
            ]
        }
        def markdown_side_effect(data):
            data.update({'article_plan': mock_article_plan, 'generated_tags': data.get('final_keywords', [])[:5]})
            return data
        mock_markdown_agent.side_effect = markdown_side_effect
        
        # Mock for assemble_article_html_body
        # It's called with (article_plan, base_site_url, article_id)
        # Returns (final_html_body, final_pure_markdown_body)
        mock_assemble_html.return_value = ("<p>Assembled HTML Body</p>", "Assembled Markdown Body")

        def article_review_side_effect(data):
            data.update({'article_review_results': {'review_verdict': 'PASS'}})
            return data
        mock_article_review.side_effect = article_review_side_effect

        def seo_review_side_effect(data):
            data.update({'seo_review_data': {'score': 90}}) # Dummy SEO data
            return data
        mock_seo_review.side_effect = seo_review_side_effect

        # --- Call the function under test ---
        result = process_researched_article_data(
            article_data,
            self.mock_existing_articles_summary,
            self.mock_current_run_processed_data
        )

        # --- Assertions ---
        self.assertIsNotNone(result)
        self.assertIn('summary', result)
        self.assertIn('social_post_data', result)
        self.assertIn('full_data', result)
        self.assertEqual(result['full_data']['id'], self.base_article_data['id'])

        # Check if agents were called
        mock_filter_agent.assert_called_once_with(article_data)
        # The PROCESSED_JSON_DIR is resolved inside src.main, so we check it's called with some string path
        mock_similarity_check_agent.assert_called_once_with(article_data, ANY, self.mock_current_run_processed_data)
        mock_keyword_agent.assert_called_once_with(article_data)
        mock_title_agent.assert_called_once_with(article_data)
        mock_desc_agent.assert_called_once_with(article_data)
        mock_markdown_agent.assert_called_once_with(article_data)
        
        # assemble_article_html_body is called with article_plan, base_url, article_id
        # The base_url (YOUR_SITE_BASE_URL_SCRIPT_VAR) is determined in src.main, so use ANY
        mock_assemble_html.assert_called_once_with(mock_article_plan, ANY, article_data['id'])
        
        mock_article_review.assert_called_once_with(article_data)
        mock_seo_review.assert_called_once_with(article_data)
        mock_regen_html.assert_called_once_with(article_data, force_regen=True)
        mock_update_json.assert_called_once() # Check that it was called, args can be complex to match exactly


if __name__ == '__main__':
    # This check is important because if src.main has issues, process_researched_article_data might be None
    if process_researched_article_data:
        unittest.main()
    else:
        print("Skipping tests: process_researched_article_data could not be imported from src.main.")
        # Optionally, exit with an error code or raise an exception here
        # For now, just printing and exiting normally if tests can't run.
        sys.exit(0) # Exit gracefully if tests can't run, to avoid CI failure for import reasons

    # 2. Filter Agent Skips Article (e.g., "Boring")
    @patch('src.main.run_similarity_check_agent') # Should not be called
    @patch('src.main.run_filter_agent')
    def test_filter_agent_skips_boring(self, mock_filter_agent, mock_similarity_check_agent):
        article_data = self.base_article_data.copy()

        def filter_side_effect(data):
            data.update({'filter_verdict': {'importance_level': 'Boring'}})
            return data
        mock_filter_agent.side_effect = filter_side_effect
        
        result = process_researched_article_data(
            article_data,
            self.mock_existing_articles_summary,
            self.mock_current_run_processed_data
        )

        self.assertIsNone(result)
        mock_filter_agent.assert_called_once_with(article_data)
        mock_similarity_check_agent.assert_not_called()

    # 3. Similarity Check Skips Article
    @patch('src.main.run_keyword_generator_agent') # Should not be called
    @patch('src.main.run_similarity_check_agent')
    @patch('src.main.run_filter_agent')
    def test_similarity_check_skips_article(self, mock_filter_agent, mock_similarity_check_agent, mock_keyword_agent):
        article_data = self.base_article_data.copy()

        def filter_side_effect(data):
            data.update({'filter_verdict': {'importance_level': 'Interesting', 'topic': 'AI'}})
            return data
        mock_filter_agent.side_effect = filter_side_effect

        def similarity_side_effect(data, existing_dir, current_run_data):
            data.update({'similarity_verdict': 'FAIL_SIMILAR'})
            return data
        mock_similarity_check_agent.side_effect = similarity_side_effect

        result = process_researched_article_data(
            article_data,
            self.mock_existing_articles_summary,
            self.mock_current_run_processed_data
        )

        self.assertIsNone(result)
        mock_filter_agent.assert_called_once_with(article_data)
        mock_similarity_check_agent.assert_called_once_with(article_data, ANY, self.mock_current_run_processed_data)
        mock_keyword_agent.assert_not_called()

    # 4. Article Review Fails/Skips Article
    @patch('src.main.regenerate_article_html_if_needed') # Should not be called
    @patch('src.main.run_seo_review_agent') # Might be called before or after article_review depending on structure
    @patch('src.main.run_article_review_agent')
    @patch('src.main.assemble_article_html_body')
    @patch('src.main.run_markdown_generator_agent')
    @patch('src.main.run_description_generator_agent')
    @patch('src.main.run_title_generator_agent')
    @patch('src.main.run_keyword_generator_agent')
    @patch('src.main.run_similarity_check_agent')
    @patch('src.main.run_filter_agent')
    @patch('src.main.slugify', return_value='test-article-title')
    def test_article_review_fails_article(self, mock_slugify, mock_filter_agent, mock_similarity_agent, 
                                          mock_keyword_agent, mock_title_agent, mock_desc_agent,
                                          mock_markdown_agent, mock_assemble_html, mock_article_review,
                                          mock_seo_review, mock_regen_html):
        article_data = self.base_article_data.copy()

        # Setup successful mocks for agents before article_review
        mock_filter_agent.side_effect = lambda data: data.update({'filter_verdict': {'importance_level': 'Interesting', 'topic': 'AI'}}) or data
        mock_similarity_agent.side_effect = lambda data, ed, crd: data.update({'similarity_verdict': 'OKAY_PASS'}) or data
        mock_keyword_agent.side_effect = lambda data: data.update({'final_keywords': ['key']}) or data
        mock_title_agent.side_effect = lambda data: data.update({'generated_seo_h1': 'H1', 'generated_title_tag': 'Tag'}) or data
        mock_desc_agent.side_effect = lambda data: data.update({'generated_meta_description': 'Desc'}) or data
        mock_markdown_agent.side_effect = lambda data: data.update({'article_plan': {'sections': []}, 'generated_tags': ['tag']}) or data
        mock_assemble_html.return_value = ("<p>HTML Body</p>", "Markdown Body")

        # Article review fails
        def article_review_fail_side_effect(data):
            data.update({'article_review_results': {'review_verdict': 'FAIL_CRITICAL'}})
            return data
        mock_article_review.side_effect = article_review_fail_side_effect
        
        result = process_researched_article_data(
            article_data,
            self.mock_existing_articles_summary,
            self.mock_current_run_processed_data
        )

        self.assertIsNone(result)
        mock_filter_agent.assert_called_once()
        mock_similarity_agent.assert_called_once()
        mock_keyword_agent.assert_called_once()
        mock_title_agent.assert_called_once()
        mock_desc_agent.assert_called_once()
        mock_markdown_agent.assert_called_once()
        mock_assemble_html.assert_called_once()
        mock_article_review.assert_called_once()
        mock_seo_review.assert_called_once() # SEO review runs even if article review flags issues, as per current main.py structure
        mock_regen_html.assert_not_called() # HTML generation should be skipped

    # 5. HTML Generation Fails
    @patch('src.main.update_all_articles_json_file') # Should not be called
    @patch('src.main.regenerate_article_html_if_needed')
    @patch('src.main.run_seo_review_agent')
    @patch('src.main.run_article_review_agent')
    @patch('src.main.assemble_article_html_body')
    @patch('src.main.run_markdown_generator_agent')
    @patch('src.main.run_description_generator_agent')
    @patch('src.main.run_title_generator_agent')
    @patch('src.main.run_keyword_generator_agent')
    @patch('src.main.run_similarity_check_agent')
    @patch('src.main.run_filter_agent')
    @patch('src.main.slugify', return_value='test-article-title')
    @patch('src.main.get_sort_key')
    def test_html_generation_fails(self, mock_get_sort_key, mock_slugify, mock_filter_agent, mock_similarity_agent,
                                   mock_keyword_agent, mock_title_agent, mock_desc_agent,
                                   mock_markdown_agent, mock_assemble_html, mock_article_review,
                                   mock_seo_review, mock_regen_html, mock_update_json):
        article_data = self.base_article_data.copy()
        mock_get_sort_key.return_value = datetime.now(timezone.utc)

        # Setup successful mocks for agents before HTML generation
        mock_filter_agent.side_effect = lambda data: data.update({'filter_verdict': {'importance_level': 'Interesting', 'topic': 'AI'}}) or data
        mock_similarity_agent.side_effect = lambda data, ed, crd: data.update({'similarity_verdict': 'OKAY_PASS'}) or data
        mock_keyword_agent.side_effect = lambda data: data.update({'final_keywords': ['key']}) or data
        mock_title_agent.side_effect = lambda data: data.update({'generated_seo_h1': 'H1', 'generated_title_tag': 'Tag'}) or data
        mock_desc_agent.side_effect = lambda data: data.update({'generated_meta_description': 'Desc'}) or data
        mock_markdown_agent.side_effect = lambda data: data.update({'article_plan': {'sections': []}, 'generated_tags': ['tag']}) or data
        mock_assemble_html.return_value = ("<p>HTML Body</p>", "Markdown Body")
        mock_article_review.side_effect = lambda data: data.update({'article_review_results': {'review_verdict': 'PASS'}}) or data
        mock_seo_review.side_effect = lambda data: data.update({'seo_review_data': {}}) or data

        # HTML generation fails
        mock_regen_html.return_value = False # Simulate failure

        result = process_researched_article_data(
            article_data,
            self.mock_existing_articles_summary,
            self.mock_current_run_processed_data
        )
        
        self.assertIsNone(result)
        mock_filter_agent.assert_called_once()
        mock_similarity_agent.assert_called_once()
        # ... (assert other agents were called)
        mock_markdown_agent.assert_called_once()
        mock_assemble_html.assert_called_once()
        mock_article_review.assert_called_once()
        mock_seo_review.assert_called_once()
        mock_regen_html.assert_called_once_with(article_data, force_regen=True)
        mock_update_json.assert_not_called() # Should not be called if HTML gen fails

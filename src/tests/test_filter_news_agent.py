import sys
import os
import unittest
import json
import re 
from unittest.mock import patch, MagicMock, call

# Add project root to sys.path to allow direct import of src.agents.filter_news_agent
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from src.agents.filter_news_agent import run_filter_agent, MAX_SUMMARY_LENGTH, ALLOWED_TOPICS, IMPORTANCE_LEVELS, DEFAULT_IMPORTANCE, DEFAULT_TOPIC, LLM_MAX_RETRIES

# Mock the Modal stub and function lookup process
mock_modal_stub = MagicMock()

# This class will be used to mock the object returned by modal.Function.lookup()
class MockModalFunction:
    def __init__(self, generate_remote_return_value=None, generate_remote_side_effect=None):
        self.generate = MagicMock()
        # The 'remote' attribute itself needs to be a callable mock if it's called like generate.remote()
        self.generate.remote = MagicMock(
            return_value=generate_remote_return_value,
            side_effect=generate_remote_side_effect
        )

    def __call__(self, *args, **kwargs): # To mock the __call__ on the class itself if needed
        return self.generate

# This function will be used as the side_effect for modal.Function.lookup
def mock_function_lookup(app_name, image=None):
    current_test_mock_modal_function = TestRunFilterAgent.current_test_mock_modal_function
    if current_test_mock_modal_function:
        return current_test_mock_modal_function
    return MockModalFunction(generate_remote_return_value='{"error": "Default mock LLM response"}')


class TestRunFilterAgent(unittest.TestCase):
    current_test_mock_modal_function = None

    def setUp(self):
        self.article_data = {
            "id": "test_id_123",
            "title": "Test Article Title",
            "link": "http://example.com/test-article",
            "summary": "This is a short test summary.", # Keep it short for most tests
            "processed_summary": "This is a short test summary.", 
            "source_feed": "Test Feed",
            "published_iso": "2023-01-01T12:00:00Z",
            "selected_image_url": "http://example.com/image.jpg",
            "raw_scraped_text": "Full raw text here for context."
        }
        TestRunFilterAgent.current_test_mock_modal_function = None

    def tearDown(self):
        TestRunFilterAgent.current_test_mock_modal_function = None

    @patch('src.agents.filter_news_agent.load_important_entities')
    @patch('modal.Function.lookup', side_effect=mock_function_lookup) 
    def test_successful_classification_interesting(self, mock_lookup, mock_load_entities):
        mock_load_entities.return_value = ([], [], []) 
        llm_response_json = {
            "importance_level": "Interesting", "topic": "Technology",
            "reasoning": "The article discusses new technology.",
            "matching_keywords": ["test", "summary"], "matching_entities": []
        }
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_return_value=json.dumps(llm_response_json)
        )
        result_article = run_filter_agent(self.article_data.copy())
        self.assertIsNotNone(result_article.get('filter_verdict'))
        self.assertIsNone(result_article.get('filter_error'))
        verdict = result_article['filter_verdict']
        self.assertEqual(verdict['importance_level'], "Interesting")
        self.assertEqual(verdict['topic'], "Technology")
        self.assertEqual(verdict['reasoning'], llm_response_json['reasoning'])
        self.assertEqual(verdict['matching_keywords'], llm_response_json['matching_keywords'])
        TestRunFilterAgent.current_test_mock_modal_function.generate.remote.assert_called_once()
        mock_load_entities.assert_called_once()

    @patch('src.agents.filter_news_agent.load_important_entities')
    @patch('modal.Function.lookup', side_effect=mock_function_lookup)
    def test_truncation_of_long_summary(self, mock_lookup, mock_load_entities):
        mock_load_entities.return_value = ([], [], [])
        long_summary = "word " * (MAX_SUMMARY_LENGTH + 50) 
        article_copy = self.article_data.copy()
        article_copy["processed_summary"] = long_summary
        llm_response_json = { 
            "importance_level": "Interesting", "topic": "Technology", "reasoning": "Default.",
            "matching_keywords": [], "matching_entities": []
        }
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_return_value=json.dumps(llm_response_json)
        )
        run_filter_agent(article_copy)
        TestRunFilterAgent.current_test_mock_modal_function.generate.remote.assert_called_once()
        call_args = TestRunFilterAgent.current_test_mock_modal_function.generate.remote.call_args
        prompt_arg_str = call_args[0][0] 
        try:
            prompt_dict_str_match = re.search(r"eval\((\{.*?\})\)", prompt_arg_str, re.DOTALL)
            if not prompt_dict_str_match: # Fallback if eval not present
                prompt_dict_str_match = re.search(r"(\{.*?\})", prompt_arg_str, re.DOTALL)
            self.assertIsNotNone(prompt_dict_str_match, "Could not find dictionary string in prompt")
            prompt_dict_content_str = prompt_dict_str_match.group(1)
            import ast
            prompt_data_dict = ast.literal_eval(prompt_dict_content_str)
            summary_in_prompt = prompt_data_dict.get("article_summary", "")
        except Exception as e:
            self.fail(f"Failed to parse prompt to extract summary: {e}\nPrompt was: {prompt_arg_str}")
        
        words = long_summary.split()
        expected_truncated_summary = ""
        for word in words:
            if len(expected_truncated_summary) + len(word) + (1 if expected_truncated_summary else 0) > MAX_SUMMARY_LENGTH:
                break
            if expected_truncated_summary: expected_truncated_summary += " "
            expected_truncated_summary += word
        expected_summary_in_prompt = expected_truncated_summary + "..."
        self.assertEqual(summary_in_prompt, expected_summary_in_prompt)

    @patch('src.agents.filter_news_agent.load_important_entities')
    @patch('modal.Function.lookup', side_effect=mock_function_lookup)
    def test_llm_malformed_json_response(self, mock_lookup, mock_load_entities):
        mock_load_entities.return_value = ([], [], [])
        malformed_json_string = "this is not json"
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_return_value=malformed_json_string
        )
        article_copy = self.article_data.copy()
        result_article = run_filter_agent(article_copy)
        self.assertIsNone(result_article.get('filter_verdict'))
        self.assertIsNotNone(result_article.get('filter_error'))
        self.assertIn("Invalid JSON response", result_article['filter_error'])
        TestRunFilterAgent.current_test_mock_modal_function.generate.remote.assert_called_once()

    @patch('src.agents.filter_news_agent.load_important_entities')
    @patch('modal.Function.lookup', side_effect=mock_function_lookup)
    @patch('src.agents.filter_news_agent.logger.warning') 
    def test_llm_invalid_verdict_content(self, mock_logger_warning, mock_lookup, mock_load_entities):
        mock_load_entities.return_value = ([], [], [])
        llm_response_invalid_content = {
            "importance_level": "SuperCritical", "topic": "Gossip",
            "reasoning": "Tried to use invalid values.", "matching_keywords": [], "matching_entities": []
        }
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_return_value=json.dumps(llm_response_invalid_content)
        )
        article_copy = self.article_data.copy()
        result_article = run_filter_agent(article_copy)
        self.assertIsNotNone(result_article.get('filter_verdict'))
        self.assertIsNone(result_article.get('filter_error')) 
        verdict = result_article['filter_verdict']
        self.assertEqual(verdict['importance_level'], DEFAULT_IMPORTANCE) 
        self.assertEqual(verdict['topic'], DEFAULT_TOPIC) 
        self.assertEqual(verdict['reasoning'], llm_response_invalid_content['reasoning'])
        expected_warnings = [
            call(f"Invalid importance_level 'SuperCritical' received. Corrected to '{DEFAULT_IMPORTANCE}'."),
            call(f"Invalid topic 'Gossip' received. Corrected to '{DEFAULT_TOPIC}'.")
        ]
        for expected_call in expected_warnings:
            self.assertIn(expected_call, mock_logger_warning.call_args_list)
        TestRunFilterAgent.current_test_mock_modal_function.generate.remote.assert_called_once()

    @patch('src.agents.filter_news_agent.load_important_entities')
    @patch('modal.Function.lookup', side_effect=mock_function_lookup)
    @patch('src.agents.filter_news_agent.time.sleep', return_value=None) 
    def test_modal_api_call_fails(self, mock_sleep, mock_lookup, mock_load_entities):
        mock_load_entities.return_value = ([], [], [])
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_side_effect=Exception("Simulated API failure")
        )
        article_copy = self.article_data.copy()
        result_article = run_filter_agent(article_copy)
        self.assertIsNone(result_article.get('filter_verdict'))
        self.assertIsNotNone(result_article.get('filter_error'))
        self.assertIn("API call failed after multiple retries", result_article['filter_error'])
        expected_call_count = 1 + LLM_MAX_RETRIES
        self.assertEqual(TestRunFilterAgent.current_test_mock_modal_function.generate.remote.call_count, expected_call_count)

    @patch('src.agents.filter_news_agent.load_important_entities') 
    def test_invalid_input_data_missing_title(self, mock_load_entities):
        article_copy = self.article_data.copy()
        del article_copy['title'] 
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction()
        result_article = run_filter_agent(article_copy)
        self.assertIsNone(result_article.get('filter_verdict'))
        self.assertIsNotNone(result_article.get('filter_error'))
        self.assertIn("Missing 'title' in article_data", result_article['filter_error'])
        mock_load_entities.assert_not_called() 

    @patch('src.agents.filter_news_agent.load_important_entities')
    def test_invalid_input_data_missing_summary(self, mock_load_entities):
        article_copy = self.article_data.copy()
        if 'processed_summary' in article_copy: del article_copy['processed_summary']
        if 'summary' in article_copy: del article_copy['summary']
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction()
        result_article = run_filter_agent(article_copy)
        self.assertIsNone(result_article.get('filter_verdict'))
        self.assertIsNotNone(result_article.get('filter_error'))
        self.assertIn("Missing 'summary' or 'processed_summary' in article_data", result_article['filter_error'])
        mock_load_entities.assert_not_called()

    @patch('src.agents.filter_news_agent.load_important_entities')
    def test_invalid_input_data_not_a_dict(self, mock_load_entities):
        invalid_article_data = "just a string, not a dictionary"
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction()
        result_article = run_filter_agent(invalid_article_data) 
        self.assertIsNotNone(result_article)
        self.assertIsInstance(result_article, dict) 
        self.assertIsNone(result_article.get('filter_verdict'))
        self.assertIsNotNone(result_article.get('filter_error'))
        self.assertIn("article_data must be a dictionary", result_article['filter_error'])
        mock_load_entities.assert_not_called()

    @patch('modal.Function.lookup', side_effect=mock_function_lookup)
    @patch('src.agents.filter_news_agent.load_important_entities')
    def test_entities_loading_failure_file_not_found(self, mock_load_entities, mock_lookup):
        # Simulate FileNotFoundError
        mock_load_entities.side_effect = FileNotFoundError("important_entities.json not found")
        
        llm_response_json = { # LLM should still be called
            "importance_level": "Interesting", "topic": "Technology", "reasoning": "Default.",
            "matching_keywords": [], "matching_entities": []
        }
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_return_value=json.dumps(llm_response_json)
        )
        
        article_copy = self.article_data.copy()
        result_article = run_filter_agent(article_copy)
        
        # Agent should proceed, filter_error should indicate entity loading issue, but not fail the whole process.
        # The current agent code logs a warning and proceeds with empty entity lists.
        # So, no filter_error is set for this specific case by run_filter_agent directly.
        # The impact is on the prompt data (content_signals.important_entities will be empty).
        self.assertIsNone(result_article.get('filter_error')) 
        self.assertIsNotNone(result_article.get('filter_verdict')) # LLM call should succeed
        
        mock_load_entities.assert_called_once()
        TestRunFilterAgent.current_test_mock_modal_function.generate.remote.assert_called_once()
        
        # Verify prompt content related to entities (should be empty)
        call_args = TestRunFilterAgent.current_test_mock_modal_function.generate.remote.call_args
        prompt_arg_str = call_args[0][0]
        try:
            prompt_dict_str_match = re.search(r"eval\((\{.*?\})\)", prompt_arg_str, re.DOTALL)
            if not prompt_dict_str_match:
                 prompt_dict_str_match = re.search(r"(\{.*?\})", prompt_arg_str, re.DOTALL)
            self.assertIsNotNone(prompt_dict_str_match)
            prompt_dict_content_str = prompt_dict_str_match.group(1)
            import ast
            prompt_data_dict = ast.literal_eval(prompt_dict_content_str)
            content_signals = prompt_data_dict.get("content_signals", {})
            self.assertEqual(content_signals.get("person_entities"), [])
            self.assertEqual(content_signals.get("org_entities"), [])
            self.assertEqual(content_signals.get("misc_entities"), [])
        except Exception as e:
            self.fail(f"Failed to parse prompt for entity check: {e}\nPrompt was: {prompt_arg_str}")

    @patch('modal.Function.lookup', side_effect=mock_function_lookup)
    @patch('src.agents.filter_news_agent.load_important_entities')
    def test_entities_loading_empty_lists(self, mock_load_entities, mock_lookup):
        # Simulate load_important_entities returning empty lists (e.g., file exists but is empty/malformed)
        mock_load_entities.return_value = ([], [], []) # Empty lists
        
        llm_response_json = {
            "importance_level": "Interesting", "topic": "Technology", "reasoning": "Default.",
            "matching_keywords": [], "matching_entities": []
        }
        TestRunFilterAgent.current_test_mock_modal_function = MockModalFunction(
            generate_remote_return_value=json.dumps(llm_response_json)
        )
        
        article_copy = self.article_data.copy()
        result_article = run_filter_agent(article_copy)
        
        self.assertIsNone(result_article.get('filter_error'))
        self.assertIsNotNone(result_article.get('filter_verdict'))
        
        mock_load_entities.assert_called_once()
        TestRunFilterAgent.current_test_mock_modal_function.generate.remote.assert_called_once()

        call_args = TestRunFilterAgent.current_test_mock_modal_function.generate.remote.call_args
        prompt_arg_str = call_args[0][0]
        try:
            prompt_dict_str_match = re.search(r"eval\((\{.*?\})\)", prompt_arg_str, re.DOTALL)
            if not prompt_dict_str_match:
                 prompt_dict_str_match = re.search(r"(\{.*?\})", prompt_arg_str, re.DOTALL)
            self.assertIsNotNone(prompt_dict_str_match)
            prompt_dict_content_str = prompt_dict_str_match.group(1)
            import ast
            prompt_data_dict = ast.literal_eval(prompt_dict_content_str)
            content_signals = prompt_data_dict.get("content_signals", {})
            self.assertEqual(content_signals.get("person_entities"), [])
            self.assertEqual(content_signals.get("org_entities"), [])
            self.assertEqual(content_signals.get("misc_entities"), [])
        except Exception as e:
            self.fail(f"Failed to parse prompt for entity check: {e}\nPrompt was: {prompt_arg_str}")


if __name__ == '__main__':
    unittest.main()

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add project root to sys.path to allow direct import of src.agents.research_agent
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from src.agents.research_agent import run_research_agent
# We will also need to import constants and potentially other functions to mock
from src.agents.research_agent import MIN_FULL_TEXT_LENGTH, NEWS_FEED_URLS 
# Assuming these are some of the external libraries that need to be mocked.
# We might not need to mock them directly if we mock the functions that use them.
# For now, let's list them as a reminder based on the problem description.
# import feedparser
# import requests
# import trafilatura
# from bs4 import BeautifulSoup
# from serpapi import GoogleSearch
# from sentence_transformers import SentenceTransformer
# from PIL import Image


class TestRunResearchAgent(unittest.TestCase):

    def setUp(self):
        # Common setup for tests, if any
        pass

    def tearDown(self):
        # Common teardown for tests, if any
        pass

    # Test scenarios will be added here as methods

    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', []) # Ensure RSS processing is skipped
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content')
    def test_successful_gyro_pick_processing(self, mock_get_full_article_content, mock_find_best_image, mock_sleep):
        # 1. Prepare input
        mock_gyro_pick = {
            "id": "gyro123",
            "title": "Test Gyro Article",
            "original_source_url": "http://example.com/gyro-article", # Changed 'link' to 'original_source_url'
            "source_type": "gyro_pick",
            "published_date": "2023-01-01T00:00:00Z",
            "image_url_from_gyro": None, # Test case where image needs to be found
            "raw_scraped_text": None # Test case where full content needs to be fetched
        }
        gyro_picks_data_list = [mock_gyro_pick]
        processed_ids_set = set()
        max_articles_to_fetch = 1

        # 2. Setup mocks
        mock_article_text = "This is the full article content. " * 10 # Ensure it's > MIN_FULL_TEXT_LENGTH
        mock_get_full_article_content.return_value = mock_article_text
        
        mock_image_url = "http://example.com/image.jpg"
        # _find_best_image is expected to return (image_url, image_extension, image_path, image_bytes)
        # For this test, we only care that it returns a URL, and the rest can be simplified
        # as they are not directly validated in this specific test's output structure for the article dictionary.
        # The critical part is that it doesn't return None.
        mock_find_best_image.return_value = mock_image_url # Actual function returns Optional[str]


        # 3. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=gyro_picks_data_list,
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 4. Assertions
        self.assertEqual(len(processed_articles), 1)
        article = processed_articles[0]

        self.assertEqual(article['id'], mock_gyro_pick['id'])
        self.assertEqual(article['title'], mock_gyro_pick['title'])
        self.assertEqual(article['link'], mock_gyro_pick['link'])
        self.assertEqual(article['text_content'], mock_article_text)
        self.assertEqual(article['image_url'], mock_image_url) # Check if the found image URL is used
        self.assertIn(mock_gyro_pick['id'], processed_ids_set) # Check if ID was added to processed set
        
        # Check that mocks were called
        mock_get_full_article_content.assert_called_once_with(mock_gyro_pick['original_source_url'], None)
        # The arguments for _find_best_image are:
        # (article_id, article_title, article_link, article_source_type, published_date_str, image_url_from_source=None, article_html_content=None)
        mock_find_best_image.assert_called_once_with(mock_gyro_pick['title'], mock_gyro_pick['original_source_url'])
        self.assertEqual(article['selected_image_url'], mock_image_url)


    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', ['http://testfeed.com/rss'])
    @patch('src.agents.research_agent.feedparser.parse')
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content')
    def test_successful_rss_feed_processing(self, mock_get_full_article_content, mock_find_best_image, mock_feedparser_parse, mock_sleep):
        # 1. Prepare input
        processed_ids_set = set()
        max_articles_to_fetch = 1

        # 2. Setup Mocks
        # Mock for feedparser.parse
        mock_feed_entry = MagicMock()
        mock_feed_entry.id = "rss123"
        mock_feed_entry.title = "Test RSS Article"
        mock_feed_entry.link = "http://example.com/rss-article"
        mock_feed_entry.summary = "RSS Summary. " * 5 # Needs to be long enough if used as fallback
        mock_feed_entry.published = "2023-01-02T00:00:00Z" # Example published date
        # Mocking enclosure if the agent uses it for images from RSS
        mock_feed_entry.enclosures = [{'type': 'image/jpeg', 'href': 'http://example.com/rss-image.jpg'}]


        mock_parsed_feed = MagicMock()
        mock_parsed_feed.entries = [mock_feed_entry]
        mock_parsed_feed.status = 200 # Fix for TypeError
        mock_feedparser_parse.return_value = mock_parsed_feed

        # Mock for _get_full_article_content
        mock_article_text = "This is the full article content from RSS. " * 10
        mock_get_full_article_content.return_value = mock_article_text

        # Mock for _find_best_image
        mock_image_url = "http://example.com/found-image.jpg"
        mock_find_best_image.return_value = mock_image_url # Actual function returns Optional[str]

        # 3. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=[], # Empty for this test
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 4. Assertions
        self.assertEqual(len(processed_articles), 1)
        article = processed_articles[0]

        self.assertEqual(article['id'], mock_feed_entry.id)
        self.assertEqual(article['title'], mock_feed_entry.title)
        self.assertEqual(article['link'], mock_feed_entry.link)
        # The key for processed text is 'processed_summary' in the agent
        # The key for image is 'selected_image_url'
        self.assertEqual(article['processed_summary'], mock_article_text) # Assuming mock_article_text is the final processed content
        self.assertEqual(article['selected_image_url'], mock_image_url)
        self.assertIn(mock_feed_entry.id, processed_ids_set)

        # Check that mocks were called
        mock_feedparser_parse.assert_called_once_with('http://testfeed.com/rss')
        # _get_full_article_content is called with link, and it tries to fetch. Summary is not directly passed.
        # The agent's _process_feed_entry calls _get_full_article_content(link)
        # The 'summary' from RSS is used if full_article_text is shorter or None.
        # If _get_full_article_content returns mock_article_text, then that's used.
        # The arguments to _get_full_article_content are just (article_url).
        # The mock for _get_full_article_content in the test is:
        # mock_get_full_article_content.return_value = mock_article_text
        # The call from _process_feed_entry is _get_full_article_content(link)
        mock_get_full_article_content.assert_called_once_with(mock_feed_entry.link)
        
        # Call to _find_best_image from _process_feed_entry:
        # _find_best_image(image_search_query, article_url_for_scrape=link)
        # image_search_query = title or summary. Here, title is "Test RSS Article"
        # link is mock_feed_entry.link
        mock_find_best_image.assert_called_once_with(
            mock_feed_entry.title, # search_query
            mock_feed_entry.link   # article_url_for_scrape
        )

    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', []) # Ensure RSS processing is skipped
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content')
    def test_skip_already_processed_id(self, mock_get_full_article_content, mock_find_best_image, mock_sleep):
        # 1. Prepare input
        mock_gyro_pick = {
            "id": "gyro123", # This ID will be in processed_ids_set
            "title": "Test Gyro Article",
            "original_source_url": "http://example.com/gyro-article", # Changed 'link'
            "source_type": "gyro_pick",
            "published_date": "2023-01-01T00:00:00Z"
        }
        gyro_picks_data_list = [mock_gyro_pick]
        processed_ids_set = {"gyro123"} # Pre-populate with the ID
        max_articles_to_fetch = 1

        # 2. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=gyro_picks_data_list,
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 3. Assertions
        self.assertEqual(len(processed_articles), 0) # Should be empty
        mock_get_full_article_content.assert_not_called()
        mock_find_best_image.assert_not_called()

    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', []) # Ensure RSS processing is skipped
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content')
    def test_content_extraction_failure_none(self, mock_get_full_article_content, mock_find_best_image, mock_sleep):
        # 1. Prepare input
        mock_gyro_pick = {
            "id": "gyro_content_fail_none",
            "title": "Test Content Fail Article",
            "original_source_url": "http://example.com/gyro-content-fail", # Changed 'link'
            "source_type": "gyro_pick",
            "published_date": "2023-01-01T00:00:00Z",
            "raw_scraped_text": None
        }
        gyro_picks_data_list = [mock_gyro_pick]
        processed_ids_set = set()
        max_articles_to_fetch = 1

        # 2. Setup mocks
        mock_get_full_article_content.return_value = None # Simulate content extraction failure

        # 3. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=gyro_picks_data_list,
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 4. Assertions
        self.assertEqual(len(processed_articles), 0)
        mock_get_full_article_content.assert_called_once_with(mock_gyro_pick['original_source_url'], None)
        mock_find_best_image.assert_not_called() # Should not be called if content fails

    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', []) # Ensure RSS processing is skipped
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content')
    def test_content_extraction_failure_too_short(self, mock_get_full_article_content, mock_find_best_image, mock_sleep):
        # 1. Prepare input
        mock_gyro_pick = {
            "id": "gyro_content_fail_short",
            "title": "Test Content Fail Short Article",
            "original_source_url": "http://example.com/gyro-content-fail-short", # Changed 'link'
            "source_type": "gyro_pick",
            "published_date": "2023-01-01T00:00:00Z",
            "raw_scraped_text": None
        }
        gyro_picks_data_list = [mock_gyro_pick]
        processed_ids_set = set()
        max_articles_to_fetch = 1

        # 2. Setup mocks
        short_content = "Too short." # Less than MIN_FULL_TEXT_LENGTH (assuming it's > len("Too short."))
        mock_get_full_article_content.return_value = short_content

        # 3. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=gyro_picks_data_list,
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 4. Assertions
        self.assertEqual(len(processed_articles), 0)
        mock_get_full_article_content.assert_called_once_with(mock_gyro_pick['original_source_url'], None)
        # Depending on the agent's logic, it might call _find_best_image even if content is short,
        # but the problem description implies the article is skipped.
        # Let's assume for now it skips before image finding if content is too short.
        # If the actual agent logic calls _find_best_image and then discards, this assertion would change.
        # Given MIN_FULL_TEXT_LENGTH check is early in _process_entry, _find_best_image shouldn't be called.
        mock_find_best_image.assert_not_called()

    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', []) # Ensure RSS processing is skipped
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content') # Corrected typo _get__full_article_content
    def test_image_finding_failure(self, mock_get_full_article_content, mock_find_best_image, mock_sleep):
        # 1. Prepare input
        mock_gyro_pick = {
            "id": "gyro_image_fail",
            "title": "Test Image Fail Article",
            "original_source_url": "http://example.com/gyro-image-fail", # Changed 'link'
            "source_type": "gyro_pick",
            "published_date": "2023-01-01T00:00:00Z",
            "raw_scraped_text": None,
            "image_url_from_gyro": None
        }
        gyro_picks_data_list = [mock_gyro_pick]
        processed_ids_set = set()
        max_articles_to_fetch = 1

        # 2. Setup mocks
        mock_article_text = "This is valid article content for image failure test. " * 10
        mock_get_full_article_content.return_value = mock_article_text
        mock_find_best_image.return_value = None # Simulate image finding/validation failure (returns Optional[str])

        # 3. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=gyro_picks_data_list,
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 4. Assertions
        self.assertEqual(len(processed_articles), 0)
        mock_get_full_article_content.assert_called_once_with(mock_gyro_pick['original_source_url'], None)
        mock_find_best_image.assert_called_once_with(
            mock_gyro_pick['title'], 
            mock_gyro_pick['original_source_url'] 
        )

    @patch('src.agents.research_agent.time.sleep', return_value=None) # Disable sleep
    @patch('src.agents.research_agent.NEWS_FEED_URLS', ['http://testfeed.com/rss'])
    @patch('src.agents.research_agent.feedparser.parse')
    @patch('src.agents.research_agent._find_best_image')
    @patch('src.agents.research_agent._get_full_article_content')
    def test_respect_max_articles_to_fetch(self, mock_get_full_article_content, mock_find_best_image, mock_feedparser_parse, mock_sleep):
        # 1. Prepare input
        processed_ids_set = set()
        max_articles_to_fetch = 1 # Crucial for this test

        # 2. Setup Mocks
        # Mock for feedparser.parse to return two entries
        mock_feed_entry1 = MagicMock()
        mock_feed_entry1.id = "rss_max_1"
        mock_feed_entry1.title = "Test RSS Article 1 (Max Fetch)"
        mock_feed_entry1.link = "http://example.com/rss-article-max1"
        mock_feed_entry1.summary = "RSS Summary 1."
        mock_feed_entry1.published = "2023-01-03T00:00:00Z"
        mock_feed_entry1.enclosures = []

        mock_feed_entry2 = MagicMock()
        mock_feed_entry2.id = "rss_max_2"
        mock_feed_entry2.title = "Test RSS Article 2 (Max Fetch)"
        mock_feed_entry2.link = "http://example.com/rss-article-max2"
        mock_feed_entry2.summary = "RSS Summary 2."
        mock_feed_entry2.published = "2023-01-03T01:00:00Z"
        mock_feed_entry2.enclosures = []

        mock_parsed_feed = MagicMock()
        mock_parsed_feed.entries = [mock_feed_entry1, mock_feed_entry2]
        mock_parsed_feed.status = 200 # Fix for TypeError
        mock_feedparser_parse.return_value = mock_parsed_feed

        # Mock for _get_full_article_content (to be called only once)
        mock_article_text = "Full content for RSS Article 1. " * 10
        mock_get_full_article_content.return_value = mock_article_text

        # Mock for _find_best_image (to be called only once)
        mock_image_url = "http://example.com/found-image-max1.jpg"
        mock_find_best_image.return_value = mock_image_url # Actual function returns Optional[str]

        # 3. Call run_research_agent
        processed_articles = run_research_agent(
            gyro_picks_data_list=[],
            processed_ids_set=processed_ids_set,
            max_articles_to_fetch=max_articles_to_fetch
        )

        # 4. Assertions
        self.assertEqual(len(processed_articles), 1) # Only one article should be processed
        article = processed_articles[0]
        self.assertEqual(article['id'], mock_feed_entry1.id) # Ensure it's the first article
        self.assertIn(mock_feed_entry1.id, processed_ids_set)
        self.assertNotIn(mock_feed_entry2.id, processed_ids_set) # Second article's ID should not be processed

        # Check that mocks were called only once (for the first article)
        mock_feedparser_parse.assert_called_once_with('http://testfeed.com/rss')
        # _get_full_article_content is called with link only from _process_feed_entry
        mock_get_full_article_content.assert_called_once_with(mock_feed_entry1.link)
        # _find_best_image is called with title and link from _process_feed_entry
        mock_find_best_image.assert_called_once_with(
            mock_feed_entry1.title, # search_query
            mock_feed_entry1.link   # article_url_for_scrape
        )


if __name__ == '__main__':
    unittest.main()

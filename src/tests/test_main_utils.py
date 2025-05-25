import sys
import os
import unittest
from datetime import datetime, timezone

# Add project root to sys.path to allow direct import of src.main
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from src.main import slugify, get_sort_key

class TestSlugify(unittest.TestCase):
    def test_simple_string(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_mixed_case(self):
        self.assertEqual(slugify("MiXeD CaSe"), "mixed-case")

    def test_special_characters(self):
        self.assertEqual(slugify("Test!@#$%^&*()_+=-`~[]{}|;':\",./<>? Me"), "test-me")

    def test_leading_trailing_spaces(self):
        self.assertEqual(slugify("  leading and trailing spaces  "), "leading-and-trailing-spaces")

    def test_empty_string(self):
        self.assertEqual(slugify(""), "untitled-article")
        self.assertEqual(slugify("   "), "untitled-article") # Also test with only spaces

    def test_long_string_truncation(self):
        long_string = "a" * 100
        slug = slugify(long_string)
        self.assertTrue(len(slug) <= 70, f"Slug '{slug}' is longer than 70 characters.")
        # Check if it's truncated to 'a-a-a...' type or just 'aaaa...' based on slugify logic
        # The current slugify logic joins with '-' after splitting by non-alphanum,
        # then truncates. For a string of all 'a's, it becomes 'a' then truncated.
        # If it were "a a a ...", it would be "a-a-a".
        # Let's refine this based on actual slugify behavior for monolithic strings.
        # The provided slugify function does:
        # slug = text_to_slugify.lower()
        # slug = re.sub(r'[^\w\s-]', '', slug).strip() # keeps underscores and hyphens if they are \w
        # slug = re.sub(r'[-\s]+', '-', slug)
        # slug = slug[:max_len].strip('-')
        # For "a"*100, it becomes "a"*70.
        self.assertEqual(slug, "a" * 70)

        long_string_with_spaces = "long string " * 20 # approx 12*20 = 240 chars
        slug_with_spaces = slugify(long_string_with_spaces)
        self.assertTrue(len(slug_with_spaces) <= 70)
        # Expected: "long-string-long-string-long-string-long-string-long-string-long-str" (or similar)
        # It should end with a full word or truncated word, not a hyphen.
        self.assertFalse(slug_with_spaces.endswith("-"))


    def test_apostrophes(self):
        self.assertEqual(slugify("It's a test"), "its-a-test")
        self.assertEqual(slugify("Authors' Names"), "authors-names")

    def test_unicode_characters(self):
        # Based on re.sub(r'[^\w\s-]', '', slug), non-ASCII letters should be kept if \w includes them.
        # Python's \w includes Unicode letters by default.
        self.assertEqual(slugify("你好 世界"), "你好-世界")
        self.assertEqual(slugify("Привет, мир!"), "привет-мир") # Russian with comma and exclamation
        self.assertEqual(slugify("Café crème"), "cafe-creme") # Accented char


class TestGetSortKey(unittest.TestCase):
    def test_valid_iso_date_zulu(self):
        article = {'published_iso': "2023-01-01T12:00:00Z"}
        expected_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(get_sort_key(article), expected_dt)

    def test_valid_iso_date_with_offset(self):
        article = {'published_iso': "2023-01-01T12:00:00+02:00"}
        # This should be converted to UTC: 2023-01-01T10:00:00Z
        expected_dt = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(get_sort_key(article), expected_dt)

    def test_valid_iso_date_naive_then_utc(self):
        # The function should treat naive datetimes (no tzinfo) as UTC.
        article = {'published_iso': "2023-01-01T12:00:00"}
        expected_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(get_sort_key(article), expected_dt)

    def test_invalid_date_string(self):
        article = {'published_iso': "not a real date string"}
        # Should fallback to a very old date (epoch or min_datetime)
        # The function uses datetime.min.replace(tzinfo=timezone.utc)
        expected_fallback_dt = datetime.min.replace(tzinfo=timezone.utc)
        self.assertEqual(get_sort_key(article), expected_fallback_dt)

    def test_missing_published_iso_key(self):
        article = {'title': "Some article without a date"}
        expected_fallback_dt = datetime.min.replace(tzinfo=timezone.utc)
        self.assertEqual(get_sort_key(article), expected_fallback_dt)

    def test_input_not_a_dict(self):
        article = "this is not a dictionary"
        expected_fallback_dt = datetime.min.replace(tzinfo=timezone.utc)
        # Ensure it handles non-dict input gracefully
        self.assertEqual(get_sort_key(article), expected_fallback_dt)

    def test_returned_datetime_is_timezone_aware_utc(self):
        article = {'published_iso': "2023-01-01T12:00:00Z"}
        dt_result = get_sort_key(article)
        self.assertIsNotNone(dt_result.tzinfo)
        self.assertEqual(dt_result.tzinfo, timezone.utc)

        article_naive = {'published_iso': "2023-01-01T15:00:00"}
        dt_naive_result = get_sort_key(article_naive)
        self.assertIsNotNone(dt_naive_result.tzinfo)
        self.assertEqual(dt_naive_result.tzinfo, timezone.utc)


if __name__ == '__main__':
    unittest.main()

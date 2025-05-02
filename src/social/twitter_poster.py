# src/social/twitter_poster.py
import tweepy
import os
import requests
import logging
import io
from dotenv import load_dotenv # Added for potential local testing

logger = logging.getLogger(__name__)

# --- Added for potential local testing ---
# Get the project root directory (assuming this script is in src/social)
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
# Load .env file from project root
dotenv_path = os.path.join(PROJECT_ROOT_DIR, '.env')
load_dotenv(dotenv_path=dotenv_path)
# --- End local testing setup ---


# Load credentials from environment variables (passed by GitHub Actions or loaded from .env)
API_KEY = os.getenv('TWITTER_API_KEY')
API_SECRET = os.getenv('TWITTER_API_SECRET')
ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET')

def authenticate_twitter_v1():
    """Authenticates using OAuth 1.0a (needed for media upload)"""
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
        logger.error("Twitter API v1 credentials missing from environment variables.")
        return None, None

    try:
        auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
        api_v1 = tweepy.API(auth)
        logger.info("Twitter API v1 authentication successful.")
        return api_v1, auth # Return auth for v2 client setup
    except Exception as e:
        logger.exception(f"Twitter API v1 authentication failed: {e}")
        return None, None

def authenticate_twitter_v2(auth_v1):
    """Authenticates using OAuth 1.0a handler for v2 client"""
    if not auth_v1:
         logger.error("Cannot init v2 client without v1 auth.")
         return None
    try:
         # Pass v1 auth handler to v2 client
         client_v2 = tweepy.Client(
             consumer_key=API_KEY,
             consumer_secret=API_SECRET,
             access_token=ACCESS_TOKEN,
             access_token_secret=ACCESS_SECRET
         )
         logger.info("Twitter API v2 client initialized.")
         return client_v2
    except Exception as e:
         logger.exception(f"Twitter API v2 client initialization failed: {e}")
         return None


def download_image_for_tweet(url):
    """Downloads image data from URL"""
    if not url or not url.startswith('http'):
        logger.warning(f"Invalid image URL for tweet download: {url}")
        return None
    try:
        headers = {'User-Agent': 'Mozilla/5.0 DacoolaBot/1.0'} # Simple user agent
        response = requests.get(url, timeout=20, stream=True, headers=headers)
        response.raise_for_status()
        # Check content type roughly
        content_type = response.headers.get('content-type', '').lower()
        if 'image' not in content_type:
            # Allow common misconfigurations like octet-stream if they are common
            logger.warning(f"URL content type ('{content_type}') not image for tweet: {url}. Trying anyway.")
            # return None # Stricter check

        # Read content into BytesIO
        image_content = io.BytesIO(response.content)
        # Quick check if it's empty
        if image_content.getbuffer().nbytes == 0:
            logger.error(f"Downloaded image content is empty for {url}")
            return None

        # Optional: Add a PIL check here to ensure it's a valid image file format
        # try:
        #     from PIL import Image, UnidentifiedImageError
        #     img = Image.open(image_content)
        #     img.verify() # Check if Pillow can identify it
        #     image_content.seek(0) # Reset position after verify
        # except (ImportError, UnidentifiedImageError, Exception) as img_err:
        #     logger.error(f"Image validation failed for {url}: {img_err}")
        #     return None

        return image_content

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download image {url} for tweet: {e}")
        return None
    except Exception as e:
        logger.error(f"Generic error downloading image {url} for tweet: {e}")
        return None

def post_tweet_with_image(article_title, article_url, image_url):
    """Posts a tweet with text and an image."""
    logger.info(f"Attempting to post tweet for: {article_title}")

    api_v1, auth_v1 = authenticate_twitter_v1()
    client_v2 = authenticate_twitter_v2(auth_v1) # Use v1 auth for v2 client

    if not api_v1 or not client_v2:
        logger.error("Twitter authentication failed. Cannot post tweet.")
        return False

    # 1. Download the image
    image_data = download_image_for_tweet(image_url)
    if not image_data:
        logger.error(f"Failed to download image, cannot tweet with media: {image_url}")
        return False

    # 2. Upload image using V1.1 API
    media = None
    try:
        image_data.seek(0) # Reset stream position
        # Determine a reasonable filename based on URL or default
        filename = os.path.basename(image_url.split('?')[0]) if '/' in image_url else "image.jpg"
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            filename = "image.jpg" # Default if extension is missing/weird

        media = api_v1.media_upload(filename=filename, file=image_data)
        if media and media.media_id_string:
             logger.info(f"Image uploaded to Twitter. Media ID: {media.media_id_string}")
        else:
             logger.error("Media upload call succeeded but returned invalid media object.")
             return False # Critical failure if media ID missing
    except tweepy.errors.TweepyException as e:
        logger.error(f"Twitter media upload failed: {e}")
        # Check for specific errors like file size too large
        if "File size exceeds" in str(e):
             logger.error("Image file size likely too large for Twitter.")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error during media upload: {e}")
        return False

    if not media or not media.media_id_string: # Check again after potential error
         logger.error("Media object or media ID is invalid after upload attempt.")
         return False

    # 3. Construct Tweet Text
    # Ensure link is absolute
    if not article_url.startswith('http'):
         logger.warning(f"Article URL '{article_url}' seems relative. Posting anyway, but might be wrong.")

    # Reserve space for the link (approx 23 chars) and the image (counts as link)
    # Also reserve space for "\n\nCheck it out: " (18 chars)
    # Max length for title is roughly 280 - 23 - 18 = 239
    max_title_len = 239
    if len(article_title) > max_title_len:
        truncated_title = article_title[:max_title_len-3] + "..." # Use ...
    else:
        truncated_title = article_title

    tweet_text = f"{truncated_title}\n\nCheck it out: {article_url}"

    # Final length check (just in case)
    if len(tweet_text) > 280:
         logger.warning(f"Calculated tweet text still exceeds 280 chars ({len(tweet_text)}). Truncating harder.")
         # Fallback to very short version
         tweet_text = f"{article_title[:100]}...\n\nCheck it out: {article_url}"
         tweet_text = tweet_text[:280] # Hard cut

    # 4. Post Tweet using V2 API with Media ID
    try:
        logger.info(f"Posting tweet text (length {len(tweet_text)}): {tweet_text}")
        response = client_v2.create_tweet(
            text=tweet_text,
            media_ids=[media.media_id_string]
        )
        tweet_id = response.data.get('id') if response.data else 'N/A'
        # Check for errors in the response itself, even if no exception occurred
        if response.errors and len(response.errors) > 0:
            logger.error(f"Twitter API returned errors: {response.errors}")
            # Check for duplicate error specifically
            for error in response.errors:
                if error.get('code') == 187: # Status is a duplicate
                    logger.warning("Twitter reported duplicate content (Error Code 187). Skipping.")
                    return True # Treat as non-fatal for workflow
            return False # Other API error

        logger.info(f"Successfully posted tweet! Tweet ID: {tweet_id}")
        return True
    except tweepy.errors.TweepyException as e:
        logger.error(f"Failed to create tweet (TweepyException): {e}")
        if hasattr(e, 'api_codes') and 187 in e.api_codes: # Duplicate status V1 error code
            logger.warning("Twitter reported duplicate content (TweepyException Code 187). Skipping.")
            return True
        # Could check other common codes like 403 Forbidden (Permissions?)
        return False
    except Exception as e:
        logger.exception(f"Unexpected error creating tweet: {e}")
        return False

# Example usage (for testing, won't run in main flow)
if __name__ == "__main__":
    # Basic logging setup for standalone run
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.info("--- Running Twitter Poster Standalone Test ---")
    # Credentials should be loaded from .env by load_dotenv() call near top
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
         logger.error("Cannot run standalone test: Twitter credentials not found in environment variables (ensure .env file is in project root).")
    else:
        # Example Data (replace with realistic test data)
        test_title = f"Automated Test Tweet ({datetime.now().strftime('%H:%M:%S')})"
        test_url = "https://dacoolaa.netlify.app/" # Link to your site homepage or a test article
        # Using a known good image URL for testing
        test_image = "https://techcrunch.com/wp-content/uploads/2024/06/YouTube-Thumb-Text-2-3.png"

        logger.info(f"Test Title: {test_title}")
        logger.info(f"Test URL: {test_url}")
        logger.info(f"Test Image URL: {test_image}")

        success = post_tweet_with_image(test_title, test_url, test_image)

        if success:
            logger.info("Standalone test tweet appears successful.")
        else:
            logger.error("Standalone test tweet failed.")
    logger.info("--- Twitter Poster Standalone Test Complete ---")
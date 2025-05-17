# src/social/social_media_poster.py (1/1) - As Provided ("Pylance Error Fixes")
import os
import sys
import logging
import time
import json
import random
from datetime import datetime, timezone # Added timezone
import requests

from dotenv import load_dotenv

# --- For Bluesky ---
try:
    from atproto import Client as BskyClient, models as bsky_models
    # For TextBuilder if used for manual facet creation:
    # from atproto.client_utils import TextBuilder
    # For specific exceptions if needed:
    # from atproto.exceptions import SomeSpecificBskyException
    BskyAPIError = Exception # General exception for now
except ImportError:
    BskyClient = None
    bsky_models = None
    # TextBuilder = None
    BskyAPIError = None
    logging.warning("atproto SDK not found. Bluesky posting will be disabled. Run: pip install atproto")

# --- For Reddit ---
try:
    import praw
    from prawcore.exceptions import Forbidden, NotFound
except ImportError:
    praw = None
    Forbidden = None
    NotFound = None
    logging.warning("praw library not found. Reddit posting will be disabled. Run: pip install praw")

# --- For Twitter ---
try:
    import tweepy
except ImportError:
    tweepy = None
    logging.warning("tweepy library not found. Twitter posting will be disabled. Run: pip install 'tweepy>=4.0.0'")


# --- Path Setup & Logging ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

# --- File Paths ---
HISTORY_FILE = os.path.join(PROJECT_ROOT, 'data', 'social_media_posts_history.json')
ALL_ARTICLES_FILE = os.path.join(PROJECT_ROOT, 'public', 'all_articles.json') # For standalone test

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Bluesky Credentials & Client Instances
BLUESKY_CLIENTS = []
for i in range(1, 4):
    handle = os.getenv(f'BLUESKY_HANDLE_{i}')
    password = os.getenv(f'BLUESKY_APP_PASSWORD_{i}')
    if handle and password:
        BLUESKY_CLIENTS.append({'handle': handle, 'password': password, 'client_instance': None})


# Reddit Credentials
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USERNAME = os.getenv('REDDIT_USERNAME')
REDDIT_PASSWORD = os.getenv('REDDIT_PASSWORD')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', f"DacoolaPostBot/0.1 by u/{REDDIT_USERNAME or 'your_reddit_username'}")

SUBREDDIT_LIST_STR = os.getenv('REDDIT_SUBREDDITS', "testingground4bots")
TARGET_SUBREDDITS_WITH_FLAIRS = []
for item in SUBREDDIT_LIST_STR.split(','):
    item = item.strip()
    if not item:
        continue
    if ':' in item:
        name, flair_id = item.split(':', 1)
        TARGET_SUBREDDITS_WITH_FLAIRS.append({'name': name.strip(), 'flair_id': flair_id.strip()})
    else:
        TARGET_SUBREDDITS_WITH_FLAIRS.append({'name': item.strip(), 'flair_id': None})

# Twitter Credentials
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')


def load_post_history():
    if not os.path.exists(HISTORY_FILE):
        return {"posted_articles": []}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict) or 'posted_articles' not in data or not isinstance(data['posted_articles'], list):
                logger.warning(f"History file {HISTORY_FILE} has invalid format. Resetting.")
                return {"posted_articles": []}
            return data
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from history file {HISTORY_FILE}. Resetting.")
        return {"posted_articles": []}
    except Exception as e:
        logger.error(f"Error loading post history: {e}")
        return {"posted_articles": []}

def save_post_history(history):
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True) # Ensure data directory exists
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving post history: {e}")

def mark_article_as_posted_in_history(article_id):
    """Explicitly marks an article ID as posted in the history file."""
    if not article_id:
        logger.warning("Cannot mark article as posted: No article ID provided.")
        return
    try:
        history = load_post_history()
        # Ensure 'posted_articles' key exists and is a list
        if 'posted_articles' not in history or not isinstance(history['posted_articles'], list):
            history['posted_articles'] = []

        if article_id not in history['posted_articles']:
            history['posted_articles'].append(article_id)
            save_post_history(history)
            logger.info(f"Article ID {article_id} marked as posted in social media history.")
        else:
            logger.debug(f"Article ID {article_id} was already in social media post history.")
    except Exception as e:
        logger.error(f"Error marking article {article_id} as posted in history: {e}")


def load_all_articles_for_standalone_test(): # Renamed for clarity
    if not os.path.exists(ALL_ARTICLES_FILE):
        logger.warning(f"{ALL_ARTICLES_FILE} not found. Cannot load articles for standalone test.")
        return []
    try:
        with open(ALL_ARTICLES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and "articles" in data and isinstance(data["articles"], list):
                return data.get('articles', [])
            logger.error(f"Invalid format in {ALL_ARTICLES_FILE} for standalone test.")
            return []
    except Exception as e:
        logger.error(f"Error loading articles from {ALL_ARTICLES_FILE} for standalone test: {e}")
        return []

def get_random_unposted_article_for_standalone_test(): # Renamed for clarity
    history = load_post_history()
    posted_ids = set(history.get('posted_articles',[]))
    all_articles = load_all_articles_for_standalone_test()

    available_articles = [
        article for article in all_articles
        if isinstance(article, dict) and article.get('id') and article['id'] not in posted_ids
    ]

    if not available_articles:
        logger.warning("No unposted articles available for random selection in standalone test!")
        return None

    chosen_article = random.choice(available_articles)
    
    # Construct the full URL properly
    base_url = os.getenv('YOUR_SITE_BASE_URL', 'https://dacoolaa.netlify.app').rstrip('/')
    article_link = chosen_article.get('link', '').lstrip('/')
    full_article_url = f"{base_url}/{article_link}"


    return {
        'id': chosen_article['id'],
        'title': chosen_article.get('title', 'Untitled Article'),
        'article_url': full_article_url, 
        'image_url': chosen_article.get('image_url'),
        'summary_short': chosen_article.get('summary_short'),
        'topic': chosen_article.get('topic', 'Technology'),
        'tags': chosen_article.get('tags', [])
    }

def _generate_bluesky_facets_atproto(text_content, link_url_to_facet):
    if not BskyClient or not bsky_models or not bsky_models.AppBskyRichtextFacet:
        logger.warning("atproto SDK components for facets not available (BskyClient, bsky_models, or RichtextFacet).")
        return None

    facets = []
    try:
        text_bytes = text_content.encode('utf-8')
        if not isinstance(link_url_to_facet, str):
            logger.warning(f"Link URL for facet is not a string: {link_url_to_facet}")
            return None

        link_bytes = link_url_to_facet.encode('utf-8')
        start_index = text_bytes.find(link_bytes)

        if start_index != -1:
            end_index = start_index + len(link_bytes)
            facet_link = bsky_models.AppBskyRichtextFacet.Link(uri=link_url_to_facet)
            facet_main = bsky_models.AppBskyRichtextFacet.Main(
                index=bsky_models.AppBskyRichtextFacet.ByteSlice(byteStart=start_index, byteEnd=end_index),
                features=[facet_link]
            )
            facets.append(facet_main)
        else:
            logger.warning(f"Could not find URL '{link_url_to_facet}' in text for facet: '{text_content}'")
    except Exception as e:
        logger.error(f"Error generating Bluesky facet for link '{link_url_to_facet}': {e}")
    return facets if facets else None


def post_to_bluesky(client_instance, title, article_url, summary_short=None, image_url=None):
    if not BskyClient or not client_instance:
        logger.error("Bluesky client not initialized or library not found.")
        return False
    if not bsky_models or not bsky_models.AppBskyEmbedExternal: # Check for necessary models
        logger.error("Bluesky models for embed not available from atproto SDK.")
        return False

    post_text_content = f"{title}\n\nRead more: {article_url}"
    if len(post_text_content) > 300: # Bluesky character limit for text part
        available_len = 300 - (len("\n\nRead more: ") + len(article_url) + 3) # +3 for "..."
        if available_len < 20: # Not enough space for a meaningful title
            post_text_content = f"Article: {article_url}"[:300]
        else:
            post_text_content = f"{title[:available_len]}...\n\nRead more: {article_url}"

    facets = _generate_bluesky_facets_atproto(post_text_content, article_url)

    embed_to_post = None
    uploaded_thumb_blob = None

    if image_url:
        try:
            logger.debug(f"Attempting to download image for Bluesky card: {image_url}")
            img_response = requests.get(image_url, timeout=15)
            img_response.raise_for_status()
            image_bytes = img_response.content

            if len(image_bytes) > 1000000: # Bluesky blob size limit (1MB)
                logger.warning(f"Image {image_url} is too large ({len(image_bytes)} bytes) for Bluesky. Skipping thumb.")
            else:
                logger.debug(f"Uploading image blob to Bluesky (size: {len(image_bytes)})...")
                upload_response = client_instance.upload_blob(image_bytes)
                if upload_response and upload_response.blob:
                    uploaded_thumb_blob = upload_response.blob
                    logger.info("Successfully uploaded image blob for Bluesky card.")
                else:
                    logger.error(f"Failed to upload image blob. Response: {upload_response}")
        except requests.exceptions.RequestException as req_e:
             logger.error(f"Request error downloading image for Bluesky card ({image_url}): {req_e}")
        except Exception as e:
            logger.error(f"Error processing image for Bluesky card ({image_url}): {e}")

    title_str = str(title if title is not None else "Article")
    card_title_str = title_str
    card_description_str = str(summary_short if summary_short is not None else title_str)

    if len(card_title_str) > 200: card_title_str = card_title_str[:197] + "..."
    if len(card_description_str) > 600: card_description_str = card_description_str[:597] + "..."

    external_data = bsky_models.AppBskyEmbedExternal.External(
        uri=article_url,
        title=card_title_str,
        description=card_description_str
    )
    if uploaded_thumb_blob:
        external_data.thumb = uploaded_thumb_blob

    embed_to_post = bsky_models.AppBskyEmbedExternal.Main(external=external_data)

    try:
        logger.info(f"Attempting to post to Bluesky: '{post_text_content[:50]}...' with embed.")
        response = client_instance.send_post(
            text=post_text_content,
            embed=embed_to_post if embed_to_post else None,
            langs=['en'],
            facets=facets if facets else None
        )
        if response and response.uri:
            logger.info(f"Successfully posted to Bluesky. URI: {response.uri}")
            return True
        else:
            logger.error(f"Bluesky post failed. Response from server: {response}")
            return False
    except BskyAPIError as e:
        logger.error(f"Bluesky API Error posting: {e}")
        return False
    except Exception as e:
        logger.error(f"General error posting to Bluesky: {e}")
        return False


def post_to_reddit(reddit_instance, title, article_url, image_url=None):
    if not praw or not reddit_instance:
        logger.error("Reddit (PRAW) not initialized or library not found.")
        return False
    if not TARGET_SUBREDDITS_WITH_FLAIRS:
        logger.warning("No target subreddits configured for Reddit. Skipping.")
        return False

    success_count = 0
    for sub_config in TARGET_SUBREDDITS_WITH_FLAIRS:
        subreddit_name = sub_config['name']
        flair_id_to_use = sub_config['flair_id']

        try:
            subreddit = reddit_instance.subreddit(subreddit_name)
            logger.debug(f"Checking subreddit r/{subreddit.display_name}")

            submit_params = {'title': title, 'url': article_url, 'nsfw': False, 'spoiler': False}
            if flair_id_to_use:
                submit_params['flair_id'] = flair_id_to_use
                logger.info(f"Attempting to post to r/{subreddit_name} with flair_id '{flair_id_to_use}': '{title}'")
            else:
                logger.info(f"Attempting to post to r/{subreddit_name} (no flair specified): '{title}'")

            submission = subreddit.submit(**submit_params)
            logger.info(f"Successfully posted to r/{subreddit_name}. Post ID: {submission.id}")
            success_count += 1
            if success_count < len(TARGET_SUBREDDITS_WITH_FLAIRS):
                time.sleep(5)
        except NotFound:
            logger.error(f"Subreddit r/{subreddit_name} not found or not accessible. Skipping.")
        except Forbidden as e:
             logger.error(f"Reddit Forbidden error for r/{subreddit_name}: {e}.")
        except praw.exceptions.APIException as e:
            logger.error(f"Reddit API Exception for r/{subreddit_name}: {e}")
            if "SUBMIT_VALIDATION_FLAIR_REQUIRED" in str(e).upper():
                logger.warning(f"Flair is REQUIRED for r/{subreddit_name}.")
                logger.info(f"Trying to list available flairs for r/{subreddit_name}:")
                try:
                    flairs = list(subreddit.flair.link_templates)
                    if flairs:
                        for flair_entry in flairs:
                            flair_text = flair_entry.get('text', 'N/A')
                            flair_id_val = flair_entry.get('id', 'N/A')
                            is_user_assignable = flair_entry.get('user_can_flair', flair_entry.get('richtext_enabled', False))
                            logger.info(f"  - Text: '{flair_text}', ID: '{flair_id_val}' (User Assignable: {is_user_assignable})")
                    else:
                        logger.info(f"    No flairs seem to be available for r/{subreddit_name} via API.")
                except Exception as flair_e:
                    logger.error(f"    Could not fetch flairs for r/{subreddit_name}: {flair_e}")
            elif "RATELIMIT" in str(e).upper():
                logger.warning(f"Reddit rate limit hit for r/{subreddit_name}.")
                time.sleep(60)
            elif "SUBREDDIT_NOEXIST" in str(e).upper():
                logger.error(f"Subreddit r/{subreddit_name} likely does not exist.")
        except praw.exceptions.PRAWException as e:
            logger.error(f"PRAW Exception for r/{subreddit_name}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error posting to r/{subreddit_name}: {e}")
    return success_count > 0


def post_to_twitter(twitter_client, article_details):
    if not tweepy or not twitter_client:
        logger.error("Twitter (Tweepy) client not initialized or library not found. Cannot post.")
        return False

    title = article_details.get('title')
    article_url = article_details.get('article_url')

    if not title or not article_url:
        logger.error("Missing title or article_url for Twitter post")
        return False

    tco_url_length = 23 # Standard length for t.co wrapped URLs
    # Max length for tweet is 280. We need space for title, a space, and the URL.
    space_for_title = 280 - tco_url_length - 1 # -1 for the space between title and URL

    title_for_tweet = title # Start with the full title

    # Truncate title if the combination exceeds 280 characters
    if len(title) > space_for_title:
        title_for_tweet = title[:space_for_title - 3] + "..." # -3 for "..."
    
    tweet_text = f"{title_for_tweet} {article_url}"

    # Final check, though usually the above logic should prevent this.
    if len(tweet_text) > 280:
         logger.warning(f"Tweet text still too long after title truncation ({len(tweet_text)} chars). Shortening further.")
         # This might happen if article_url itself is extremely long, though t.co wrapping usually handles this.
         # For safety, truncate the whole tweet_text if it's still over.
         tweet_text = tweet_text[:279] # Force it under limit, might look odd but prevents API error.

    try:
        logger.info(f"Attempting to post to Twitter: {tweet_text}")
        # With Tweepy v2 Client, just providing the URL in the text is usually enough
        # for Twitter to attempt to generate a card if the URL's meta tags are correct.
        # No explicit media_id attachment is needed for link previews (cards).
        response = twitter_client.create_tweet(text=tweet_text)
        
        if response.data and response.data.get("id"):
            logger.info(f"Successfully posted to Twitter. Tweet ID: {response.data['id']}")
            # The daily tweet count update should be handled by the calling script (e.g., main.py)
            # to maintain a centralized daily limit tracker.
            return True
        else:
            error_message_twitter = "Unknown error"
            if hasattr(response, 'errors') and response.errors:
                error_message_twitter = "; ".join([e.get("message", str(e)) for e in response.errors])
            logger.error(f"Twitter post failed. Response: {error_message_twitter}")
            return False
    except tweepy.TweepyException as e:
        logger.error(f"Tweepy API error posting to Twitter: {e}")
        if e.response and e.response.status_code == 429:
             logger.error("Twitter API rate limit (429 Too Many Requests) hit during posting.")
        elif hasattr(e, 'api_codes') and e.api_codes and 187 in e.api_codes: # Status is a duplicate
            logger.warning("Twitter reported this as a duplicate tweet.")
            return False # Or True if you consider duplicates as "posted" in a sense
    except Exception as e:
        logger.exception(f"Unexpected error posting to Twitter: {e}")
        return False
    return False

def initialize_social_clients():
    clients = {"bluesky_clients": [], "reddit_instance": None, "twitter_client": None}

    if BskyClient and BLUESKY_CLIENTS:
        for acc_idx, acc_details in enumerate(BLUESKY_CLIENTS):
            handle = acc_details['handle']
            password = acc_details['password']
            try:
                logger.info(f"Attempting Bluesky login for account {acc_idx + 1} ({handle})...")
                client_instance = BskyClient()
                login_response = client_instance.login(handle, password)

                if client_instance.me and client_instance.me.did:
                     logger.info(f"Bluesky login successful for {handle} (DID: {client_instance.me.did})")
                     acc_details['client_instance'] = client_instance
                     clients["bluesky_clients"].append(client_instance)
                else:
                    login_error_details = str(login_response) if login_response else "Login response missing data."
                    logger.error(f"Bluesky login check failed for {handle}. Response: {login_error_details}")
            except BskyAPIError as e:
                 logger.error(f"Bluesky API login failed for {handle}: {e}")
            except Exception as e:
                logger.error(f"General error during Bluesky login for {handle}: {e}")
    elif not BskyClient:
        logger.warning("Bluesky (atproto SDK) not installed. Skipping Bluesky client initialization.")


    if praw and all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD]):
        try:
            logger.info(f"Attempting Reddit login for u/{REDDIT_USERNAME}...")
            clients["reddit_instance"] = praw.Reddit(
                client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_CLIENT_SECRET,
                username=REDDIT_USERNAME, password=REDDIT_PASSWORD, user_agent=REDDIT_USER_AGENT,
                check_for_async=False
            )
            auth_user = clients["reddit_instance"].user.me()
            if auth_user:
                logger.info(f"Reddit PRAW instance initialized for u/{auth_user.name}.")
            else:
                logger.error("Reddit authentication check failed (user.me() returned None).")
                clients["reddit_instance"] = None
        except Exception as e:
            logger.exception(f"Reddit PRAW initialization failed: {e}")
            clients["reddit_instance"] = None
    elif not praw:
        logger.warning("Reddit (PRAW) library not installed. Skipping Reddit.")
    else:
        logger.warning("Reddit credentials missing. Skipping Reddit.")

    if tweepy and all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        try:
            logger.info("Attempting Twitter API v2 client initialization (OAuth 1.0a)...")
            client = tweepy.Client(
                consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET,
                access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET,
                wait_on_rate_limit=False # Let main script handle rate limits if needed
            )
            # Verify client
            user_info_response = client.get_me() # Returns a Response object
            if user_info_response.data: # Access the 'data' attribute for user info
                logger.info(f"Twitter client initialized successfully for @{user_info_response.data.username}")
                clients["twitter_client"] = client
            else:
                error_msg_twitter_init = "Unknown error during Twitter client get_me"
                if hasattr(user_info_response, 'errors') and user_info_response.errors:
                    error_msg_twitter_init = "; ".join([e.get("message", str(e)) for e in user_info_response.errors])
                logger.error(f"Twitter client initialization check (get_me) failed: {error_msg_twitter_init}")
        except tweepy.TweepyException as e:
            logger.error(f"Tweepy API error during Twitter client initialization: {e}")
            if e.response and e.response.status_code == 429: # Check for rate limit error
                 logger.error("Twitter API rate limit (429 Too Many Requests) hit during client initialization.")
        except Exception as e:
            logger.exception(f"Unexpected error during Twitter client initialization: {e}")
    elif not tweepy:
        logger.warning("Twitter (Tweepy) library not installed. Skipping Twitter client initialization.")
    else:
        logger.warning("Twitter API credentials (OAuth 1.0a) missing. Skipping Twitter client initialization.")

    return clients

def run_social_media_poster(article_details, social_clients, platforms_to_post=None):
    article_id_to_post = article_details.get('id')
    title = article_details.get('title')
    article_url = article_details.get('article_url')
    image_url = article_details.get('image_url')
    summary_short = article_details.get('summary_short')

    if not article_id_to_post or not title or not article_url:
        logger.error("Missing article_id, title, or article_url. Cannot post to social media.")
        return False

    attempt_all = platforms_to_post is None
    any_post_successful_flag = False

    # Post to Bluesky
    if attempt_all or "bluesky" in platforms_to_post:
        if social_clients.get("bluesky_clients"):
            for bsky_client_index, bsky_client_inst in enumerate(social_clients["bluesky_clients"]):
                if bsky_client_inst:
                    logger.info(f"Posting to Bluesky account {bsky_client_index + 1}...")
                    if post_to_bluesky(bsky_client_inst, title, article_url, summary_short, image_url):
                        any_post_successful_flag = True
                    if bsky_client_index < len(social_clients["bluesky_clients"]) - 1:
                        time.sleep(10) # Stagger posts if multiple Bsky accounts
                else:
                    logger.warning(f"Skipping Bluesky account {bsky_client_index + 1} due to uninitialized client.")
        else:
            logger.info("Bluesky posting requested/default but no clients configured, library missing, or all logins failed.")

    # Post to Reddit
    if attempt_all or "reddit" in platforms_to_post:
        if social_clients.get("reddit_instance"):
            if post_to_reddit(social_clients["reddit_instance"], title, article_url, image_url):
                any_post_successful_flag = True
        else: logger.info("Reddit posting requested/default but no instance configured or library missing.")

    # Post to Twitter
    if attempt_all or "twitter" in platforms_to_post:
        twitter_client = social_clients.get("twitter_client")
        if twitter_client:
            if post_to_twitter(twitter_client, article_details): # Pass the whole dict
                any_post_successful_flag = True
        else:
            logger.info("Twitter posting requested/default but no client configured or library/credentials missing.")

    # Mark as posted in history *after* all attempts for this article ID
    if article_id_to_post:
        mark_article_as_posted_in_history(article_id_to_post)

    return any_post_successful_flag

if __name__ == "__main__":
    logger.info("--- Running Social Media Poster Standalone Test ---")

    clients = initialize_social_clients()

    # Get a real unposted article for testing standalone functionality
    article_to_post = get_random_unposted_article_for_standalone_test()
    if not article_to_post:
        logger.error("No unposted articles available for standalone test. Exiting.")
        if not (clients.get("bluesky_clients") or clients.get("reddit_instance") or clients.get("twitter_client")):
            logger.warning("No social media clients were successfully initialized AND no articles to post for test. Exiting.")
        sys.exit(1)

    logger.info(f"Selected article for standalone test: '{article_to_post['title']}'")
    logger.info(f"Article URL: {article_to_post['article_url']}")
    logger.info(f"Image URL: {article_to_post['image_url']}")
    logger.info(f"Summary: {article_to_post['summary_short']}")

    if not (clients.get("bluesky_clients") or clients.get("reddit_instance") or clients.get("twitter_client")):
        logger.warning("No social media clients were successfully initialized. Cannot perform test post.")
    else:
        # run_social_media_poster will call mark_article_as_posted_in_history internally
        run_social_media_poster(article_to_post, clients)

    logger.info("--- Social Media Poster Standalone Test Complete ---")
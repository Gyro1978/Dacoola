# src/social/social_media_poster.py (1/1) - Fully Functional

import os
import sys
import logging
import time
from dotenv import load_dotenv

# --- For Bluesky ---
try:
    from atprototools import Session
    from atprototools.exceptions import AtException
except ImportError:
    Session = None
    AtException = None
    logging.warning("atprototools library not found. Bluesky posting will be disabled. Run: pip install atprototools")

# --- For Reddit ---
try:
    import praw
except ImportError:
    praw = None
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

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Bluesky Credentials
BLUESKY_ACCOUNTS = []
for i in range(1, 4):
    handle = os.getenv(f'BLUESKY_HANDLE_{i}')
    password = os.getenv(f'BLUESKY_APP_PASSWORD_{i}')
    if handle and password:
        BLUESKY_ACCOUNTS.append({'handle': handle, 'password': password})

# Reddit Credentials
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USERNAME = os.getenv('REDDIT_USERNAME')
REDDIT_PASSWORD = os.getenv('REDDIT_PASSWORD')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', f"DacoolaPostBot/0.1 by u/{REDDIT_USERNAME or 'your_reddit_username'}")
SUBREDDIT_LIST_STR = os.getenv('REDDIT_SUBREDDITS', "testingground4bots,Dacoola")
TARGET_SUBREDDITS = [s.strip() for s in SUBREDDIT_LIST_STR.split(',') if s.strip()]

# Twitter Credentials
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
# TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN') # Not used for OAuth 1.0a posting


def _bsky_create_link_facet(text, link_url):
    facets = []
    start_index = text.find(link_url)
    if start_index != -1:
        end_index = start_index + len(link_url)
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": start_index, "byteEnd": end_index},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link_url}]
        })
    return facets

def post_to_bluesky(session, title, article_url, summary_short=None, image_url=None):
    if not Session or not session:
        logger.error("Bluesky session not initialized or library not found.")
        return False

    post_text = f"{title}\n\nRead more: {article_url}"
    if len(post_text) > 300:
        available_len = 300 - (len("\n\nRead more: ") + len(article_url) + 3)
        if available_len < 20:
            post_text = f"Article: {article_url}"[:300]
        else:
            post_text = f"{title[:available_len]}...\n\nRead more: {article_url}"

    embed_data = None
    if article_url:
        embed_data = {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": article_url,
                "title": title,
                "description": summary_short or title,
            }
        }
    facets = _bsky_create_link_facet(post_text, article_url)

    try:
        logger.info(f"Attempting to post to Bluesky ({session.handle}): {post_text[:50]}...")
        if embed_data:
            session.postBloot(text=post_text, facets=facets if facets else None, embed=embed_data)
        else:
            session.postBloot(text=post_text, facets=facets if facets else None)
        logger.info(f"Successfully posted to Bluesky handle: {session.handle}")
        return True
    except AtException as e:
        logger.error(f"Bluesky API error for {session.handle}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error posting to Bluesky for {session.handle}: {e}")
    return False


def post_to_reddit(reddit_instance, title, article_url, image_url=None):
    if not praw or not reddit_instance:
        logger.error("Reddit (PRAW) not initialized or library not found.")
        return False
    if not TARGET_SUBREDDITS:
        logger.warning("No target subreddits configured for Reddit. Skipping.")
        return False

    success_count = 0
    for subreddit_name in TARGET_SUBREDDITS:
        try:
            subreddit = reddit_instance.subreddit(subreddit_name)
            logger.info(f"Attempting to post to r/{subreddit_name}: '{title}' URL: {article_url}")
            submission = subreddit.submit(title=title, url=article_url, nsfw=False, spoiler=False)
            logger.info(f"Successfully posted to r/{subreddit_name}. Post ID: {submission.id}")
            success_count += 1
            time.sleep(2)
        except praw.exceptions.APIException as e:
            logger.error(f"Reddit API Exception for r/{subreddit_name}: {e}")
            if "RATELIMIT" in str(e).upper():
                logger.warning("Reddit rate limit hit.")
        except praw.exceptions.PRAWException as e:
            logger.error(f"PRAW Exception for r/{subreddit_name}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error posting to r/{subreddit_name}: {e}")
    return success_count > 0

def post_to_twitter(twitter_client, title, article_url):
    """Posts a tweet using the provided Tweepy v2 client."""
    if not tweepy or not twitter_client:
        logger.error("Twitter (Tweepy) client not initialized or library not found. Cannot post.")
        return False

    # Twitter's URL shortener (t.co) counts any URL as 23 characters.
    # Max tweet length is 280.
    tco_url_length = 23
    space_for_title = 280 - tco_url_length - 1 # -1 for the space between title and URL

    tweet_text = f"{title} {article_url}" # Initial attempt

    if len(title) > space_for_title:
        title = title[:space_for_title - 3] + "..." # Truncate title with ellipsis
        tweet_text = f"{title} {article_url}"

    # Final check, though unlikely to be needed if title truncation is correct
    if len(tweet_text) > 280: # Should not happen with t.co, but as a safeguard
         logger.warning(f"Tweet text still too long after attempted truncation ({len(tweet_text)} chars). Final attempt to shorten.")
         tweet_text = tweet_text[:279] # Hard truncate if somehow still over

    try:
        logger.info(f"Attempting to post to Twitter: {tweet_text}")
        response = twitter_client.create_tweet(text=tweet_text)
        if response.data and response.data.get("id"):
            logger.info(f"Successfully posted to Twitter. Tweet ID: {response.data['id']}")
            return True
        else:
            error_message = "Unknown error"
            if response.errors:
                error_message = "; ".join([e.get("message", str(e)) for e in response.errors])
            logger.error(f"Twitter post failed. Response: {error_message}")
            return False
    except tweepy.TweepyException as e: # Catch specific Tweepy exceptions
        logger.error(f"Tweepy API error posting to Twitter: {e}")
        # You could check e.api_codes or e.api_messages for more details
        # e.g., if 403 and "duplicate content" is in message, it's a duplicate tweet
        if e.api_codes and 187 in e.api_codes: # Status is a duplicate
            logger.warning("Twitter reported this as a duplicate tweet.")
            return False # Or True if you consider duplicate as "handled"
    except Exception as e:
        logger.exception(f"Unexpected error posting to Twitter: {e}")
        return False
    return False


def initialize_social_clients():
    clients = {"bluesky_sessions": [], "reddit_instance": None, "twitter_client": None}

    # Bluesky
    if Session and BLUESKY_ACCOUNTS:
        for acc in BLUESKY_ACCOUNTS:
            try:
                logger.info(f"Attempting Bluesky login for {acc['handle']}...")
                bsky_session = Session(handle=acc['handle'], password=acc['password'])
                logger.info(f"Bluesky login successful for {bsky_session.handle}")
                clients["bluesky_sessions"].append(bsky_session)
            except AtException as e: logger.error(f"Bluesky login failed for {acc['handle']}: {e}")
            except Exception as e: logger.exception(f"Unexpected error during Bluesky login for {acc['handle']}: {e}")
    elif not Session: logger.warning("Bluesky (atprototools) library not installed. Skipping Bluesky.")

    # Reddit
    if praw and all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD]):
        try:
            logger.info(f"Attempting Reddit login for u/{REDDIT_USERNAME}...")
            clients["reddit_instance"] = praw.Reddit(
                client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_CLIENT_SECRET,
                username=REDDIT_USERNAME, password=REDDIT_PASSWORD, user_agent=REDDIT_USER_AGENT
            )
            logger.info(f"Reddit PRAW instance initialized for u/{clients['reddit_instance'].user.me()}.")
        except Exception as e:
            logger.exception(f"Reddit PRAW initialization failed: {e}")
            clients["reddit_instance"] = None
    elif not praw: logger.warning("Reddit (PRAW) library not installed. Skipping Reddit.")
    else: logger.warning("Reddit credentials missing. Skipping Reddit.")

    # Twitter
    if tweepy and all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        try:
            logger.info("Attempting Twitter API v2 client initialization (OAuth 1.0a)...")
            client = tweepy.Client(
                consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET,
                access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET
            )
            # Test the client by getting authenticated user's info
            user_info_response = client.get_me()
            if user_info_response.data:
               logger.info(f"Twitter client initialized successfully for @{user_info_response.data.username}")
               clients["twitter_client"] = client
            else:
               error_message = "Unknown error"
               if user_info_response.errors:
                   error_message = "; ".join([e.get("message", str(e)) for e in user_info_response.errors])
               logger.error(f"Twitter client initialization check (get_me) failed: {error_message}")
        except tweepy.TweepyException as e:
            logger.error(f"Tweepy API error during Twitter client initialization: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error during Twitter client initialization: {e}")
    elif not tweepy:
        logger.warning("Twitter (Tweepy) library not installed. Skipping Twitter client initialization.")
    else:
        logger.warning("Twitter API credentials (OAuth 1.0a) missing. Skipping Twitter client initialization.")

    return clients

def run_social_media_poster(article_details, social_clients, platforms_to_post=None):
    title = article_details.get('title')
    article_url = article_details.get('article_url')
    image_url = article_details.get('image_url') # Currently used by Reddit for thumbnail hint, Bluesky for card
    summary_short = article_details.get('summary_short') # Used by Bluesky for card

    if not title or not article_url:
        logger.error("Missing title or article_url. Cannot post to social media.")
        return

    attempt_all = platforms_to_post is None
    posted_to_twitter_successfully = False # Flag for main.py if it needs to know

    # Post to Bluesky
    if attempt_all or "bluesky" in platforms_to_post:
        if social_clients.get("bluesky_sessions"):
            for bsky_session in social_clients["bluesky_sessions"]:
                post_to_bluesky(bsky_session, title, article_url, summary_short, image_url)
                time.sleep(5) # Delay between different Bluesky accounts
        else: logger.info("Bluesky posting requested/default but no sessions configured or library missing.")

    # Post to Reddit
    if attempt_all or "reddit" in platforms_to_post:
        if social_clients.get("reddit_instance"):
            post_to_reddit(social_clients["reddit_instance"], title, article_url, image_url)
        else: logger.info("Reddit posting requested/default but no instance configured or library missing.")

    # Post to Twitter
    if attempt_all or "twitter" in platforms_to_post:
        twitter_client = social_clients.get("twitter_client")
        if twitter_client:
            if post_to_twitter(twitter_client, title, article_url):
                posted_to_twitter_successfully = True # Mark as success for potential external tracking
        else:
            logger.info("Twitter posting requested/default but no client configured or library/credentials missing.")
    
    # Could return a dict of successes if main.py needs to know which platforms succeeded, e.g.
    # return {"twitter_posted": posted_to_twitter_successfully, ...}


# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logger.info("--- Running Social Media Poster Standalone Test (Fully Functional Twitter) ---")
    test_article = {
        "id": "test-social-post-003",
        "title": f"Functional Twitter Test Post via Python ({time.strftime('%Y-%m-%d %H:%M:%S')})",
        "article_url": "https://dacoolaa.netlify.app/home.html", # Use a real, short URL
        "image_url": "https://i.imgur.com/A5Wdp6f.png",
        "topic": "Live Testing",
        "tags": ["tweepy", "python", "socialmedia", "live"],
        "summary_short": "This is a live test post to Twitter using Tweepy v2 OAuth 1.0a."
    }
    clients = initialize_social_clients()

    # Test only Twitter if client is available
    if clients.get("twitter_client"):
        logger.info("\n--- Test: Posting only to Twitter (Live Attempt) ---")
        run_social_media_poster(test_article, clients, platforms_to_post=("twitter",))
    else:
        logger.warning("\nTwitter client not initialized. Skipping Twitter-only test.")

    # Example of posting to all (if you want to test other platforms too)
    # logger.info("\n--- Test: Posting to all available platforms ---")
    # test_article["title"] = f"Functional All Platforms Test ({time.strftime('%Y-%m-%d %H:%M:%S')})"
    # run_social_media_poster(test_article, clients)


    logger.info("--- Social Media Poster Standalone Test Complete ---")
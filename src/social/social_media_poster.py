import os
import sys
import logging
import time
from dotenv import load_dotenv

# --- For Bluesky ---
try:
    # This is the structurally correct import based on the library's __init__.py
    from atprototools import Session, AtException 
except ImportError:
    Session = None
    AtException = None
    logging.warning("atprototools library components (Session/AtException) FAILED TO IMPORT. Bluesky posting will be disabled. Ensure it's in requirements.txt and installs correctly.")

# --- For Twitter ---
try:
    import tweepy
except ImportError:
    tweepy = None
    logging.warning("tweepy library FAILED TO IMPORT. Twitter posting will be disabled. Ensure it's in requirements.txt and installs correctly.")


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
    elif os.getenv(f'BLUESKY_HANDLE_{i}') or os.getenv(f'BLUESKY_APP_PASSWORD_{i}'):
        logger.warning(f"Bluesky Handle or Password missing for account index {i}. It will be skipped.")


# Twitter Credentials
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')


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
    if not Session or not session or not AtException: 
        logger.error("Bluesky client (Session or AtException) not available. Cannot post to Bluesky.")
        return False

    post_text = f"{title}\n\nRead more: {article_url}"
    if len(post_text) > 300: 
        available_len = 300 - (len("\n\nRead more: ") + len(article_url) + 3) 
        if available_len < 20 : 
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
        logger.info(f"Attempting to post to Bluesky ({session.handle}): {post_text[:60]}...")
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


def post_to_twitter(twitter_client, title, article_url):
    if not tweepy or not twitter_client:
        logger.error("Twitter (Tweepy) client not available. Cannot post to Twitter.")
        return False

    tco_url_length = 23
    space_for_title = 280 - tco_url_length - 1 

    tweet_text = f"{title} {article_url}" 

    if len(title) > space_for_title:
        title = title[:space_for_title - 3] + "..." 
        tweet_text = f"{title} {article_url}"
    
    if len(tweet_text) > 280:
         logger.warning(f"Tweet text still too long ({len(tweet_text)} chars). Final truncate.")
         tweet_text = tweet_text[:279]

    try:
        logger.info(f"Attempting to post to Twitter: {tweet_text}")
        response = twitter_client.create_tweet(text=tweet_text)
        if response.data and response.data.get("id"):
            logger.info(f"Successfully posted to Twitter. Tweet ID: {response.data['id']}")
            return True
        else:
            error_message = "Unknown error during Twitter post."
            if response.errors: 
                error_message = "; ".join([e.get("message", str(e)) for e in response.errors])
            logger.error(f"Twitter post failed. API Response: {error_message}. Full response: {response}")
            return False
    except tweepy.TweepyException as e: 
        logger.error(f"Tweepy API error posting to Twitter: {e}")
        if hasattr(e, 'api_codes') and e.api_codes and 187 in e.api_codes: 
            logger.warning("Twitter reported this as a duplicate tweet.")
        return False 
    except Exception as e:
        logger.exception(f"Unexpected error posting to Twitter: {e}")
        return False


def initialize_social_clients():
    clients = {"bluesky_sessions": [], "twitter_client": None}
    logger.info("Initializing social media clients...")

    if Session and AtException: 
        if BLUESKY_ACCOUNTS:
            for acc_idx, acc in enumerate(BLUESKY_ACCOUNTS):
                try:
                    logger.info(f"Attempting Bluesky login for {acc['handle']} (Account {acc_idx+1})...")
                    bsky_session = Session(handle=acc['handle'], password=acc['password'])
                    logger.info(f"Bluesky login successful for {bsky_session.handle}")
                    clients["bluesky_sessions"].append(bsky_session)
                except AtException as e: logger.error(f"Bluesky login failed for {acc['handle']}: {e}")
                except Exception as e: logger.exception(f"Unexpected error during Bluesky login for {acc['handle']}: {e}")
        else:
            logger.warning("No Bluesky accounts configured in .env (BLUESKY_HANDLE_n, BLUESKY_APP_PASSWORD_n).")
    else:
        logger.warning("Bluesky (atprototools) library components (Session/AtException) not available. Skipping Bluesky client initialization.")

    if tweepy: 
        if all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
            try:
                logger.info("Attempting Twitter API v2 client initialization (OAuth 1.0a)...")
                client = tweepy.Client(
                    consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET,
                    access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET
                )
                user_info_response = client.get_me()
                if user_info_response.data:
                   logger.info(f"Twitter client initialized successfully for @{user_info_response.data.username}")
                   clients["twitter_client"] = client
                else:
                   error_message = "Unknown error"
                   if user_info_response.errors: error_message = "; ".join([e.get("message", str(e)) for e in user_info_response.errors])
                   logger.error(f"Twitter client initialization check (get_me) failed: {error_message}")
            except tweepy.TweepyException as e: logger.error(f"Tweepy API error during Twitter client initialization: {e}")
            except Exception as e: logger.exception(f"Unexpected error during Twitter client initialization: {e}")
        else:
            logger.warning("Twitter API credentials (OAuth 1.0a for v2) missing in .env. Skipping Twitter client initialization.")
    else:
        logger.warning("Twitter (Tweepy) library not available. Skipping Twitter client initialization.")
    return clients

def run_social_media_poster(article_details, social_clients, platforms_to_post=None):
    title = article_details.get('title')
    article_url = article_details.get('article_url')
    summary_short = article_details.get('summary_short') 

    if not title or not article_url:
        logger.error("Missing title or article_url for social post. Aborting.")
        return False 

    attempt_all = platforms_to_post is None
    any_post_succeeded = False

    if attempt_all or "bluesky" in platforms_to_post:
        if social_clients.get("bluesky_sessions"):
            logger.info(f"Attempting Bluesky posts for: {title[:50]}...")
            for bsky_session in social_clients["bluesky_sessions"]:
                if post_to_bluesky(bsky_session, title, article_url, summary_short): 
                    any_post_succeeded = True
                time.sleep(3) 
        else: 
            logger.info("Bluesky posting skipped: No initialized sessions or library issue.")

    if attempt_all or "twitter" in platforms_to_post:
        twitter_client = social_clients.get("twitter_client")
        if twitter_client:
            logger.info(f"Attempting Twitter post for: {title[:50]}...")
            if post_to_twitter(twitter_client, title, article_url):
                any_post_succeeded = True
        else:
            logger.info("Twitter posting skipped: Client not initialized or library issue.")
    
    return any_post_succeeded

if __name__ == "__main__":
    if not logger.handlers: 
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)], force=True)
    logger.setLevel(logging.DEBUG)
    
    logger.info("--- Running Social Media Poster Standalone Test (Twitter & Bluesky, Reddit Removed) ---")
    test_article = {
        "id": "test-social-post-005",
        "title": f"Social Poster Standalone Test ({time.strftime('%Y-%m-%d %H:%M:%S')}) - Twitter & Bluesky",
        "article_url": "https://dacoolaa.netlify.app/home.html", 
        "image_url": "https://i.imgur.com/A5Wdp6f.png", 
        "summary_short": "Testing social media posting for Twitter and Bluesky via the standalone script execution."
    }
    print("Initializing social media clients...")
    logger.debug("Attempting to initialize clients for standalone test...")
    clients = initialize_social_clients()

    if not clients.get("bluesky_sessions") and not clients.get("twitter_client"):
        print("\nNo Bluesky or Twitter clients were initialized. Check .env credentials and library installations.")
    else:
        print(f"\nBluesky sessions initialized: {len(clients.get('bluesky_sessions', []))}")
        print(f"Twitter client initialized: {'Yes' if clients.get('twitter_client') else 'No'}")
        platforms_to_test = []
        if clients.get("bluesky_sessions"): platforms_to_test.append("bluesky")
        if clients.get("twitter_client"): platforms_to_test.append("twitter")
        
        if platforms_to_test:
            print(f"\n--- Attempting to post to: {', '.join(platforms_to_test)} ---")
            success = run_social_media_poster(test_article, clients, platforms_to_post=tuple(platforms_to_test))
            if success: print("\nSocial media posting function completed. At least one post may have succeeded.")
            else: print("\nSocial media posting function reported all attempts failed or no platforms were viable.")
            print("Check logs above for specific details on each platform.")
        else:
            print("\nNo social media platforms could be tested due to client initialization issues.")
    logger.info("--- Social Media Poster Standalone Test Complete ---")
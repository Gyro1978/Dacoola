# src/social/social_media_poster.py (1/1)

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


# --- Path Setup & Logging ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers(): # Basic config if not already configured by main
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

# --- Load Environment Variables ---
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Bluesky Credentials (Example for 3 accounts, add more as needed)
BLUESKY_ACCOUNTS = []
for i in range(1, 4): # Assuming up to 3 accounts, adjust as needed
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
# Subreddits to post to (comma-separated string in .env, e.g., "artificialintelligence,technology")
SUBREDDIT_LIST_STR = os.getenv('REDDIT_SUBREDDITS', "testingground4bots,Dacoola") # Default to test subreddits
TARGET_SUBREDDITS = [s.strip() for s in SUBREDDIT_LIST_STR.split(',') if s.strip()]


def _bsky_create_link_facet(text, link_url):
    """Creates a facet for a link within Bluesky post text."""
    facets = []
    # Find all occurrences of the link_url in the text to make them clickable
    # This simple approach assumes the link_url is unique and clearly identifiable.
    # For more complex text, you might need more robust parsing.
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
    """Posts to a Bluesky account."""
    if not Session or not session:
        logger.error("Bluesky session not initialized or library not found.")
        return False

    post_text = f"{title}\n\nRead more: {article_url}"
    if len(post_text) > 300: # Bluesky character limit
        # Truncate title if necessary to fit URL
        available_len = 300 - (len("\n\nRead more: ") + len(article_url) + 3) # 3 for "..."
        if available_len < 20: # Not enough space even for a short title
            logger.warning(f"Bluesky post too long even after truncation attempt for {article_url}")
            post_text = f"Article: {article_url}"[:300] # Fallback
        else:
            post_text = f"{title[:available_len]}...\n\nRead more: {article_url}"

    embed_data = None
    if article_url:
        # Attempt to create an external link card embed
        # This requires fetching metadata from the URL, which Bluesky clients often do.
        # The atprototools library might handle some of this automatically if the PDS supports it.
        # For a more robust card, you might need to fetch image data and provide it explicitly.
        embed_data = {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": article_url,
                "title": title, # Title for the link card
                "description": summary_short or title, # Description for the link card
            }
        }
        # If you have an image_url and want to try to add it to the card:
        # You'd typically need to upload it to Bluesky's blob storage first and get a CID.
        # For simplicity, we'll rely on Bluesky to fetch the preview from the link.
        # If you want to force an image, you might use app.bsky.embed.images instead or alongside.

    facets = _bsky_create_link_facet(post_text, article_url)

    try:
        logger.info(f"Attempting to post to Bluesky: {post_text[:50]}...")
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
    """Posts a link to specified subreddits."""
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
            # Submit as a link post. Reddit usually fetches a thumbnail automatically.
            submission = subreddit.submit(title=title, url=article_url, nsfw=False, spoiler=False)
            logger.info(f"Successfully posted to r/{subreddit_name}. Post ID: {submission.id}")
            success_count += 1
            time.sleep(2) # Small delay between posting to different subreddits
        except praw.exceptions.APIException as e:
            logger.error(f"Reddit API Exception for r/{subreddit_name}: {e}")
            if "RATELIMIT" in str(e).upper():
                logger.warning("Reddit rate limit hit. Consider reducing post frequency or subreddits.")
        except praw.exceptions.PRAWException as e: # More general PRAW errors
            logger.error(f"PRAW Exception for r/{subreddit_name}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error posting to r/{subreddit_name}: {e}")
    return success_count > 0


def initialize_social_clients():
    """Initializes and returns clients for enabled social media."""
    clients = {"bluesky_sessions": [], "reddit_instance": None}

    # Initialize Bluesky Sessions
    if Session and BLUESKY_ACCOUNTS:
        for acc in BLUESKY_ACCOUNTS:
            try:
                logger.info(f"Attempting Bluesky login for {acc['handle']}...")
                bsky_session = Session(handle=acc['handle'], password=acc['password'])
                logger.info(f"Bluesky login successful for {bsky_session.handle}")
                clients["bluesky_sessions"].append(bsky_session)
            except AtException as e:
                logger.error(f"Bluesky login failed for {acc['handle']}: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error during Bluesky login for {acc['handle']}: {e}")
    elif not Session:
        logger.warning("Bluesky (atprototools) library not installed. Skipping Bluesky.")

    # Initialize Reddit Instance
    if praw and all([REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD]):
        try:
            logger.info(f"Attempting Reddit login for u/{REDDIT_USERNAME}...")
            clients["reddit_instance"] = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                username=REDDIT_USERNAME,
                password=REDDIT_PASSWORD,
                user_agent=REDDIT_USER_AGENT
            )
            # Check if login was successful (PRAW might not raise error until first request)
            logger.info(f"Reddit PRAW instance initialized for u/{clients['reddit_instance'].user.me()}.")
        except Exception as e:
            logger.exception(f"Reddit PRAW initialization failed: {e}")
            clients["reddit_instance"] = None # Ensure it's None on failure
    elif not praw:
        logger.warning("Reddit (PRAW) library not installed. Skipping Reddit.")
    else:
        logger.warning("Reddit credentials missing. Skipping Reddit.")

    return clients

def run_social_media_poster(article_details, social_clients):
    """
    Takes article details and posts to configured social media.
    article_details should be a dict like the webhook_data:
    {
        "id": "article_id_here",
        "title": "Article Title Here",
        "article_url": "https://...",
        "image_url": "https://...", (optional for Bluesky card, used for Reddit thumbnail attempt)
        "topic": "AI Models",
        "tags": ["tag1", "tag2"],
        "summary_short": "A short summary..."
    }
    """
    title = article_details.get('title')
    article_url = article_details.get('article_url')
    image_url = article_details.get('image_url') # For potential future use with direct image uploads
    summary_short = article_details.get('summary_short')

    if not title or not article_url:
        logger.error("Missing title or article_url. Cannot post to social media.")
        return

    # Post to Bluesky
    if social_clients.get("bluesky_sessions"):
        for bsky_session in social_clients["bluesky_sessions"]:
            post_to_bluesky(bsky_session, title, article_url, summary_short, image_url)
            time.sleep(5) # Delay between posting to different Bluesky accounts
    else:
        logger.info("No Bluesky sessions configured or library missing. Skipping Bluesky.")

    # Post to Reddit
    if social_clients.get("reddit_instance"):
        post_to_reddit(social_clients["reddit_instance"], title, article_url, image_url)
    else:
        logger.info("No Reddit instance configured or library missing. Skipping Reddit.")


# --- Standalone Execution (for testing) ---
if __name__ == "__main__":
    logger.info("--- Running Social Media Poster Standalone Test ---")

    # Example article details (mimicking what main.py would send)
    test_article = {
        "id": "test-social-post-001",
        "title": f"Automated Test Post via Python Script ({time.strftime('%H:%M')})",
        "article_url": "https://dacoolaa.netlify.app/home.html", # Replace with a valid link
        "image_url": "https://i.imgur.com/A5Wdp6f.png", # A sample image
        "topic": "Testing",
        "tags": ["automation", "python", "socialmedia"],
        "summary_short": "This is a test post generated by an automated Python script for social media."
    }

    # Initialize clients (this would happen once in a real workflow)
    clients = initialize_social_clients()

    # Run the poster
    run_social_media_poster(test_article, clients)

    logger.info("--- Social Media Poster Standalone Test Complete ---")
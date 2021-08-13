from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import tweepy, os, logging
from typing import Tuple, List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# Tweepy setup

def create_api():
	consumer_key = os.getenv("TWITTER_API_KEY")
	consumer_secret = os.getenv("TWITTER_API_KEY_SECRET")
	access_token = os.getenv("ACCESS_TOKEN")
	access_token_secret = os.getenv("ACCESS_TOKEN_SECRET")

	auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
	auth.set_access_token(access_token, access_token_secret)
	api = tweepy.API(auth, wait_on_rate_limit=True,
		wait_on_rate_limit_notify=True)

	try:
		api.verify_credentials()
	except Exception as e:
		logger.error("Error creating API", exc_info=True)
		print('failed')
		raise e
	logger.info("API created")
	return api

api = create_api()

# Utilities

def clean_str(string: str) -> str:
	return string.replace('\n', ' ').replace("'", "’")


def scrape_twitter(query: str) -> List[Dict]:
	tweets = []
	for status in tweepy.Cursor(
		api.search,
		q=query,
		lang='en',
		tweet_mode="extended",
		count=100
	).items(500):
		tweets.append({
			"tweet_id": status.id_str,
			"user_name": clean_str(status.user.name),
			"description": clean_str(status.full_text),
			"src": f'["https://twitter.com/{status.user.screen_name}/status/{status.id_str}"]'
		})
	return tweets


# Users

def user_tweets(user_id: str) -> List[Dict]:
	"""For testing, getting one user's tweets for tweet ids to test reponse"""
	temp = api.user_timeline(screen_name=f'{user_id}',
		count = 200,
		include_rts = False,
		tweet_mode='extended')
	tweets = []
	for tweet in temp:
		tweets.append({
			"tweet_id":tweet.id,
			"full_text":tweet.full_text,
			"author":tweet.author.screen_name
			})
	return tweets


def get_user_id(screen_name: str) -> List[Dict]:
	"""Get user ids"""
	name_id_pairs = []
	resp = api.lookup_users(screen_name=screen_name)
	for user in resp:
		name_id_pairs.append({
			"screen_name":user.screen_name,
			"user_id":user.id
			})
	return name_id_pairs


# Tweets

def get_replies(user_id: str, tweet_id: int, tweeter_id: str) -> str:
	""" System to get replies to a given tweet, tweeted by user, replied by replier """
	# if type(user_id) != str:
	# 	user_id = get_user_id(user_id)
	replies = tweepy.Cursor(api.search, q='to:{}'.format(user_id),
		since_id=tweet_id, tweet_mode='extended').items(100)
	list_replies = []
	#print(replies.next())
	#return replies
	while True:
		try:
			reply = replies.next()
			if not hasattr(reply, 'in_reply_to_status_id_str'):
				continue
			if reply.in_reply_to_status_id == int(tweet_id) and reply.user.screen_name == tweeter_id:
				return reply
		except tweepy.RateLimitError as e:
			logging.error("Twitter api rate limit reached".format(e))
			time.sleep(60)
		except tweepy.TweepError as e:
			logging.error("Tweepy error occured:{}".format(e))
			break
		except StopIteration:
			print('StopIteration')
			break
		except Exception as e:
			logger.error("Failed while fetching replies {}".format(e))
			break


def respond_to_tweet(tweet_id: int, tweet_body: str) -> str:
	"""Function to reply to a certain tweet_id"""
	return api.update_status(status=tweet_body, in_reply_to_status_id = tweet_id, auto_populate_reply_metadata=True)


# Direct Messaging

# witt_rowen - 1078337070, 1423359730983051266
def send_dm(user_id: str, dm_body: str) -> str:
	"""Function to send dm"""
	api = create_api()
	dm = api.send_direct_message(user_id, dm_body)


def get_dms(count:int) -> List[Dict]:
	"""Function to get 'number' dms"""
	api = create_api()
	dms = api.list_direct_messages()
	dm_list = []
	for dm in dms:
		dm_list.append({
			"dm_id":dm.id,
			"time_created":dm.created_timestamp,
			"recipient_id":dm.message_create['target']['recipient_id'],
			"sender_id":dm.message_create['sender_id'],
			"text":dm.message_create['message_data']['text'],
			"hashtags":dm.message_create['message_data']['entities']['hashtags'],
			"symbols":dm.message_create['message_data']['entities']['symbols'],
			"user_mentions":dm.message_create['message_data']['entities']['user_mentions'],
			"urls":dm.message_create['message_data']['entities']['urls'],
			})
	return dm_list

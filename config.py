from os import getcwd
from os.path import join

from yaml import full_load

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dify_client import ChatClient
from discord import Client as DiscordClient, Intents as DiscordIntents


# Load configuration from a YAML file
config_path = join(getcwd(), "config.yaml")
with open(config_path, "r") as fp:
    config: dict = full_load(fp)

# Initialize the database
db_engine = create_engine(config.get("SQLALCHEMY_DATABASE_URI"))
db_session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()

# Initialize ChatClient
dify_chat_client = ChatClient(config.get("DIFY_API_KEY"))

# Discord config
intents = DiscordIntents.default()
intents.message_content = True
discord_client = DiscordClient(intents=intents)

LIMIT_SPEAKING_CHANNELS = config.get("LIMIT_SPEAKING_CHANNELS")
ALLOWED_CHANNELS = config.get("ALLOWED_CHANNELS")
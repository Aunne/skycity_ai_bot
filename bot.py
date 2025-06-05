from config import config, ALLOWED_CHANNELS, LIMIT_SPEAKING_CHANNELS
from config import discord_client as client
from command import *


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Get data from the message
    source_id = message.channel.id
    
    # Check if the channels id is allowed
    if (not LIMIT_SPEAKING_CHANNELS) or (source_id not in ALLOWED_CHANNELS):
        return
    # 判斷與執行使用者說的內容是否要執行
    await command_check( message )
    
if __name__ == "__main__":
    client.run(config.get("DISCORD_BOT_TOKEN"))

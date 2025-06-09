from config import config
from config import discord_client as client
from command import *


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message):
    """
    取得 on_message 事件
    並且做基礎處理 不要讓 bot 回應自己
    """
    # 不要回應自己
    if message.author == client.user:
        return
    
    # 判斷使用者說的內容是否要執行
    await command_check( message )
    
if __name__ == "__main__":
    client.run(config.get("DISCORD_BOT_TOKEN"))

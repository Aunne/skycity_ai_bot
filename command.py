from config import db_engine,db_session
from requests import HTTPError
from dify import Base, Conversation, chat_with_ai
from config import ALLOWED_CHANNELS, LIMIT_SPEAKING_CHANNELS
import logging
import discord


# 資料庫建立
Base.metadata.create_all(bind=db_engine)

# 設定 logger
logging.basicConfig(
    filename='invite_log.txt',
    filemode='a',   # append 模式
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    encoding='utf-8'
)


async def chat( message:discord.Member ):
    """
        機器人客服聊天功能
    """
    # 取得對話頻道 id 
    source_id = message.channel.id

    # Check if the channels id is allowed
    if (not LIMIT_SPEAKING_CHANNELS) or (source_id not in ALLOWED_CHANNELS):
        return
    
    # 如果遇到打招呼直接回覆這個節省效率
    user_text = message.content
    if user_text == "你好":
        await message.channel.send("你好,有什麼可以幫助您的?")
        return

    # 取得完整與玩家的對話
    conversation = db_session.query(
        Conversation).filter_by(source_id=source_id).first()
    if isinstance(conversation, Conversation):
        conversation_id = conversation.conversation_id
    else:
        conversation_id = None

    # 生成回應
    async with message.channel.typing():
        try:
            result = chat_with_ai(conversation_id, source_id, user_text)
        except HTTPError:
            await message.channel.send("伺服器錯誤 等下再試")
            return

    # 檢查是否完成
    if not isinstance(result, dict):
        return

    # 從結果中取得回答
    ai_text = result.get("answer")
    ai_text = ai_text.strip()

    # 傳送回答
    ai_text_length = len(ai_text)
    for index in range(0, ai_text_length, 2000):
        await message.channel.send(ai_text[index: index + 2000])

    # 如果沒有對話 就新增一個
    if not conversation:
        conversation_id = result.get("conversation_id")
        conversation = Conversation(
            conversation_id=conversation_id,
            source_id=source_id,
        )
        db_session.add(conversation)
        db_session.commit()


async def inviteurl( message:discord.Member ):
    """
        建立永久單次伺服器邀請
    """
    # 確定指令沒有下錯
    if not message.content == "": 
        return
    # 取得對話頻道 id 
    source_id = message.channel.id
    # 確認 channel id 允許發言 ( 確認是否有啟限制頻道功能 )
    if (not LIMIT_SPEAKING_CHANNELS) or (source_id not in ALLOWED_CHANNELS):
        return

    # 確定下指令的人有權限
    role_names = [role.name for role in message.author.roles]
    if "invite" not in role_names:
        await message.channel.send("您沒有建立邀請的權限 , 請洽有權限的人!")
        return
    
    # 產生邀請
    invite = await message.channel.create_invite(
        max_uses=1,       # 只允許 1 次使用
        max_age=0,        # 永不過期，單位為秒
        unique=True       # 確保每次都新建連結
    )
    
    # 紀錄 log 
    log_msg = f"{message.author} 在 {message.channel} 產生邀請：{invite.url}"
    logging.info(log_msg)    # 寫 log
    await message.channel.send(f"邀請連結已傳送至私人訊息!")
    await message.author.send(f"邀請連結：{invite.url}")
    

async def hi(message : discord.Member):
    """
    測試用,進行單次聊天不儲存記憶
    """
    # 取得對話頻道 id 
    source_id = message.channel.id

    # Check if the channels id is allowed
    if (not LIMIT_SPEAKING_CHANNELS) or (source_id not in ALLOWED_CHANNELS):
        return

    # 如果遇到打招呼直接回覆這個節省效率
    user_text = message.content
    if user_text == "你好":
        await message.channel.send("你好,有什麼可以幫助您的?")
        return
    
    # 生成回應
    async with message.channel.typing():
        try:
            result = chat_with_ai( source_id, user_text)
        except HTTPError:
            await message.channel.send("伺服器錯誤 等下再試")
            return

    # 檢查是否完成
    if not isinstance(result, dict):
        return

    # 從結果中取得回答
    ai_text = result.get("answer")
    ai_text = ai_text.strip()

    # 傳送回答
    ai_text_length = len(ai_text)
    for index in range(0, ai_text_length, 2000):
        await message.channel.send(ai_text[index: index + 2000])
    

async def setPass( message:discord.Member ):
    """
    賦予成員天空之城通行證身分組
    """
    # 檢查身分，沒有 foot-businessman 身分組的人不可使用此指令 
    role_names = [role.name for role in message.author.roles]
    if "foot-businessman" not in role_names:
        await message.channel.send("您沒有權限使用此指令!")
        return
    
    # 取得對話頻道 id 
    source_id = message.channel.id
    # Check if the channels id is allowed
    if (not LIMIT_SPEAKING_CHANNELS) or (source_id not in [713523805233872966]):
        return

    # 取得 message.mentions
    if not message.mentions:
        await message.channel.send("請標記一位成員（@某人）")
        return
    
    member = message.mentions[0]  # 只抓第一個
    # 要添加的身分組名稱
    ROLE_NAME = "天空之城居民"
    role = discord.utils.get(message.guild.roles, name=ROLE_NAME )
    if not role:
        await message.channel.send(f"找不到身分組 {ROLE_NAME}")
        return
    
    # 嘗試添加身分組
    try:
        await member.add_roles(role)
        await message.channel.send(f"已給 {member.mention} 身分組 {role.name}")
    except Exception as e:
        await message.channel.send(f"添加失敗: {e}")
    

# 用來判斷是否有內含的指令並執行
async def command_check( message:discord.Member ):
    # 取得使用者說話的內容
    user_text = message.content
    # 尋找指令是否符合
    for command in command_actions:
        # 找到指令就執行他
        if user_text.startswith( command ):
            # 去除指令 ( prefix )
            message.content = message.content.lstrip( command )
            await command_actions[ command ]( message )


command_actions = {
    "顧問" : chat,
    "/inviteurl":inviteurl,
    "/setPass": setPass,
    "/hi ": hi
}

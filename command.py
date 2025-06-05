from config import db_engine,db_session
from requests import HTTPError
from dify import Base, Conversation, chat_with_ai
import logging

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


async def chat( message ):
    """
        機器人客服聊天功能
    """

    # Get data from the message
    source_id = message.channel.id

    # Get conversation
    conversation = db_session.query(
        Conversation).filter_by(source_id=source_id).first()
    if isinstance(conversation, Conversation):
        conversation_id = conversation.conversation_id
    else:
        conversation_id = None

    # Remove the prefix
    user_text = message.content.lstrip("顧問")

    # 如果遇到打招呼直接回覆這個節省效率
    if user_text == "你好":
        await message.channel.send("你好,有什麼可以幫助您的?")
        return
    
    # Generate response
    async with message.channel.typing():
        try:
            result = chat_with_ai(conversation_id, source_id, user_text)
        except HTTPError:
            await message.channel.send("伺服器錯誤 等下再試")
            return

    # Check completion
    if not isinstance(result, dict):
        return

    # Extract answer from result
    ai_text = result.get("answer")
    ai_text = ai_text.strip()

    # Send the awnsers
    ai_text_length = len(ai_text)
    for index in range(0, ai_text_length, 2000):
        await message.channel.send(ai_text[index: index + 2000])

    # Set conversation
    if not conversation:
        conversation_id = result.get("conversation_id")
        conversation = Conversation(
            conversation_id=conversation_id,
            source_id=source_id,
        )
        db_session.add(conversation)
        db_session.commit()



async def invite( message ):
    """
        建立永久單次伺服器邀請
    """
    # 確定指令沒有下錯
    if not message.content.lstrip("/inviteurl") == "":
        return

    # 確定下指令的人有權限
    if message.author.id not in [ 626767393665843210, 692029559754719314, 742648999143538710, 614095160829149373 ]:
        await message.channel.send("您沒有建立邀請的權限 , 請洽有權限的人!")
        return
    
    # 產生邀請
    invite = await message.channel.create_invite(
        max_uses=1,       # 只允許 1 次使用
        max_age=0,        # 永不過期，單位為秒
        unique=True       # 確保每次都新建連結
    )

    log_msg = f"{message.author} 在 {message.channel} 產生邀請：{invite.url}"
    logging.info(log_msg)    # 寫 log
    await message.channel.send(f"邀請連結：{invite.url}")
    

async def command_check( message ):
    user_text = message.content
    for i in command:
        if user_text.startswith(i):
            await command_action[i]( message )


command = ["顧問","/inviteurl"]
command_action = {
    "顧問" : chat,
    "/inviteurl":invite
}

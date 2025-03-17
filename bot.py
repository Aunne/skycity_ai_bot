from requests import HTTPError

from dify import Base, Conversation, chat_with_ai
from config import db_engine, db_session, config, discord_client as client


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # Get data from the message
    source_id = message.channel.id
    user_text = message.content

    # Get conversation
    conversation = db_session.query(Conversation).filter_by(source_id=source_id).first()
    if isinstance(conversation, Conversation):
        conversation_id = conversation.conversation_id
    else:
        conversation_id = None

    # Check if the text starts with "bot"
    if not user_text.startswith("顧問"):
        return

    # Remove the prefix
    user_text = user_text.lstrip("顧問")

    # Generate response
    async with message.channel.typing():
        
            result = chat_with_ai(conversation_id, source_id, user_text)
        

    # Check completion
    if not isinstance(result, dict):
        return

    # Extract answer from result
    ai_text = result.get("answer")
    ai_text = ai_text.strip()

    # Send the awnsers
    ai_text_length = len(ai_text)
    for index in range(0, ai_text_length, 2000) :
        await message.channel.send(ai_text[index : index + 2000])

    # Set conversation
    if not conversation:
        conversation_id = result.get("conversation_id")
        conversation = Conversation(
            conversation_id=conversation_id,
            source_id=source_id,
        )
        db_session.add(conversation)
        db_session.commit()


if __name__ == "__main__":
    Base.metadata.create_all(bind=db_engine)
    client.run(config.get("DISCORD_BOT_TOKEN"))
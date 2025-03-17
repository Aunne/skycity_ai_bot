from typing import Union
from sqlalchemy import Column, String
from sqlalchemy.orm import DeclarativeBase
from config import dify_chat_client


class Base(DeclarativeBase):
    pass


# Define the Conversation model for the database
class Conversation(Base):
    """
    This model represents a Conversation.
    """

    __tablename__ = "conversations"
    source_id = Column(String(33), primary_key=True)
    conversation_id = Column(String(36), unique=True, nullable=False)


def chat_with_ai(
    conversation_id: Union[str, None], user_id: str, user_text: str
) -> dict:
    # Create Completion Message using CompletionClient
    completion_response = dify_chat_client.create_chat_message(
        conversation_id=conversation_id,
        user=user_id,
        query=user_text,
        inputs={},
        response_mode="blocking",
    )
    completion_response.raise_for_status()
    return completion_response.json()
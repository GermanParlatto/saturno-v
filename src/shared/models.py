from pydantic import BaseModel, Field


class TextIn(BaseModel):
    body: str


class MessageIn(BaseModel):
    sender: str = Field(alias="from")
    text: TextIn


class WebhookIn(BaseModel):
    message: MessageIn
    phone_number_id: str

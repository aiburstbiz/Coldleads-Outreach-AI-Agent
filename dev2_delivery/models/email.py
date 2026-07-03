from pydantic import BaseModel


class EmailDraft(BaseModel):
    recipient_email: str
    subject: str
    body: str
    company_name: str

from pydantic import BaseModel, Field
from typing import Optional

class ContactInfo(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class CompanyJSON(BaseModel):
    company_name: str
    website_url: str
    about: Optional[str] = None
    products: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    contact_info: Optional[ContactInfo] = None
    news: list[str] = Field(default_factory=list)
    llm_analysis: Optional[str] = None
    recommended_services: list[str] = Field(default_factory=list)
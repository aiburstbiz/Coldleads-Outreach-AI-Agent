"""
Shared JSON contract between Dev1 (research) and Dev2 (delivery).

Dev1's pipeline (search -> scraper -> analyzer -> knowledge_base -> recommender)
must produce a single CompanyResearch object.

Dev2's pipeline (ppt_generator, email_generator) consumes CompanyResearch only.
Treat this file as the single source of truth for the data shape - if a field
needs to change, update it here first and tell the other developer.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class About(BaseModel):
    summary: str
    industry: str
    founded: Optional[str] = None
    size: Optional[str] = None


class Contact(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    social_links: List[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    title: str
    date: Optional[str] = None
    summary: str


class LLMAnalysis(BaseModel):
    pain_points: List[str] = Field(default_factory=list)
    growth_signals: List[str] = Field(default_factory=list)
    tech_stack_hints: List[str] = Field(default_factory=list)
    summary: str


class RecommendedService(BaseModel):
    service: str
    reason: str
    priority: Priority


class CompanyResearch(BaseModel):
    """The single object Dev1 produces and Dev2 consumes."""

    company_name: str
    website_url: str
    scraped_at: datetime

    about: About
    products: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    contact: Contact
    news: List[NewsItem] = Field(default_factory=list)

    llm_analysis: LLMAnalysis
    recommended_services: List[RecommendedService] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "company_name": "Acme Corp",
                "website_url": "https://acme.com",
                "scraped_at": "2025-01-01T00:00:00Z",
                "about": {
                    "summary": "Acme Corp builds widgets for the modern enterprise.",
                    "industry": "Manufacturing",
                    "founded": "1998",
                    "size": "201-500 employees",
                },
                "products": ["Widget Pro", "Widget Lite"],
                "services": ["Custom manufacturing", "Logistics"],
                "contact": {
                    "email": "info@acme.com",
                    "phone": "+1-555-0100",
                    "address": "123 Main St, Springfield",
                    "social_links": ["https://linkedin.com/company/acme"],
                },
                "news": [
                    {
                        "title": "Acme opens new facility",
                        "date": "2024-11-01",
                        "summary": "Acme expanded production capacity by 30%.",
                    }
                ],
                "llm_analysis": {
                    "pain_points": ["Manual inventory tracking", "Slow order processing"],
                    "growth_signals": ["New facility opening", "Hiring engineers"],
                    "tech_stack_hints": ["SAP", "Excel-based reporting"],
                    "summary": "Acme is scaling production and shows signs of operational strain.",
                },
                "recommended_services": [
                    {
                        "service": "AI-driven inventory automation",
                        "reason": "Manual tracking flagged as a pain point",
                        "priority": "high",
                    }
                ],
            }
        }
    )


if __name__ == "__main__":
    # Quick self-check: validate the example against the schema
    example = CompanyResearch.model_config["json_schema_extra"]["example"]
    parsed = CompanyResearch.model_validate(example)
    print("Schema OK. Sample company:", parsed.company_name)
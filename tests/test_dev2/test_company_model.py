import pytest
from pydantic import ValidationError
from shared.schema import CompanyResearch


def test_full_payload_from_dev1_example():
    example = CompanyResearch.model_config["json_schema_extra"]["example"]
    company = CompanyResearch.model_validate(example)
    assert company.company_name == "Acme Corp"
    assert company.about.industry == "Manufacturing"
    assert company.contact.email is not None
    assert company.recommended_services[0].priority.value == "high"


def test_missing_required_fields_fails():
    with pytest.raises(ValidationError):
        CompanyResearch(
            company_name="Acme",
            website_url="https://acme.com",
            scraped_at="2025-01-01T00:00:00Z"
        )
from shared.schema import CompanyResearch
from dev2_delivery.email_generator import generate_email
from dev2_delivery.models.email import EmailDraft


def test_email_generates_correctly():
    example = CompanyResearch.model_config["json_schema_extra"]["example"]
    data = CompanyResearch.model_validate(example)
    draft = generate_email(data)

    assert isinstance(draft, EmailDraft)
    assert draft.company_name == "Acme Corp"
    assert "Acme Corp" in draft.body
    assert "acme.com" in draft.recipient_email
    assert len(draft.subject) > 0


def test_email_handles_missing_contact():
    example = CompanyResearch.model_config["json_schema_extra"]["example"]
    example = dict(example)
    example["contact"] = {}  # no email
    data = CompanyResearch.model_validate(example)
    draft = generate_email(data)

    assert draft.recipient_email == "unknown@unknown.com"


def test_email_filters_low_priority_services():
    example = CompanyResearch.model_config["json_schema_extra"]["example"]
    example = dict(example)
    example["recommended_services"] = [
        {"service": "Low value thing", "reason": "Not critical", "priority": "low"}
    ]
    data = CompanyResearch.model_validate(example)
    draft = generate_email(data)

    assert "Low value thing" not in draft.body
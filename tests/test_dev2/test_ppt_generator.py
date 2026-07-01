import os
from shared.schema import CompanyResearch
from dev2_delivery.ppt_generator import generate_pptx


def test_ppt_generates_file():
    example = CompanyResearch.model_config["json_schema_extra"]["example"]
    data = CompanyResearch.model_validate(example)
    output_path = generate_pptx(data)
    assert os.path.exists(output_path)
    assert output_path.endswith(".pptx")
    # cleanup
    os.remove(output_path)
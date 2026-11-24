import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ap_assistant.schemas import CaseRequest

CASES = Path(__file__).parents[2] / "fixtures" / "cases"


@pytest.mark.parametrize("case_file", sorted(CASES.glob("FIN-*.json")), ids=lambda p: p.stem)
def test_case_file_is_a_valid_request(case_file):
    request = CaseRequest.model_validate_json(case_file.read_text())
    assert request.case_id == case_file.stem


def test_negative_amount_is_refused():
    data = json.loads((CASES / "FIN-001.json").read_text())
    data["amount"] = "-5"
    with pytest.raises(ValidationError):
        CaseRequest.model_validate(data)

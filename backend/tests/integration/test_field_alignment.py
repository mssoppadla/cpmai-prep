"""
Smoke-tests that the OpenAPI schema includes every field documented in the
contract. Run pytest with backend running OR with TestClient and inspect /openapi.json.
"""
from tests.conftest import auth_header

REQUIRED_QUESTION_RESULT_FIELDS = {
    "id", "stem", "topic_id", "domain", "task", "enablers", "remarks",
    "difficulty", "explanation", "options", "is_user_correct",
}
REQUIRED_OPTION_RESULT_FIELDS = {
    "option_letter", "text", "is_correct", "reasoning", "selected_by_user",
}


def test_openapi_exposes_question_result_fields(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schemas = r.json()["components"]["schemas"]
    assert "QuestionResultView" in schemas
    props = set(schemas["QuestionResultView"]["properties"].keys())
    missing = REQUIRED_QUESTION_RESULT_FIELDS - props
    assert not missing, f"QuestionResultView missing: {missing}"


def test_openapi_question_attempt_does_NOT_expose_answers(client):
    r = client.get("/openapi.json")
    schemas = r.json()["components"]["schemas"]
    attempt_props = set(schemas["QuestionAttemptView"]["properties"].keys())
    assert "is_correct" not in attempt_props
    assert "reasoning" not in attempt_props
    # Same for the inner option type referenced by attempt view
    attempt_option = schemas.get("QuestionOptionOut", {})
    if attempt_option:
        opt_props = set(attempt_option.get("properties", {}).keys())
        assert opt_props == {"option_letter", "text"}, opt_props

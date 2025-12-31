import sys
import types

from app import gemini_service


def test_parse_message_with_fake_gemini():
    fake = types.SimpleNamespace()

    def configure(api_key=None):
        return None

    class FakeModel:
        def __init__(self, name):
            pass

        def generate_content(self, prompts):
            return types.SimpleNamespace(text='{"action":"ADD","seller":"Acme","sku":"ABC-123","qty":10,"location":"WH1"}')

    fake.configure = configure
    fake.GenerativeModel = FakeModel

    sys.modules['google.generativeai'] = fake

    result = gemini_service.parse_message("Restocked 10 units of SKU: ABC-123")

    assert isinstance(result, dict)
    assert result.get("action") == "ADD"
    assert result.get("qty") == 10


def test_parse_message_fallback_on_invalid_response(monkeypatch):
    # Simulate gemini raising an exception
    class BadModule(types.SimpleNamespace):
        def configure(self, api_key=None):
            raise RuntimeError("nope")

    sys.modules['google.generativeai'] = BadModule()

    res = gemini_service.parse_message("Ship 5 of SKU: XYZ-9 to Dock")

    assert isinstance(res, dict)
    assert res.get("sku")
    assert "action" in res

"""Thin Gemini wrapper. Every caller must work if this returns None (no key / quota / network)."""
import logging

from ..config import settings

log = logging.getLogger("llm")
_client = None


def available() -> bool:
    return bool(settings.GEMINI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def generate(prompt: str, system: str = None, temperature: float = 0.3):
    if not available():
        return None
    try:
        from google.genai import types
        r = _get_client().models.generate_content(
            model=settings.GEMINI_MODEL, contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature))
        return (r.text or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("LLM generate failed: %s", e)
        return None


def run_agent(system: str, history: list, message: str, tools: list):
    """Gemini function-calling loop (SDK executes the python tools automatically)."""
    from google.genai import types
    contents = [types.Content(role="user" if h["role"] == "user" else "model",
                              parts=[types.Part(text=h["text"])]) for h in history[-10:]]
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    r = _get_client().models.generate_content(
        model=settings.GEMINI_MODEL, contents=contents,
        config=types.GenerateContentConfig(system_instruction=system, tools=tools, temperature=0.2))
    return (r.text or "").strip() or None

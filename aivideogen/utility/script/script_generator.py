import os
from openai import OpenAI
import json

# Choose Groq or OpenAI based on your API key
if os.environ.get("GROQ_API_KEY", "") and len(os.environ["GROQ_API_KEY"]) > 30:
    from groq import Groq
    model = "gemma2-9b-it"
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
else:
    OPENAI_API_KEY = os.getenv("OPENAI_KEY")
    model = "gpt-4o"
    client = OpenAI(api_key=OPENAI_API_KEY)

def generate_script(topic: str, duration: int) -> str:
    """
    Generates a punchy social-media “reel” script for the given topic and duration.
    Returns only the script text, safely parsed from model output.
    """
    system_prompt = f"""
You are a creative, persuasive copywriter specializing in short-form social media videos 
(Instagram Reels, TikTok, YouTube Shorts). Your task is to craft a highly engaging, 
emotionally resonant script under {duration} seconds that hooks viewers in the first 2 seconds 
and drives them to action or keeps them watching.

Rules:
- Always respond ONLY in valid JSON.
- The JSON must have exactly one key: "script".
- No explanations, no markdown, no extra text.

Example:
{{ "script": "Did you know 90% of people fail their goals by February? Here's how to stay on track..." }}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": topic}
        ]
    )

    content = response.choices[0].message.content.strip()
    print("🔍 Raw LLM content >>>", content)


    # First, try direct JSON parsing
    try:
        return json.loads(content)["script"]

    # If model added extra text → try extracting {...}
    except Exception:
        start = content.find("{")
        end = content.rfind("}") + 1
        raw_json = content[start:end].strip()

        if not raw_json:
            print("⚠️ Model returned non-JSON:", content)
            return f"[Script fallback] {topic} in {duration} seconds."

        try:
            data = json.loads(raw_json)
            return data.get("script", f"[Script fallback] {topic}")
        except json.JSONDecodeError as e:
            print("⚠️ JSON decode error:", e)
            print("Raw model content:", content)
            return f"[Script fallback] {topic} in {duration} seconds."

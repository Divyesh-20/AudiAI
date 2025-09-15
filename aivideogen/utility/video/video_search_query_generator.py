from openai import OpenAI
import os
import json
import re
from datetime import datetime
from utility.utils import log_response, LOG_TYPE_GPT

# Choose model
if os.environ.get("GROQ_API_KEY") and len(os.environ["GROQ_API_KEY"]) > 30:
    from groq import Groq
    model = "gemma2-9b-it"
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
else:
    model = "gpt-4o"
    OPENAI_API_KEY = os.environ.get('OPENAI_KEY')
    client = OpenAI(api_key=OPENAI_API_KEY)

log_directory = ".logs/gpt_logs"

prompt = """# Instructions
Extract 2–3 word visually concrete keywords for each timed caption.
Each keyword must depict something visually specific, like 'rainy street' or 'cat sleeping'.
Return output strictly in JSON: [[[t1, t2], ["keyword1", "keyword2", "keyword3"]], ...].
Do not add extra text or explanation."""

def fix_json(json_str):
    # Fix quotes for proper JSON parsing
    json_str = json_str.replace("’", "'").replace("“", '"').replace("”", '"').replace("‘", '"')
    json_str = json_str.replace('"you didn"t"', '"you didn\'t"')
    return json_str

def getVideoSearchQueriesTimed(script, captions_timed, duration=60):
    """
    Generate visually concrete search queries for each timed caption.
    Returns: list of [[start, end], ["query1", "query2", ...]]
    """
    out = []
    for interval, caption_list in captions_timed:
        keywords = []
        for caption in caption_list:
            # Clean caption and ensure 2-3 word visually concrete phrase
            caption_clean = re.sub(r'[^a-zA-Z0-9 ]', '', caption).strip()
            words = caption_clean.split()
            if len(words) == 0:
                kw = "nature background"
            elif len(words) == 1:
                kw = words[0] + " scene"
            else:
                kw = " ".join(words[:3])
            keywords.append(kw)

        out.append([interval, keywords])

    # Ensure full duration coverage
    if out and out[-1][0][1] < duration:
        out.append([[out[-1][0][1], duration], ["nature background"]])

    return out

def call_OpenAI(script, captions_timed):
    user_content = f"Script: {script}\nTimed Captions: {captions_timed}"
    print("Content:", user_content)

    response = client.chat.completions.create(
        model=model,
        temperature=1,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ]
    )

    text = response.choices[0].message.content.strip()
    text = re.sub(r'\s+', ' ', text)
    print("Text:", text)
    log_response(LOG_TYPE_GPT, script, text)
    return text

def merge_empty_intervals(segments, duration: int = 60):
    """
    Merge consecutive None intervals with previous valid URL.
    If everything is None or empty, return fallback covering full duration.
    """
    if not segments:
        return [[(0, duration), None]]

    merged = []
    i = 0
    while i < len(segments):
        interval, url = segments[i]
        if url is None:
            j = i + 1
            while j < len(segments) and segments[j][1] is None:
                j += 1

            if merged and merged[-1][1] is not None:
                prev_interval, prev_url = merged[-1]
                merged[-1] = [[prev_interval[0], segments[j-1][0][1]], prev_url]
            else:
                merged.append([interval, None])
            i = j
        else:
            merged.append([interval, url])
            i += 1

    # Fallback if all URLs are None
    if all(url is None for _, url in merged):
        return [[(0, duration), None]]

    return merged


import os, io, time, hashlib, threading
from flask import Flask, render_template, request, send_file, jsonify
from gtts import gTTS
from openai import OpenAI

app = Flask(__name__)

# Keep your API key ONLY on the server:
# Linux/macOS: export GEMINI_API_KEY="..."
# Windows PowerShell: $env:GEMINI_API_KEY="..."
client = OpenAI(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL = os.environ.get("ARIA_MODEL", "gpt-5.6-luna")

TTS_LANGUAGES = {
    "en-IN":"en","hi-IN":"hi","mr-IN":"mr","ta-IN":"ta","te-IN":"te",
    "bn-IN":"bn","kn-IN":"kn","ml-IN":"ml","gu-IN":"gu","pa-IN":"pa",
    "or-IN":"or","ur-IN":"ur"
}
LANGUAGE_NAMES = {
    "en-IN":"English","hi-IN":"Hindi","mr-IN":"Marathi","ta-IN":"Tamil",
    "te-IN":"Telugu","bn-IN":"Bengali","kn-IN":"Kannada","ml-IN":"Malayalam",
    "gu-IN":"Gujarati","pa-IN":"Punjabi","or-IN":"Odia","ur-IN":"Urdu"
}

TTS_CACHE = {}
TTS_LOCK = threading.Lock()
MAX_CACHE_ITEMS = 100

def cache_key(text, language):
    return hashlib.sha256(f"{language}|{text}".encode("utf-8")).hexdigest()

def cleanup_cache():
    while len(TTS_CACHE) > MAX_CACHE_ITEMS:
        oldest = min(TTS_CACHE, key=lambda k:TTS_CACHE[k]["created"])
        del TTS_CACHE[oldest]

def generate_tts(text, language):
    key = cache_key(text, language)
    if key in TTS_CACHE:
        return TTS_CACHE[key]["audio"]
    with TTS_LOCK:
        if key in TTS_CACHE:
            return TTS_CACHE[key]["audio"]
        tts = gTTS(text=text, lang=TTS_LANGUAGES[language], slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        audio = buf.getvalue()
        TTS_CACHE[key] = {"audio":audio, "created":time.time()}
        cleanup_cache()
        return audio

@app.route("/")
def home():
    return render_template("index.html")

@app.post("/api/tts")
def tts():
    try:
        data=request.get_json(silent=True) or {}
        text=str(data.get("text","")).strip()
        language=str(data.get("language","en-IN")).strip()
        if not text: return jsonify(error="No text provided"),400
        if language not in TTS_LANGUAGES: language="en-IN"
        audio=io.BytesIO(generate_tts(text,language))
        audio.seek(0)
        response=send_file(audio,mimetype="audio/mpeg",download_name="aria_voice.mp3")
        response.headers["Cache-Control"]="public,max-age=3600"
        return response
    except Exception as e:
        return jsonify(error="TTS failed",details=str(e)),500

@app.post("/api/chat")
def chat():
    try:
        data=request.get_json(silent=True) or {}
        text=str(data.get("text","")).strip()
        language=str(data.get("language","en-IN")).strip()
        profile=data.get("profile") or {}
        contacts=data.get("contacts") or []
        history=data.get("history") or []
        location=data.get("location")
        if not text: return jsonify(error="No text provided"),400
        if language not in LANGUAGE_NAMES: language="en-IN"

        system = f"""
You are ARIA, a friendly, concise voice assistant.
The user's current preferred language is {LANGUAGE_NAMES[language]} ({language}).
Reply in that language unless the user explicitly asks for another supported language.
Supported languages: {", ".join(LANGUAGE_NAMES.values())}.
The user may ask to change language. If they do, set language to the requested language.
You may have a normal conversation and must understand natural follow-up questions.
Keep spoken replies short and natural, normally 1-3 sentences.
Do not claim to have performed an action unless the application can perform it.
For weather, the app can obtain live weather from the user's browser location.
For calls, only use contacts supplied by the application. Never invent a phone number.
Profile name: {profile.get("name","")}
Nickname: {profile.get("nickname","")}
Saved contacts: {", ".join(contacts) if contacts else "none"}.
Browser location supplied: {location if location else "not supplied"}.

Return ONLY valid JSON with:
{{
  "reply": "the spoken reply",
  "language": "one supported language code",
  "action": null OR {{
      "type": "weather" OR "medicine" OR "call",
      "contact": "contact name when type is call"
  }}
}}
Use action=weather when the user asks for current/local weather.
Use action=medicine when the user wants to set/manage a medicine reminder.
Use action=call only when the user clearly asks to call a saved contact.
"""

        input_items=[]
        for h in history[-20:]:
            if h.get("role") in ("user","assistant"):
                input_items.append({"role":h["role"],"content":h.get("content","")})
        input_items.append({"role":"user","content":text})

        response=client.responses.create(
            model=MODEL,
            instructions=system,
            input=input_items,
            text={
                "format":{
                    "type":"json_schema",
                    "name":"aria_response",
                    "strict":True,
                    "schema":{
                        "type":"object",
                        "properties":{
                            "reply":{"type":"string"},
                            "language":{"type":"string","enum":list(LANGUAGE_NAMES.keys())},
                            "action":{
                                "anyOf":[
                                    {"type":"null"},
                                    {"type":"object","properties":{
                                        "type":{"type":"string","enum":["weather","medicine","call"]},
                                        "contact":{"type":"string"}
                                    },"required":["type","contact"],"additionalProperties":False}
                                ]
                            }
                        },
                        "required":["reply","language","action"],
                        "additionalProperties":False
                    }
                }
            }
        )
        import json
        result=json.loads(response.output_text)
        return jsonify(result)
    except Exception as e:
        print("CHAT ERROR:",repr(e))
        return jsonify(error="AI conversation failed",details=str(e)),500

@app.get("/api/weather")
def weather():
    # Open-Meteo does not require an API key for this use.
    import requests
    try:
        lat=float(request.args["lat"]); lon=float(request.args["lon"])
        r=requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude":lat,"longitude":lon,"current":"temperature_2m,wind_speed_10m,weather_code","timezone":"auto"},
            timeout=8
        )
        r.raise_for_status()
        d=r.json()["current"]
        codes={
          0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",
          45:"Fog",48:"Rime fog",51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",
          61:"Light rain",63:"Rain",65:"Heavy rain",71:"Light snow",73:"Snow",75:"Heavy snow",
          80:"Rain showers",81:"Rain showers",82:"Heavy rain showers",95:"Thunderstorm",
          96:"Thunderstorm with hail",99:"Thunderstorm with heavy hail"
        }
        return jsonify(temperature=d["temperature_2m"],wind=d["wind_speed_10m"],description=codes.get(d["weather_code"],"Current conditions"))
    except Exception as e:
        return jsonify(error="Weather failed",details=str(e)),500

if __name__=="__main__":
    app.run(host="127.0.0.1",port=5000,debug=True,threaded=True)

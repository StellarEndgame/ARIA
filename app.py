import os
import io
import time
import hashlib
import threading
import json

from flask import Flask, render_template, request, send_file, jsonify
from gtts import gTTS
from google import genai
from google.genai import types


app = Flask(__name__)


# ============================================================
# GOOGLE GEMINI
# ============================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

client = genai.Client(api_key=GEMINI_API_KEY)

# You can override this in Render with ARIA_MODEL.
MODEL = os.environ.get("ARIA_MODEL", "gemini-3.7-flash")


# ============================================================
# LANGUAGES
# ============================================================

TTS_LANGUAGES = {
    "en-IN": "en",
    "hi-IN": "hi",
    "mr-IN": "mr",
    "ta-IN": "ta",
    "te-IN": "te",
    "bn-IN": "bn",
    "kn-IN": "kn",
    "ml-IN": "ml",
    "gu-IN": "gu",
    "pa-IN": "pa",
    "or-IN": "or",
    "ur-IN": "ur"
}

LANGUAGE_NAMES = {
    "en-IN": "English",
    "hi-IN": "Hindi",
    "mr-IN": "Marathi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "bn-IN": "Bengali",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "gu-IN": "Gujarati",
    "pa-IN": "Punjabi",
    "or-IN": "Odia",
    "ur-IN": "Urdu"
}


# ============================================================
# TTS CACHE
# ============================================================

TTS_CACHE = {}
TTS_LOCK = threading.Lock()
MAX_CACHE_ITEMS = 100


def cache_key(text, language):
    return hashlib.sha256(
        f"{language}|{text}".encode("utf-8")
    ).hexdigest()


def cleanup_cache():
    while len(TTS_CACHE) > MAX_CACHE_ITEMS:
        oldest = min(
            TTS_CACHE,
            key=lambda k: TTS_CACHE[k]["created"]
        )
        del TTS_CACHE[oldest]


def generate_tts(text, language):
    key = cache_key(text, language)

    if key in TTS_CACHE:
        return TTS_CACHE[key]["audio"]

    with TTS_LOCK:

        if key in TTS_CACHE:
            return TTS_CACHE[key]["audio"]

        tts = gTTS(
            text=text,
            lang=TTS_LANGUAGES[language],
            slow=False
        )

        buf = io.BytesIO()
        tts.write_to_fp(buf)

        audio = buf.getvalue()

        TTS_CACHE[key] = {
            "audio": audio,
            "created": time.time()
        }

        cleanup_cache()

        return audio


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


# ============================================================
# TEXT TO SPEECH
# ============================================================

@app.post("/api/tts")
def tts():

    try:

        data = request.get_json(silent=True) or {}

        text = str(
            data.get("text", "")
        ).strip()

        language = str(
            data.get("language", "en-IN")
        ).strip()

        if not text:
            return jsonify(
                error="No text provided"
            ), 400

        if language not in TTS_LANGUAGES:
            language = "en-IN"

        audio = io.BytesIO(
            generate_tts(text, language)
        )

        audio.seek(0)

        response = send_file(
            audio,
            mimetype="audio/mpeg",
            download_name="aria_voice.mp3"
        )

        response.headers[
            "Cache-Control"
        ] = "public,max-age=3600"

        return response

    except Exception as e:

        print("TTS ERROR:", repr(e))

        return jsonify(
            error="TTS failed",
            details=str(e)
        ), 500


# ============================================================
# ARIA CHAT
# ============================================================

@app.post("/api/chat")
def chat():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        text = str(
            data.get("text", "")
        ).strip()

        language = str(
            data.get("language", "en-IN")
        ).strip()

        profile = data.get("profile") or {}

        contacts = data.get("contacts") or []

        history = data.get("history") or []

        location = data.get("location")


        if not text:
            return jsonify(
                error="No text provided"
            ), 400


        if language not in LANGUAGE_NAMES:
            language = "en-IN"


        # ====================================================
        # SYSTEM INSTRUCTIONS
        # ====================================================

        system = f"""
You are ARIA, a friendly, concise voice assistant.

The user's current preferred language is:
{LANGUAGE_NAMES[language]} ({language})

Reply in that language unless the user explicitly asks
for another supported language.

Supported languages:
{", ".join(LANGUAGE_NAMES.values())}

The user may ask to change language.
If they do, set the language field to the requested
supported language code.

Understand natural conversation and follow-up questions.

Keep spoken replies short and natural,
normally 1-3 sentences.

Do not claim to have performed an action unless the
application can actually perform that action.

For weather, the application can obtain live weather
using the user's browser location.

For calls, ONLY use contacts supplied by the application.
Never invent a phone number or contact.

For medicine reminders, the application may handle
the reminder action.

Profile name:
{profile.get("name", "")}

Nickname:
{profile.get("nickname", "")}

Saved contacts:
{", ".join(str(c) for c in contacts) if contacts else "none"}

Browser location:
{location if location else "not supplied"}


AVAILABLE ACTIONS

Use action type "weather" when the user asks for
current or local weather.

Use action type "medicine" when the user wants to
set or manage a medicine reminder.

Use action type "call" ONLY when the user clearly
asks to call a saved contact.


IMPORTANT

Return ONLY valid JSON matching the required schema.

The JSON must contain:

reply:
The spoken response.

language:
One of the supported language codes.

action:
Either null, or an object containing:

type:
"weather", "medicine", or "call"

contact:
The contact name when type is "call".
For other action types, use an empty string.
"""


        # ====================================================
        # BUILD CONVERSATION
        # ====================================================

        conversation_parts = []

        conversation_parts.append(
            "SYSTEM INSTRUCTIONS:\n" + system
        )


        # Keep the latest 20 messages
        for h in history[-20:]:

            role = h.get("role")

            content = str(
                h.get("content", "")
            )

            if not content:
                continue

            if role == "user":

                conversation_parts.append(
                    f"USER:\n{content}"
                )

            elif role == "assistant":

                conversation_parts.append(
                    f"ARIA:\n{content}"
                )


        conversation_parts.append(
            f"USER:\n{text}"
        )


        prompt = "\n\n".join(
            conversation_parts
        )


        # ====================================================
        # JSON SCHEMA
        # ====================================================

        response_schema = {
            "type": "object",
            "properties": {

                "reply": {
                    "type": "string",
                    "description": "ARIA's spoken response."
                },

                "language": {
                    "type": "string",
                    "enum": list(
                        LANGUAGE_NAMES.keys()
                    )
                },

"action": {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["weather", "medicine", "call"]
        },
        "contact": {
            "type": "string"
        }
    },
    "required": ["type", "contact"],
    "additionalProperties": False
},

                        "contact": {
                            "type": "string"
                        }

                    },

                    "required": [
                        "type",
                        "contact"
                    ],

                    "additionalProperties": False
                }

            },

            "required": [
                "reply",
                "language",
                "action"
            ],

            "additionalProperties": False
        }


        # ====================================================
        # GEMINI REQUEST
        # ====================================================

        response = client.models.generate_content(

            model=MODEL,

            contents=prompt,

            config=types.GenerateContentConfig(

                temperature=0.7,

                response_mime_type="application/json",

                response_schema=response_schema
            )
        )


        # ====================================================
        # GET GEMINI RESPONSE
        # ====================================================

        output_text = response.text

        if not output_text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )


        result = json.loads(
            output_text
        )


        # ====================================================
        # SAFETY / NORMALIZATION
        # ====================================================

        if result.get("language") not in LANGUAGE_NAMES:

            result["language"] = language


        if "reply" not in result:

            result["reply"] = (
                "Sorry, I couldn't generate a response."
            )


        if "action" not in result:

            result["action"] = None


        # Make sure action has the expected structure
        if result["action"] is not None:

            action = result["action"]

            if action.get("type") not in (
                "weather",
                "medicine",
                "call"
            ):

                result["action"] = None

            elif "contact" not in action:

                action["contact"] = ""


        return jsonify(result)


    except Exception as e:

        print(
            "CHAT ERROR:",
            repr(e)
        )

        return jsonify(
            error="AI conversation failed",
            details=str(e)
        ), 500


# ============================================================
# WEATHER
# ============================================================

@app.get("/api/weather")
def weather():

    import requests

    try:

        lat = float(
            request.args["lat"]
        )

        lon = float(
            request.args["lon"]
        )


        r = requests.get(

            "https://api.open-meteo.com/v1/forecast",

            params={
                "latitude": lat,
                "longitude": lon,
                "current":
                    "temperature_2m,"
                    "wind_speed_10m,"
                    "weather_code",

                "timezone": "auto"
            },

            timeout=8
        )


        r.raise_for_status()


        d = r.json()["current"]


        codes = {

            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",

            45: "Fog",
            48: "Rime fog",

            51: "Light drizzle",
            53: "Drizzle",
            55: "Heavy drizzle",

            61: "Light rain",
            63: "Rain",
            65: "Heavy rain",

            71: "Light snow",
            73: "Snow",
            75: "Heavy snow",

            80: "Rain showers",
            81: "Rain showers",
            82: "Heavy rain showers",

            95: "Thunderstorm",
            96: "Thunderstorm with hail",
            99: "Thunderstorm with heavy hail"
        }


        return jsonify(

            temperature=d[
                "temperature_2m"
            ],

            wind=d[
                "wind_speed_10m"
            ],

            description=codes.get(
                d["weather_code"],
                "Current conditions"
            )
        )


    except Exception as e:

        print(
            "WEATHER ERROR:",
            repr(e)
        )

        return jsonify(
            error="Weather failed",
            details=str(e)
        ), 500


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False,
        threaded=True
    )

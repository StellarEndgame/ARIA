# ARIA Voice Assistant

## Files
- `app.py` — Flask backend, AI conversation, gTTS, weather endpoint
- `templates/index.html` — ARIA interface and voice logic
- `requirements.txt` — Python packages

## Run

1. Install Python 3.10+.
2. Install packages:
   `pip install -r requirements.txt`
3. Set your OpenAI API key as an environment variable. Do NOT put it in `index.html`.
4. Start:
   `python app.py`
5. Open:
   `http://127.0.0.1:5000`

## Features
- Spoken welcome on startup
- Natural speech recognition
- AI conversational replies
- Follow-up context during the session
- gTTS output
- 12 Indian language options
- Spoken language switching
- Weather using browser location + Open-Meteo
- Local profile and saved contacts
- Phone dialer handoff using `tel:`
- Medicine reminder UI
- Settings and privacy controls

Browser microphone and location permissions must be granted when requested.
A normal web page cannot silently read the phone's private address book, so ARIA stores contacts that you explicitly add in its local browser storage.

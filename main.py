import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
HISTORY_FILE = BASE_DIR / "historia.json"

MODEL_NAME = "gemini-2.5-flash"
SYSTEM_PROMPT = (
    "Jesteś szefem kuchni. Gdy otrzymasz zdjęcie składników, nie podawaj od razu przepisu. "
    "Najpierw przeanalizuj zdjęcie i zadaj użytkownikowi jedno pytanie o jego preferencje "
    "(np. ile ma czasu, czy woli na ciepło/zimno). Dopiero gdy użytkownik odpowie, podaj zwięzły przepis."
)

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

app = FastAPI(title="RecipeFinder Chat API")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []

    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    return data if isinstance(data, list) else []


def save_history(history: list[dict[str, Any]]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_prompt(history: list[dict[str, Any]], message: str, has_image: bool) -> str:
    serialized_history = json.dumps(history, ensure_ascii=False, indent=2)
    image_note = "tak" if has_image else "nie"

    return f"""
Dotychczasowa historia rozmowy w aplikacji RecipeFinder:
{serialized_history}

Aktualna wiadomość użytkownika:
{message or "[brak wiadomości tekstowej]"}

Czy użytkownik dołączył zdjęcie w tym zapytaniu: {image_note}.

Odpowiadaj po polsku, naturalnie i zwięźle. Zwróć wyłącznie treść wiadomości dla użytkownika,
bez HTML oraz bez opakowywania odpowiedzi w JSON.
""".strip()


async def read_optional_image(file: UploadFile | None) -> tuple[Image.Image | None, str | None]:
    if file is None or not file.filename:
        return None, None

    if file.content_type and not file.content_type.startswith("image/"):
        raise ValueError("Załączony plik musi być obrazem.")

    content = await file.read()
    if not content:
        return None, None

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except UnidentifiedImageError as exc:
        raise ValueError("Nie udało się odczytać obrazu.") from exc

    return image, file.filename


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/chat")
async def chat(
    wiadomosc: str = Form(default=""),
    plik: UploadFile | None = File(default=None),
):
    message = wiadomosc.strip()

    try:
        image, image_name = await read_optional_image(plik)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "odpowiedz_bota": str(exc)},
        )

    if not message and image is None:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "odpowiedz_bota": "Napisz wiadomość albo dodaj zdjęcie składników.",
            },
        )

    history = load_history()
    user_entry = {
        "rola": "uzytkownik",
        "tresc": message,
        "zalacznik": image_name,
        "czas": now_iso(),
    }

    prompt = build_prompt(history, message, image is not None)
    contents: list[Any] = [prompt]
    if image is not None:
        contents.append(image)

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "odpowiedz_bota": "Nie udało się teraz uzyskać odpowiedzi od modelu.",
            },
        )

    bot_reply = (response.text or "").strip()
    if not bot_reply:
        bot_reply = "Nie udało mi się wygenerować odpowiedzi. Spróbuj doprecyzować wiadomość."

    history.extend(
        [
            user_entry,
            {
                "rola": "bot",
                "tresc": bot_reply,
                "zalacznik": None,
                "czas": now_iso(),
            },
        ]
    )
    save_history(history)

    return {"status": "success", "odpowiedz_bota": bot_reply}

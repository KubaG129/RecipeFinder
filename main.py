import base64
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "recipefinder.db"

MODEL_NAME = "gemini-2.5-flash"
SYSTEM_PROMPT = (
    "Jesteś szefem kuchni. Gdy otrzymasz zdjęcie składników, nie podawaj od razu przepisu. "
    "Najpierw przeanalizuj zdjęcie i zadaj użytkownikowi jedno pytanie o jego preferencje "
    "(np. ile ma czasu, czy woli na ciepło/zimno). Dopiero gdy użytkownik odpowie, podaj zwięzły przepis."
)
SESSION_COOKIE = "recipefinder_session"
SESSION_SECRET = os.getenv("SESSION_SECRET", "recipefinder-dev-secret")

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

app = FastAPI(title="RecipeFinder Chat API")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AuthPayload(BaseModel):
    username: str
    password: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachment_name TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
            );
            """
        )


@app.on_event("startup")
async def startup() -> None:
    init_db()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt_text, digest_text = password_hash.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_text)
        expected_digest = base64.b64decode(digest_text)
    except Exception:
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(actual_digest, expected_digest)


def create_session_token(user_id: int) -> str:
    payload = str(user_id)
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session_token(token: str | None) -> int | None:
    if not token or "." not in token:
        return None

    payload, signature = token.split(".", 1)
    expected_signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        return int(payload)
    except ValueError:
        return None


def get_current_user(recipefinder_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    user_id = read_session_token(recipefinder_session)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Nie jesteś zalogowany.")

    with get_db() as db:
        user = db.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="Sesja jest nieaktualna.")

    return row_to_dict(user)


def build_prompt(history: list[dict[str, Any]], message: str, has_image: bool) -> str:
    formatted_history = "\n".join(
        f"{entry['role']}: {entry['content']}" for entry in history
    ) or "[brak wcześniejszych wiadomości w tej rozmowie]"
    image_note = "tak" if has_image else "nie"

    return f"""
Dotychczasowa historia tej rozmowy w aplikacji RecipeFinder:
{formatted_history}

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


def get_user_conversation(db: sqlite3.Connection, conversation_id: int, user_id: int) -> sqlite3.Row:
    conversation = db.execute(
        "SELECT id, user_id, title, created_at FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id),
    ).fetchone()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rozmowy.")
    return conversation


def create_conversation(db: sqlite3.Connection, user_id: int, message: str, image_name: str | None) -> int:
    title_source = message.strip() or image_name or "Nowa rozmowa"
    title = title_source[:50]
    cursor = db.execute(
        "INSERT INTO conversations (user_id, title, created_at) VALUES (?, ?, ?)",
        (user_id, title, now_iso()),
    )
    return int(cursor.lastrowid)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/register")
async def register(payload: AuthPayload, response: Response):
    username = payload.username.strip()
    password = payload.password

    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Nazwa użytkownika musi mieć co najmniej 3 znaki.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Hasło musi mieć co najmniej 6 znaków.")

    try:
        with get_db() as db:
            cursor = db.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hash_password(password), now_iso()),
            )
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Taki użytkownik już istnieje.")

    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user_id),
        httponly=True,
        samesite="lax",
    )
    return {"id": user_id, "username": username}


@app.post("/login")
async def login(payload: AuthPayload, response: Response):
    with get_db() as db:
        user = db.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (payload.username.strip(),),
        ).fetchone()

    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Nieprawidłowy login albo hasło.")

    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user["id"]),
        httponly=True,
        samesite="lax",
    )
    return {"id": user["id"], "username": user["username"]}


@app.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "success"}


@app.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)):
    return user


@app.get("/conversations")
async def conversations(user: dict[str, Any] = Depends(get_current_user)):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                conversations.id,
                conversations.title,
                conversations.created_at,
                COUNT(messages.id) AS message_count
            FROM conversations
            LEFT JOIN messages ON messages.conversation_id = conversations.id
            WHERE conversations.user_id = ?
            GROUP BY conversations.id
            ORDER BY conversations.created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db() as db:
        get_user_conversation(db, conversation_id, user["id"])
        rows = db.execute(
            """
            SELECT id, role, content, attachment_name, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, user: dict[str, Any] = Depends(get_current_user)):
    with get_db() as db:
        get_user_conversation(db, conversation_id, user["id"])
        db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return {"status": "success"}


@app.post("/chat")
async def chat(
    wiadomosc: str = Form(default=""),
    conversation_id: int | None = Form(default=None),
    plik: UploadFile | None = File(default=None),
    user: dict[str, Any] = Depends(get_current_user),
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

    is_new_conversation = conversation_id is None
    history: list[dict[str, Any]] = []

    if conversation_id is not None:
        with get_db() as db:
            get_user_conversation(db, conversation_id, user["id"])
            history_rows = db.execute(
                """
                SELECT role, content, attachment_name, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()
            history = [row_to_dict(row) for row in history_rows]

    prompt = build_prompt(history, message, image is not None)
    contents: list[Any] = [prompt]
    if image is not None:
        contents.append(image)

    try:
        gemini_response = client.models.generate_content(
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

    bot_reply = (gemini_response.text or "").strip()
    if not bot_reply:
        bot_reply = "Nie udało mi się wygenerować odpowiedzi. Spróbuj doprecyzować wiadomość."

    with get_db() as db:
        if is_new_conversation:
            conversation_id = create_conversation(db, user["id"], message, image_name)

        get_user_conversation(db, conversation_id, user["id"])
        db.execute(
            """
            INSERT INTO messages (conversation_id, role, content, attachment_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, "user", message, image_name, now_iso()),
        )
        db.execute(
            """
            INSERT INTO messages (conversation_id, role, content, attachment_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, "assistant", bot_reply, None, now_iso()),
        )

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "odpowiedz_bota": bot_reply,
    }

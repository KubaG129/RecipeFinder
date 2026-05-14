import io
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from google import genai
from PIL import Image

load_dotenv()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def strona_glowna():
    return """
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>AI Szef Kuchni</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; text-align: center; padding: 50px; }
            .container { background: white; padding: 40px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 500px; margin: auto; }
            h1 { color: #2c3e50; }
            .btn { background-color: #e67e22; color: white; padding: 12px 25px; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 20px; transition: 0.3s; }
            .btn:hover { background-color: #d35400; }
            input[type=file] { margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AI Szef Kuchni</h1>
            <p>Zrób zdjęcie swojej lodówki i sprawdź, co możemy ugotować!</p>
            <form action="/wygeneruj-przepis/" method="post" enctype="multipart/form-data">
                <input type="file" name="plik" accept="image/*" required>
                <br>
                <button type="submit" class="btn">Wygeneruj przepis</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.post("/wygeneruj-przepis/", response_class=HTMLResponse)
async def wygeneruj_przepis(plik: UploadFile = File(...)):
    try:
        zawartosc = await plik.read()
        zdjecie = Image.open(io.BytesIO(zawartosc))

        prompt = """
        Jesteś szefem kuchni. Na podstawie tego zdjęcia:
        1. Wypisz składniki, które rozpoznajesz.
        2. Zaproponuj danie.
        3. Podaj prosty przepis krok po kroku.

        WAŻNE: Zwróć całą odpowiedź używając znaczników HTML.
        Używaj nagłówków <h2>, list wypunktowanych <ul> <li> oraz paragrafów <p>.
        Nie używaj w ogóle znaczników Markdown.
        """

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[prompt, zdjecie],
        )
        gotowy_przepis_html = response.text or "<p>Nie udało się wygenerować przepisu.</p>"

        return f"""
        <!DOCTYPE html>
        <html lang="pl">
        <head>
            <meta charset="UTF-8">
            <title>Twój Przepis</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; padding: 30px; }}
                .container {{ background: white; padding: 40px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 700px; margin: auto; line-height: 1.6; }}
                .btn {{ background-color: #34495e; color: white; padding: 10px 20px; text-decoration: none; border-radius: 8px; display: inline-block; margin-bottom: 20px; }}
                h2 {{ color: #e67e22; border-bottom: 2px solid #ecf0f1; padding-bottom: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="/" class="btn">Wróć i spróbuj ponownie</a>
                <br>
                {gotowy_przepis_html}
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"<h2>Wystąpił błąd:</h2><p>{str(e)}</p>"

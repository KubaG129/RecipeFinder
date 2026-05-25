const form = document.querySelector("#chat-form");
const messages = document.querySelector("#messages");
const messageInput = document.querySelector("#message-input");
const fileInput = document.querySelector("#file-input");
const attachButton = document.querySelector("#attach-button");
const sendButton = document.querySelector("#send-button");
const filePreview = document.querySelector("#file-preview");

function scrollToLatest() {
    messages.scrollTop = messages.scrollHeight;
}

function setBusy(isBusy) {
    sendButton.disabled = isBusy;
    attachButton.disabled = isBusy;
    messageInput.disabled = isBusy;
}

function autoResizeInput() {
    messageInput.style.height = "auto";
    messageInput.style.height = `${messageInput.scrollHeight}px`;
}

function updateFilePreview() {
    const file = fileInput.files[0];

    if (!file) {
        filePreview.hidden = true;
        filePreview.textContent = "";
        return;
    }

    filePreview.hidden = false;
    filePreview.replaceChildren();

    const name = document.createElement("span");
    name.textContent = file.name;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Usuń";
    remove.addEventListener("click", () => {
        fileInput.value = "";
        updateFilePreview();
    });

    filePreview.append(name, remove);
}

function createMessage(role, text, imageUrl = null) {
    const article = document.createElement("article");
    article.className = `message ${role === "user" ? "user-message" : "bot-message"}`;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "user" ? "TY" : "RF";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text || "";

    if (imageUrl) {
        const image = document.createElement("img");
        image.className = "message-image";
        image.src = imageUrl;
        image.alt = "Załączone zdjęcie";
        bubble.append(image);
    }

    article.append(avatar, bubble);
    messages.append(article);
    scrollToLatest();

    return article;
}

function removeMessage(element) {
    if (element) {
        element.remove();
    }
}

attachButton.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", updateFilePreview);
messageInput.addEventListener("input", autoResizeInput);

messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
    }
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const text = messageInput.value.trim();
    const file = fileInput.files[0];

    if (!text && !file) {
        messageInput.focus();
        return;
    }

    const imageUrl = file ? URL.createObjectURL(file) : null;
    createMessage("user", text, imageUrl);

    const pending = createMessage("bot", "Szef kuchni pisze...");
    const payload = new FormData();
    payload.append("wiadomosc", text);
    if (file) {
        payload.append("plik", file);
    }

    messageInput.value = "";
    fileInput.value = "";
    updateFilePreview();
    autoResizeInput();
    setBusy(true);

    try {
        const response = await fetch("/chat", {
            method: "POST",
            body: payload,
        });

        const data = await response.json();
        removeMessage(pending);

        if (!response.ok || data.status !== "success") {
            createMessage("bot", data.odpowiedz_bota || "Wystąpił błąd podczas rozmowy.");
            return;
        }

        createMessage("bot", data.odpowiedz_bota);
    } catch (error) {
        removeMessage(pending);
        createMessage("bot", "Nie udało się połączyć z backendem. Sprawdź, czy FastAPI działa.");
    } finally {
        setBusy(false);
        messageInput.focus();
        if (imageUrl) {
            URL.revokeObjectURL(imageUrl);
        }
    }
});

autoResizeInput();

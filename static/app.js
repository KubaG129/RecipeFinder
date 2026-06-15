const authView = document.querySelector("#auth-view");
const chatView = document.querySelector("#chat-view");
const authForm = document.querySelector("#auth-form");
const usernameInput = document.querySelector("#username-input");
const passwordInput = document.querySelector("#password-input");
const authError = document.querySelector("#auth-error");
const loginButton = document.querySelector("#login-button");
const registerButton = document.querySelector("#register-button");
const logoutButton = document.querySelector("#logout-button");
const currentUser = document.querySelector("#current-user");

const form = document.querySelector("#chat-form");
const messages = document.querySelector("#messages");
const messageInput = document.querySelector("#message-input");
const fileInput = document.querySelector("#file-input");
const attachButton = document.querySelector("#attach-button");
const sendButton = document.querySelector("#send-button");
const filePreview = document.querySelector("#file-preview");
const conversationList = document.querySelector("#conversation-list");
const newChatButton = document.querySelector("#new-chat-button");
const chatTitle = document.querySelector("#chat-title");

let activeConversationId = null;
let conversations = [];

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

function showAuthError(text) {
    authError.textContent = text;
    authError.hidden = !text;
}

function showLoggedOut() {
    authView.hidden = false;
    chatView.hidden = true;
    currentUser.textContent = "";
    activeConversationId = null;
    conversations = [];
    conversationList.replaceChildren();
    resetMessages();
}

function showLoggedIn(user) {
    authView.hidden = true;
    chatView.hidden = false;
    currentUser.textContent = user.username;
    messageInput.focus();
}

async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.detail || "Wystąpił błąd.");
    }
    return data;
}

async function authenticate(endpoint) {
    showAuthError("");
    const username = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!username || !password) {
        showAuthError("Podaj nazwę użytkownika i hasło.");
        return;
    }

    loginButton.disabled = true;
    registerButton.disabled = true;

    try {
        const user = await apiFetch(endpoint, {
            method: "POST",
            body: JSON.stringify({ username, password }),
        });
        passwordInput.value = "";
        showLoggedIn(user);
        await loadConversations();
        startNewChat();
    } catch (error) {
        showAuthError(error.message);
    } finally {
        loginButton.disabled = false;
        registerButton.disabled = false;
    }
}

async function checkSession() {
    try {
        const user = await apiFetch("/me");
        showLoggedIn(user);
        await loadConversations();
        startNewChat();
    } catch (error) {
        showLoggedOut();
    }
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

function resetMessages() {
    messages.replaceChildren();
    createMessage("assistant", "Cześć. Dodaj zdjęcie składników albo napisz, co masz pod ręką.");
}

function createMessage(role, text, attachmentName = null, imageUrl = null) {
    const article = document.createElement("article");
    article.className = `message ${role === "user" ? "user-message" : "bot-message"}`;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "user" ? "TY" : "RF";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text || "";

    if (attachmentName && !imageUrl) {
        const attachment = document.createElement("div");
        attachment.className = "attachment-name";
        attachment.textContent = `Załącznik: ${attachmentName}`;
        bubble.append(attachment);
    }

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

function renderConversations() {
    conversationList.replaceChildren();

    if (conversations.length === 0) {
        const empty = document.createElement("p");
        empty.className = "empty-history";
        empty.textContent = "Brak zapisanych rozmów.";
        conversationList.append(empty);
        return;
    }

    conversations.forEach((conversation) => {
        const row = document.createElement("div");
        row.className = "conversation-row";
        if (conversation.id === activeConversationId) {
            row.classList.add("active");
        }

        const button = document.createElement("button");
        button.type = "button";
        button.className = "conversation-button";
        button.textContent = conversation.title;
        button.addEventListener("click", () => loadMessages(conversation.id));

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "delete-button";
        deleteButton.title = "Usuń rozmowę";
        deleteButton.setAttribute("aria-label", "Usuń rozmowę");
        deleteButton.textContent = "×";
        deleteButton.addEventListener("click", async () => {
            await deleteConversation(conversation.id);
        });

        row.append(button, deleteButton);
        conversationList.append(row);
    });
}

async function loadConversations() {
    conversations = await apiFetch("/conversations");
    renderConversations();
}

async function loadMessages(conversationId) {
    const items = await apiFetch(`/conversations/${conversationId}/messages`);
    activeConversationId = conversationId;
    const conversation = conversations.find((item) => item.id === conversationId);
    chatTitle.textContent = conversation ? conversation.title : "AI szef kuchni";
    messages.replaceChildren();

    items.forEach((item) => {
        createMessage(item.role, item.content, item.attachment_name);
    });

    if (items.length === 0) {
        resetMessages();
    }

    renderConversations();
}

async function deleteConversation(conversationId) {
    await apiFetch(`/conversations/${conversationId}`, { method: "DELETE" });
    if (activeConversationId === conversationId) {
        startNewChat();
    }
    await loadConversations();
}

function startNewChat() {
    activeConversationId = null;
    chatTitle.textContent = "AI szef kuchni";
    resetMessages();
    renderConversations();
}

authForm.addEventListener("submit", (event) => {
    event.preventDefault();
    authenticate("/login");
});

registerButton.addEventListener("click", () => authenticate("/register"));

logoutButton.addEventListener("click", async () => {
    await apiFetch("/logout", { method: "POST" });
    showLoggedOut();
});

newChatButton.addEventListener("click", startNewChat);
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
    createMessage("user", text, file ? file.name : null, imageUrl);

    const pending = createMessage("assistant", "Szef kuchni pisze...");
    const payload = new FormData();
    payload.append("wiadomosc", text);
    if (activeConversationId !== null) {
        payload.append("conversation_id", activeConversationId);
    }
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
            createMessage("assistant", data.odpowiedz_bota || data.detail || "Wystąpił błąd podczas rozmowy.");
            return;
        }

        activeConversationId = data.conversation_id;
        createMessage("assistant", data.odpowiedz_bota);
        await loadConversations();
    } catch (error) {
        removeMessage(pending);
        createMessage("assistant", "Nie udało się połączyć z backendem. Sprawdź, czy FastAPI działa.");
    } finally {
        setBusy(false);
        messageInput.focus();
        if (imageUrl) {
            URL.revokeObjectURL(imageUrl);
        }
    }
});

autoResizeInput();
checkSession();

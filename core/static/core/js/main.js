window.consumeChatbotStream = async function (response, onToken) {
    if (!response.ok) {
        let message = 'The assistant is temporarily unavailable. Please try again.';
        try {
            const data = await response.json();
            if (data.reply) message = data.reply;
        } catch (error) {
            // Keep a generic message when the server did not return JSON.
        }
        throw new Error(message);
    }

    const contentType = response.headers.get('Content-Type') || '';
    if (!contentType.includes('text/event-stream')) {
        try {
            const data = await response.json();
            if (typeof data.reply !== 'string') throw new Error();
            onToken(data.reply);
            return data;
        } catch (error) {
            throw new Error('The assistant returned an unreadable response. Please try again.');
        }
    }
    if (!response.body) throw new Error('This browser cannot display streamed replies. Please try again.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let completion = null;

    function handleEvent(frame) {
        const data = frame
            .split(/\r?\n/)
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).replace(/^ /, ''))
            .join('\n');
        if (!data || data === '[DONE]') return;

        let event;
        try {
            event = JSON.parse(data);
        } catch (error) {
            throw new Error('The assistant returned an unreadable response. Please try again.');
        }
        if (event.type === 'token' && typeof event.text === 'string') onToken(event.text);
        if (event.type === 'error') throw new Error(event.message || 'The assistant is temporarily unavailable. Please try again.');
        if (event.type === 'done') completion = event;
    }

    try {
        while (!completion) {
            const {value, done} = await reader.read();
            buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
            const frames = buffer.split(/\r?\n\r?\n/);
            buffer = frames.pop();
            frames.forEach(handleEvent);
            if (done) {
                if (buffer.trim()) handleEvent(buffer);
                break;
            }
        }
    } catch (error) {
        await reader.cancel();
        throw error;
    }
    if (!completion) throw new Error('The assistant response ended unexpectedly. Please try again.');
    return completion;
};

document.addEventListener('DOMContentLoaded', function () {
    const chatbotButton = document.getElementById('chatbot-fab');
    const panel = document.getElementById('chatbot-panel');
    const closeButton = document.getElementById('chatbot-close');
    const chatForm = document.getElementById('floating-chat-form');
    const chatInput = document.getElementById('floating-chat-input');
    const messages = document.getElementById('chatbot-messages');
    const status = document.getElementById('floating-chat-status');

    if (!chatbotButton || !panel || !chatForm || !chatInput || !messages || !status) return;

    const chatbotUrl = chatbotButton.dataset.chatbotUrl;
    const csrfToken = chatForm.querySelector('[name=csrfmiddlewaretoken]').value;
    let historyLoaded = false;

    function renderAssistantContent(element, content) {
        element.textContent = '';
        const urlPattern = /https:\/\/www\.google\.com\/maps\/search\/\?api=1&query=[^\s]+/g;
        let lastIndex = 0;
        for (const match of content.matchAll(urlPattern)) {
            const url = match[0].replace(/[.,)]+$/, '');
            element.append(document.createTextNode(content.slice(lastIndex, match.index)));
            const link = document.createElement('a');
            link.href = url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = 'Open in Google Maps';
            element.appendChild(link);
            lastIndex = match.index + url.length;
        }
        element.append(document.createTextNode(content.slice(lastIndex)));
    }

    function appendMessage(sender, content, places = [], showGoogleAttribution = false, databaseRestaurants = []) {
        const message = document.createElement('div');
        message.className = `chatbot-message ${sender === 'user' ? 'chatbot-message-user' : 'chatbot-message-bot'}`;
        const label = document.createElement('strong');
        label.textContent = sender === 'user' ? 'You' : 'Assistant';
        const text = document.createElement('p');
        if (sender === 'user') text.textContent = content;
        else renderAssistantContent(text, content);
        message.append(label, text);
        if (sender !== 'user' && Array.isArray(places) && places.length) {
            const list = document.createElement('ul');
            list.className = 'chatbot-place-results';
            places.forEach((place) => {
                const item = document.createElement('li');
                const name = document.createElement('strong');
                name.textContent = place.name || 'Restaurant';
                item.appendChild(name);
                if (place.address) {
                    const address = document.createElement('p');
                    address.textContent = place.address;
                    item.appendChild(address);
                }
                if (place.google_rating !== null && place.google_rating !== undefined) {
                    const rating = document.createElement('p');
                    const count = place.google_review_count
                        ? ` (${place.google_review_count} ratings)`
                        : '';
                    rating.textContent = `Google rating: ${place.google_rating}${count}`;
                    item.appendChild(rating);
                }
                if (place.place_type) {
                    const type = document.createElement('p');
                    type.textContent = place.place_type;
                    item.appendChild(type);
                }
                try {
                    const mapsUrl = new URL(place.google_maps_url);
                    if (mapsUrl.protocol === 'https:' && ['maps.google.com', 'google.com', 'www.google.com'].includes(mapsUrl.hostname)) {
                        const link = document.createElement('a');
                        link.href = mapsUrl.href;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.textContent = 'View in Google Maps';
                        item.appendChild(link);
                    }
                } catch (error) {
                    // Omit an invalid provider URL; keep the live listing details visible.
                }
                list.appendChild(item);
            });
            message.appendChild(list);
        }
        if (sender !== 'user' && Array.isArray(databaseRestaurants) && databaseRestaurants.length) {
            const list = document.createElement('ul');
            list.className = 'chatbot-place-results';
            databaseRestaurants.forEach((restaurant) => {
                const item = document.createElement('li');
                const name = document.createElement('strong');
                name.textContent = restaurant.name || 'Restaurant';
                item.appendChild(name);
                if (restaurant.map_url) {
                    const link = document.createElement('a');
                    link.href = restaurant.map_url;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.textContent = 'Open in Google Maps';
                    item.appendChild(document.createTextNode(' '));
                    item.appendChild(link);
                }
                list.appendChild(item);
            });
            message.appendChild(list);
        }
        if (showGoogleAttribution) {
            const attribution = document.createElement('span');
            attribution.className = 'google-maps-attribution';
            attribution.setAttribute('translate', 'no');
            attribution.textContent = 'Google Maps';
            message.appendChild(attribution);
        }
        messages.appendChild(message);
        messages.scrollTop = messages.scrollHeight;
        return text;
    }

    function setOpen(isOpen) {
        panel.hidden = !isOpen;
        chatbotButton.setAttribute('aria-expanded', String(isOpen));
        chatbotButton.setAttribute('aria-label', isOpen ? 'Close travel assistant' : 'Open travel assistant');
        chatbotButton.textContent = isOpen ? '×' : '💬';

        if (isOpen) {
            chatInput.focus();
            if (!historyLoaded) loadHistory();
        }
    }

    async function loadHistory() {
        historyLoaded = true;
        try {
            const response = await fetch(`${chatbotUrl}?floating=1`, {
                headers: {'Accept': 'application/json'},
                credentials: 'same-origin'
            });
            if (!response.ok) throw new Error('Could not load chat history.');
            const data = await response.json();
            messages.replaceChildren();
            if (!data.messages.length) {
                const empty = document.createElement('p');
                empty.className = 'chatbot-empty';
                empty.textContent = 'Ask about routes, destinations, restaurants, or local dishes.';
                messages.appendChild(empty);
            } else {
                data.messages.forEach((message) => appendMessage(message.sender, message.content));
            }
        } catch (error) {
            historyLoaded = false;
            status.textContent = error.message || 'Could not load chat history.';
        }
    }

    chatbotButton.addEventListener('click', function () {
        setOpen(panel.hidden);
    });

    closeButton?.addEventListener('click', function () {
        setOpen(false);
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !panel.hidden) {
            setOpen(false);
            chatbotButton.focus();
        }
    });

    chatForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        if (window.chatbotRequestInFlight) return;
        const prompt = chatInput.value.trim();
        if (!prompt) return;

        window.chatbotRequestInFlight = true;
        messages.querySelector('.chatbot-empty')?.remove();
        appendMessage('user', prompt);
        chatInput.value = '';
        const submitButton = chatForm.querySelector('button[type=submit]');
        submitButton.disabled = true;
        status.textContent = 'Assistant is thinking...';
        const assistantText = appendMessage('bot', '');

        try {
            const response = await fetch(chatbotUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'Accept': 'text/event-stream'
                },
                body: new URLSearchParams({prompt}),
                credentials: 'same-origin'
            });
            const completion = await window.consumeChatbotStream(response, (text) => {
                assistantText.textContent += text;
                messages.scrollTop = messages.scrollHeight;
            });
            renderAssistantContent(assistantText, assistantText.textContent);
            if ((Array.isArray(completion.google_places) && completion.google_places.length)
                || (Array.isArray(completion.database_restaurants) && completion.database_restaurants.length)) {
                assistantText.parentElement.remove();
                appendMessage(
                    'bot',
                    completion.reply || '',
                    completion.google_places,
                    completion.google_maps_attribution,
                    completion.database_restaurants,
                );
            }
            status.textContent = '';
        } catch (error) {
            const message = error.message || 'The assistant is unavailable. Please try again.';
            assistantText.textContent = assistantText.textContent
                ? `${assistantText.textContent}\n\n${message}`
                : message;
            status.textContent = '';
        } finally {
            window.chatbotRequestInFlight = false;
            submitButton.disabled = false;
            chatInput.focus();
            messages.scrollTop = messages.scrollHeight;
        }
    });
});

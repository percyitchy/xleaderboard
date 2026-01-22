export const getApiUrl = () => {
    // In production, we want to use relative paths so requests go to the same origin
    // (or whatever the server is serving).
    // In development, Vite proxy will handle it, or we can force a URL via env var.
    return import.meta.env.VITE_API_URL || '';
};

export const getWsUrl = () => {
    if (import.meta.env.VITE_WS_URL) {
        return import.meta.env.VITE_WS_URL;
    }

    // Construct WebSocket URL based on current window location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}/ws`;
};

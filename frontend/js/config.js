window.API_BASE_URL =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1"
    ? "http://localhost:5000"
    : "https://SEU-APP.onrender.com";

window.apiUrl = (path) =>
  `${window.API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;

"""Provider errors safe for GUI/logs: never include response bodies or request URLs."""
import httpx


class YouTubeAPIError(ValueError):
    def __init__(self, message, reauth=False):
        super().__init__(message)
        self.reauth = reauth


def require_success(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.is_success and isinstance(payload, dict):
        return payload
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    reason = error if isinstance(error, str) else next(
        (v.get("reason", "") for v in error.get("errors", []) if isinstance(v, dict)), "") if isinstance(error, dict) else ""
    messages = {
        "access_denied": "Google отклонил доступ. Проверьте тестовых пользователей OAuth-проекта и выбранный аккаунт.",
        "invalid_grant": "Доступ Google истёк или отозван. Подключите YouTube повторно.",
        "invalid_client": "Google не принял настройки OAuth-приложения. Проверьте тип клиента и его настройки.",
        "quotaExceeded": "Квота YouTube API исчерпана. Повторите позже; не отправляйте ролик повторно вслепую.",
        "dailyLimitExceeded": "Дневная квота YouTube API исчерпана.",
        "uploadLimitExceeded": "YouTube ограничил количество загрузок для этого канала.",
        "youtubeSignupRequired": "Создайте YouTube-канал для выбранного Google-аккаунта.",
        "channelClosed": "YouTube-канал закрыт или недоступен.",
        "channelSuspended": "YouTube-канал приостановлен.",
        "insufficientPermissions": "Не хватает разрешений YouTube. Подключите аккаунт повторно с доступом к загрузке и чтению.",
    }
    message = messages.get(reason)
    if message is None:
        message = ("Доступ YouTube истёк или отозван. Подключите аккаунт повторно." if response.status_code == 401 else
                   "YouTube запретил операцию. Проверьте разрешения, доступность канала и включение YouTube Data API." if response.status_code == 403 else
                   "YouTube временно недоступен. Повторите проверку статуса позже." if response.status_code >= 500 else
                   f"YouTube не принял запрос (HTTP {response.status_code}). Проверьте настройки и данные ролика.")
    raise YouTubeAPIError(message, reason in {"invalid_grant", "invalid_client"} or response.status_code == 401) from None

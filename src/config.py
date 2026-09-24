from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Zebaro-Core-Bot"
    description: str = ""
    author: str = "Zebaro (zebaro.dev)"
    version: str = "0.10.1"

    debug: bool = False

    # Читается из стандартной переменной TZ: в Docker она же задаёт время в логах,
    # а здесь — часовой пояс cron-задач шедулера (иначе в контейнере это UTC).
    tz: str = "Europe/Berlin"

    services_state_file: str = "services.json"

    telegram_admin_id: int
    telegram_docker_access_ids: list[int] | str

    telegram_bot_token: str
    discord_bot_token: str
    personal_github_token: str

    personal_github_secret: str

    webhook_url: str

    job_stats_api_token: str = ""

    # Shared secret with zebaro.dev's contact form; empty = the endpoint refuses everything.
    site_contact_token: str = ""

    # wg-easy (the VPN server) API: host network, web UI bound to the Docker bridge.
    wg_easy_url: str = "http://host.docker.internal:51821"
    wg_easy_username: str = "zebaro"
    wg_easy_password: str = ""
    # 7zSD.sfx and the WireGuard MSIs the Windows installer is built from (baked into the image).
    vpn_installer_dir: str = "/opt/vpn-installer"

    mongo_uri: str = "mongodb://localhost:27017/zebaro_core"

    playwright_ws_endpoint: str = "ws://localhost:9222"

    mongodb_container_name: str = "zebaro-core-db"
    playwright_container_name: str = "zebaro-core-playwright"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("telegram_docker_access_ids", mode="before")
    def split_admin_ids(cls, v):  # noqa
        if isinstance(v, str):
            return [int(i) for i in v.split(",") if i]
        return v

    @model_validator(mode="after")
    def check_all_not_none(cls, model):  # noqa
        values = model.model_dump()
        missing = [k for k, v in values.items() if v is None]
        if missing:
            raise ValueError(f"The following settings are not set: {', '.join(missing)}")
        return model


settings = Settings()  # type: ignore

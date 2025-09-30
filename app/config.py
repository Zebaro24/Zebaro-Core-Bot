from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Zebaro-Core-Bot"
    description: str = ""
    author: str = "Zebaro (zebaro.dev)"
    version: str = "0.1.0"

    debug: bool = False

    telegram_admin_id: int | None = None

    telegram_bot_token: str | None = None
    discord_bot_token: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

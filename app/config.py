from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Zebaro-Core-Bot"
    description: str = ""
    author: str = "Zebaro (zebaro.dev)"
    version: str = "0.1.0"

    debug: bool = False

    telegram_admin_id: int | None = None
    telegram_docker_access_ids: list[int] | None = None

    telegram_bot_token: str | None = None
    discord_bot_token: str | None = None
    personal_github_token: str | None = None

    personal_github_secret: str | None = None

    webhook_url: str | None = None

    mongo_uri: str = "mongodb://localhost:27017/zebaro_core"

    playwright_ws_endpoint: str = "ws://localhost:9222"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("telegram_docker_access_ids", mode="before")
    def split_admin_ids(cls, v): # noqa
        if isinstance(v, str):
            return [int(i) for i in v.split(",") if i]
        return v

    @model_validator(mode="after")
    def check_all_not_none(cls, model): # noqa
        values = model.model_dump()
        missing = [k for k, v in values.items() if v is None]
        if missing:
            raise ValueError(f"The following settings are not set: {', '.join(missing)}")
        return model


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_telegram_id: int = 653179867
    admin_telegram_ids: str = '653179867,8435563121'

    @property
    def admin_ids(self) -> set[int]:
        ids = {self.admin_telegram_id}
        for value in self.admin_telegram_ids.split(','):
            value = value.strip()
            if value:
                ids.add(int(value))
        return ids

    payments_enabled: bool = False
    solana_rpc_url: str | None = None
    trumpty_token_mint: str | None = None
    payment_wallet_address: str | None = None
    x_api_client_id: str | None = None
    x_api_client_secret: str | None = None
    x_api_redirect_uri: str | None = None
    x_api_token_encryption_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

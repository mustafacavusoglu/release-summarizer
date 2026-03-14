from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    model: str = "gpt-5-mini"  # .env'de MODEL=... şeklinde override edilebilir
    github_token: str = ""
    max_concurrent_ai: int = 4   # Paralel OpenAI çağrısı limiti — RPM/TPM rate limit koruması
    source_timeout: int = 90     # Tek kaynak için toplam timeout (fetch + summarize)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./shop.db"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60
    payment_api_url: str = "https://payments.example.com"


settings = Settings()

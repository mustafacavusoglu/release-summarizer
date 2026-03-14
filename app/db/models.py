import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Any

from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON

from app.core.database import Base


# --- Enums ---

class SourceType(str, Enum):
    github = "github"
    url = "url"


# --- SQLAlchemy ORM Models ---

class Source(Base):
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    source_type = Column(String, nullable=False)  # SourceType değerlerinden biri
    config = Column(JSON, nullable=False)          # GithubConfig veya UrlConfig'e karşılık gelir
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Release(Base):
    __tablename__ = "releases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(String, nullable=False)
    source_name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    title = Column(String)
    body = Column(Text)
    summary = Column(Text)
    url = Column(String)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    release_ids = Column(JSON)


# --- Kaynak Konfigürasyon Şemaları ---

class GithubConfig(BaseModel):
    """GitHub Releases API için gerekli konfigürasyon."""
    repo: str = Field(..., description="org/repo formatında GitHub deposu", examples=["mlflow/mlflow"])


class UrlConfig(BaseModel):
    """RSS feed veya release sayfası için gerekli konfigürasyon."""
    url: str = Field(..., description="RSS feed veya release/changelog sayfası URL'si",
                     examples=["https://example.com/releases/rss.xml"])


# Discriminated union — source_type field'ı otomatik doğrulama için kullanılır
SourceConfig = Annotated[GithubConfig | UrlConfig, Field(union_mode="left_to_right")]


# --- Pydantic API Şemaları ---

class SourceCreate(BaseModel):
    name: str
    slug: str = Field(..., description="URL'de kullanılan benzersiz tanımlayıcı", examples=["mlflow"])
    source_type: SourceType = SourceType.github
    config: SourceConfig
    enabled: bool = True

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "LangChain",
                    "slug": "langchain",
                    "source_type": "github",
                    "config": {"repo": "langchain-ai/langchain"},
                },
                {
                    "name": "Red Hat Blog",
                    "slug": "redhat-blog",
                    "source_type": "url",
                    "config": {"url": "https://www.redhat.com/en/rss/blog/channel/red-hat-ai"},
                },
            ]
        }
    }


class SourceRead(BaseModel):
    id: str
    name: str
    slug: str
    source_type: SourceType
    config: dict[str, Any]
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ReleaseRead(BaseModel):
    id: str
    source_id: str
    source_name: str
    version: str
    title: Optional[str]
    summary: Optional[str]
    url: Optional[str]
    published_at: Optional[datetime]
    fetched_at: datetime

    model_config = {"from_attributes": True}


class ReportRead(BaseModel):
    id: str
    content: str
    created_at: datetime
    release_ids: list[str]

    model_config = {"from_attributes": True}

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from config import Settings


class Base(DeclarativeBase):
    pass


class TargetUser(Base):
    __tablename__ = "target_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    handle: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    did: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    follower_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_keyword: Mapped[str] = mapped_column(String(255), default="")
    followed_at_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="discovered", index=True)


def create_database(settings: Settings) -> tuple[Any, sessionmaker[Session]]:
    if settings.database_url.startswith("sqlite"):
        Path("data").mkdir(exist_ok=True)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def target_exists(session: Session, did: str, handle: str) -> bool:
    return session.scalar(select(TargetUser.id).where((TargetUser.did == did) | (TargetUser.handle == handle))) is not None


def save_discovered_user(
    session: Session,
    *,
    handle: str,
    did: str,
    follower_count: int,
    matched_keyword: str,
) -> TargetUser:
    user = session.scalar(select(TargetUser).where(TargetUser.did == did))
    if user is None:
        user = TargetUser(
            handle=handle,
            did=did,
            follower_count=follower_count,
            matched_keyword=matched_keyword,
            status="discovered",
        )
        session.add(user)
    else:
        user.follower_count = follower_count
        user.matched_keyword = matched_keyword
    session.commit()
    return user


def mark_followed(session: Session, did: str) -> None:
    user = session.scalar(select(TargetUser).where(TargetUser.did == did))
    if user:
        user.status = "followed"
        user.followed_at_timestamp = datetime.now(timezone.utc)
        session.commit()


def mark_failed(session: Session, did: str, reason: str = "failed") -> None:
    user = session.scalar(select(TargetUser).where(TargetUser.did == did))
    if user:
        user.status = reason[:32]
        session.commit()


def list_targets(session: Session, limit: int = 500) -> list[TargetUser]:
    return list(session.scalars(select(TargetUser).order_by(TargetUser.id.desc()).limit(limit)))


def count_follows_today(session: Session) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(session.scalar(select(func.count(TargetUser.id)).where(TargetUser.followed_at_timestamp >= start)) or 0)

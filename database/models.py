from sqlalchemy import BigInteger, String, ForeignKey, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Yekaterinburg")
    tasks: Mapped[list["Task"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id'))
    cron_expression: Mapped[str] = mapped_column(String)
    message_text: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    content_type: Mapped[str] = mapped_column(String, default="text")
    file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # share_link_token больше не нужен тут, но пусть висит, не мешает
    share_link_token: Mapped[str | None] = mapped_column(String, nullable=True)
    
    user: Mapped["User"] = relationship(back_populates="tasks")

class SharedLink(Base):
    __tablename__ = 'shared_links'
    
    token: Mapped[str] = mapped_column(String, primary_key=True)
    cron_expression: Mapped[str] = mapped_column(String)
    message_text: Mapped[str | None] = mapped_column(String, nullable=True)
    content_type: Mapped[str] = mapped_column(String, default="text")
    file_id: Mapped[str | None] = mapped_column(String, nullable=True)
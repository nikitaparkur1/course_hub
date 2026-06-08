from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)  # Название урока
    course_name = Column(String, index=True, nullable=False)  # Название модуля/курса
    summary_content = Column(Text, nullable=True)  # Текст выжимки (result.md)
    raw_transcript = Column(Text, nullable=True)  # Сырой транскрипт (.txt)
    srt_content = Column(Text, nullable=True)  # Тайминги (.srt)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

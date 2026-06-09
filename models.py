from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True, unique=True, nullable=False)
    author = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lessons = relationship(
        "Lesson", back_populates="course", cascade="all, delete-orphan"
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    title = Column(String(255), index=True, nullable=False)
    order_number = Column(Integer, default=1)

    summary_content = Column(Text, nullable=True)  # Редактируемый текст MD
    summary_file_path = Column(String(500), nullable=True)  # Путь к файлу
    srt_file_path = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="lessons")

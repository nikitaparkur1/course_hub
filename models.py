from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import (
    LONGTEXT,  # Импортируем LONGTEXT для объемных текстов
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True, unique=True, nullable=False)
    author = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связь автоматически сортирует подразделы по их order_number
    subcategories = relationship(
        "Subcategory",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Subcategory.order_number",
    )


class Subcategory(Base):
    __tablename__ = "subcategories"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    name = Column(String(255), nullable=False)
    order_number = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="subcategories")

    # Связь автоматически сортирует уроки по их order_number
    lessons = relationship(
        "Lesson",
        back_populates="subcategory",
        cascade="all, delete-orphan",
        order_by="Lesson.order_number",
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"), nullable=False)
    title = Column(String(255), index=True, nullable=False)
    order_number = Column(Integer, default=1)

    # Заменяем Text на LONGTEXT для поддержки очень длинных конспектов и транскриптов
    summary_content = Column(LONGTEXT, nullable=True)

    summary_file_path = Column(String(500), nullable=True)
    srt_file_path = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subcategory = relationship("Subcategory", back_populates="lessons")

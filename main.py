import os
import uuid

import aiofiles
import markdown
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import Base, engine, get_db
from models import Course, Lesson

# Инициализация приложения
app = FastAPI(title="Course Hub UI/UX Edition")

# Создаем папку для загрузок, если ее нет
os.makedirs("uploads", exist_ok=True)

# Монтируем статику для отдачи сохраненных файлов по прямой ссылке
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Подключаем Jinja2 шаблоны
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    """Создаем таблицы в базе данных при запуске приложения."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_upload_file(
    upload_file: UploadFile, dest_dir: str = "uploads"
) -> str | None:
    """Вспомогательная функция для асинхронного сохранения файлов на диск."""
    if not upload_file or not upload_file.filename:
        return None

    unique_name = f"{uuid.uuid4().hex}_{upload_file.filename}"
    file_path = os.path.join(dest_dir, unique_name)

    async with aiofiles.open(file_path, "wb") as out_file:
        content = await upload_file.read()
        await out_file.write(content)
        await upload_file.seek(0)

    return file_path


@app.get("/", response_class=HTMLResponse)
async def index_page(
    request: Request, q: str = None, db: AsyncSession = Depends(get_db)
):
    """Главная страница: список модулей (курсов) с поиском по названию и автору."""
    query = select(Course)
    if q:
        # Ищем совпадения ИЛИ в названии курса, ИЛИ в имени автора (без учета регистра)
        query = query.filter(
            or_(Course.name.ilike(f"%{q}%"), Course.author.ilike(f"%{q}%"))
        )

    result = await db.execute(query.order_by(Course.created_at.desc()))
    courses = result.scalars().all()

    # Подсчет уроков для каждого курса
    courses_with_counts = []
    for c in courses:
        count_res = await db.execute(
            select(func.count()).select_from(Lesson).filter(Lesson.course_id == c.id)
        )
        lesson_count = count_res.scalar()
        courses_with_counts.append({"course": c, "lesson_count": lesson_count})

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"courses": courses_with_counts, "search_query": q},
    )


@app.get("/course/{course_id}", response_class=HTMLResponse)
async def course_page(
    course_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Страница отдельного модуля: список уроков внутри него."""
    result = await db.execute(select(Course).filter(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    res_lessons = await db.execute(
        select(Lesson)
        .filter(Lesson.course_id == course.id)
        .order_by(Lesson.order_number)
    )
    lessons = res_lessons.scalars().all()

    # ИСПОЛЬЗУЕМ ЯВНЫЕ КЛЮЧЕВЫЕ АРГУМЕНТЫ
    return templates.TemplateResponse(
        request=request,
        name="course.html",
        context={"course": course, "lessons": lessons},
    )


@app.get("/lesson/{lesson_id}", response_class=HTMLResponse)
async def lesson_page(
    lesson_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Страница чтения урока и просмотра материалов."""
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    course_res = await db.execute(select(Course).filter(Course.id == lesson.course_id))
    course = course_res.scalar_one()

    # Загружаем все уроки текущего модуля для навигации
    course_lessons_res = await db.execute(
        select(Lesson)
        .filter(Lesson.course_id == course.id)
        .order_by(Lesson.order_number)
    )
    course_lessons = course_lessons_res.scalars().all()

    # Поиск предыдущего и следующего урока
    prev_lesson = None
    next_lesson = None
    current_idx = 0
    for idx, cl in enumerate(course_lessons):
        if cl.id == lesson.id:
            current_idx = idx
            if idx > 0:
                prev_lesson = course_lessons[idx - 1]
            if idx < len(course_lessons) - 1:
                next_lesson = course_lessons[idx + 1]
            break

    # Строим список страниц для умной пагинации с троеточиями (...)
    total = len(course_lessons)
    pagination_items = []

    if total <= 7:
        # Если страниц мало, просто выводим их все по порядку
        for i, cl in enumerate(course_lessons):
            pagination_items.append(
                {
                    "type": "page",
                    "id": cl.id,
                    "number": cl.order_number or (i + 1),
                    "is_current": cl.id == lesson.id,
                }
            )
    else:
        # Всегда показываем первую страницу
        pagination_items.append(
            {
                "type": "page",
                "id": course_lessons[0].id,
                "number": course_lessons[0].order_number or 1,
                "is_current": course_lessons[0].id == lesson.id,
            }
        )

        # Левое троеточие
        start = max(1, current_idx - 1)
        if start > 1:
            pagination_items.append({"type": "ellipsis"})
        else:
            start = 1

        # Среднее "окно" из страниц вокруг текущей
        end = min(total - 1, current_idx + 2)
        for i in range(start, end):
            cl = course_lessons[i]
            pagination_items.append(
                {
                    "type": "page",
                    "id": cl.id,
                    "number": cl.order_number or (i + 1),
                    "is_current": cl.id == lesson.id,
                }
            )

        # Правое троеточие
        if end < total - 1:
            pagination_items.append({"type": "ellipsis"})

        # Всегда показываем последнюю страницу
        pagination_items.append(
            {
                "type": "page",
                "id": course_lessons[-1].id,
                "number": course_lessons[-1].order_number or total,
                "is_current": course_lessons[-1].id == lesson.id,
            }
        )

    # Преобразуем Markdown в HTML
    html_summary = markdown.markdown(
        lesson.summary_content or "", extensions=["fenced_code", "tables"]
    )

    return templates.TemplateResponse(
        request=request,
        name="lesson.html",
        context={
            "lesson": lesson,
            "course": course,
            "course_lessons": course_lessons,
            "html_summary": html_summary,
            "prev_lesson": prev_lesson,
            "next_lesson": next_lesson,
            "pagination_items": pagination_items,
        },
    )


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница формы добавления нового урока."""
    res = await db.execute(select(Course).order_by(Course.name))
    courses = res.scalars().all()

    # ИСПОЛЬЗУЕМ ЯВНЫЕ КЛЮЧЕВЫЕ АРГУМЕНТЫ
    return templates.TemplateResponse(
        request=request, name="upload.html", context={"courses": courses}
    )


@app.post("/upload")
async def handle_upload(
    course_name: str = Form(...),
    author: str = Form(""),
    title: str = Form(...),
    order_number: int = Form(1),
    summary_file: UploadFile = File(...),
    srt_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    """Обработчик сохранения нового урока и создания модуля, если его нет."""
    course_name = course_name.strip()

    course_res = await db.execute(select(Course).filter(Course.name == course_name))
    course = course_res.scalar_one_or_none()

    if not course:
        course = Course(name=course_name, author=author.strip())
        db.add(course)
        await db.flush()

    summary_path = await save_upload_file(summary_file)
    srt_path = (
        await save_upload_file(srt_file) if (srt_file and srt_file.filename) else None
    )

    summary_content = ""
    if summary_file and summary_file.filename:
        summary_content = (await summary_file.read()).decode("utf-8")

    new_lesson = Lesson(
        course_id=course.id,
        title=title,
        order_number=order_number,
        summary_content=summary_content,
        summary_file_path=summary_path,
        srt_file_path=srt_path,
    )
    db.add(new_lesson)
    await db.commit()

    return RedirectResponse(url=f"/course/{course.id}", status_code=303)


@app.get("/lesson/{lesson_id}/edit", response_class=HTMLResponse)
async def edit_page(
    lesson_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Страница редактирования существующего урока."""
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    # ИСПОЛЬЗУЕМ ЯВНЫЕ КЛЮЧЕВЫЕ АРГУМЕНТЫ
    return templates.TemplateResponse(
        request=request, name="edit.html", context={"lesson": lesson}
    )


@app.post("/lesson/{lesson_id}/edit")
async def handle_edit(
    lesson_id: int,
    title: str = Form(...),
    order_number: int = Form(...),
    summary_content: str = Form(...),
    summary_file: UploadFile = File(None),
    srt_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    """Обработчик обновления урока."""
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    lesson.title = title
    lesson.order_number = order_number
    lesson.summary_content = summary_content

    if summary_file and summary_file.filename:
        lesson.summary_file_path = await save_upload_file(summary_file)
        lesson.summary_content = (await summary_file.read()).decode("utf-8")

    if srt_file and srt_file.filename:
        lesson.srt_file_path = await save_upload_file(srt_file)

    await db.commit()
    return RedirectResponse(url=f"/lesson/{lesson.id}", status_code=303)


@app.post("/lesson/{lesson_id}/delete")
async def delete_lesson(lesson_id: int, db: AsyncSession = Depends(get_db)):
    """Удаление урока с проверкой на 'пустой модуль'."""
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    course_id = lesson.course_id
    await db.delete(lesson)
    await db.commit()

    count_res = await db.execute(
        select(func.count()).select_from(Lesson).filter(Lesson.course_id == course_id)
    )
    remaining_lessons = count_res.scalar()

    if remaining_lessons == 0:
        course_res = await db.execute(select(Course).filter(Course.id == course_id))
        course = course_res.scalar_one()
        await db.delete(course)
        await db.commit()
        return RedirectResponse(url="/", status_code=303)

    return RedirectResponse(url=f"/course/{course_id}", status_code=303)

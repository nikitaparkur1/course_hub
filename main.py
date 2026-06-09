import os
import uuid

import aiofiles
import markdown
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload  # Для асинхронной подгрузки связей

from database import Base, engine, get_db
from models import Course, Lesson, Subcategory

app = FastAPI(title="Course Hub UI/UX Edition")

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_upload_file(
    upload_file: UploadFile, dest_dir: str = "uploads"
) -> str | None:
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
    """Главная страница: список курсов."""
    query = select(Course)
    if q:
        from sqlalchemy import or_

        query = query.filter(
            or_(Course.name.ilike(f"%{q}%"), Course.author.ilike(f"%{q}%"))
        )

    result = await db.execute(query.order_by(Course.created_at.desc()))
    courses = result.scalars().all()

    courses_with_counts = []
    for c in courses:
        # Считаем количество уроков через подкатегории
        count_res = await db.execute(
            select(func.count(Lesson.id))
            .select_from(Lesson)
            .join(Subcategory)
            .filter(Subcategory.course_id == c.id)
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
    """Страница курса: отображает подразделы (модули) и уроки внутри них."""
    result = await db.execute(select(Course).filter(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не найден")

    # Мы убрали .order_by() из selectinload. Сортировка уроков теперь происходит автоматически!
    res_subs = await db.execute(
        select(Subcategory)
        .filter(Subcategory.course_id == course.id)
        .options(selectinload(Subcategory.lessons))
        .order_by(Subcategory.order_number)
    )
    subcategories = res_subs.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="course.html",
        context={"course": course, "subcategories": subcategories},
    )


@app.get("/lesson/{lesson_id}", response_class=HTMLResponse)
async def lesson_page(
    lesson_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Страница чтения урока."""
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    sub_res = await db.execute(
        select(Subcategory).filter(Subcategory.id == lesson.subcategory_id)
    )
    current_subcategory = sub_res.scalar_one()

    course_res = await db.execute(
        select(Course).filter(Course.id == current_subcategory.course_id)
    )
    course = course_res.scalar_one()

    # Мы убрали .order_by() из selectinload. Сортировка уроков теперь происходит автоматически!
    course_structure_res = await db.execute(
        select(Subcategory)
        .filter(Subcategory.course_id == course.id)
        .options(selectinload(Subcategory.lessons))
        .order_by(Subcategory.order_number)
    )
    subcategories = course_structure_res.scalars().all()

    # Сплющиваем список уроков для постраничной навигации
    all_lessons = []
    for sub in subcategories:
        all_lessons.extend(sub.lessons)

    prev_lesson = None
    next_lesson = None
    current_idx = 0
    for idx, cl in enumerate(all_lessons):
        if cl.id == lesson.id:
            current_idx = idx
            if idx > 0:
                prev_lesson = all_lessons[idx - 1]
            if idx < len(all_lessons) - 1:
                next_lesson = all_lessons[idx + 1]
            break

    # Строим список страниц для умной пагинации
    total = len(all_lessons)
    pagination_items = []
    if total <= 7:
        for i, cl in enumerate(all_lessons):
            pagination_items.append(
                {
                    "type": "page",
                    "id": cl.id,
                    "number": cl.order_number or (i + 1),
                    "is_current": cl.id == lesson.id,
                }
            )
    else:
        pagination_items.append(
            {
                "type": "page",
                "id": all_lessons[0].id,
                "number": all_lessons[0].order_number or 1,
                "is_current": all_lessons[0].id == lesson.id,
            }
        )
        start = max(1, current_idx - 1)
        if start > 1:
            pagination_items.append({"type": "ellipsis"})
        else:
            start = 1
        end = min(total - 1, current_idx + 2)
        for i in range(start, end):
            cl = all_lessons[i]
            pagination_items.append(
                {
                    "type": "page",
                    "id": cl.id,
                    "number": cl.order_number or (i + 1),
                    "is_current": cl.id == lesson.id,
                }
            )
        if end < total - 1:
            pagination_items.append({"type": "ellipsis"})
        pagination_items.append(
            {
                "type": "page",
                "id": all_lessons[-1].id,
                "number": all_lessons[-1].order_number or total,
                "is_current": all_lessons[-1].id == lesson.id,
            }
        )

    html_summary = markdown.markdown(
        lesson.summary_content or "", extensions=["fenced_code", "tables"]
    )

    return templates.TemplateResponse(
        request=request,
        name="lesson.html",
        context={
            "lesson": lesson,
            "course": course,
            "subcategories": subcategories,
            "html_summary": html_summary,
            "prev_lesson": prev_lesson,
            "next_lesson": next_lesson,
            "pagination_items": pagination_items,
        },
    )


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request, course_name: str = None, db: AsyncSession = Depends(get_db)
):
    """Страница формы добавления. Автоматически принимает параметр course_name из GET-запроса."""
    res = await db.execute(select(Course).order_by(Course.name))
    courses = res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"courses": courses, "prefilled_course": course_name},
    )


@app.post("/upload")
async def handle_upload(
    course_name: str = Form(...),
    subcategory_name: str = Form(...),  # Новое поле: Подраздел
    author: str = Form(""),
    title: str = Form(...),
    order_number: int = Form(1),
    summary_file: UploadFile = File(...),
    srt_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    course_name = course_name.strip()
    subcategory_name = subcategory_name.strip()

    # Ищем или создаем курс
    course_res = await db.execute(select(Course).filter(Course.name == course_name))
    course = course_res.scalar_one_or_none()
    if not course:
        course = Course(name=course_name, author=author.strip())
        db.add(course)
        await db.flush()

    # Ищем или создаем подраздел (модуль) внутри этого курса
    sub_res = await db.execute(
        select(Subcategory).filter(
            Subcategory.course_id == course.id, Subcategory.name == subcategory_name
        )
    )
    subcategory = sub_res.scalar_one_or_none()
    if not subcategory:
        subcategory = Subcategory(course_id=course.id, name=subcategory_name)
        db.add(subcategory)
        await db.flush()

    summary_path = await save_upload_file(summary_file)
    srt_path = (
        await save_upload_file(srt_file) if (srt_file and srt_file.filename) else None
    )

    summary_content = ""
    if summary_file and summary_file.filename:
        summary_content = (await summary_file.read()).decode("utf-8")

    new_lesson = Lesson(
        subcategory_id=subcategory.id,
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
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

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
    """Каскадное удаление: если подраздел пустеет — удаляем его. Если курс пустеет — удаляем курс."""
    result = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    subcategory_id = lesson.subcategory_id
    await db.delete(lesson)
    await db.commit()

    # 1. Проверяем уроки в подкатегории
    count_res = await db.execute(
        select(func.count())
        .select_from(Lesson)
        .filter(Lesson.subcategory_id == subcategory_id)
    )
    if count_res.scalar() == 0:
        sub_res = await db.execute(
            select(Subcategory).filter(Subcategory.id == subcategory_id)
        )
        subcategory = sub_res.scalar_one()
        course_id = subcategory.course_id

        # Удаляем подкатегорию
        await db.delete(subcategory)
        await db.commit()

        # 2. Проверяем подкатегории в курсе
        count_subs = await db.execute(
            select(func.count())
            .select_from(Subcategory)
            .filter(Subcategory.course_id == course_id)
        )
        if count_subs.scalar() == 0:
            course_res = await db.execute(select(Course).filter(Course.id == course_id))
            course = course_res.scalar_one()

            # Удаляем пустой курс
            await db.delete(course)
            await db.commit()
            return RedirectResponse(url="/", status_code=303)

        return RedirectResponse(url=f"/course/{course_id}", status_code=303)

    # Если уроки еще есть
    sub_res = await db.execute(
        select(Subcategory).filter(Subcategory.id == subcategory_id)
    )
    return RedirectResponse(
        url=f"/course/{sub_res.scalar_one().course_id}", status_code=303
    )

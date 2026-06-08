import markdown
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
from database import engine, get_db

# Создаем таблицы в БД при запуске
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Course Hub")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request, db: Session = Depends(get_db)):
    lessons = (
        db.query(models.Lesson)
        .order_by(models.Lesson.course_name, models.Lesson.title)
        .all()
    )

    grouped_lessons = {}
    for lesson in lessons:
        grouped_lessons.setdefault(lesson.course_name, []).append(lesson)

    return templates.TemplateResponse(
        request=request, name="index.html", context={"grouped_lessons": grouped_lessons}
    )


@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse(request=request, name="upload.html", context={})


# Обработчик загрузки
@app.post("/upload")
async def handle_upload(
    course_name: str = Form(...),
    title: str = Form(...),
    summary_file: UploadFile = File(...),
    srt_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    # Читаем содержимое загруженного MD файла
    summary_content = (await summary_file.read()).decode("utf-8")

    # Читаем SRT (тайминги), если файл был прикреплен
    srt_content = None
    if srt_file and srt_file.filename:
        srt_content = (await srt_file.read()).decode("utf-8")

    # Создаем запись в БД
    new_lesson = models.Lesson(
        course_name=course_name,
        title=title,
        summary_content=summary_content,
        srt_content=srt_content,
    )
    db.add(new_lesson)
    db.commit()

    return RedirectResponse(url="/", status_code=303)


@app.get("/lesson/{lesson_id}", response_class=HTMLResponse)
async def read_lesson(lesson_id: int, request: Request, db: Session = Depends(get_db)):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    # Конвертируем Markdown-выжимку в HTML
    html_summary = ""
    if lesson.summary_content:
        html_summary = markdown.markdown(
            lesson.summary_content, extensions=["fenced_code", "tables"]
        )

    return templates.TemplateResponse(
        request=request,
        name="lesson.html",
        context={"lesson": lesson, "html_summary": html_summary},
    )


# Удаление урока
@app.post("/lesson/{lesson_id}/delete")
async def delete_lesson(lesson_id: int, db: Session = Depends(get_db)):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    db.delete(lesson)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

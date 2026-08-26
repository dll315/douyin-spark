import asyncio
import os
import random
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import store
from .douyin_bot import bot
from .scheduler import apply_schedule, scheduler

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_FILE = os.path.join(BASE_DIR, "app", "static", "index.html")

job_running = False


async def execute_round(trigger):
    global job_running
    if job_running:
        store.add_log("warn", "已有任务在执行，忽略重复触发")
        return
    job_running = True
    try:
        data = store.load()
        contacts = [c for c in data["contacts"] if c.get("enabled", True)]
        if not contacts:
            store.add_log("warn", "没有启用的联系人，本轮跳过")
            return
        if not await bot.check_login():
            store.add_log("error", "抖音未登录或已掉线，请在页面上重新扫码登录")
            return
        label = "手动" if trigger == "manual" else "定时"
        store.add_log("info", f"开始执行续火花任务（{label}触发，共 {len(contacts)} 人）")
        jitter = int(data["settings"].get("jitter_minutes", 0))
        if jitter > 0:
            delay = random.uniform(0, jitter * 60)
            store.add_log("info", f"随机延迟 {int(delay // 60)} 分 {int(delay % 60)} 秒后开始")
            await asyncio.sleep(delay)
        results = await bot.run_all(contacts)
        data = store.load()
        by_id = {c["id"]: c for c in data["contacts"]}
        success = 0
        for r in results:
            contact = by_id.get(r["id"])
            if contact is not None:
                contact["last"] = {
                    "time": store.now_str(),
                    "ok": r["ok"],
                    "detail": r["detail"],
                }
            store.add_log(
                "info" if r["ok"] else "error",
                f"[{r['name']}]{'发送成功' if r['ok'] else '发送失败'}：{r['detail']}",
            )
            success += 1 if r["ok"] else 0
        store.save(data)
        store.add_log("info", f"本轮结束：成功 {success}/{len(results)}")
    except Exception as exc:
        store.add_log("error", f"任务异常：{exc}")
    finally:
        job_running = False


async def scheduled_job():
    await execute_round("cron")


@asynccontextmanager
async def lifespan(_app):
    apply_schedule(scheduled_job)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    await bot.shutdown()


app = FastAPI(title="Douyin Spark Keeper", lifespan=lifespan)


class ContactIn(BaseModel):
    name: str
    enabled: bool = True
    messages: List[str] = Field(default_factory=list)


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    messages: Optional[List[str]] = None


class SettingsIn(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    jitter_minutes: int = Field(default=0, ge=0, le=180)
    headless: bool = True
    default_messages: List[str] = Field(default_factory=list)


@app.get("/")
async def index():
    return FileResponse(INDEX_FILE)


@app.get("/api/overview")
async def overview():
    data = store.load()
    job = scheduler.get_job("spark")
    next_run = None
    if job is not None and job.next_run_time is not None:
        next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "logged_in": await bot.check_login(),
        "login_phase": bot.login_phase,
        "qr_image": bot.qr_image_b64,
        "running": job_running,
        "next_run": next_run,
        "settings": data["settings"],
        "contacts": data["contacts"],
        "logs": data["logs"][:60],
    }


@app.post("/api/login/start")
async def login_start():
    if await bot.check_login():
        return {"phase": "already_logged_in"}
    await bot.start_login()
    return {"phase": bot.login_phase}


@app.post("/api/login/reset")
async def login_reset():
    bot.reset_login_state()
    return {"phase": bot.login_phase}


@app.post("/api/logout")
async def logout():
    await bot.logout()
    return {"ok": True}


@app.put("/api/settings")
async def update_settings(payload: SettingsIn):
    data = store.load()
    data["settings"] = payload.model_dump()
    store.save(data)
    apply_schedule(scheduled_job)
    return data["settings"]


def _clean_messages(messages):
    return [m.strip() for m in (messages or []) if m and m.strip()]


@app.post("/api/contacts")
async def add_contact(payload: ContactIn):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="昵称不能为空")
    data = store.load()
    if any(c["name"] == name for c in data["contacts"]):
        raise HTTPException(status_code=400, detail="该联系人已存在")
    contact = {
        "id": store.new_id(),
        "name": name,
        "enabled": payload.enabled,
        "messages": _clean_messages(payload.messages),
        "last": None,
    }
    data["contacts"].append(contact)
    store.save(data)
    return contact


@app.put("/api/contacts/{contact_id}")
async def update_contact(contact_id: str, payload: ContactUpdate):
    data = store.load()
    for contact in data["contacts"]:
        if contact["id"] == contact_id:
            if payload.name is not None:
                new_name = payload.name.strip()
                if not new_name:
                    raise HTTPException(status_code=400, detail="昵称不能为空")
                if any(c["name"] == new_name and c["id"] != contact_id for c in data["contacts"]):
                    raise HTTPException(status_code=400, detail="该联系人已存在")
                contact["name"] = new_name
            if payload.enabled is not None:
                contact["enabled"] = payload.enabled
            if payload.messages is not None:
                contact["messages"] = _clean_messages(payload.messages)
            store.save(data)
            return contact
    raise HTTPException(status_code=404, detail="联系人不存在")


@app.delete("/api/contacts/{contact_id}")
async def delete_contact(contact_id: str):
    data = store.load()
    before = len(data["contacts"])
    data["contacts"] = [c for c in data["contacts"] if c["id"] != contact_id]
    if len(data["contacts"]) == before:
        raise HTTPException(status_code=404, detail="联系人不存在")
    store.save(data)
    return {"ok": True}


@app.post("/api/run")
async def run_now(background_tasks: BackgroundTasks):
    global job_running
    if job_running:
        raise HTTPException(status_code=409, detail="任务正在执行中，请稍候")
    background_tasks.add_task(execute_round, "manual")
    return {"started": True}

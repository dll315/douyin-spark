from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import store

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


def apply_schedule(job_func):
    settings = store.load()["settings"]
    try:
        scheduler.remove_job("spark")
    except Exception:
        pass
    scheduler.add_job(
        job_func,
        "cron",
        id="spark",
        hour=settings["hour"],
        minute=settings["minute"],
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

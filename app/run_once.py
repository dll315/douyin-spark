import asyncio

from . import store
from .douyin_bot import bot


async def main():
    data = store.load()
    data["settings"]["headless"] = True
    store.save(data)
    contacts = [c for c in data["contacts"] if c.get("enabled", True)]
    if not contacts:
        print("没有启用的联系人，跳过")
        return
    if not await bot.check_login():
        print("未登录或凭证已过期：请在本地网页重新扫码，然后更新 DOUYIN_STATE Secret")
        raise SystemExit(2)
    results = await bot.run_all(contacts)
    failed = 0
    for r in results:
        mark = "成功" if r["ok"] else "失败"
        print(f"[{r['name']}]{mark}：{r['detail']}")
        failed += 0 if r["ok"] else 1
    await bot.shutdown()
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

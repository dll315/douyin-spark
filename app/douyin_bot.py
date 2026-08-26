import base64
import datetime
import os
import random
import asyncio

from playwright.async_api import Error as PWError
from playwright.async_api import async_playwright

from . import store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
STATE_FILE = os.path.join(DATA_DIR, "douyin_state.json")

HOME_URL = "https://www.douyin.com/"
MESSAGE_URL = "https://www.douyin.com/message/"

SESSION_COOKIE_NAMES = {"sessionid", "sessionid_ss"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

QR_SELECTORS = [
    'img[class*="qrcode"]',
    'canvas[class*="qrcode"]',
    'div[class*="qrcode"] img',
    'div[id*="qrcode"] img',
]
LOGIN_TRIGGER_SELECTORS = [
    '[data-e2e="login-icon"]',
    'button:has-text("登录")',
]
CONVERSATION_SELECTORS = [
    '[data-e2e="chat-item"]',
    '[data-e2e="conversation-item"]',
    '[class*="conversationItem"]',
    '[class*="conv-item"]',
    '#sideBarChatList li',
]
CHAT_INPUT_SELECTORS = [
    '[data-e2e="chat-input"]',
    'div[contenteditable="true"]',
    'textarea[placeholder]',
]


def _now_tag():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class DouyinBot:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._run_lock = asyncio.Lock()
        self.login_phase = "idle"
        self.qr_image_b64 = ""
        self._poll_task = None

    async def check_login(self):
        if self._context is None:
            return False
        try:
            cookies = await self._context.cookies("https://www.douyin.com")
        except PWError:
            return False
        return any(c.get("name") in SESSION_COOKIE_NAMES for c in cookies)

    async def _ensure_context(self):
        if self._context is not None:
            return
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        self._pw = await async_playwright().start()
        headless = bool(store.load()["settings"].get("headless", True))
        self._browser = await self._pw.chromium.launch(headless=headless)
        kwargs = {
            "viewport": {"width": 1400, "height": 900},
            "user_agent": USER_AGENT,
            "locale": "zh-CN",
        }
        if os.path.exists(STATE_FILE):
            kwargs["storage_state"] = STATE_FILE
        self._context = await self._browser.new_context(**kwargs)
        self._page = await self._context.new_page()

    async def _close_session(self):
        for obj in (self._page, self._context, self._browser):
            if obj is None:
                continue
            try:
                await obj.close()
            except PWError:
                pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except PWError:
                pass
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def start_login(self):
        if self.login_phase == "waiting":
            return
        self.login_phase = "waiting"
        self.qr_image_b64 = ""
        try:
            await self._ensure_context()
            page = self._page
            await page.goto(HOME_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            png = await self._capture_qrcode(page)
            if png is None:
                for sel in LOGIN_TRIGGER_SELECTORS:
                    try:
                        await page.locator(sel).first.click(timeout=1500)
                        await page.wait_for_timeout(1500)
                    except PWError:
                        continue
                    png = await self._capture_qrcode(page)
                    if png is not None:
                        break
            if png is None:
                shot = await self._save_screenshot("no_qrcode")
                self.login_phase = "failed"
                store.add_log(
                    "error",
                    "未能捕获登录二维码，请重试，或关闭无头模式后人工排查"
                    + (f"（截图：{shot}）" if shot else ""),
                )
                return
            self.qr_image_b64 = base64.b64encode(png).decode("ascii")
            if self._poll_task is not None and not self._poll_task.done():
                self._poll_task.cancel()
            self._poll_task = asyncio.create_task(self._wait_scan())
        except Exception as exc:
            self.login_phase = "failed"
            store.add_log("error", f"启动登录失败：{exc}")

    async def _capture_qrcode(self, page):
        for sel in QR_SELECTORS:
            try:
                loc = page.locator(sel).first
                await loc.wait_for(state="visible", timeout=2000)
                png = await loc.screenshot()
                if len(png) > 1000:
                    return png
            except PWError:
                continue
        return None

    async def _wait_scan(self):
        for _ in range(90):
            await asyncio.sleep(3)
            if self.login_phase != "waiting":
                return
            if await self.check_login():
                try:
                    await self._context.storage_state(path=STATE_FILE)
                except PWError as exc:
                    self.login_phase = "failed"
                    store.add_log("error", f"保存登录态失败：{exc}")
                    return
                self.login_phase = "ok"
                self.qr_image_b64 = ""
                store.add_log("info", "抖音扫码登录成功，凭证已保存到本地")
                return
        self.login_phase = "failed"
        store.add_log("error", "扫码超时，请重新获取二维码")

    def reset_login_state(self):
        if self.login_phase == "waiting":
            self.login_phase = "idle"
            self.qr_image_b64 = ""

    async def logout(self):
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        await self._close_session()
        self.login_phase = "idle"
        self.qr_image_b64 = ""
        store.add_log("info", "已退出登录并清除本地凭证")

    async def _find_conversation(self, page, name):
        for sel in CONVERSATION_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
            except PWError:
                continue
            for i in range(count):
                item = loc.nth(i)
                try:
                    if not await item.is_visible():
                        continue
                    text = (await item.inner_text()).strip()
                except PWError:
                    continue
                if name in text:
                    return item
        return None

    async def _find_input(self, page):
        for sel in CHAT_INPUT_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
            except PWError:
                continue
            for i in range(count):
                box = loc.nth(i)
                try:
                    if await box.is_visible() and await box.is_editable():
                        return box
                except PWError:
                    continue
        raise RuntimeError("未找到聊天输入框，页面结构可能已更新")

    async def _save_screenshot(self, stage):
        if self._page is None:
            return ""
        try:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            path = os.path.join(SCREENSHOT_DIR, f"{_now_tag()}_{stage}.png")
            await self._page.screenshot(path=path)
            return path
        except PWError:
            return ""

    async def send_message(self, name, text):
        await self._ensure_context()
        page = self._page
        await page.goto(MESSAGE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        conv = await self._find_conversation(page, name)
        if conv is None:
            shot = await self._save_screenshot(f"conv_not_found_{name}")
            raise RuntimeError(
                f"会话列表中未找到「{name}」" + (f"（截图：{shot}）" if shot else "")
            )
        await conv.click()
        await page.wait_for_timeout(1200)
        box = await self._find_input(page)
        await box.click()
        await page.keyboard.type(text, delay=random.uniform(30, 70))
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(900)
        leftover = (await box.inner_text()).strip()
        if leftover:
            shot = await self._save_screenshot(f"send_unconfirmed_{name}")
            raise RuntimeError(
                f"输入框内容未清空，消息可能未发送" + (f"（截图：{shot}）" if shot else "")
            )
        return text

    async def run_all(self, contacts):
        if self._run_lock.locked():
            raise RuntimeError("已有发送任务正在进行")
        async with self._run_lock:
            settings = store.load()["settings"]
            results = []
            for contact in contacts:
                pool = (
                    contact.get("messages")
                    or settings.get("default_messages")
                    or ["续火花啦 🔥"]
                )
                text = random.choice(pool)
                ok, detail = True, ""
                try:
                    detail = await self.send_message(contact["name"], text)
                except Exception as exc:
                    ok = False
                    detail = str(exc)[:400]
                results.append(
                    {"id": contact["id"], "name": contact["name"], "ok": ok, "detail": detail}
                )
                await asyncio.sleep(random.uniform(4, 9))
            return results

    async def shutdown(self):
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
        await self._close_session()


bot = DouyinBot()

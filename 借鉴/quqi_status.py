from pathlib import Path
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from playwright.async_api import async_playwright
from core.myconfig import SAVE_PATH
import asyncio

URL = "https://status.w1ndys.top/status/easy-qfnu#/"
SCREENSHOT_PATH = SAVE_PATH / "quqi_status.png"

quqi_status = on_command("曲奇状态", priority=5, block=True)


async def take_screenshot(url: str, selector: str, save_path: Path) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        element = await page.wait_for_selector(selector, timeout=20000)
        await element.screenshot(path=str(save_path))
        final_url = page.url
        await browser.close()
        return final_url


@quqi_status.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    try:
        url = await take_screenshot(URL, ".main", SCREENSHOT_PATH)
        for _ in range(10):
            if SCREENSHOT_PATH.exists():
                break
            await asyncio.sleep(0.5)
        else:
            await bot.send_group_msg(group_id=event.group_id, message="⚠️ 截图文件未生成")
            return
        await bot.send_group_msg(group_id=event.group_id, message=Message(url))
        await bot.send_group_msg(
            group_id=event.group_id,
            message=Message(MessageSegment.image(SCREENSHOT_PATH.as_uri()))
        )
    except Exception as e:
        await quqi_status.finish(f"⚠️ 截图失败：{e}")


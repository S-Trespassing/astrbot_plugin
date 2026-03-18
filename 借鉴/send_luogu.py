import json
from pathlib import Path
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message,MessageSegment
from nonebot_plugin_apscheduler import scheduler
from playwright.async_api import async_playwright
from core.myconfig import SAVE_PATH,load_config,save_config
from nonebot.permission import SUPERUSER
import asyncio
import random
# 配置
URL = "https://www.luogu.com.cn/problem/random"
SCREENSHOT_PATH = SAVE_PATH / "screenshot.png"
GROUPS_FILE = load_config()
# -------------------- 指令部分 --------------------
screenshot_cmd = on_command("每日一题", priority=5, block=True)
add_cmd = on_command("添加每日一题", priority=5,permission=SUPERUSER, block=True)
remove_cmd = on_command("移除每日一题", priority=5,permission=SUPERUSER, block=True)


async def take_screenshot(url: str, save_path: Path):
    """用 Playwright 截取指定元素截图（高分辨率版）"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=4
        )
        await page.goto(url, timeout=60000)

        selector = "#app > div.main-container.lside-nav > main > div > div > div.side > div:nth-child(1)"
        # 等待元素出现
        element = await page.wait_for_selector(selector, timeout=5000)
        await element.screenshot(path=str(save_path))
        await browser.close()
        return page.url


@scheduler.scheduled_job("cron", hour="8,16,0", minute=0)  # 00:00, 09:00, 18:00, 22:00
async def daily_screenshot():
    bot = get_driver().bots.get(list(get_driver().bots.keys())[0])
    if not bot:
        return

    groups = load_config()['luogu_groups']
    joks=load_config()["acm_jokes"]
    jok_msg = random.choice(joks)+'\n'

    try:
        url=await take_screenshot(URL, SCREENSHOT_PATH)
        for gid in groups:
            for i in range(10):
                if SCREENSHOT_PATH.exists():
                    break
                await asyncio.sleep(0.5)
            else:
                await bot.send_group_msg(group_id=gid, message="⚠️ 截图文件未生成")
                return
            try:
                await bot.send_group_msg(group_id=gid, message=jok_msg+url)
                await bot.send_group_msg(
                    group_id=gid,
                    message=Message(MessageSegment.image(SCREENSHOT_PATH.as_uri()))
                )
            except Exception as e:
                await bot.send_group_msg(group_id=gid, message=f"⚠️ 截图发送失败：{e}")
    except Exception as e:
        for gid in groups:
            await bot.send_group_msg(group_id=gid, message=f"⚠️ 截图失败：{e}")

@screenshot_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    try:
        joks = load_config()["acm_jokes"]
        url=await take_screenshot(URL, SCREENSHOT_PATH)
        jok_msg = random.choice(joks) + '\n'
        for i in range(10):
            if SCREENSHOT_PATH.exists():
                break
            await asyncio.sleep(0.5)
        else:
            await bot.send_group_msg(group_id=event.group_id, message="⚠️ 截图文件未生成")
            return
        await bot.send_group_msg(
            group_id=event.group_id,
            message=Message(jok_msg+url)
        )
        await bot.send_group_msg(
            group_id=event.group_id,
            message=Message(MessageSegment.image(SCREENSHOT_PATH.as_uri()))
        )
    except Exception as e:
        await screenshot_cmd.finish(f"⚠️ 截图失败：{e}")

@add_cmd.handle()
async def _(event: GroupMessageEvent):
    args = event.get_plaintext().strip().split()
    if len(args) < 2:
        await add_cmd.finish("❌ 格式错误，用法：/添加每日一题 <群号>")
    try:
        gid = int(args[1])
        groups = load_config()
        if gid in groups['luogu_groups']:
            groups['luogu_groups'].append(gid)
            save_config(groups)
            await add_cmd.finish(f"✅ 已添加群 {gid} 到每日一题推送列表")
        else:
            await add_cmd.finish(f"⚠️ 群 {gid} 已经在列表中")
    except ValueError:
        await add_cmd.finish("❌ 群号必须是数字")

@remove_cmd.handle()
async def _(event: GroupMessageEvent):
    args = event.get_plaintext().strip().split()
    if len(args) < 2:
        await remove_cmd.finish("❌ 格式错误，用法：/移除每日一题 <群号>")
    try:
        gid = int(args[1])
        groups = load_config()
        # await remove_cmd.finish(str(groups))
        if gid in groups['luogu_groups']:
            groups['luogu_groups'].remove(gid)
            save_config(groups)
            await remove_cmd.finish(f"✅ 已移除群 {gid} 的每日一题推送")
        else:
            await remove_cmd.finish(f"⚠️ 群 {gid} 不在列表中")
    except ValueError:
        await remove_cmd.finish("❌ 群号必须是数字")

from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

import tempfile
import urllib.request
from pathlib import Path
import json
import re

try:
    from pypdf import PdfReader, PdfWriter
except Exception:
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except Exception:
        PdfReader = None
        PdfWriter = None


# ============ PDF 裁剪函数 ============
def crop_page_by_percent(page, percent: float):
    box = page.mediabox
    left = float(box.left)
    right = float(box.right)
    bottom = float(box.bottom)
    top = float(box.top)
    h = top - bottom
    cut = h * abs(percent) / 100.0

    if percent >= 0:
        new_bottom = bottom + cut
        new_bottom = min(new_bottom, (top + bottom) / 2)
        page.mediabox.lower_left = (left, new_bottom)
        page.mediabox.upper_right = (right, top)
    else:
        new_top = top - cut
        new_top = max(new_top, (top + bottom) / 2)
        page.mediabox.lower_left = (left, bottom)
        page.mediabox.upper_right = (right, new_top)

    return page


def process_pdf(input_path: Path, percent: float, output_path: Path):
    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(crop_page_by_percent(page, percent))
    with output_path.open("wb") as f:
        writer.write(f)


# ============ 提取 JSON 文件卡片 ============
def extract_file_info_from_json(seg: MessageSegment):
    """
    尝试从 CQ:json 的 meta.file 中提取 (file_id, busid, name)
    """
    raw = seg.data.get("data") or seg.data.get("json") or ""
    try:
        obj = json.loads(raw)
    except Exception:
        return None

    def dfs(o):
        if isinstance(o, dict):
            # 目标结构通常在 data.meta.file
            if "meta" in o and "file" in o["meta"]:
                f = o["meta"]["file"]
                fid = f.get("file_id")
                busid = f.get("busid", 102)
                name = f.get("name")
                if fid and name:
                    return fid, busid, name
            for v in o.values():
                r = dfs(v)
                if r:
                    return r
        elif isinstance(o, list):
            for it in o:
                r = dfs(it)
                if r:
                    return r
        return None

    return dfs(obj)


# ============ 插件本体 ============
matcher = on_command("去水印", block=True, priority=10)


@matcher.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    if PdfReader is None:
        await matcher.finish("⚠️ 请先安装 pypdf 或 PyPDF2")

    # 提取裁剪比例
    text = args.extract_plain_text().strip()
    percent = float(text) if text else 6.5
    if abs(percent) >= 99:
        await matcher.finish("⚠️ 裁剪比例需在 -99 到 99 之间")

    file_id = None
    busid = None
    filename = None
    file_url = None

    # ================= ① 当前消息是否带 file? ==================
    for seg in event.message:
        if seg.type == "file":
            file_id = seg.data.get("file_id") or seg.data.get("id")
            busid = seg.data.get("busid", 102)
            filename = seg.data.get("file") or seg.data.get("name")
            file_url_raw = seg.data.get("url")
            file_url = None
            if file_url_raw:
                m = re.search(r"https?://\S+", file_url_raw)
                file_url = m.group(0) if m else file_url_raw.strip()
            break

    # ========== ② 如无 file，则检查 reply 消息 ==========
    if not file_id:
        reply_id = None
        # 优先检查 event.reply (OneBot V11 标准字段)
        if getattr(event, "reply", None):
            reply_id = event.reply.message_id
        else:
            # 兼容性检查：遍历消息段寻找 reply
            for s in event.message:
                if s.type == "reply":
                    reply_id = s.data.get("id")
                    break

        if not reply_id:
            await matcher.finish("⚠️ 请直接发送 PDF，或引用一条包含 PDF 的消息")

        # 获取被引用的消息
        msg = await bot.get_msg(message_id=reply_id)
        raw_message = msg.get("message", "")
        
        # 兼容处理: 如果是 list[dict]，需转换为 MessageSegment
        if isinstance(raw_message, list):
            quoted = Message()
            for item in raw_message:
                if isinstance(item, dict):
                    quoted.append(MessageSegment(type=item.get("type"), data=item.get("data") or {}))
                else:
                    quoted.append(item)
        else:
            quoted = Message(raw_message)

        # 尝试从被引用的消息中提取 file_id
        for seg in quoted:
            # 情况 A: 直接是 file 消息段
            if seg.type == "file":
                file_id = seg.data.get("file_id") or seg.data.get("id")
                busid = seg.data.get("busid", 102)
                filename = seg.data.get("file") or seg.data.get("name")
                file_url_raw = seg.data.get("url")
                file_url = None
                if file_url_raw:
                    m = re.search(r"https?://\S+", file_url_raw)
                    file_url = m.group(0) if m else file_url_raw.strip()
                break
            # 情况 B: 是 JSON 卡片 (如转发的文件)
            elif seg.type == "json":
                r = extract_file_info_from_json(seg)
                if r:
                    file_id, busid, filename = r
                    break

    # ========== ③ 如果还没有 file_id，就无法处理 ==========
    if not file_id:
        await matcher.finish("❌️ 引用的消息中未找到可识别的 PDF 文件（无法获取 file_id）")

    if not filename or not str(filename).lower().endswith(".pdf"):
        base = str(filename) if filename else "file"
        if not base.lower().endswith(".pdf"):
            filename = base + ".pdf"

    # ========== ④ 获取文件下载链接 ==========
    if file_url:
        url = file_url
    else:
        url_info = await bot.call_api(
            "get_group_file_url",
            group_id=event.group_id,
            file_id=file_id,
            busid=busid,
        )
        url = url_info.get("url")
    if not url:
        await matcher.finish("❌️ 无法获取文件下载链接")

    # ========== ⑤ 开始下载 ==========
    tmpdir = Path(tempfile.mkdtemp(prefix="pdf_"))
    src = tmpdir / filename
    urllib.request.urlretrieve(url, str(src))

    # ========== ⑥ 处理 ==========
    out = tmpdir / (Path(filename).stem + "_去水印.pdf")
    try:
        process_pdf(src, percent, out)
    except Exception as e:
        await matcher.finish("❌️ PDF 处理失败：" + str(e))

    # ========== ⑦ 上传 ==========
    await bot.upload_group_file(
        group_id=event.group_id,
        file=str(out),
        name=out.name
    )

    await matcher.finish(f"✅️ 处理完成：{out.name}")

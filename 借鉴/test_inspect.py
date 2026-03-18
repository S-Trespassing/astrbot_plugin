from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

import json

matcher = on_command("测试", block=True, priority=5)


@matcher.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    info = []
    info.append(("✅ " if len(event.message) > 0 else "❌ ") + "current_message_segments:")
    info.append(json.dumps([{"type": seg.type, "data": seg.data} for seg in event.message], ensure_ascii=False, indent=2))

    reply_id = None
    if getattr(event, "reply", None):
        reply_id = event.reply.message_id
    else:
        for s in event.message:
            if s.type == "reply":
                reply_id = s.data.get("id")
                break

    info.append(("✅ " if reply_id else "❌ ") + f"reply_id: {reply_id}")

    if reply_id:
        try:
            msg = await bot.get_msg(message_id=reply_id)
            info.append("✅ quoted_msg:")
            info.append(json.dumps(msg, ensure_ascii=False, indent=2))

            raw = msg.get("message", "")
            if isinstance(raw, list):
                quoted = []
                for item in raw:
                    if isinstance(item, dict):
                        quoted.append({"type": item.get("type"), "data": item.get("data")})
                    else:
                        quoted.append(str(item))
                info.append("✅ quoted_message_segments:")
                info.append(json.dumps(quoted, ensure_ascii=False, indent=2))
            else:
                info.append("⚠️ quoted_message_raw:")
                info.append(str(raw))
        except Exception as e:
            info.append("❌ quoted_msg_fetch_failed:")
            info.append(str(e))

    try:
        evt = event.model_dump(mode="json")
    except Exception:
        try:
            evt = event.dict()
        except Exception:
            try:
                evt = json.loads(event.json())
            except Exception:
                evt = {"error": "event serialization failed"}

    def norm_msg(m):
        if isinstance(m, Message):
            return [{"type": s.type, "data": s.data} for s in m]
        if isinstance(m, list):
            return ([{"type": s.type, "data": s.data} if isinstance(s, MessageSegment) else s for s in m])
        return m

    if isinstance(evt, dict):
        if "message" in evt:
            evt["message"] = norm_msg(evt["message"])
        if "original_message" in evt:
            evt["original_message"] = norm_msg(evt["original_message"])
        if "reply" in evt and isinstance(evt["reply"], dict) and "message" in evt["reply"]:
            evt["reply"]["message"] = norm_msg(evt["reply"]["message"])

    info.append("✅ event_dump:")
    info.append(json.dumps(evt, ensure_ascii=False, indent=2))

    await matcher.finish("\n".join(info))

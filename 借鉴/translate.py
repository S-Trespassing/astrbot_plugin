import json
from base64 import b64decode
import traceback
import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.exception import FinishedException
from core.youdaoyun import get_key, get_tmstp, get_md5, HEADERS, COOKIES
from core.myconfig import ck_if_admin
from nonebot.adapters.onebot.v11 import MessageSegment

translate = on_command("翻译", aliases={"/翻译"}, priority=5)
translate_debug = on_command("翻译调试", priority=5)


def safe_get(obj, path):
    try:
        for p in path:
            if isinstance(obj, dict):
                obj = obj.get(p, None)
            elif isinstance(obj, list) and isinstance(p, int):
                obj = obj[p] if 0 <= p < len(obj) else None
            else:
                return None
            if obj is None:
                return None
        return obj
    except Exception:
        return None


async def youdao_request(text: str) -> str:
    """请求有道接口，返回原始解密数据"""
    try:
        tmstp = get_tmstp()
        salt, key, iv = get_key()
        md5 = get_md5(
            f"client=fanyideskweb&mysticTime={tmstp}&product=webfanyi&key={salt}"
        )

        data = {
            "i": text,
            "from": "auto",
            "to": "",
            "useTerm": "false",
            "dictResult": "true",
            "keyid": "webfanyi",
            "sign": md5,
            "client": "fanyideskweb",
            "product": "webfanyi",
            "appVersion": "1.0.0",
            "vendor": "web",
            "pointParam": "client,mysticTime,product",
            "mysticTime": tmstp,
            "keyfrom": "fanyi.web",
            "mid": "1",
            "screen": "1",
            "model": "1",
            "network": "wifi",
            "abtest": "0",
            "yduuid": "abcdefg",
        }

        res = httpx.post(
            "https://dict.youdao.com/webtranslate",
            headers=HEADERS,
            cookies=COOKIES,
            data=data,
            timeout=10,
        )
        res.raise_for_status()

        encrypted_data = b64decode(
            res.text.replace("-", "+").replace("_", "/").encode()
        )
        decipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted_data = unpad(decipher.decrypt(encrypted_data), AES.block_size)
        return decrypted_data.decode("utf-8", errors="replace")

    except Exception as e:
        # 记录详细错误（终端日志）
        traceback.print_exc()
        # 把简短错误信息返回上层
        raise RuntimeError(f"❌ 请求或解密失败:  {e}")


async def youdao_translate(text: str) -> str:
    try:
        decrypted_str = await youdao_request(text)
        obj = json.loads(decrypted_str)

        # 先尝试 dictResult（查词）
        dict_text = safe_get(obj, ["dictResult", "ce", "word", "trs", 0, "#text"])
        if dict_text:
            return dict_text

        # 再尝试 translateResult（翻句子）
        trs = safe_get(obj, ["translateResult"])
        if trs and isinstance(trs, list):
            results = []
            for group in trs:  # 每个 group 是一个 list
                for item in group:
                    tgt = item.get("tgt")
                    if tgt:
                        results.append(tgt)
            if results:
                return "".join(results)

        # 如果走到这里，说明没有任何结果
        raise ValueError("翻译结果为空")

    except Exception as e:
        return f"❌ 翻译失败:  {e}"


@translate.handle()
async def _( event: MessageEvent, args: Message = CommandArg()):
    text = args.extract_plain_text().strip()
    if not text and event.reply:
        text = event.reply.message.extract_plain_text().strip()
    if not text:
        await translate.finish("❌ 没有找到需要翻译的文本")

    result = await youdao_translate(text)
    await translate.finish(result)

@translate_debug.handle()
async def _(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    user_id = event.get_user_id()
    try:
        ck_if_admin(user_id)
    except Exception as e:
        await translate_debug.finish(str(e))

    # 获取文本
    text = args.extract_plain_text().strip()
    if not text and event.reply:
        text = event.reply.message.extract_plain_text().strip()
    if not text:
        await translate_debug.finish("❌ 没有找到需要翻译的文本")

    try:
        decrypted_str = await youdao_request(text)
        if len(decrypted_str) > 1500:
            decrypted_str = decrypted_str[:1500] + "...(已截断)"

        # 私聊给管理员
        await bot.send_private_msg(user_id=int(user_id), message=f"🛠 调试结果：{decrypted_str}")

        # 在群里 @ 管理员提示已私发
        if hasattr(event, "group_id") and event.group_id:
            await translate_debug.send(
                MessageSegment.at(user_id)+" ✅ 已发送"
            )

    except FinishedException:
        raise
    except Exception as e:
        await translate_debug.finish(f"❌ 调试失败:  {e}")

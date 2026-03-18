from core.tools import extract_uid
import json
import asyncio
from core.myconfig import load_config
from typing import Dict, List
from core.myconfig import BASE_DIR
from nonebot import on_command, on_notice
from nonebot.adapters.onebot.v11 import (
    Bot, GroupIncreaseNoticeEvent, GroupMessageEvent, Message
)
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from core.tools import  is_admin_or_owner
# === 配置 ===
DATA_PATH = BASE_DIR / "my_resources" / "inviting_tree.json"

# === 命令 ===
kick_tree = on_command("踢出邀请树", priority=5)
check_tree = on_command("查看邀请树", priority=5)
invite_record = on_notice(priority=5, block=False)


# === 数据持久化 ===
def load_data() -> Dict[str, Dict[str, str]]:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"加载邀请树失败: {e}")
            return {}
    else:
        DATA_PATH.write_text("{}", encoding="utf-8")
        return {}


invite_tree: Dict[str, Dict[str, str]] = load_data()


def save_data(data):
    try:
        DATA_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"保存邀请树失败: {e}")


# === 并查集核心 ===
def find_ancestor(x: str, data: Dict[str, str]) -> str:
    """路径压缩"""
    if x not in data:
        data[x] = x
    if data[x] != x:
        data[x] = find_ancestor(data[x], data)
    return data[x]


def union(x: str, y: str, data: Dict[str, str]):
    """合并集合：让 y 挂到 x 的祖先上"""
    fx, fy = find_ancestor(x, data), find_ancestor(y, data)
    if fx != fy:
        data[fy] = fx


# === 邀请逻辑 ===
async def start_record(bot: Bot, inviter: int, invitee: int, group_id: int):
    """记录邀请关系（跳过群主/管理员）"""
    try:
        info = await bot.get_group_member_info(group_id=group_id, user_id=inviter)
        role = info.get("role", "member")
        if role in ["owner", "admin"]:
            return  # 群主或管理员不记录
    except Exception:
        pass

    gid = str(group_id)
    inviter, invitee = str(inviter), str(invitee)
    data = invite_tree.setdefault(gid, {})

    if inviter not in data:
        data[inviter] = inviter
    if invitee not in data:
        data[invitee] = invitee

    union(inviter, invitee, data)
    invite_tree[gid] = data
    save_data(invite_tree)


# === 工具函数 ===
def get_subtree(group_id: int, root: int) -> List[str]:
    """获取某个 root 节点的所有子树成员"""
    data = invite_tree.get(str(group_id), {})
    root = find_ancestor(str(root), data)
    return [u for u in data.keys() if find_ancestor(u, data) == root]


def build_tree(group_id: int, root: int) -> List[str]:
    """返回子树成员（不包含 root 本身）"""
    users = get_subtree(group_id, root)
    return [u for u in users if u != str(root)]


def collect_tree_users(group_id: int, root: int) -> List[str]:
    """删除并返回 root 的整个邀请子树"""
    users = get_subtree(group_id, root)
    data = invite_tree.get(str(group_id), {})
    for u in users:
        if u in data:
            del data[u]
    invite_tree[str(group_id)] = data
    save_data(invite_tree)
    return users


async def get_name(bot: Bot, group_id: int, uid: str) -> str:
    """获取群昵称"""
    try:
        info = await bot.get_group_member_info(group_id=group_id, user_id=int(uid))
        nickname = info.get("card") or info.get("nickname") or uid
        return f"{nickname}({uid})"
    except Exception:
        return uid


# === 事件处理 ===
@check_tree.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    try:
        target = extract_uid(args)
    except Exception as e:
        await check_tree.finish(f"{e}")
        return

    group_id = event.group_id
    gid = str(group_id)
    if gid not in invite_tree or str(target) not in invite_tree[gid]:
        await check_tree.finish("⚠️ 该用户未与其他用户关联")
        return

    children = build_tree(group_id, target)
    if not children:
        await check_tree.finish(f"⚠️ [用户 {target}] 没有下级用户")
        return

    names = [await get_name(bot, group_id, uid) for uid in children]
    tree_str = "\n".join(names)
    root_name = await get_name(bot, group_id, str(target))
    await check_tree.finish(Message(f"✅ {root_name} 的邀请树:\n{tree_str}"))


@invite_record.handle()
async def _(bot: Bot, event: GroupIncreaseNoticeEvent):
    cfg = load_config()
    monitor_groups = cfg.get("monitor_groups", [])  # 如果需要通知，就在 config.json 里加 monitor_notify
    white_list = cfg.get("white_list", [])
    gid = str(event.group_id)
    # 只处理配置中的群
    if gid not in monitor_groups:
        return
    if event.user_id in white_list:
        return  # 白名单用户跳过
    group_id = event.group_id
    inviter = event.operator_id  # 邀请者
    invitee = event.user_id      # 新人
    await start_record(bot, inviter, invitee, group_id)


@kick_tree.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    try:
        is_admin_or_owner(event,bot)
    except Exception as e:
        await kick_tree.finish(f"{e}")
    try:
        target = extract_uid(args)
    except Exception as e:
        await kick_tree.finish(f"{e}")
        return

    group_id = event.group_id
    gid = str(group_id)
    if gid not in invite_tree or str(target) not in invite_tree[gid]:
        await kick_tree.finish("⚠️ 没有找到该用户的邀请记录。")
        return

    users_to_kick = collect_tree_users(group_id, target)

    kicked_names = []
    for uid in users_to_kick:
        try:
            user_str = await get_name(bot, group_id, uid)
            await bot.set_group_kick(group_id=group_id, user_id=int(uid), reject_add_request=False)
            kicked_names.append(user_str)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"[群 {group_id}] 踢出失败 {uid}: {e}")

    kicked_summary = "，".join(kicked_names)
    await kick_tree.finish(f"✅ [群 {group_id}] 已踢出 {len(users_to_kick)} 人：{kicked_summary}")

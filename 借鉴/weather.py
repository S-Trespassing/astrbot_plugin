from typing import Dict, Any
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import Message, Bot, MessageEvent
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from core.data_source import find_city_code, search_city_code, get_weather, get_all_districts
from core.myconfig import load_config, save_config


# ========== 指令部分 ==========
add_weather = on_command("添加每日天气", permission=SUPERUSER, priority=5)
remove_weather = on_command("移除每日天气", permission=SUPERUSER, priority=5)
weather = on_command("天气", aliases={"查天气"}, priority=5)
districts = on_command("支持区县", aliases={"查询区县", "可查区县"}, priority=5)


@weather.handle()
async def handle_weather(event: MessageEvent, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()
    logger.debug(f"收到天气查询请求: {arg_text}")

    if not arg_text:
        await weather.finish("请输入查询指令，例如：\n天气 北京\n天气 河北-大城")

    if "-" in arg_text:
        province, city = arg_text.split("-", 1)
        stationid = await find_city_code(province, city)
    else:
        stationid = await search_city_code(arg_text)

    if not stationid:
        await weather.finish(f"未找到城市 '{arg_text}'，请检查输入是否正确（格式：省份-城市）")

    weather_data = await get_weather(stationid)
    if not weather_data:
        await weather.finish("获取天气数据失败，请稍后再试")

    await send_weather_report(weather_data, matcher=weather)


async def send_weather_report(
    data: Dict[str, Any],
    matcher=None,
    bot: Bot = None,
    group_id: int = None,
):
    """格式化天气信息（支持命令调用和定时推送）"""

    real_data = data["data"]["real"]
    station = real_data["station"]
    weather_info = real_data["weather"]
    wind_info = real_data["wind"]

    msg = [
        f"【{station['province']}{station['city']}天气】",
        f"🕒 发布时间：{real_data['publish_time'] if str(real_data['publish_time']).strip() not in ['9999', '9999.0'] else '❓'}",
        "",
        f"🌤 当前天气：{weather_info['info'] if str(weather_info['info']).strip() not in ['9999', '9999.0'] else '❓'}",
        f"🌡 温度：{format_value(weather_info['temperature'], '{}℃')} (体感{format_value(weather_info['feelst'], '{}℃')})",
        f"📈 温差：{format_value(weather_info['temperatureDiff'], '{}℃')}",
        f"💧 湿度：{format_value(weather_info['humidity'], '{}%')}",
        f"🌬 风力：{wind_info['direct'] if str(wind_info['direct']).strip() not in ['9999', '9999.0'] else '❓'} "
        f"{wind_info['power'] if str(wind_info['power']).strip() not in ['9999', '9999.0'] else '❓'} "
        f"({format_value(wind_info['speed'], '{}m/s')})",
        f"☔ 降水量：{format_value(weather_info['rain'], '{}mm')}",
        f"📊 舒适度：{_get_comfort_desc(weather_info['icomfort']) if str(weather_info['icomfort']).strip() not in ['9999', '9999.0'] else '❓'}",
        f"🌅 日出：{real_data['sunriseSunset']['sunrise'] if str(real_data['sunriseSunset']['sunrise']).strip() not in ['9999', '9999.0'] else '❓'}",
        f"🌇 日落：{real_data['sunriseSunset']['sunset'] if str(real_data['sunriseSunset']['sunset']).strip() not in ['9999', '9999.0'] else '❓'}"
    ]

    text = "\n".join(msg)

    if matcher is not None:
        await matcher.finish(text)
    elif bot is not None and group_id is not None:
        await bot.send_group_msg(group_id=group_id, message=text)


def format_value(value, pattern):
    str_value = str(value).strip()
    if str_value in ["9999", "9999.0"]:
        return "❓"
    return pattern.format(value)


def _get_comfort_desc(level: int) -> str:
    comfort_map = {
        -4: "很冷，极不适应",
        -3: "冷，很不舒适",
        -2: "凉，不舒适",
        -1: "凉爽，较舒适",
        0: "舒适，最可接受",
        1: "温暖，较舒适",
        2: "暖，不舒适",
        3: "热，很不舒适",
        4: "很热，极不适应",
        9999: "❓"
    }
    return comfort_map.get(level, "未知")


@districts.handle()
async def handle_all_districts(event: MessageEvent, args: Message = CommandArg()):
    province = args.extract_plain_text().strip()
    if not province:
        await districts.finish("请输入省份名称，例如：支持区县 河北")

    result = await get_all_districts(province)
    if not result["districts"]:
        await districts.finish(f"未找到省份 '{province}' 或该省份下无可用区县数据")

    total = len(result["districts"])
    msg = [
        f"📌 {result['province']} 全部区县 ({total}个)：",
        "、".join(result["districts"])
    ]
    await districts.finish("\n".join(msg))


# ========== 定时任务部分 ==========
@scheduler.scheduled_job("cron", hour=7, minute=30)
async def scheduled_weather_push():
    config = load_config()
    push_config: Dict[str, list] = config.get("weather_push", {})

    if not push_config:
        logger.warning("定时任务未配置 weather_push")
        return

    bots = list(get_driver().bots.values())
    if not bots:
        logger.error("没有可用的 Bot 实例")
        return
    bot: Bot = bots[0]

    for group_id, cities in push_config.items():
        if not isinstance(cities, list):
            continue
        for city in cities:
            try:
                if "-" in city:
                    province, city_name = city.split("-", 1)
                    stationid = await find_city_code(province, city_name)
                else:
                    stationid = await search_city_code(city)

                if not stationid:
                    await bot.send_group_msg(
                        group_id=int(group_id),
                        message=f"❌ 未找到城市代码: {city}"
                    )
                    continue

                weather_data = await get_weather(stationid)
                if not weather_data:
                    await bot.send_group_msg(
                        group_id=int(group_id),
                        message=f"❌ 获取天气数据失败: {city}"
                    )
                    continue

                await send_weather_report(weather_data, bot=bot, group_id=int(group_id))
            except Exception as e:
                # 这里发送详细错误信息到群
                await bot.send_group_msg(
                    group_id=int(group_id),
                    message=f"⚠️ 推送 {city} 天气失败：{str(e)}"
                )
                logger.exception(f"推送 {group_id} - {city} 天气失败")



# ========== 订阅管理指令 ==========
@add_weather.handle()
async def handle_add_weather(event: MessageEvent, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()
    parts = arg_text.split()
    if len(parts) != 2:
        await add_weather.finish("用法：/添加每日天气 群号 城市")

    group_id, city = parts
    group_id = str(group_id)

    config = load_config()
    weather_push = config.setdefault("weather_push", {})

    city_list = weather_push.setdefault(group_id, [])
    if city in city_list:
        await add_weather.finish(f"群 {group_id} 已经订阅过 {city} 了")

    city_list.append(city)
    save_config(config)
    await add_weather.finish(f"✅ 已添加每日天气订阅：群 {group_id}   {city}")


@remove_weather.handle()
async def handle_remove_weather(event: MessageEvent, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()
    parts = arg_text.split()
    if len(parts) != 2:
        await remove_weather.finish("用法：/移除每日天气 群号 城市")

    group_id, city = parts
    group_id = str(group_id)

    config = load_config()
    weather_push = config.get("weather_push", {})

    if group_id not in weather_push or city not in weather_push[group_id]:
        await remove_weather.finish(f"群 {group_id} 未订阅 {city}")

    weather_push[group_id].remove(city)
    if not weather_push[group_id]:
        weather_push.pop(group_id)

    save_config(config)
    await remove_weather.finish(f"✅ 已移除每日天气订阅：群 {group_id}   {city}")

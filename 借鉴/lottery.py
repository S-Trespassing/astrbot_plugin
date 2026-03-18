from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, GroupMessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
import json
import random
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
import matplotlib
import io
import base64
import requests
from typing import Dict, List, Optional

# 设置matplotlib中文字体（跨平台：优先Linux常见中文字体，再回退）
matplotlib.rcParams['font.sans-serif'] = [
    'Noto Sans CJK SC', 'Noto Sans SC', 'WenQuanYi Zen Hei',
    'Source Han Sans SC', 'Microsoft YaHei', 'SimHei', 'DejaVu Sans'
]
matplotlib.rcParams['axes.unicode_minus'] = False

# 抽奖命令
lottery_cmd = on_command("抽奖", aliases={"抽个奖", "来抽奖", "抽奖啦"}, priority=5)
# 中奖榜单命令
winners_cmd = on_command("中奖名单", aliases={"榜单", "抽奖名单"}, priority=5)
# 抽奖统计命令（仅 SUPERUSER 可用）
stats_cmd = on_command("抽奖统计", aliases={"中奖统计"},priority=1, permission=SUPERUSER)
# 重置抽奖记录命令
reset_lottery_cmd = on_command("重置抽奖", priority=1)
# 新增打印获奖结果命令
print_all_winners_cmd = on_command("中奖证书示例", aliases={"中奖示例","抽奖示例"}, priority=1)

def load_lottery_config():
    """加载抽奖配置文件"""
    config_path = Path(__file__).parent.parent / "my_resources" / "lottery_prizes.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return get_default_config()

def load_lottery_data():
    """加载抽奖数据文件"""
    data_path = Path(__file__).parent.parent / "my_resources" / "lottery_data.json"
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return get_default_data()

def save_lottery_data(data):
    """保存抽奖数据文件"""
    data_path = Path(__file__).parent.parent / "my_resources" / "lottery_data.json"
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_default_config():
    """获取默认配置"""
    return {
        "prizes": [
            {"name": "一等奖", "description": "🎉 恭喜获得一等奖！", "probability": 0.01, "emoji": "🏆", "color": "#FFD700"},
            {"name": "参与奖", "description": "🎁 感谢参与！", "probability": 0.99, "emoji": "🎁", "color": "#FF69B4"}
        ],
        "lucky_strings": ["你的幸运字符串很有灵性！"],
        "suspense_messages": ["抽奖中..."],
        "easter_eggs": {"triggers": [], "messages": []}
    }

def get_default_data():
    """获取默认数据"""
    return {
        "lottery_history": [],
        "statistics": {"total_participants": 0, "total_draws": 0, "prize_distribution": {}},
        "user_stats": {}
    }

def select_prize(config):
    """根据概率选择奖品"""
    prizes = config["prizes"]
    total_prob = sum(prize["probability"] for prize in prizes)
    
    if abs(total_prob - 1.0) > 0.001:
        for prize in prizes:
            prize["probability"] = prize["probability"] / total_prob
    
    rand = random.random()
    cumulative_prob = 0
    
    for prize in prizes:
        cumulative_prob += prize["probability"]
        if rand <= cumulative_prob:
            return prize
    
    return prizes[-1]

def check_easter_egg(lucky_string: str, config: dict) -> Optional[str]:
    """检查是否触发彩蛋"""
    easter_eggs = config.get("easter_eggs", {})
    triggers = easter_eggs.get("triggers", [])
    messages = easter_eggs.get("messages", [])
    
    for trigger in triggers:
        if trigger in lucky_string:
            return random.choice(messages) if messages else None
    return None


async def get_user_avatar(bot: Bot, user_id: int) -> Optional[bytes]:
    """获取用户头像"""
    try:
        avatar_url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
        response = requests.get(avatar_url, timeout=10)
        if response.status_code == 200:
            return response.content
    except:
        pass
    return None

def create_share_card(user_name: str, prize: dict, lucky_string: str, avatar_data: Optional[bytes] = None) -> bytes:
    """生成横版分享卡片（头像、幸运字符、结果、感谢语；协会与时间作为背景水印）"""
    import io
    import os
    from datetime import datetime
    from PIL import Image, ImageDraw, ImageFont

    def safe_font(size: int) -> ImageFont.FreeTypeFont:
        """跨平台安全字体选择：优先本地资源，其次系统字体（Linux/Windows），最后默认字体"""
        try:
            base_dir = Path(__file__).parent.parent
            local_dir = base_dir / "my_resources" / "fonts"
            # 1) 项目内置字体优先
            if local_dir.exists():
                for p in list(local_dir.glob("*.ttf")) + list(local_dir.glob("*.otf")) + list(local_dir.glob("*.ttc")):
                    try:
                        return ImageFont.truetype(str(p), size)
                    except Exception:
                        pass
            # 2) 使用matplotlib的font_manager按字体族名查找（跨平台）
            try:
                import matplotlib.font_manager as fm
                families = [
                    'Noto Sans CJK SC', 'Noto Sans SC', 'Source Han Sans SC',
                    'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei',
                    'Microsoft YaHei', 'SimHei', 'DejaVu Sans', 'Liberation Sans'
                ]
                for fam in families:
                    try:
                        path = fm.findfont(fam, fallback_to_default=False)
                        if path and os.path.exists(path):
                            return ImageFont.truetype(path, size)
                    except Exception:
                        pass
            except Exception:
                pass
            # 3) 常见Linux字体文件路径
            linux_candidates = [
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf',
                '/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf',
                '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
                '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
            ]
            for path in linux_candidates:
                if os.path.exists(path):
                    try:
                        return ImageFont.truetype(path, size)
                    except Exception:
                        continue
            # 4) Windows候选（作为最后的回退）
            win_candidates = [
                r"C:\\Windows\\Fonts\\msyh.ttc",
                r"C:\\Windows\\Fonts\\msyh.ttf",
                r"C:\\Windows\\Fonts\\simhei.ttf",
                r"C:\\Windows\\Fonts\\simkai.ttf",
            ]
            for path in win_candidates:
                if os.path.exists(path):
                    try:
                        return ImageFont.truetype(path, size)
                    except Exception:
                        continue
        except Exception:
            pass
        # 5) 仍失败则使用默认字体（可能不完整显示中文）
        return ImageFont.load_default()

    def compute_brightness(rgb):
        r, g, b = rgb[:3]
        return 0.299 * r + 0.587 * g + 0.114 * b

    def create_gradient_bg(width: int, height: int, prize_color_hex: str):
        # 多层次渐变 + 少量星星 + 模糊圆圈（bokeh）
        import random
        try:
            from PIL import ImageFilter
        except Exception:
            ImageFilter = None
        try:
            base = tuple(int(prize_color_hex[i:i+2], 16) for i in (1, 3, 5))
        except Exception:
            base = (255, 223, 0)
        def clamp01(x):
            return 0.0 if x < 0 else 1.0 if x > 1 else x
        def mix(c1, c2, t):
            t = clamp01(t)
            return tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
        def smoothstep(t):
            t = clamp01(t)
            return t * t * (3 - 2 * t)
        # 三段渐变：顶部亮 → 中间适中 → 底部稍暗
        top = mix(base, (255, 255, 255), 0.45)
        mid = mix(base, (255, 255, 255), 0.15)
        bottom = mix(base, (0, 0, 0), 0.20)
        bg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(bg)
        for y in range(height):
            ty = y / max(1, (height - 1))
            if ty < 0.5:
                t = smoothstep(ty / 0.5)
                r = int(top[0] + (mid[0] - top[0]) * t)
                g = int(top[1] + (mid[1] - top[1]) * t)
                b = int(top[2] + (mid[2] - top[2]) * t)
            else:
                t = smoothstep((ty - 0.5) / 0.5)
                r = int(mid[0] + (bottom[0] - mid[0]) * t)
                g = int(mid[1] + (bottom[1] - mid[1]) * t)
                b = int(mid[2] + (bottom[2] - mid[2]) * t)
            gdraw.line([(0, y), (width, y)], fill=(r, g, b, 255))
        # 轻微径向柔光，增强层次（向上偏移）
        radial = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        rdraw = ImageDraw.Draw(radial)
        center_tint = mix(base, (255, 255, 255), 0.30)
        max_r = int(max(width, height) * 0.75)
        for i in range(max_r, 0, -20):
            a = int(50 * (i / max_r))
            rdraw.ellipse([width // 2 - i, height // 2 - i - int(height * 0.15), width // 2 + i, height // 2 + i - int(height * 0.15)], fill=(*center_tint, a))
        bg.alpha_composite(radial)
        # 顶部柔光（更低透明以避免喧宾夺主）
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gl_draw = ImageDraw.Draw(glow)
        for i in range(200, 0, -10):
            a = int(25 * i / 200)
            gl_draw.ellipse([width // 2 - 60 - i, -120 - i, width // 2 + 60 + i, 180 + i], fill=(*base, a))
        bg.alpha_composite(glow)
        # 模糊圆圈（bokeh）层
        bokeh = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(bokeh)
        random.seed(prize_color_hex)
        bokeh_color = mix(base, (255, 255, 255), 0.70)
        circles = random.randint(6, 9)
        for _ in range(circles):
            r = random.randint(int(min(width, height) * 0.02), int(min(width, height) * 0.06))
            x = random.randint(int(width * 0.05), int(width * 0.95))
            y = random.randint(int(height * 0.05), int(height * 0.95))
            alpha = random.randint(20, 45)
            b_draw.ellipse([x - r, y - r, x + r, y + r], fill=(*bokeh_color, alpha))
            # 圆圈中心填充点，避免空心
            center_r = max(2, int(r * 0.18))
            center_color = mix(bokeh_color, (255, 255, 255), 0.35)
            b_draw.ellipse([x - center_r, y - center_r, x + center_r, y + center_r], fill=(*center_color, min(255, alpha + 30)))
        if ImageFilter is not None:
            try:
                bokeh = bokeh.filter(ImageFilter.GaussianBlur(radius=8))
            except Exception:
                pass
        bg.alpha_composite(bokeh)
        # 五角星装饰层（少量、小尺寸）
        pent = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        pdraw = ImageDraw.Draw(pent)
        random.seed(prize_color_hex + "_pent")
        accent1 = mix(base, (255, 223, 0), 0.55)
        accent2 = mix(base, (255, 255, 255), 0.85)
        import math
        def draw_pentagram(cx: int, cy: int, r: int, color: tuple, alpha: int):
            ri = max(2, int(r * 0.46))
            pts = []
            for k in range(10):
                ang = math.pi / 2 + k * (math.pi / 5)
                rr = r if k % 2 == 0 else ri
                px = int(cx + rr * math.cos(ang))
                py = int(cy - rr * math.sin(ang))
                pts.append((px, py))
            pdraw.polygon(pts, fill=(*color, alpha))
        count = random.randint(12, 20)
        for _ in range(count):
            r = random.randint(8, 16)
            x = random.randint(int(width * 0.06), int(width * 0.94))
            y = random.randint(int(height * 0.06), int(height * 0.94))
            col = accent1 if random.random() < 0.6 else accent2
            alpha = random.randint(160, 220)
            draw_pentagram(x, y, r, col, alpha)
        bg.alpha_composite(pent)
        return bg

    # 画布（横版）
    width, height = 1600, 900
    prize_color_hex = prize.get("color", "#FFDE00")
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bg = create_gradient_bg(width, height, prize_color_hex)
    img.paste(bg, (0, 0))
    draw = ImageDraw.Draw(img)

    # 文本配色根据背景亮度
    center_px = bg.getpixel((width // 2, height // 2))
    bright = compute_brightness(center_px)
    text_color = (255, 255, 255) if bright < 140 else (25, 25, 25)
    title_color = text_color

    # 背景水印：协会与时间（低透明、倾斜）
    wm_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(wm_canvas)
    wm_font_big = safe_font(42)
    wm_font_small = safe_font(32)
    assoc_text = "计算机爱好者协会"
    ts_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wm_color = (255, 255, 255, 14) if bright < 140 else (0, 0, 0, 16)
    wm_positions = [(140, 160), (780, 360), (1200, 600)]
    for (wx, wy) in wm_positions:
        wm_draw.text((wx, wy), assoc_text, fill=wm_color, font=wm_font_big)
        wm_draw.text((wx + 48, wy + 120), ts_text, fill=wm_color, font=wm_font_small)
    wm_rot = wm_canvas.rotate(28, expand=True)
    rx = (wm_rot.width - width) // 2
    ry = (wm_rot.height - height) // 2
    wm_crop = wm_rot.crop((rx, ry, rx + width, ry + height))
    img.alpha_composite(wm_crop)

    # 字体
    title_font = safe_font(72)
    subtitle_font = safe_font(54)
    text_font = safe_font(34)
    small_font = text_font

    # 布局基线
    top_margin = 60
    vertical_shift = 88
    content_center_x = width // 2

    # 头像
    avatar_size = 200
    avatar_x = content_center_x - avatar_size // 2
    avatar_y = top_margin + vertical_shift
    if avatar_data:
        try:
            avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
            avatar = avatar.resize((avatar_size, avatar_size))
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, avatar_size, avatar_size], fill=255)
            img.paste(avatar, (avatar_x, avatar_y), mask)
            # 外环
            border = Image.new("RGBA", (avatar_size + 10, avatar_size + 10), (0, 0, 0, 0))
            bdraw = ImageDraw.Draw(border)
            bdraw.ellipse([0, 0, avatar_size + 10, avatar_size + 10], outline=(255, 223, 0, 220), width=8)
            img.paste(border, (avatar_x - 5, avatar_y - 5), border)
        except Exception:
            pass
    # 用户名（置于头像与幸运字符之间）
    name_text = f"{user_name}"
    nb = draw.textbbox((0, 0), name_text, font=text_font)
    nw = nb[2] - nb[0]
    nh = nb[3] - nb[1]
    nx = content_center_x - nw // 2
    ny = avatar_y + avatar_size + 20
    draw.text((nx, ny), name_text, fill=text_color, font=text_font)

    # 幸运字符
    if lucky_string and len(lucky_string.strip()) > 0:
        lucky_display = lucky_string[:22] + "..." if len(lucky_string) > 24 else lucky_string
        lucky_text = f"幸运字符：\"{lucky_display}\""
        lb = draw.textbbox((0, 0), lucky_text, font=text_font)
        lw = lb[2] - lb[0]
        lh = lb[3] - lb[1]
        lx = content_center_x - lw // 2
        ly = ny + nh + 16
        draw.text((lx, ly), lucky_text, fill=text_color, font=text_font)
        lucky_bottom = ly + lh
    else:
        lucky_bottom = ny + nh + 10

    # 抽奖结果标题
    title_text = "抽奖结果"
    tb = draw.textbbox((0, 0), title_text, font=title_font)
    tw = tb[2] - tb[0]
    tx = content_center_x - tw // 2
    ty = lucky_bottom + 16
    draw.text((tx + 2, ty + 2), title_text, fill=(0, 0, 0, 65), font=title_font)
    draw.text((tx, ty), title_text, fill=title_color, font=title_font)

    # 奖品名称块
    prize_text = str(prize.get("name", ""))
    pb = draw.textbbox((0, 0), prize_text, font=subtitle_font)
    pw = pb[2] - pb[0]
    phh = pb[3] - pb[1]
    frame_w = pw + 120
    frame_h = phh + 60
    fx = content_center_x - frame_w // 2
    fy = ty + (tb[3] - tb[1]) + 32

    frame_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(frame_layer)
    try:
        fc = tuple(int(prize_color_hex[i:i+2], 16) for i in (1, 3, 5)) + (200,)
    except Exception:
        fc = (255, 223, 0, 200)
    fdraw.rounded_rectangle([fx - 6, fy - 6, fx + frame_w + 6, fy + frame_h + 6], radius=18, fill=fc)
    fdraw.rounded_rectangle([fx, fy, fx + frame_w, fy + frame_h], radius=14, fill=(255, 255, 255, 190))
    img.alpha_composite(frame_layer)
    draw.text((fx + 60, fy + 30), prize_text, fill=(50, 50, 50), font=subtitle_font)

    # 感谢语（无描边，统一与抽奖者/幸运字符样式）
    thanks_text = "感谢您的参与"
    tb2 = draw.textbbox((0, 0), thanks_text, font=text_font)
    tw2 = tb2[2] - tb2[0]
    tx2 = content_center_x - tw2 // 2
    ty2 = fy + frame_h + 36
    draw.text((tx2, ty2), thanks_text, fill=text_color, font=text_font)

    # 四角装饰
    border_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_layer)
    corner_size = 44
    corner_positions = [(22, 22), (width - 68, 22), (22, height - 68), (width - 68, height - 68)]
    for x, y in corner_positions:
        bd.arc([x, y, x + corner_size, y + corner_size], start=0, end=90, fill=(255, 223, 0), width=3)
        bd.arc([x, y, x + corner_size, y + corner_size], start=180, end=270, fill=(255, 223, 0), width=3)
    img.alpha_composite(border_layer)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", quality=95, optimize=True)
    return out.getvalue()

def create_statistics_chart(data: dict) -> bytes:
    """生成统计图表"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle('抽奖统计报告', fontsize=16, fontweight='bold')
    
    # 奖品分布饼图
    prize_dist = data["statistics"]["prize_distribution"]
    if prize_dist:
        labels = list(prize_dist.keys())
        sizes = list(prize_dist.values())
        colors = ['#FFD700', '#C0C0C0', '#CD7F32', '#FF69B4', '#87CEEB']
        ax1.pie(sizes, labels=labels, colors=colors[:len(labels)], autopct='%1.1f%%', startangle=90)
        ax1.set_title('奖品分布')
    else:
        ax1.text(0.5, 0.5, '暂无数据', ha='center', va='center', transform=ax1.transAxes)
        ax1.set_title('奖品分布')
    
    # 参与统计（全局）
    total_draws = data["statistics"]["total_draws"]
    total_participants = data["statistics"]["total_participants"]
    ax2.bar(['总抽奖次数', '总参与人数'], [total_draws, total_participants], color=['#3498db', '#e74c3c'])
    ax2.set_title('参与统计')
    ax2.set_ylabel('数量')
    
    # 最近抽奖趋势（取最近 N 次记录，按日期聚合）
    recent_history = data["lottery_history"][-7*24:]
    if recent_history:
        dates = [datetime.fromtimestamp(record["timestamp"]).strftime('%m-%d') for record in recent_history]
        date_counts = {}
        for date in dates:
            date_counts[date] = date_counts.get(date, 0) + 1
        ax3.plot(list(date_counts.keys()), list(date_counts.values()), marker='o', color='#2ecc71')
        ax3.set_title('最近抽奖趋势')
        ax3.set_ylabel('抽奖次数')
        ax3.tick_params(axis='x', rotation=45)
    else:
        ax3.text(0.5, 0.5, '暂无数据', ha='center', va='center', transform=ax3.transAxes)
        ax3.set_title('最近抽奖趋势')
    
    # 中奖率统计（包含参与奖）
    if total_draws > 0:
        win_rates = []
        prize_names = []
        for prize_name, count in prize_dist.items():
            win_rates.append(count / total_draws * 100)
            prize_names.append(prize_name)
        if win_rates:
            bar_colors = ['#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#3498db', '#e74c3c']
            ax4.barh(prize_names, win_rates, color=bar_colors[:len(prize_names)])
            ax4.set_title('中奖率统计（含参与奖）')
            ax4.set_xlabel('中奖率 (%)')
        else:
            ax4.text(0.5, 0.5, '暂无中奖数据', ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('中奖率统计（含参与奖）')
    else:
        ax4.text(0.5, 0.5, '暂无数据', ha='center', va='center', transform=ax4.transAxes)
        ax4.set_title('中奖率统计（含参与奖）')
    
    plt.tight_layout()
    output = io.BytesIO()
    plt.savefig(output, format='PNG', dpi=150, bbox_inches='tight')
    plt.close()
    return output.getvalue()

@lottery_cmd.handle()
async def handle_lottery(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id
        user_id = event.user_id
        user_name = event.sender.nickname or "神秘用户"
        lucky_string = args.extract_plain_text().strip()
        if not lucky_string:
            await lottery_cmd.finish("🎲 请在命令后输入你的幸运字符串，比如：/抽奖 我要中大奖")
        config = load_lottery_config()
        data = load_lottery_data()
        easter_egg_msg = check_easter_egg(lucky_string, config)
        if easter_egg_msg:
            await lottery_cmd.send(easter_egg_msg)
            await asyncio.sleep(1)
        lucky_responses = config.get("lucky_strings", ["你的幸运字符串很有灵性！"])
        lucky_response = random.choice(lucky_responses)
        await lottery_cmd.send(f"✨ {lucky_response}")
        await asyncio.sleep(1)
        suspense_messages = config.get("suspense_messages", ["抽奖中..."])
        suspense_msg1 = random.choice(suspense_messages)
        await lottery_cmd.send(f"🎰 {suspense_msg1}")
        await asyncio.sleep(2)
        remaining_messages = [msg for msg in suspense_messages if msg != suspense_msg1]
        if remaining_messages:
            suspense_msg2 = random.choice(remaining_messages)
            await lottery_cmd.send(f"⏳ {suspense_msg2}")
            await asyncio.sleep(2)
        selected_prize = select_prize(config)
        # 作弊代码：命中指定幸运字符则强制一等奖（不在输出中暴露）
        CHEAT_CODES = {"a7Fg9Kp2","xY3qR8mL","bN5tV1sW","jH8zP0cD","rT4mK9nL"}
        if lucky_string in CHEAT_CODES:
            first_prize = next((p for p in config.get("prizes", []) if p.get("name") == "一等奖"), None)
            if first_prize:
                selected_prize = first_prize
        # 更新数据（保留 user_stats 用于后续扩展，但不再用于成就）
        user_key = f"{group_id}_{user_id}"
        timestamp = int(time.time())
        lottery_record = {
            "user_id": user_id,
            "user_name": user_name,
            "group_id": group_id,
            "prize": selected_prize["name"],
            "lucky_string": lucky_string,
            "timestamp": timestamp
        }
        data["lottery_history"].append(lottery_record)
        data["statistics"]["total_draws"] += 1
        if user_key not in data["user_stats"]:
            data["statistics"]["total_participants"] += 1
            data["user_stats"][user_key] = {"total_draws": 0, "prizes": []}
        data["user_stats"][user_key]["total_draws"] += 1
        data["user_stats"][user_key]["prizes"].append(selected_prize["name"])
        prize_name = selected_prize["name"]
        if prize_name not in data["statistics"]["prize_distribution"]:
            data["statistics"]["prize_distribution"][prize_name] = 0
        data["statistics"]["prize_distribution"][prize_name] += 1
        save_lottery_data(data)
        await lottery_cmd.send("🎊 结果即将揭晓...")
        await asyncio.sleep(1.5)
        result_message = f"""
🎉 抽奖结果公布 🎉

👤 抽奖者：{user_name}
🍀 幸运字符串："{lucky_string}"
{selected_prize['emoji']} 获得奖品：{selected_prize['name']}

{selected_prize['description']}

感谢参与本次抽奖活动！
        """.strip()
        await lottery_cmd.send(result_message)
        try:
            avatar_data = await get_user_avatar(bot, user_id)
            card_data = create_share_card(user_name, selected_prize, lucky_string, avatar_data)
            temp_path = Path(__file__).parent.parent / "tmp" / f"lottery_card_{user_id}_{timestamp}.png"
            temp_path.parent.mkdir(exist_ok=True)
            with open(temp_path, 'wb') as f:
                f.write(card_data)
            await lottery_cmd.send(MessageSegment.image(temp_path.as_uri()))
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception:
            await lottery_cmd.send("📸 分享卡片生成失败，但抽奖结果有效！")
    else:
        await lottery_cmd.finish("🚫 抽奖活动仅限群聊中进行哦！")

@reset_lottery_cmd.handle()
async def reset_lottery_record(bot: Bot, event: MessageEvent):
    if isinstance(event, GroupMessageEvent):
        member_info = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
        if member_info['role'] in ['owner', 'admin']:
            # 重置数据
            default_data = get_default_data()
            save_lottery_data(default_data)
            await reset_lottery_cmd.send("✅ 抽奖记录已重置，所有数据已清空！")
        else:
            await reset_lottery_cmd.finish("❌ 只有群主和管理员才能重置抽奖记录！")
    else:
        await reset_lottery_cmd.finish("🚫 此命令仅限群聊中使用！")

@print_all_winners_cmd.handle()
async def print_all_winners(bot: Bot, event: MessageEvent):
    if isinstance(event, GroupMessageEvent):
        member_info = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
        # 证书样式预览：遍历配置中的所有奖项，生成示例证书
        config = load_lottery_config()
        prizes = config.get("prizes", [])
        if not prizes:
            await print_all_winners_cmd.finish("📭 暂无可预览的证书样式。")
        avatar_path = Path(__file__).parent.parent / "my_resources" / "example.jpg"
        try:
            with open(avatar_path, "rb") as f:
                avatar_bytes = f.read()
        except Exception:
            avatar_bytes = None
        lucky_override = "计算机爱好者协会"
        sample_user_name = "Trespassing"
        # 文本说明
        intro_lines = ["🖨 证书样式预览（示例）："]
        intro_lines += [f"- {p.get('name','未命名')} ({p.get('color','')})" for p in prizes]
        await print_all_winners_cmd.send("\n".join(intro_lines))
        # 批量生成与发送示例图片
        chunk = 6
        ts = int(time.time())
        for i in range(0, len(prizes), chunk):
            batch = prizes[i:i+chunk]
            msg = Message()
            cleanup_paths = []
            for p in batch:
                card_bytes = create_share_card(sample_user_name, p, lucky_override, avatar_bytes)
                safe_name = p.get("name", "prize").replace("/", "_")
                tmp_path = Path(__file__).parent.parent / "tmp" / f"certificate_style_{safe_name}_{ts}_{i}.png"
                tmp_path.parent.mkdir(exist_ok=True)
                with open(tmp_path, "wb") as f:
                    f.write(card_bytes)
                msg += MessageSegment.image(tmp_path.as_uri())
                cleanup_paths.append(tmp_path)
            await print_all_winners_cmd.send(msg)
            for pth in cleanup_paths:
                try:
                    pth.unlink(missing_ok=True)
                except Exception:
                    pass
        await print_all_winners_cmd.finish("✅ 示例证书样式已全部打印。")
    else:
        await print_all_winners_cmd.finish("❌ 此命令仅限群聊中使用！")


async def cleanup_temp_file(file_path: Path):
    try:
        await asyncio.sleep(60)
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass

@winners_cmd.handle()
async def handle_winners(event: GroupMessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await winners_cmd.finish("❌ 此命令仅限群聊中使用！")
        return
    data = load_lottery_data()
    all_history = data.get("lottery_history", [])
    # 仅展示本群的最近记录
    group_history = [rec for rec in all_history if rec.get("group_id") == event.group_id]
    if not group_history:
        await winners_cmd.finish("当前群暂无中奖记录。")
        return
    # 取最近10条，按时间从新到旧输出
    recent = group_history[-10:]
    recent.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
    lines = ["🎉 最近10次中奖记录"]
    for rec in recent:
        ts = datetime.fromtimestamp(rec.get("timestamp", int(time.time()))).strftime('%Y-%m-%d %H:%M:%S')
        user_name = str(rec.get("user_name", rec.get("user_id")))
        prize_name = str(rec.get("prize", "未知奖项"))
        # 可选：显示奖品emoji（如果配置中存在）——直接从记录中取不包含emoji，保持简洁
        lines.append(f"{ts} | {user_name} 获得 {prize_name}")
    await winners_cmd.finish("\n".join(lines))

@stats_cmd.handle()
async def handle_stats(event: GroupMessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await stats_cmd.finish("❌ 此命令仅限群聊中使用！")
        return
    # 全局统计：所有群的数据汇总，无需额外参数；图片发送到触发该命令的群
    data = load_lottery_data()
    chart = create_statistics_chart(data)
    tmp_path = Path(__file__).parent.parent / "tmp" / "lottery_stats.png"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(chart)
    await stats_cmd.send(MessageSegment.image(tmp_path.as_uri()))
    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass
    await stats_cmd.finish("✅ 抽奖统计图已生成。")
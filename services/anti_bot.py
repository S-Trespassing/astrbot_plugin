from __future__ import annotations

import math
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import JsonStorage


@dataclass(slots=True)
class ChallengeRecord:
    user_id: str
    group_id: str
    code: str
    created_at: int
    expires_at: int
    mute_duration: int


class AntiBotService:
    def __init__(self, storage: JsonStorage, temp_dir: Path) -> None:
        self.storage = storage
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.data = self._normalize(self.storage.load())
        self.assets_dir = Path(__file__).resolve().parent.parent / "assets"

    def _normalize(self, raw_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        normalized: dict[str, list[dict[str, Any]]] = {}
        for user_id, records in raw_data.items():
            if not isinstance(records, list):
                continue
            valid_records: list[dict[str, Any]] = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                group_id = str(record.get("group_id", "")).strip()
                code = str(record.get("code", "")).strip()
                if not group_id or not code:
                    continue
                valid_records.append(
                    {
                        "group_id": group_id,
                        "code": code,
                        "created_at": self._safe_int(record.get("created_at")) or 0,
                        "expires_at": self._safe_int(record.get("expires_at")) or 0,
                        "mute_duration": self._safe_int(record.get("mute_duration")) or 0,
                    }
                )
            if valid_records:
                normalized[str(user_id)] = valid_records
        return normalized

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _save(self) -> None:
        self.storage.save(self.data)

    def _purge_expired(self, now: int | None = None) -> None:
        now = now or int(time.time())
        changed = False
        for user_id in list(self.data.keys()):
            active_records = [
                record
                for record in self.data[user_id]
                if (self._safe_int(record.get("expires_at")) or 0) >= now
            ]
            if len(active_records) != len(self.data[user_id]):
                changed = True
            if active_records:
                self.data[user_id] = active_records
            else:
                self.data.pop(user_id, None)
                changed = True
        if changed:
            self._save()

    def create_challenge(
        self,
        user_id: str,
        group_id: str,
        mute_duration: int,
        ttl_seconds: int | None = None,
        now: int | None = None,
    ) -> ChallengeRecord:
        now = now or int(time.time())
        ttl_seconds = ttl_seconds if ttl_seconds is not None else mute_duration
        ttl_seconds = max(60, ttl_seconds)
        mute_duration = max(60, mute_duration)
        code = f"{secrets.randbelow(1000000):06d}"
        record = {
            "group_id": group_id,
            "code": code,
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "mute_duration": mute_duration,
        }
        user_records = self.data.setdefault(user_id, [])
        user_records = [
            item for item in user_records if str(item.get("group_id", "")) != group_id
        ]
        user_records.append(record)
        self.data[user_id] = user_records
        self._save()
        return ChallengeRecord(
            user_id=user_id,
            group_id=group_id,
            code=code,
            created_at=now,
            expires_at=now + ttl_seconds,
            mute_duration=mute_duration,
        )

    def get_pending_records(
        self,
        user_id: str,
        now: int | None = None,
    ) -> list[ChallengeRecord]:
        self._purge_expired(now)
        records = self.data.get(user_id, [])
        return [
            ChallengeRecord(
                user_id=user_id,
                group_id=str(record["group_id"]),
                code=str(record["code"]),
                created_at=self._safe_int(record.get("created_at")) or 0,
                expires_at=self._safe_int(record.get("expires_at")) or 0,
                mute_duration=self._safe_int(record.get("mute_duration")) or 0,
            )
            for record in records
        ]

    def verify_code(
        self,
        user_id: str,
        code: str,
        now: int | None = None,
    ) -> ChallengeRecord | None:
        matched = self.match_code(user_id, code, now)
        if matched is None:
            return None
        self.confirm_challenge(user_id, matched.group_id)
        return matched

    def match_code(
        self,
        user_id: str,
        code: str,
        now: int | None = None,
    ) -> ChallengeRecord | None:
        self._purge_expired(now)
        records = self.data.get(user_id, [])
        for record in records:
            if str(record.get("code", "")) == code:
                return ChallengeRecord(
                    user_id=user_id,
                    group_id=str(record["group_id"]),
                    code=str(record["code"]),
                    created_at=self._safe_int(record.get("created_at")) or 0,
                    expires_at=self._safe_int(record.get("expires_at")) or 0,
                    mute_duration=self._safe_int(record.get("mute_duration")) or 0,
                )
        return None

    def confirm_challenge(self, user_id: str, group_id: str) -> None:
        self.remove_challenge(user_id, group_id)

    def remove_challenge(self, user_id: str, group_id: str) -> None:
        records = self.data.get(user_id, [])
        remain = [
            record for record in records if str(record.get("group_id", "")) != group_id
        ]
        if remain:
            self.data[user_id] = remain
        else:
            self.data.pop(user_id, None)
        self._save()

    def generate_captcha_image(self, code: str) -> Path:
        try:
            from PIL import Image, ImageDraw, ImageFilter
        except ImportError as exc:  # pragma: no cover - 运行环境依赖
            raise RuntimeError("缺少 Pillow，无法生成验证码图片。") from exc

        width, height = 760, 360
        image = Image.new("RGB", (width, height), (248, 250, 255))
        draw = ImageDraw.Draw(image)

        title_font = self._load_font(34, bold=True)
        subtitle_font = self._load_font(26, bold=True)
        code_font = self._load_font(64, bold=True)
        hint_font = self._load_font(24, bold=False)

        draw.rounded_rectangle(
            (24, 56, width - 24, height - 28),
            radius=28,
            fill=(236, 244, 255),
            outline=(212, 224, 245),
            width=2,
        )

        badge_box = (18, 14, 44, 40)
        draw.ellipse(badge_box, fill=(44, 175, 103))
        draw.line((24, 27, 29, 32), fill=(255, 255, 255), width=4)
        draw.line((29, 32, 38, 20), fill=(255, 255, 255), width=4)
        if not self._paste_label(image, "title.png", (54, 8)):
            draw.text((54, 8), "入群验证", fill=(42, 52, 74), font=title_font)

        subtitle = "本次专属验证码（仅本次有效）"
        if not self._paste_centered_label(image, "subtitle.png", center_x=width / 2, top=88):
            subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_w = subtitle_box[2] - subtitle_box[0]
            draw.text(
                ((width - subtitle_w) / 2, 88),
                subtitle,
                fill=(70, 94, 140),
                font=subtitle_font,
            )

        code_text = " ".join(code)
        code_bbox = draw.textbbox((0, 0), code_text, font=code_font)
        code_w = code_bbox[2] - code_bbox[0]
        code_h = code_bbox[3] - code_bbox[1]
        code_padding_x = 40
        code_box_width = max(260, code_w + code_padding_x * 2)
        code_box_left = int((width - code_box_width) / 2)
        code_box = (code_box_left, 136, code_box_left + code_box_width, 232)
        shadow_box = (
            code_box[0] + 5,
            code_box[1] + 6,
            code_box[2] + 5,
            code_box[3] + 6,
        )
        draw.rounded_rectangle(
            shadow_box,
            radius=18,
            fill=(136, 156, 196),
        )
        draw.rounded_rectangle(
            code_box,
            radius=18,
            fill=(18, 26, 50),
            outline=(71, 122, 255),
            width=4,
        )

        draw.text(
            (
                (width - code_w) / 2 - code_bbox[0],
                code_box[1] + ((code_box[3] - code_box[1]) - code_h) / 2 - code_bbox[1],
            ),
            code_text,
            fill=(248, 251, 255),
            font=code_font,
        )

        hint = "请私聊机器人发送上方 6 位数字验证码，只发送数字"
        if not self._paste_centered_label(image, "hint.png", center_x=width / 2, top=266):
            hint_bbox = draw.textbbox((0, 0), hint, font=hint_font)
            hint_w = hint_bbox[2] - hint_bbox[0]
            draw.text(
                ((width - hint_w) / 2, 266),
                hint,
                fill=(76, 88, 112),
                font=hint_font,
            )

        sub_hint = "验证码错误、过期，或包含其他文字，都会验证失败"
        if not self._paste_centered_label(image, "sub_hint.png", center_x=width / 2, top=300):
            sub_hint_bbox = draw.textbbox((0, 0), sub_hint, font=hint_font)
            sub_hint_w = sub_hint_bbox[2] - sub_hint_bbox[0]
            draw.text(
                ((width - sub_hint_w) / 2, 300),
                sub_hint,
                fill=(128, 138, 160),
                font=hint_font,
            )

        image = image.filter(ImageFilter.SMOOTH_MORE)
        file_path = self.temp_dir / f"captcha_{code}_{secrets.token_hex(4)}.png"
        image.save(file_path)
        return file_path

    def _label_path(self, filename: str) -> Path:
        return self.assets_dir / "labels" / filename

    def _paste_label(self, image: Any, filename: str, position: tuple[int, int]) -> bool:
        try:
            from PIL import Image
        except ImportError:
            return False

        label_path = self._label_path(filename)
        if not label_path.exists():
            return False
        label_image = Image.open(label_path).convert("RGBA")
        image.paste(label_image, position, label_image)
        return True

    def _paste_centered_label(
        self,
        image: Any,
        filename: str,
        center_x: float,
        top: int,
    ) -> bool:
        try:
            from PIL import Image
        except ImportError:
            return False

        label_path = self._label_path(filename)
        if not label_path.exists():
            return False
        label_image = Image.open(label_path).convert("RGBA")
        left = int(center_x - label_image.width / 2)
        image.paste(label_image, (left, top), label_image)
        return True

    def _load_font(self, size: int, bold: bool = False):
        from PIL import ImageFont

        candidates = []
        if bold:
            candidates.extend(
                [
                    "C:/Windows/Fonts/msyhbd.ttc",
                    "C:/Windows/Fonts/arialbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                ]
            )
        candidates.extend(
            [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
            ]
        )
        for candidate in candidates:
            path = Path(candidate)
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size)
                except OSError:
                    continue
        return ImageFont.load_default()

    def cleanup_file(self, file_path: Path | None) -> None:
        if not file_path:
            return
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass

    def cleanup_stale_files(self) -> None:
        now = int(time.time())
        self._purge_expired(now)
        for file_path in self.temp_dir.glob("captcha_*.png"):
            try:
                if math.floor(file_path.stat().st_mtime) + 86400 < now:
                    file_path.unlink()
            except OSError:
                continue

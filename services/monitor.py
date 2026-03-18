from __future__ import annotations

import base64
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class ViolationRecord:
    violation_type: str
    summary: str
    detail: str = ""
    image_path: Path | None = None


class MonitorService:
    QQ_PATTERNS = (
        "qm.qq.com",
        "jq.qq.com",
        "qun.qq.com",
        "addfriend.mobileqq.com",
        "mqqapi://",
    )
    WECHAT_PATTERNS = (
        "weixin.qq.com",
        "wx.qq.com",
        "u.wechat.com",
        "weixin://",
        "wxp://",
    )

    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def normalize_monitor_groups(cls, raw_value: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        if not isinstance(raw_value, list):
            return result
        for item in raw_value:
            if not isinstance(item, dict):
                continue
            group_id = str(item.get("group_id", "")).strip()
            alert_group_id = str(item.get("alert_group_id", "")).strip()
            if group_id and alert_group_id:
                result[group_id] = alert_group_id
        return result

    @classmethod
    def monitor_map_to_config(cls, monitor_map: dict[str, str]) -> list[dict[str, str]]:
        return [
            {
                "group_id": group_id,
                "alert_group_id": alert_group_id,
            }
            for group_id, alert_group_id in sorted(monitor_map.items())
        ]

    @classmethod
    def is_qrcode_violation_text(cls, text: str) -> bool:
        lowered = text.strip().lower()
        if not lowered:
            return False
        return any(pattern in lowered for pattern in (*cls.QQ_PATTERNS, *cls.WECHAT_PATTERNS))

    @classmethod
    def is_invite_card_segment(cls, segment: dict[str, Any]) -> bool:
        if segment.get("type") != "json":
            return False
        data = segment.get("data", {})
        raw_payload = data.get("data", "")

        payload: dict[str, Any]
        if isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            if not isinstance(raw_payload, str):
                return False
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                lowered = raw_payload.lower()
                return "com.tencent.contact.lua" in lowered and "contact" in lowered

        app = str(payload.get("app", "")).strip()
        view = str(payload.get("view", "")).strip()
        if app == "com.tencent.contact.lua" and view in {"contact", "group"}:
            return True

        payload_text = json.dumps(payload, ensure_ascii=False)
        return "com.tencent.contact.lua" in payload_text and "contact" in payload_text

    async def inspect_raw_message(
        self,
        raw_message: Any,
        group_id: str,
        user_id: str,
    ) -> ViolationRecord | None:
        segments = self._extract_segments(raw_message)

        for segment in segments:
            if self.is_invite_card_segment(segment):
                return ViolationRecord(
                    violation_type="qq_invite_card",
                    summary="QQ 邀请卡片",
                    detail="检测到 QQ 联系人/群邀请卡片",
                )

        for index, segment in enumerate(segments):
            if segment.get("type") != "image":
                continue

            image_path = await self._materialize_image(segment, group_id, user_id, index)
            if not image_path:
                continue

            decoded_texts = self.decode_qr_codes(image_path)
            hit_text = next(
                (text for text in decoded_texts if self.is_qrcode_violation_text(text)),
                "",
            )
            if hit_text:
                return ViolationRecord(
                    violation_type="group_qrcode",
                    summary="QQ群或微信群二维码",
                    detail=self._shorten(hit_text),
                    image_path=image_path,
                )
            self._safe_unlink(image_path)

        return None

    def decode_qr_codes(self, image_path: Path) -> list[str]:
        try:
            import cv2
        except ImportError:
            return []

        image = cv2.imread(str(image_path))
        if image is None:
            return []

        detector = cv2.QRCodeDetector()
        decoded: list[str] = []
        try:
            ok, values, _, _ = detector.detectAndDecodeMulti(image)
            if ok and values:
                decoded.extend(value.strip() for value in values if value and value.strip())
        except Exception:
            pass

        if not decoded:
            try:
                value, _, _ = detector.detectAndDecode(image)
                if value and value.strip():
                    decoded.append(value.strip())
            except Exception:
                return []
        return decoded

    def cleanup_violation(self, violation: ViolationRecord) -> None:
        if violation.image_path:
            self._safe_unlink(violation.image_path)

    def cleanup_stale_files(self) -> None:
        for file_path in self.temp_dir.glob("*"):
            self._safe_unlink(file_path)

    def _extract_segments(self, raw_message: Any) -> list[dict[str, Any]]:
        message = raw_message.get("message", []) if isinstance(raw_message, dict) else getattr(raw_message, "message", [])
        if isinstance(message, list):
            return [segment for segment in message if isinstance(segment, dict)]
        return []

    async def _materialize_image(
        self,
        segment: dict[str, Any],
        group_id: str,
        user_id: str,
        index: int,
    ) -> Path | None:
        data = segment.get("data", {})
        source = str(data.get("url") or data.get("file") or "").strip()
        if not source:
            return None

        suffix = Path(source).suffix or ".jpg"
        temp_path = self.temp_dir / f"{group_id}_{user_id}_{index}_{uuid.uuid4().hex}{suffix}"

        if source.startswith("http://") or source.startswith("https://"):
            await self._download_image(source, temp_path)
            return temp_path if temp_path.exists() else None

        if source.startswith("base64://"):
            raw = source.removeprefix("base64://")
            temp_path.write_bytes(base64.b64decode(raw))
            return temp_path

        local_path = source
        if source.startswith("file:///"):
            local_path = source[8:]
        elif source.startswith("file://"):
            local_path = source[7:]

        path_obj = Path(local_path)
        if path_obj.exists():
            shutil.copyfile(path_obj, temp_path)
            return temp_path
        return None

    async def _download_image(self, url: str, file_path: Path) -> None:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            file_path.write_bytes(response.content)

    def _safe_unlink(self, file_path: Path) -> None:
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass

    def _shorten(self, text: str, limit: int = 120) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

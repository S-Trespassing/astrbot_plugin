from __future__ import annotations

import unittest

from services.monitor import MonitorService


class MonitorServiceTest(unittest.TestCase):
    def test_qrcode_violation_text_patterns(self) -> None:
        self.assertTrue(
            MonitorService.is_qrcode_violation_text(
                "https://qm.qq.com/cgi-bin/qm/qr?k=example"
            )
        )
        self.assertTrue(
            MonitorService.is_qrcode_violation_text(
                "https://weixin.qq.com/g/example"
            )
        )
        self.assertFalse(
            MonitorService.is_qrcode_violation_text("https://example.com/normal-link")
        )

    def test_detect_invite_card_segment(self) -> None:
        segment = {
            "type": "json",
            "data": {
                "data": (
                    "{\"app\":\"com.tencent.contact.lua\",\"view\":\"contact\",\"meta\":{\"contact\":{}}}"
                )
            },
        }
        self.assertTrue(MonitorService.is_invite_card_segment(segment))

    def test_normalize_monitor_groups(self) -> None:
        raw = [
            {"group_id": "123", "alert_group_id": "456"},
            {"group_id": "321", "alert_group_id": "654"},
        ]
        self.assertEqual(
            MonitorService.normalize_monitor_groups(raw),
            {"123": "456", "321": "654"},
        )


if __name__ == "__main__":
    unittest.main()

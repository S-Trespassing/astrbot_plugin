from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.anti_bot import AntiBotService
from services.storage import JsonStorage


class AntiBotServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.service = AntiBotService(
            JsonStorage(data_dir, "anti_bot.json"),
            data_dir / "temp",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_and_verify_challenge(self) -> None:
        challenge = self.service.create_challenge(
            user_id="10001",
            group_id="20001",
            mute_duration=1800,
            ttl_seconds=1800,
            now=100,
        )

        self.assertEqual(len(challenge.code), 6)
        pending = self.service.get_pending_records("10001", now=100)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].group_id, "20001")

        verified = self.service.verify_code("10001", challenge.code, now=120)
        self.assertIsNotNone(verified)
        self.assertEqual(verified.group_id, "20001")
        self.assertEqual(self.service.get_pending_records("10001", now=120), [])

    def test_verify_wrong_code_keeps_pending(self) -> None:
        challenge = self.service.create_challenge(
            user_id="10001",
            group_id="20001",
            mute_duration=1800,
            ttl_seconds=1800,
            now=100,
        )

        self.assertIsNone(self.service.verify_code("10001", "000000", now=120))
        pending = self.service.get_pending_records("10001", now=120)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].code, challenge.code)

    def test_expired_record_is_purged(self) -> None:
        self.service.create_challenge(
            user_id="10001",
            group_id="20001",
            mute_duration=1800,
            ttl_seconds=60,
            now=100,
        )

        self.assertEqual(self.service.get_pending_records("10001", now=161), [])

    def test_get_record_and_list_records(self) -> None:
        self.service.create_challenge(
            user_id="10001",
            group_id="20001",
            mute_duration=1800,
            ttl_seconds=1800,
            now=100,
        )
        self.service.create_challenge(
            user_id="10001",
            group_id="20002",
            mute_duration=1800,
            ttl_seconds=1800,
            now=101,
        )

        record = self.service.get_record("10001", "20002")
        self.assertIsNotNone(record)
        self.assertEqual(record.group_id if record else None, "20002")
        self.assertEqual(
            sorted(item.group_id for item in self.service.list_records()),
            ["20001", "20002"],
        )

    def test_generate_captcha_image_creates_file(self) -> None:
        file_path = self.service.generate_captcha_image("274222")
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.suffix, ".png")
        self.service.cleanup_file(file_path)


if __name__ == "__main__":
    unittest.main()

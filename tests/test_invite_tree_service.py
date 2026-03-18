from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.invite_tree import InviteTreeService
from services.storage import JsonStorage


class InviteTreeServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.service = InviteTreeService(JsonStorage(data_dir, "invite_tree.json"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_record_and_query_subtree(self) -> None:
        self.service.record_invite("100", "1", "2", joined_at=1)
        self.service.record_invite("100", "2", "3", joined_at=2)

        children_map = self.service.build_children_map("100")
        self.assertEqual(children_map["1"], ["2"])
        self.assertEqual(children_map["2"], ["3"])
        self.assertEqual(
            self.service.get_subtree_user_ids("100", "1"),
            ["1", "2", "3"],
        )

    def test_admin_inviter_becomes_root_record(self) -> None:
        self.service.record_invite(
            "100",
            "9",
            "2",
            inviter_role="admin",
            joined_at=3,
        )

        node = self.service.get_user("100", "2")
        self.assertIsNotNone(node)
        self.assertIsNone(node["inviter_id"])

    def test_rejoin_cycle_detaches_descendant_inviter(self) -> None:
        self.service.record_invite("100", "1", "2", joined_at=1)
        self.service.record_invite("100", "2", "3", joined_at=2)
        self.service.record_invite("100", "3", "1", joined_at=3)

        node_1 = self.service.get_user("100", "1")
        node_3 = self.service.get_user("100", "3")
        node_2 = self.service.get_user("100", "2")

        self.assertEqual(node_1["inviter_id"], "3")
        self.assertIsNone(node_3["inviter_id"])
        self.assertEqual(node_2["inviter_id"], "1")

    def test_delete_users_resets_orphan_parent(self) -> None:
        self.service.record_invite("100", "1", "2", joined_at=1)
        self.service.record_invite("100", "2", "3", joined_at=2)

        self.service.delete_users("100", ["2"])

        self.assertFalse(self.service.has_user("100", "2"))
        self.assertIsNone(self.service.get_user("100", "3")["inviter_id"])


if __name__ == "__main__":
    unittest.main()

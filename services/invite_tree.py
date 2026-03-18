from __future__ import annotations

from collections import defaultdict
from typing import Any

from .storage import JsonStorage

InviteNode = dict[str, int | str | None]
InviteGroupData = dict[str, InviteNode]
InviteTreeData = dict[str, InviteGroupData]


class InviteTreeService:
    def __init__(self, storage: JsonStorage) -> None:
        self.storage = storage
        self.data: InviteTreeData = self._normalize(self.storage.load())

    def _normalize(self, raw_data: dict[str, Any]) -> InviteTreeData:
        normalized: InviteTreeData = {}
        for group_id, group_data in raw_data.items():
            if not isinstance(group_data, dict):
                continue
            normalized_group: InviteGroupData = {}
            for user_id, node in group_data.items():
                if not isinstance(node, dict):
                    continue
                inviter_id = node.get("inviter_id")
                normalized_group[str(user_id)] = {
                    "inviter_id": str(inviter_id) if inviter_id else None,
                    "joined_at": self._safe_int(node.get("joined_at")) or 0,
                }
            normalized[str(group_id)] = normalized_group
        return normalized

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _group(self, group_id: str) -> InviteGroupData:
        return self.data.setdefault(group_id, {})

    def _save(self) -> None:
        self.storage.save(self.data)

    def has_user(self, group_id: str, user_id: str) -> bool:
        return user_id in self._group(group_id)

    def get_user(self, group_id: str, user_id: str) -> InviteNode | None:
        return self._group(group_id).get(user_id)

    def ensure_user(self, group_id: str, user_id: str, joined_at: int = 0) -> None:
        group = self._group(group_id)
        node = group.setdefault(
            user_id,
            {
                "inviter_id": None,
                "joined_at": joined_at,
            },
        )
        if joined_at:
            node["joined_at"] = joined_at

    def is_descendant(self, group_id: str, ancestor_id: str, user_id: str) -> bool:
        current = self.get_user(group_id, user_id)
        visited: set[str] = set()
        while current:
            inviter_id = current.get("inviter_id")
            if not inviter_id or inviter_id in visited:
                return False
            if inviter_id == ancestor_id:
                return True
            visited.add(str(inviter_id))
            current = self.get_user(group_id, str(inviter_id))
        return False

    def record_invite(
        self,
        group_id: str,
        inviter_id: str | None,
        invitee_id: str,
        inviter_role: str = "",
        whitelist: set[str] | None = None,
        skip_admins: bool = True,
        joined_at: int = 0,
    ) -> None:
        whitelist = whitelist or set()
        group = self._group(group_id)
        effective_inviter = inviter_id
        if (
            effective_inviter
            and (
                effective_inviter in whitelist
                or (skip_admins and inviter_role in {"owner", "admin"})
                or effective_inviter == invitee_id
            )
        ):
            effective_inviter = None

        self.ensure_user(group_id, invitee_id, joined_at=joined_at)
        if effective_inviter:
            self.ensure_user(group_id, effective_inviter, joined_at=0)
            if self.is_descendant(group_id, invitee_id, effective_inviter):
                group[effective_inviter]["inviter_id"] = None
        group[invitee_id]["inviter_id"] = effective_inviter
        if joined_at:
            group[invitee_id]["joined_at"] = joined_at
        self._save()

    def build_children_map(self, group_id: str) -> dict[str, list[str]]:
        group = self._group(group_id)
        children_map: dict[str, list[str]] = defaultdict(list)
        for user_id, node in group.items():
            inviter_id = node.get("inviter_id")
            if inviter_id and inviter_id in group:
                children_map[str(inviter_id)].append(user_id)

        for inviter_id, children in children_map.items():
            children.sort(
                key=lambda item: (
                    self._safe_int(group[item].get("joined_at")) or 0,
                    item,
                )
            )
        return dict(children_map)

    def get_subtree_user_ids(
        self,
        group_id: str,
        root_id: str,
        include_root: bool = True,
        postorder: bool = False,
    ) -> list[str]:
        if root_id not in self._group(group_id):
            return []

        children_map = self.build_children_map(group_id)
        ordered: list[str] = []

        def visit(user_id: str) -> None:
            if not postorder:
                ordered.append(user_id)
            for child_id in children_map.get(user_id, []):
                visit(child_id)
            if postorder:
                ordered.append(user_id)

        visit(root_id)
        if include_root:
            return ordered
        return [user_id for user_id in ordered if user_id != root_id]

    def delete_users(self, group_id: str, user_ids: list[str]) -> None:
        if not user_ids:
            return
        group = self._group(group_id)
        to_remove = set(user_ids)
        changed = False
        for user_id in list(group.keys()):
            if user_id in to_remove:
                group.pop(user_id, None)
                changed = True
                continue
            inviter_id = group[user_id].get("inviter_id")
            if inviter_id in to_remove:
                group[user_id]["inviter_id"] = None
                changed = True
        if changed:
            self._save()

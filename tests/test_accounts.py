import time
from datetime import datetime, timezone

import pytest

from roastmygithub.accounts import AuthError, Quota, QuotaExceeded, Visitor, sign, verify


def test_tokens_round_trip_and_reject_tampering():
    t = sign({"login": "alice", "id": 1, "exp": time.time() + 60}, "s")
    assert verify(t, "s") == Visitor("alice", 1)
    head, body, mac = t.split(".")
    with pytest.raises(AuthError):
        verify(f"{head}.{body}x.{mac}", "s")
    with pytest.raises(AuthError):
        verify(t, "other")
    with pytest.raises(AuthError, match="expired"):
        verify(sign({"login": "a", "id": 1, "exp": time.time() - 1}, "s"), "s")


def test_quota_counts_per_account_per_day_with_a_site_ceiling(tmp_path):
    q = Quota(tmp_path, per_user=2, global_cap=3)
    day = datetime(2026, 10, 21, tzinfo=timezone.utc)
    alice, bob = Visitor("alice", 1), Visitor("bob", 2)
    assert q.take(alice, now=day) == 1 and q.take(alice, now=day) == 0
    with pytest.raises(QuotaExceeded) as exc:
        q.take(alice, now=day)
    assert exc.value.scope == "user"
    assert q.take(bob, now=day) == 1
    with pytest.raises(QuotaExceeded) as exc:
        q.take(bob, now=day)
    assert exc.value.scope == "global"
    assert q.take(alice, now=datetime(2026, 10, 22, tzinfo=timezone.utc)) == 1  # a new day

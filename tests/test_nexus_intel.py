from app.services import nexus_intel


def test_uid_mismatch():
    logs = {"u1": {"e1": {"report": {"uid": "u2", "ads_watched": 1, "page_context": "d", "session_duration": 10}, "received_at": "2026-01-01T00:00:00"}}}
    intel = nexus_intel.analyze_nexus(logs, {"u1": {"email": "a@a.com"}}, now=__import__("datetime").datetime(2026, 1, 2))
    assert any(f["code"] == "UID_MISMATCH" for f in intel["findings"])


def test_duplicate_cpf():
    users = {"u1": {"cpf": "123.456.789-00"}, "u2": {"cpf": "12345678900"}}
    intel = nexus_intel.analyze_nexus({}, users, now=__import__("datetime").datetime(2026, 1, 2))
    assert any(f["code"] == "DUPLICATE_CPF" for f in intel["findings"])


def test_activity_hash_invalid():
    logs = {"u1": {"e1": {"report": {"uid": "u1", "ads_watched": 1, "page_context": "d", "session_duration": 10, "activity_hash": "!!!"}, "received_at": "2026-01-01T00:00:00"}}}
    intel = nexus_intel.analyze_nexus(logs, {"u1": {}}, now=__import__("datetime").datetime(2026, 1, 2))
    assert any(f["code"] == "ACTIVITY_HASH_INVALID" for f in intel["findings"])


def test_orphan_report():
    logs = {"u9": {"e1": {"report": {"uid": "u9", "ads_watched": 1, "page_context": "d", "session_duration": 10}, "received_at": "2026-01-01T00:00:00"}}}
    intel = nexus_intel.analyze_nexus(logs, {"u1": {}}, now=__import__("datetime").datetime(2026, 1, 2))
    assert any(f["code"] == "ORPHAN_REPORT" for f in intel["findings"])


def test_audit_balance_mismatch_and_withdrawal():
    now = __import__("datetime").datetime(2026, 1, 2)
    logs = {"u1": {"e1": {"report": {"uid": "u1", "ads_watched": 5, "page_context": "d", "session_duration": 10, "balance": 1.00}, "received_at": "2026-01-01T12:00:00"}}}
    intel = nexus_intel.analyze_nexus(logs, {"u1": {"balance": 2.00, "videosWatched": 3}}, now=now)
    audit = nexus_intel.audit_financial_consistency(intel, {"u1": {"balance": 2.00, "videosWatched": 3}}, {"w1": {"uid": "u1", "amount": 5.00}}, now=now)
    assert any(f["code"] == "REPORT_AHEAD_OF_LEDGER" for f in audit["findings"])
    assert any(f["code"] == "WITHDRAWAL_EXCEEDS_BALANCE" for f in audit["findings"])


def test_action_plan_blocks():
    now = __import__("datetime").datetime(2026, 1, 2)
    logs = {"u1": {"e1": {"report": {"uid": "u1", "ads_watched": 1, "page_context": "d", "session_duration": 10}, "received_at": "2026-01-01T00:00:00"}}}
    users = {"u1": {"cpf": "111"}, "u2": {"cpf": "111"}}
    intel = nexus_intel.analyze_nexus(logs, users, now=now)
    audit = nexus_intel.audit_financial_consistency(intel, users, {}, now=now)
    plan = nexus_intel.build_action_plan(intel, audit, {"pending_count": 0}, now=now)
    assert plan["actions"]
    assert any("BLOCK_ACCOUNT_PENDING_REVIEW" in a["actions"] for a in plan["actions"])

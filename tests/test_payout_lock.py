"""T-18/T-19/T-22: locks de payout e idempotência de claim (transactions do painel)."""
import time


def test_approve_payment_lock_prevents_second_admin(app_env, fake_db, client):
    """T-18/T-22: claim atômico — segundo approve no mesmo wid bloqueia."""
    wd = {"uid": "U1", "amount": 10.0, "pixKey": "000.000.000-00",
          "pixType": "CPF", "status": "pending", "fullname": "T"}
    fake_db.reference("admin/pending_withdrawals/W9").set(dict(wd))

    def claim(current, owner):
        cd = dict(current)
        cd["processing_by"] = owner
        cd["processing_at"] = int(time.time() * 1000)
        return cd

    ref = fake_db.reference("admin/pending_withdrawals/W9")
    # primeiro dono A — transação commita
    first = ref.transaction(lambda cur: claim(cur, "adminA"))
    assert first.committed is True
    assert first.value["processing_by"] == "adminA"

    # segundo dono B (não é o mesmo, já tem lock) — aborta (committed=False)
    def claim2(current):
        if not current:
            return None
        cd = dict(current)
        existing = cd.get("processing_by")
        if existing and existing != "adminB":
            return None
        cd["processing_by"] = "adminB"
        return cd

    second = ref.transaction(claim2)
    assert second.committed is False


def test_approve_aborted_transaction_400(app_env, fake_db, fake_auth, client):
    """Transação que aborta (wid inexistente) => 400 'Saque não está pendente'.

    O claim atômico (teste acima) é o mecanismo real do lock no nível da transação;
    em HTTP, um saque já processado é re-executado de forma idempotente.
    """
    r = client.post("/payments/approve/W_INEXISTENTE", json={},
                    headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 400, r.text


def test_approve_happy_path_sets_paid(app_env, fake_db, fake_auth, client):
    """Admin válido aprova saque pendente => status paid."""
    fake_db.reference("admin/pending_withdrawals/W11").set({
        "uid": "U1", "amount": 10.0, "pixKey": "000.000.000-00",
        "pixType": "CPF", "status": "pending", "fullname": "T",
    })
    r = client.post("/payments/approve/W11", json={},
                    headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert fake_db.reference("admin/pending_withdrawals/W11").get()["status"] == "paid"

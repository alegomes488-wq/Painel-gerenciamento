import copy
import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.core.config import settings
from app.routers import payments, projects
from app.services.asaas_service import process_asaas_pix


class FakeTransactionReference:
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def transaction(self, callback):
        updated = callback(copy.deepcopy(self.value))
        self.value = updated
        return copy.deepcopy(updated)


class PaymentModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulation_is_default_and_never_opens_http_client(self):
        old_env, old_mode = settings.APP_ENV, settings.PAYMENTS_MODE
        settings.APP_ENV, settings.PAYMENTS_MODE = "development", "simulation"
        try:
            with patch("app.services.asaas_service.httpx.AsyncClient") as client:
                result = await process_asaas_pix(10, "key", "EVP", "test", "withdrawal-1")
            self.assertTrue(result["simulated"])
            self.assertTrue(result["id"].startswith("sim_"))
            client.assert_not_called()
        finally:
            settings.APP_ENV, settings.PAYMENTS_MODE = old_env, old_mode

    async def test_payment_mode_alone_cannot_enable_real_payment(self):
        old_env, old_mode = settings.APP_ENV, settings.PAYMENTS_MODE
        settings.APP_ENV, settings.PAYMENTS_MODE = "development", "production"
        try:
            with patch("app.services.asaas_service.httpx.AsyncClient") as client:
                result = await process_asaas_pix(10, "key", "EVP", "test", "withdrawal-2")
            self.assertTrue(result["simulated"])
            client.assert_not_called()
        finally:
            settings.APP_ENV, settings.PAYMENTS_MODE = old_env, old_mode


class TransactionTests(unittest.TestCase):
    def test_rejected_claim_does_not_delete_or_change_withdrawal(self):
        original = {"status": "processing", "processing_by": "other", "amount": 10}
        ref = FakeTransactionReference(original)
        with self.assertRaises(payments._TransactionAbort):
            payments._claim_withdrawal(ref, "admin")
        self.assertEqual(ref.value, original)

    def test_claim_and_release_use_explicit_idempotent_states(self):
        ref = FakeTransactionReference({"status": "pending", "amount": 10})
        claimed = payments._claim_withdrawal(ref, "admin")
        self.assertEqual(claimed["status"], "processing")
        payments._release_claim(ref, "admin")
        self.assertEqual(ref.value["status"], "pending")
        self.assertNotIn("processing_by", ref.value)


class SsrfTests(unittest.TestCase):
    def test_blocks_loopback_private_link_local_and_metadata(self):
        blocked = (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/",
            "http://[::1]/",
        )
        for url in blocked:
            with self.subTest(url=url), self.assertRaises(projects.UnsafeTargetError):
                projects._validate_public_url(url)

    def test_all_resolved_addresses_must_be_public(self):
        answers = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.4", 443)),
        ]
        with patch("app.routers.projects.socket.getaddrinfo", return_value=answers):
            with self.assertRaises(projects.UnsafeTargetError):
                projects._validate_public_url("https://public.example/")


class RedirectSsrfTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_target_is_validated_before_second_request(self):
        class Response:
            status_code = 302
            headers = {"location": "http://127.0.0.1/admin"}
            url = "https://93.184.216.34/start"

        class Client:
            calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, *args, **kwargs):
                self.calls += 1
                return Response()

        client = Client()
        with patch("app.routers.projects.httpx.AsyncClient", return_value=client):
            with self.assertRaises(projects.UnsafeTargetError):
                await projects._probe("https://93.184.216.34/start", "website")
        self.assertEqual(client.calls, 1)


class CorsTests(unittest.TestCase):
    def test_preflight_reaches_cors_before_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        response = TestClient(app).options(
            "/api/project/analyze",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()

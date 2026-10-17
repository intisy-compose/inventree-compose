import unittest
from unittest import mock

from inventory import settings
from inventory.api import ApiError, UnreachableError

CONFIG = {"INVENTREE_HOST": "inventree.example.ts.net", "INVENTREE_ADMIN_USER": "admin", "INVENTREE_ADMIN_PASSWORD": "secret"}


class ConnectTest(unittest.TestCase):
    def connect_with(self, client_factory):
        with mock.patch.object(settings, "read_config", return_value=CONFIG), \
                mock.patch.object(settings, "Client", side_effect=client_factory):
            return settings.connect()

    def test_uses_the_tailnet_name_when_it_answers(self):
        client = self.connect_with(lambda url, user, password: url)
        self.assertEqual(client, "https://inventree.example.ts.net")

    def test_falls_back_to_loopback_when_the_tailnet_name_is_unreachable(self):
        def factory(url, user, password):
            if "ts.net" in url:
                raise UnreachableError("getaddrinfo failed")
            return url
        self.assertEqual(self.connect_with(factory), "http://localhost:8441")

    def test_a_refused_login_does_not_fall_back(self):
        def factory(url, user, password):
            raise ApiError("GET /api/user/token/: HTTP 401")
        with self.assertRaisesRegex(ApiError, "401"):
            self.connect_with(factory)


if __name__ == "__main__":
    unittest.main()

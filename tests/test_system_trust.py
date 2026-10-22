"""The CLI verifies TLS with the OS trust store before doing anything else."""

import ssl
import unittest
from unittest import mock

import truststore

from jev import cli


class SystemTrustStoreTests(unittest.TestCase):
    def test_main_enables_system_trust_store_before_loading_settings(self):
        with mock.patch.object(cli, "use_system_trust_store", side_effect=SystemExit(0)) as trust, \
             mock.patch.object(cli, "load_dotenv") as dotenv:
            with self.assertRaises(SystemExit):
                cli.main(["--help"])
        trust.assert_called_once_with()
        dotenv.assert_not_called()

    def test_new_ssl_contexts_verify_with_the_system_store(self):
        try:
            cli.use_system_trust_store()
            self.assertIsInstance(ssl.create_default_context(), truststore.SSLContext)
        finally:
            truststore.extract_from_ssl()


if __name__ == "__main__":
    unittest.main()

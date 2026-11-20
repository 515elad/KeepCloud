"""detect-secrets plugin: finds KeepAir gateway tokens (SEC-22).

The token format (kair_ prefix, fixed length, checksum) exists so that a leaked
token is recognizable. This plugin makes the repository's secret scan do that.
"""

import re

from detect_secrets.plugins.base import RegexBasedDetector


class KeepAirTokenDetector(RegexBasedDetector):
    secret_type = "KeepAir Gateway Token"  # noqa: S105  # pragma: allowlist secret

    denylist = (re.compile(r"kair_[0-9A-Za-z]{43}_[0-9A-Za-z]{6}"),)

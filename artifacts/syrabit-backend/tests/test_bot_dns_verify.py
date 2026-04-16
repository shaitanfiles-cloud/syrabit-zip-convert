from unittest.mock import MagicMock, patch

from utils import _do_rdns_verify


def _mock_resolve(mapping):
    def resolver(name, rdtype, lifetime=None):
        key = (str(name), rdtype)
        if key not in mapping:
            import dns.resolver
            raise dns.resolver.NXDOMAIN()
        records = mapping[key]
        answers = []
        for r in records:
            m = MagicMock()
            m.__str__ = lambda self, _r=r: _r
            answers.append(m)
        return answers
    return resolver


class TestDoRdnsVerify:
    def test_valid_googlebot(self):
        mapping = {
            ("1.66.249.66.in-addr.arpa.", "PTR"): ["crawl-66-249-66-1.googlebot.com."],
            ("crawl-66-249-66-1.googlebot.com", "A"): ["66.249.66.1"],
        }
        with patch("dns.resolver.resolve", side_effect=_mock_resolve(mapping)):
            assert _do_rdns_verify("66.249.66.1", "googlebot") is True

    def test_hostname_mismatch(self):
        mapping = {
            ("1.66.249.66.in-addr.arpa.", "PTR"): ["evil.example.com."],
        }
        with patch("dns.resolver.resolve", side_effect=_mock_resolve(mapping)):
            assert _do_rdns_verify("66.249.66.1", "googlebot") is False

    def test_forward_ip_mismatch(self):
        mapping = {
            ("1.66.249.66.in-addr.arpa.", "PTR"): ["crawl-66-249-66-1.googlebot.com."],
            ("crawl-66-249-66-1.googlebot.com", "A"): ["1.2.3.4"],
        }
        with patch("dns.resolver.resolve", side_effect=_mock_resolve(mapping)):
            assert _do_rdns_verify("66.249.66.1", "googlebot") is False

    def test_ipv6_aaaa_match(self):
        mapping = {
            ("1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.", "PTR"): ["crawl-v6.googlebot.com."],
            ("crawl-v6.googlebot.com", "A"): ["1.2.3.4"],
            ("crawl-v6.googlebot.com", "AAAA"): ["2001:db8::1"],
        }
        with patch("dns.resolver.resolve", side_effect=_mock_resolve(mapping)):
            assert _do_rdns_verify("2001:db8::1", "googlebot") is True

    def test_unknown_bot_key(self):
        assert _do_rdns_verify("66.249.66.1", "unknownbot") is False

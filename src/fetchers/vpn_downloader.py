from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.parse import quote

import requests

try:
    from Crypto.Cipher import AES
except Exception:  # pragma: no cover
    AES = None

try:
    from curl_cffi import requests as curl_requests  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    curl_requests = None


@dataclass
class VPNConfig:
    enabled: bool
    base_url: str
    prefix: str
    ticket: str
    ticket_cookie_name: str
    route: str
    extra_cookies: str
    cookie_header: str
    referer: str
    user_agent: str
    accept: str
    sec_fetch_dest: str
    sec_fetch_mode: str
    sec_fetch_site: str
    use_curl_cffi: bool
    curl_impersonate: str
    ustc_encrypt_host: bool
    ustc_cipher_key: str
    probe_url: str
    timeout: int


class VPNDownloader:
    def __init__(self, cfg: VPNConfig):
        self.cfg = cfg
        self._use_curl = bool(self.cfg.use_curl_cffi and curl_requests is not None)
        curl_module: Any = curl_requests
        self.session: Any = curl_module.Session() if self._use_curl else requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.cfg.user_agent,
                "Accept": self.cfg.accept,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
                "Cache-Control": "max-age=0",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-CH-UA": '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"Windows"',
                "Sec-Fetch-Dest": self.cfg.sec_fetch_dest,
                "Sec-Fetch-Mode": self.cfg.sec_fetch_mode,
                "Sec-Fetch-Site": self.cfg.sec_fetch_site,
                "Sec-Fetch-User": "?1",
            }
        )
        self._activated = False

    @classmethod
    def from_env(cls) -> "VPNDownloader":
        cfg = VPNConfig(
            enabled=str(os.getenv("WEBVPN_ENABLED", "false")).lower() == "true",
            base_url=str(os.getenv("WEBVPN_BASE_URL", "")).strip().rstrip("/"),
            prefix=str(os.getenv("WEBVPN_PREFIX", "")).strip(),
            ticket=str(os.getenv("WEBVPN_TICKET", "")).strip(),
            ticket_cookie_name=str(os.getenv("WEBVPN_TICKET_COOKIE_NAME", "wengine_vpn_ticket")).strip()
            or "wengine_vpn_ticket",
            route=str(os.getenv("WEBVPN_ROUTE", "")).strip(),
            extra_cookies=str(os.getenv("WEBVPN_EXTRA_COOKIES", "")).strip(),
            cookie_header=str(os.getenv("WEBVPN_COOKIE_HEADER", "")).strip(),
            referer=str(os.getenv("WEBVPN_REFERER", "")).strip(),
            user_agent=str(
                os.getenv(
                    "WEBVPN_USER_AGENT",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
                )
            ).strip(),
            accept=str(
                os.getenv(
                    "WEBVPN_ACCEPT",
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                )
            ).strip(),
            sec_fetch_dest=str(os.getenv("WEBVPN_SEC_FETCH_DEST", "document")).strip() or "document",
            sec_fetch_mode=str(os.getenv("WEBVPN_SEC_FETCH_MODE", "navigate")).strip() or "navigate",
            sec_fetch_site=str(os.getenv("WEBVPN_SEC_FETCH_SITE", "same-origin")).strip() or "same-origin",
            use_curl_cffi=str(os.getenv("WEBVPN_USE_CURL_CFFI", "true")).lower() == "true",
            curl_impersonate=str(os.getenv("WEBVPN_CURL_IMPERSONATE", "chrome120")).strip() or "chrome120",
            ustc_encrypt_host=str(os.getenv("WEBVPN_USTC_ENCRYPT_HOST", "false")).lower() == "true",
            ustc_cipher_key=str(os.getenv("WEBVPN_USTC_CIPHER_KEY", "wrdvpnisthebest!")).strip() or "wrdvpnisthebest!",
            probe_url=str(os.getenv("WEBVPN_PROBE_URL", "")).strip(),
            timeout=max(8, int(os.getenv("WEBVPN_TIMEOUT", "25"))),
        )
        if cfg.use_curl_cffi and curl_requests is None:
            logging.warning("WEBVPN_USE_CURL_CFFI=true 但未安装 curl_cffi，回退 requests")
        return cls(cfg)

    def _session_get(self, url: str, **kwargs: Any):
        if self._use_curl:
            kwargs.setdefault("impersonate", self.cfg.curl_impersonate)
        return self.session.get(url, **kwargs)

    @property
    def is_enabled(self) -> bool:
        return self.cfg.enabled and bool(self.cfg.ticket)

    def _vpn_url(self, target_url: str) -> str:
        if not self.is_enabled:
            return target_url
        if self.cfg.prefix:
            return f"{self.cfg.prefix}{target_url}"

        # 针对常见高校 WebVPN（如 USTC）在未配置 prefix 时的默认映射
        if self.cfg.base_url:
            parsed = urlparse(target_url)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                path_q = parsed.path or "/"
                if parsed.query:
                    path_q = f"{path_q}?{parsed.query}"
                if "wvpn.ustc.edu.cn" in self.cfg.base_url:
                    if self.cfg.ustc_encrypt_host:
                        enc_url = self._ustc_encrypt_url(target_url)
                        if enc_url:
                            return enc_url
                    return f"{self.cfg.base_url}/{parsed.scheme}/{parsed.netloc}{path_q}"

        if self.cfg.base_url:
            encoded = quote(target_url, safe="")
            return f"{self.cfg.base_url}/proxy/{encoded}"
        return target_url

    def _ustc_encrypt_url(self, target_url: str) -> str:
        if AES is None:
            logging.warning("未安装 pycryptodome，USTC 域名加密 URL 回退为明文模式")
            return ""

        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""

        key_raw = (self.cfg.ustc_cipher_key or "wrdvpnisthebest!").encode("utf-8")
        if len(key_raw) != 16:
            logging.warning("WEBVPN_USTC_CIPHER_KEY 长度不是 16 字节，USTC 加密 URL 已跳过")
            return ""

        iv = key_raw
        cipher = AES.new(key_raw, AES.MODE_CFB, iv=iv, segment_size=128)
        encrypted_domain = cipher.encrypt(parsed.netloc.encode("utf-8")).hex()
        encoded_prefix = iv.hex() + encrypted_domain

        path_q = parsed.path or "/"
        if parsed.query:
            path_q = f"{path_q}?{parsed.query}"
        return f"{self.cfg.base_url}/{parsed.scheme}/{encoded_prefix}{path_q}"

    @staticmethod
    def _parse_cookie_string(raw: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for part in (raw or "").split(";"):
            seg = part.strip()
            if not seg or "=" not in seg:
                continue
            k, v = seg.split("=", 1)
            key = k.strip()
            val = v.strip()
            if key and val:
                cookies[key] = val
        return cookies

    def _build_cookies(self) -> dict[str, str] | None:
        if not self.is_enabled:
            return None
        cookies = self._parse_cookie_string(self.cfg.extra_cookies)
        if self.cfg.route:
            cookies["route"] = self.cfg.route
        cookies[self.cfg.ticket_cookie_name] = self.cfg.ticket
        return cookies or None

    def _build_cookie_header(self) -> str:
        if self.cfg.cookie_header:
            return self.cfg.cookie_header
        cookies = self._build_cookies() or {}
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def export_cookies(self) -> dict[str, str]:
        """导出当前会话可用的 cookie 字典（优先使用完整 cookie_header）。"""
        if self.cfg.cookie_header:
            return self._parse_cookie_string(self.cfg.cookie_header)
        return self._build_cookies() or {}

    def build_vpn_url(self, target_url: str) -> str:
        """将目标 URL 转换为 VPN 可访问 URL。"""
        return self._vpn_url(target_url)

    def _build_headers_for_url(self, final_url: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        parsed = urlparse(final_url)
        if parsed.netloc:
            headers["Host"] = parsed.netloc
        if self.cfg.referer:
            headers["Referer"] = self.cfg.referer
        cookie_header = self._build_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def ensure_active(self) -> None:
        if not self.is_enabled or self._activated:
            return

        cookies = self._build_cookies()
        probe = self.cfg.probe_url or self.cfg.base_url
        if not probe:
            self._activated = True
            return

        try:
            self._session_get(
                probe,
                cookies=cookies,
                headers=self._build_headers_for_url(probe),
                timeout=self.cfg.timeout,
            )
            self._activated = True
        except Exception as exc:
            logging.warning("WebVPN 探活失败，将继续按需请求: %s", exc)

    def get(self, url: str, *, via_vpn: bool = False, extra_headers: dict[str, str] | None = None) -> requests.Response:
        cookies = self._build_cookies()
        final_url = self._vpn_url(url) if via_vpn else url
        headers = self._build_headers_for_url(final_url) if via_vpn else {}
        if extra_headers:
            headers.update({k: v for k, v in extra_headers.items() if v})
        if not headers:
            headers = None
        return self._session_get(final_url, cookies=cookies, headers=headers, timeout=self.cfg.timeout, allow_redirects=True)

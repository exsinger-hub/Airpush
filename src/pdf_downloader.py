from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from typing import cast
from urllib.parse import urljoin

import requests
from src.fetchers.vpn_downloader import VPNDownloader

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    sync_playwright = None


class PDFDownloader:
    def __init__(self, out_dir: str = "data/pdfs", timeout: int = 25):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = max(8, int(timeout))
        self.vpn = VPNDownloader.from_env()
        self.vpn.ensure_active()
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        )
        self.elsevier_api_key = str(os.getenv("ELSEVIER_API_KEY", "")).strip()
        self.playwright_fallback = str(os.getenv("WEBVPN_PLAYWRIGHT_FALLBACK", "true")).lower() == "true"
        self.playwright_headless = str(os.getenv("WEBVPN_PLAYWRIGHT_HEADLESS", "true")).lower() == "true"
        self.playwright_timeout_ms = max(15000, int(os.getenv("WEBVPN_PLAYWRIGHT_TIMEOUT_MS", "45000")))

    @staticmethod
    def _safe_name(text: str, max_len: int = 80) -> str:
        s = re.sub(r"[^\w\-.]+", "_", str(text or "paper").strip(), flags=re.UNICODE)
        s = s.strip("_.") or "paper"
        return s[:max_len]

    @staticmethod
    def _guess_pdf_url(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        lu = u.lower()
        if lu.endswith(".pdf"):
            return u
        if "arxiv.org/abs/" in lu:
            return re.sub(r"/abs/", "/pdf/", u).rstrip("/") + ".pdf"
        if "openreview.net/forum?id=" in lu:
            return u.replace("/forum?id=", "/pdf?id=")
        return ""

    def _request(self, url: str, *, extra_headers: dict[str, str] | None = None) -> requests.Response:
        lower_url = url.lower()
        is_elsevier = any(k in lower_url for k in ["elsevier.com", "sciencedirect.com", "api.elsevier.com"])

        if self.vpn.is_enabled and any(
            k in lower_url
            for k in [
                "sciencedirect.com",
                "elsevier.com",
                "linkinghub.elsevier.com",
                "springer",
                "wiley",
                "ieeexplore",
                "nature.com",
            ]
        ):
            return self.vpn.get(url, via_vpn=True, extra_headers=extra_headers)

        headers = {"User-Agent": self.user_agent}
        if extra_headers:
            headers.update({k: v for k, v in extra_headers.items() if v})
        if self.elsevier_api_key and is_elsevier:
            headers["X-ELS-APIKey"] = self.elsevier_api_key
        cookies: dict[str, str] | None = None
        token = str(os.getenv("OPENREVIEW_ACCESS_TOKEN", "")).strip()
        if token and "openreview.net" in lower_url:
            cookies = {"openreview.accessToken": token}
        return requests.get(url, headers=headers, cookies=cookies, timeout=self.timeout, allow_redirects=True)

    def _is_pdf_response(self, resp: requests.Response) -> bool:
        ctype = str(resp.headers.get("content-type", "")).lower()
        if "application/pdf" in ctype:
            return True
        if str(resp.url or "").lower().endswith(".pdf"):
            return True
        return (resp.content or b"")[:4] == b"%PDF"

    def _extract_pdf_from_html(self, html: str, base_url: str) -> str:
        # 常见元信息
        m = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
        if m:
            return urljoin(base_url, m.group(1).strip())

        # Elsevier LinkingHub 等页面常见的 meta refresh 跳转
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\'][^"\']*url=["\']?([^"\' >]+)',
            html,
            flags=re.I,
        )
        if m:
            refresh_url = m.group(1).strip().replace("&amp;", "&")
            return urljoin(base_url, refresh_url)

        # 常见链接模式
        patterns = [
            r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
            r'href=["\']([^"\']*/pdf/[^"\']*)["\']',
            r'href=["\']([^"\']*download[^"\']*\.pdf[^"\']*)["\']',
        ]
        for p in patterns:
            m = re.search(p, html, flags=re.I)
            if m:
                return urljoin(base_url, m.group(1).strip())
        return ""

    def _extract_publisher_pdf(self, html: str, page_url: str) -> str:
        host = page_url.lower()

        if "sciencedirect.com" in host:
            m = re.search(r'href=["\']([^"\']*(?:/pdf|/pdfft)[^"\']*)["\']', html, flags=re.I)
            if m:
                return urljoin(page_url, m.group(1))

        if "springer" in host:
            m = re.search(r'href=["\']([^"\']*content/pdf/[^"\']+\.pdf[^"\']*)["\']', html, flags=re.I)
            if m:
                return urljoin(page_url, m.group(1))

        if "wiley" in host:
            m = re.search(r'href=["\']([^"\']*(?:/doi/pdf|/pdfdirect)[^"\']*)["\']', html, flags=re.I)
            if m:
                return urljoin(page_url, m.group(1))

        if "ieeexplore" in host:
            m = re.search(r'"pdfPath"\s*:\s*"([^"]+)"', html, flags=re.I)
            if m:
                return urljoin("https://ieeexplore.ieee.org", m.group(1))

        return ""

    @staticmethod
    def _extract_elsevier_pii(*texts: str) -> str:
        patterns = [
            r"/pii/([A-Z0-9]{8,30})",
            r"\bpii=([A-Z0-9]{8,30})\b",
            r'"pii"\s*:\s*"([A-Z0-9]{8,30})"',
            r"\b(S[0-9A-Z]{8,30})\b",
        ]
        for text in texts:
            if not text:
                continue
            for p in patterns:
                m = re.search(p, text, flags=re.I)
                if m:
                    return m.group(1).upper()
        return ""

    @staticmethod
    def _build_elsevier_pdfft_url(pii: str) -> str:
        return f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true"

    @staticmethod
    def _build_elsevier_article_url(pii: str) -> str:
        return f"https://www.sciencedirect.com/science/article/pii/{pii}"

    def _extract_redirect_url_from_html(self, html: str, base_url: str) -> str:
        # meta refresh
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\'][^"\']*url=["\']?([^"\' >]+)',
            html,
            flags=re.I,
        )
        if m:
            return urljoin(base_url, m.group(1).strip().replace("&amp;", "&"))

        # window.location / location.replace
        m = re.search(r"(?:window\.)?location(?:\.href|\.replace)?\s*\(?\s*[\"']([^\"']+)[\"']", html, flags=re.I)
        if m:
            return urljoin(base_url, m.group(1).strip().replace("&amp;", "&"))

        # iframe 容器页
        m = re.search(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.I)
        if m:
            return urljoin(base_url, m.group(1).strip().replace("&amp;", "&"))

        # 兜底：抓第一个 pdf/pdfft 链接
        m = re.search(r'href=["\']([^"\']*(?:\.pdf|/pdfft)[^"\']*)["\']', html, flags=re.I)
        if m:
            return urljoin(base_url, m.group(1).strip().replace("&amp;", "&"))

        return ""

    @staticmethod
    def _is_challenge_html(html: str, url: str = "") -> bool:
        text = f"{url}\n{html}".lower()
        signals = [
            "cra_js_challenge",
            "datadome",
            "turnstile",
            "cf-challenge",
            "js_challenge",
        ]
        return any(s in text for s in signals)

    def _try_elsevier_pdfft(self, pii: str, article_url: str) -> requests.Response | None:
        if not pii:
            return None
        referer = article_url or self._build_elsevier_article_url(pii)
        headers = {
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Referer": referer,
            "Connection": "keep-alive",
        }
        candidates = [
            self._build_elsevier_pdfft_url(pii),
            f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft",
        ]

        for direct_url in candidates:
            resp = self._request(direct_url, extra_headers=headers)
            resp.raise_for_status()
            if self._is_pdf_response(resp):
                return resp

            ctype = str(resp.headers.get("content-type", "")).lower()
            if "text/html" not in ctype:
                continue
            lower_html = resp.text.lower()
            if "cra_js_challenge" in lower_html:
                pw = self._playwright_capture_pdf(direct_url, referer=referer)
                if pw is not None:
                    content, final_url = pw
                    fake = requests.Response()
                    fake.status_code = 200
                    fake._content = content
                    fake.url = final_url or direct_url
                    fake.headers["content-type"] = "application/pdf"
                    return fake

            redirect_url = self._extract_redirect_url_from_html(resp.text, str(resp.url or direct_url))
            if not redirect_url:
                continue
            resp2 = self._request(redirect_url, extra_headers=headers)
            resp2.raise_for_status()
            if self._is_pdf_response(resp2):
                return resp2
            ctype2 = str(resp2.headers.get("content-type", "")).lower()
            if "text/html" in ctype2 and "cra_js_challenge" in resp2.text.lower():
                pw2 = self._playwright_capture_pdf(redirect_url, referer=referer)
                if pw2 is not None:
                    content2, final_url2 = pw2
                    fake2 = requests.Response()
                    fake2.status_code = 200
                    fake2._content = content2
                    fake2.url = final_url2 or redirect_url
                    fake2.headers["content-type"] = "application/pdf"
                    return fake2
        return None

    def _playwright_capture_pdf(self, target_url: str, *, referer: str = "") -> tuple[bytes, str] | None:
        if not self.playwright_fallback:
            return None
        if sync_playwright is None:
            logging.warning("未安装 playwright，无法执行 JS challenge 回退")
            return None
        if not self.vpn.is_enabled:
            return None

        try:
            final_url = self.vpn.build_vpn_url(target_url)
            cookies = self.vpn.export_cookies()
            if not cookies:
                return None

            captured: dict[str, Any] = {"body": None, "url": ""}

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.playwright_headless)
                context = browser.new_context(user_agent=self.user_agent)

                cookie_items: list[dict[str, Any]] = [
                    {"name": k, "value": v, "domain": "wvpn.ustc.edu.cn", "path": "/"}
                    for k, v in cookies.items()
                    if k and v
                ]
                if cookie_items:
                    context.add_cookies(cast(Any, cookie_items))

                page = context.new_page()

                def handle_response(resp):
                    ctype = str(resp.headers.get("content-type", "")).lower()
                    if "application/pdf" in ctype and captured["body"] is None:
                        captured["body"] = resp.body()
                        captured["url"] = resp.url

                page.on("response", handle_response)
                goto_headers = {"Accept": "application/pdf,application/octet-stream,*/*"}
                if referer:
                    goto_headers["Referer"] = self.vpn.build_vpn_url(referer)
                page.goto(final_url, wait_until="networkidle", timeout=self.playwright_timeout_ms, referer=goto_headers.get("Referer"))
                if captured["body"] is None:
                    page.wait_for_timeout(5000)

                page.close()
                context.close()
                browser.close()

            if captured["body"]:
                return captured["body"], str(captured["url"] or final_url)
        except Exception as exc:
            logging.debug("Playwright PDF 回退失败 url=%s err=%s", target_url, exc)
        return None

    def _candidate_urls(self, paper: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("pdf_url", "url"):
            v = str(paper.get(key, "") or "").strip()
            if v:
                urls.append(v)
                guessed = self._guess_pdf_url(v)
                if guessed:
                    urls.append(guessed)

        doi = str(paper.get("doi", "") or "").strip()
        if doi:
            urls.append(f"https://doi.org/{doi}")

        # 去重保序
        seen: set[str] = set()
        uniq: list[str] = []
        for u in urls:
            if u and u not in seen:
                uniq.append(u)
                seen.add(u)
        return uniq

    def download_for_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        paper_id = self._safe_name(str(paper.get("id", "paper")))
        title = self._safe_name(str(paper.get("title", "paper")), max_len=60)
        filename = f"{paper_id}_{title}.pdf"
        file_path = self.out_dir / filename

        if file_path.exists() and file_path.stat().st_size > 0:
            return {
                **paper,
                "pdf_local_path": str(file_path),
                "pdf_downloaded": True,
            }

        hit_js_challenge = False
        last_error = ""
        failure_reason = "download_failed"

        for u in self._candidate_urls(paper):
            try:
                resp = self._request(u)
                resp.raise_for_status()

                if self._is_pdf_response(resp):
                    file_path.write_bytes(resp.content)
                    return {
                        **paper,
                        "pdf_url": str(resp.url or u),
                        "pdf_local_path": str(file_path),
                        "pdf_downloaded": True,
                    }

                html = resp.text if "text/html" in str(resp.headers.get("content-type", "")).lower() else ""
                if html:
                    if self._is_challenge_html(html, str(resp.url or u)):
                        hit_js_challenge = True
                        failure_reason = "js_challenge"
                        break

                    lower_resp_url = str(resp.url or u).lower()
                    # Elsevier 深水区：只做一次 PII 直链尝试，不纠缠
                    if any(k in lower_resp_url for k in ["elsevier", "sciencedirect", "linkinghub"]):
                        pii = self._extract_elsevier_pii(str(resp.url or ""), u, html)
                        if pii:
                            article_url = self._build_elsevier_article_url(pii)
                            resp_direct = self._try_elsevier_pdfft(pii, article_url)
                            if resp_direct is not None and self._is_pdf_response(resp_direct):
                                file_path.write_bytes(resp_direct.content)
                                return {
                                    **paper,
                                    "pdf_url": str(resp_direct.url or article_url),
                                    "pdf_local_path": str(file_path),
                                    "pdf_downloaded": True,
                                }
                        failure_reason = "non_pdf_html"
                        break

                    pdf_url = self._extract_pdf_from_html(html, str(resp.url or u))
                    if not pdf_url:
                        pdf_url = self._extract_publisher_pdf(html, str(resp.url or u))
                    if pdf_url:
                        resp2 = self._request(pdf_url)
                        resp2.raise_for_status()
                        if self._is_pdf_response(resp2):
                            file_path.write_bytes(resp2.content)
                            return {
                                **paper,
                                "pdf_url": str(resp2.url or pdf_url),
                                "pdf_local_path": str(file_path),
                                "pdf_downloaded": True,
                            }
                        html2 = resp2.text if "text/html" in str(resp2.headers.get("content-type", "")).lower() else ""
                        if html2 and self._is_challenge_html(html2, str(resp2.url or pdf_url)):
                            hit_js_challenge = True
                            failure_reason = "js_challenge"
                            break
                        if html2 and any(
                            k in str(resp2.url or pdf_url).lower() for k in ["elsevier", "sciencedirect", "linkinghub"]
                        ):
                            pii2 = self._extract_elsevier_pii(str(resp2.url or ""), pdf_url, html2)
                            if pii2:
                                article_url2 = self._build_elsevier_article_url(pii2)
                                resp_direct2 = self._try_elsevier_pdfft(pii2, article_url2)
                                if resp_direct2 is not None and self._is_pdf_response(resp_direct2):
                                    file_path.write_bytes(resp_direct2.content)
                                    return {
                                        **paper,
                                        "pdf_url": str(resp_direct2.url or article_url2),
                                        "pdf_local_path": str(file_path),
                                        "pdf_downloaded": True,
                                    }
                            failure_reason = "non_pdf_html"
                            break
            except Exception as exc:
                last_error = str(exc)
                logging.debug("PDF 下载失败 id=%s url=%s err=%s", paper.get("id", "unknown"), u, exc)

        return {
            **paper,
            "pdf_downloaded": False,
            "pdf_failure_reason": "js_challenge" if hit_js_challenge else failure_reason,
            "manual_fulltext_required": bool(hit_js_challenge),
            "pdf_error": last_error[:300] if last_error else "",
        }

    def download_batch(self, papers: list[dict[str, Any]], top_k: int = 3) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in papers[: max(1, top_k)]:
            out.append(self.download_for_paper(p))
        return out

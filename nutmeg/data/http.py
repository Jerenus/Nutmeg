"""抓取的公共件（2026-10-08 第二轮瘦身 B5）：浏览器 UA / 请求头、按编码解码、GET 文本与 JSON。

此前体彩、titan007、500.com、官方奖金页各自抄一份 UA（Chrome 124 / 126 / 126.0.0.0 三种写法）
与解码逻辑。体彩 WAF 拦非浏览器 UA（2026-07-04 起 "Nutmeg/0.2" 稳定 403），整套头须像浏览器。
单测一律注入 fetcher / transport，这里只放真网络的默认实现。
"""
from __future__ import annotations

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 Mobile/15E148")
"""okooo 移动开奖页只认移动端 UA。"""
SPORTTERY_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.sporttery.cn",
}
SPORTTERY_REFERER = "https://www.sporttery.cn/"


def browser_headers(referer: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": BROWSER_UA}
    if referer:
        headers["Referer"] = referer
    return headers


def decode(body: bytes, encodings: tuple[str, ...] = ("utf-8",), *,
           errors: str = "strict") -> str:
    """依次按 `encodings` 严格解码，第一个成功的为准；都失败时用最后一个编码按 `errors` 解。

    titan007 必须全程 strict（宽松解码会在 `^` 分隔符处错位、凭空吞掉字段）；
    500.com / okooo 的国标页历来按 `errors="ignore"` / `"replace"` 解。"""
    for encoding in encodings[:-1]:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode(encodings[-1], errors=errors)


def get_text(url: str, *, referer: str | None = None, encodings: tuple[str, ...] = ("utf-8",),
             errors: str = "strict", timeout: float = 20.0) -> str:
    """GET（跟随跳转，浏览器 UA）→ 按 `decode` 解码的正文；HTTP 错误抛 httpx.HTTPError。"""
    import httpx

    response = httpx.get(url, headers=browser_headers(referer), timeout=timeout,
                         follow_redirects=True)
    response.raise_for_status()
    return decode(response.content, encodings, errors=errors)


def get_json(url: str, *, headers: dict[str, str] | None = None, referer: str | None = None,
             timeout: float = 20.0):
    """GET → JSON。`headers` 缺省为浏览器 UA（+ Referer）；HTTP 错误抛 httpx.HTTPError，
    非 JSON 抛 ValueError。"""
    import httpx

    sent = dict(headers) if headers is not None else browser_headers()
    if referer:
        sent["Referer"] = referer
    response = httpx.get(url, headers=sent, timeout=timeout)
    response.raise_for_status()
    return response.json()

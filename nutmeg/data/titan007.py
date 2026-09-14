"""球探网 007（titan007）数据源 —— 竞彩板面 + 国际欧赔。

退役背景：国际欧赔原走 API-Football（``services/jczq_apifootball_odds``）。该源
Free 档 100 次/天，2026-09-14 实测板面覆盖率仅 6/10；且其基础 ``/odds`` **不含开赛
前 opening 赔率**，故 drift 信号对全部场次恒为 0。

titan007 用两个免费无配额端点同时解掉三件事：

1. ``jc.titan007.com/xml/bf_jc.txt`` —— 当日竞彩板面，**自带竞彩编号 ↔ 007 match id**
   映射（2026-09-14 实测 10/10 逐字对齐）。因此本源**不需要任何中文→英文别名表**、
   不需要 UTC 跨日换算、不需要 fixture 池模糊匹配。
2. ``1x2d.titan007.com/{match_id}.js`` —— 该场 152 家博彩的 **初赔 + 即时赔**，含
   Pinnacle / Crown / Macauslot / IBCBET / Sbobet 等去水锚要的锐盘。

两个端点都是 **UTF-8**（欧赔 JS 带 BOM，板面不带）；欧赔 JS 另需欧指列表页 Referer
才正常返回。站点 HTML 页的 ``<meta charset>`` 写的是 gb2312，会诱导人按 GBK 解——
**别信**：这两个数据端点实测 UTF-8 strict 可解。按 GBK + ``errors="replace"`` 解会
静默错位（GBK 尾字节范围含 ``0x5E``，正是 ``^`` 分隔符），实测把板面 10 行的字段数
从整齐的 24 撕成 ``{24:5, 23:4, 22:1}``，且队名全成乱码。

**绝不猜测 / 绝不假空盘**：解析拿不到最小规模数据一律 ``raise
Titan007ParseError``，由调用方决定降级——从不返回空值冒充「今天没有盘」。那正是
2026-06 WAF 降级响应覆盖完好快照的死法。

本模块零业务语义：不做去水、不判断哪些书可信、不碰体彩盘。那些住在
``services/jczq_titan007_odds``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import httpx

__all__ = [
    "Titan007BoardRow",
    "Titan007BookQuote",
    "Titan007Client",
    "Titan007Error",
    "Titan007ParseError",
    "parse_board",
    "parse_euro_odds",
]

_BOARD_URL = "http://jc.titan007.com/xml/bf_jc.txt"
_EURO_URL_TEMPLATE = "http://1x2d.titan007.com/{match_id}.js"
_BOARD_REFERER = "http://jc.titan007.com/"
_EURO_REFERER = "http://odds.titan007.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 板面行实测恒 24 字段；欧赔行实测恒 27 字段。字段数不符 = 站点改版，宁可炸不可猜。
_BOARD_FIELD_COUNT = 24
_EURO_FIELD_COUNT = 27

# 解析结果低于此规模视为降级响应（WAF / 错误页 / 半截内容）。
_MIN_BOARD_ROWS = 1
_MIN_EURO_ROWS = 5

_RE_EURO_GAME_ARRAY = re.compile(r"game=Array\((.*?)\);", re.S)
_RE_EURO_ROW = re.compile(r'"([^"]*)"')


class Titan007Error(RuntimeError):
    """titan007 抓取失败（网络/HTTP）。"""


class Titan007ParseError(Titan007Error):
    """titan007 响应无法解析或规模不足——降级响应，绝不当作空盘。"""


@dataclass(frozen=True, slots=True)
class Titan007BoardRow:
    """板面一行：竞彩编号 ↔ titan007 match id 的权威映射。

    ``kickoff`` 是**北京时间 naive datetime**，与体彩 ``matchDate``+``matchTime``
    同一时区口径，可直接比对（对齐守卫用）。
    """

    match_id: str
    match_no: str
    kickoff: datetime
    home_names: tuple[str, ...]
    away_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Titan007BookQuote:
    """一家博彩对一场的报价：初赔 + 即时赔，键 ``home``/``draw``/``away``。"""

    company_id: str
    company_name: str
    opening: dict[str, float]
    current: dict[str, float]
    updated_at: datetime | None


def _parse_titan_datetime(raw: str) -> datetime | None:
    """解 titan007 的 JS Date 风格时间串。

    两种实测形态，月份都是 **0 起**（JS ``Date`` 口径）：

    - 开球：``2026,8,14,23,00,00``      → 2026-09-14 23:00:00
    - 更新：``2026,09-1,13,23,28,00``   → 2026-09-13 23:28:00

    第二种的月份位是字面量算式 ``09-1``，同样求值为 0 起月份。无法解析返回
    ``None``（调用方按缺失处理，绝不猜）。
    """
    parts = [p.strip() for p in (raw or "").split(",")]
    if len(parts) != 6:
        return None
    month_token = parts[1]
    try:
        if "-" in month_token:
            left, right = month_token.split("-", 1)
            month_zero_based = int(left) - int(right)
        else:
            month_zero_based = int(month_token)
        return datetime(
            year=int(parts[0]),
            month=month_zero_based + 1,
            day=int(parts[2]),
            hour=int(parts[3]),
            minute=int(parts[4]),
            second=int(parts[5]),
        )
    except (TypeError, ValueError):
        return None


def _names(raw: str) -> tuple[str, ...]:
    """``简,繁,别名`` → 去空去重（保序）的名字元组。"""
    seen: dict[str, None] = {}
    for part in (raw or "").split(","):
        name = part.strip()
        if name:
            seen.setdefault(name, None)
    return tuple(seen)


def parse_board(text: str) -> list[Titan007BoardRow]:
    """解 ``bf_jc.txt`` → 板面行。

    形状 ``<联赛块>$<场次>!<场次>!…``；场次 24 字段，关键位：

    ===== ==========================================
    下标   含义
    ===== ==========================================
    0      titan007 match id
    1      开球时间（北京，0 起月份）
    4      **竞彩编号**（``周一002``）
    8      主队名 ``简,繁,别名``
    10     客队名 ``简,繁,别名``
    ===== ==========================================

    降级响应（无 ``$``、场次段空、字段数不符）一律 raise。
    """
    if "$" not in (text or ""):
        raise Titan007ParseError(
            "titan007 板面响应无 `$` 分隔符——疑似 WAF/错误页，拒绝当作空盘"
        )
    _, _, match_section = text.partition("$")
    rows: list[Titan007BoardRow] = []
    for chunk in match_section.split("!"):
        if not chunk.strip():
            continue
        fields = chunk.split("^")
        if len(fields) != _BOARD_FIELD_COUNT:
            raise Titan007ParseError(
                f"titan007 板面行字段数 {len(fields)} != {_BOARD_FIELD_COUNT}——疑似站点改版"
            )
        kickoff = _parse_titan_datetime(fields[1])
        match_no = fields[4].strip()
        if kickoff is None or not match_no:
            continue
        rows.append(
            Titan007BoardRow(
                match_id=fields[0].strip(),
                match_no=match_no,
                kickoff=kickoff,
                home_names=_names(fields[8]),
                away_names=_names(fields[10]),
            )
        )
    if len(rows) < _MIN_BOARD_ROWS:
        raise Titan007ParseError("titan007 板面解出 0 场——降级响应，拒绝当作空盘")
    return rows


_OUTCOME_KEYS = ("home", "draw", "away")


def _odds_triplet(fields: list[str], start: int) -> dict[str, float] | None:
    """取 ``fields[start:start+3]`` 为 home/draw/away 十进制赔率；任一不合法返回 None。"""
    out: dict[str, float] = {}
    for offset, key in enumerate(_OUTCOME_KEYS):
        try:
            value = float(fields[start + offset])
        except (TypeError, ValueError, IndexError):
            return None
        if value <= 1.0:
            return None
        out[key] = value
    return out


def parse_euro_odds(text: str) -> list[Titan007BookQuote]:
    """解 ``1x2d.titan007.com/{id}.js`` 的 ``game=Array(...)`` → 各家报价。

    行 27 字段，实测布局（2026-09-14，152/152 行一致）：

    ====== ==========================================
    下标    含义
    ====== ==========================================
    0       公司 id（稳定，按 id 筛选而非按名字）
    2       公司英文名
    3-5     **初赔** 主/平/客
    6-8     初赔去水概率 %（站点自算；本仓不用，用自己的 ``_devig``）
    9       初赔返还率 %
    10-12   **即时赔** 主/平/客
    13-15   即时去水概率 %
    16      即时返还率 %
    20      更新时间
    21      公司中文名
    ====== ==========================================

    字段 6-8 与 ``_devig(字段 3-5)`` 的一致性已实测 152/152 通过——可作解析自检的
    旁证，但本仓一律用自己的 ``_devig`` 保持全局口径统一。

    初赔或即时赔任一不合法的行直接跳过（不猜）。解出书目 < ``_MIN_EURO_ROWS``
    视为降级响应 → raise。
    """
    match = _RE_EURO_GAME_ARRAY.search(text or "")
    if match is None:
        raise Titan007ParseError(
            "titan007 欧赔响应无 `game=Array(...)`——疑似 WAF/错误页，拒绝当作无盘"
        )
    quotes: list[Titan007BookQuote] = []
    for raw_row in _RE_EURO_ROW.findall(match.group(1)):
        fields = raw_row.split("|")
        if len(fields) != _EURO_FIELD_COUNT:
            continue
        opening = _odds_triplet(fields, 3)
        current = _odds_triplet(fields, 10)
        if opening is None or current is None:
            continue
        quotes.append(
            Titan007BookQuote(
                company_id=fields[0].strip(),
                company_name=fields[2].strip(),
                opening=opening,
                current=current,
                updated_at=_parse_titan_datetime(fields[20]),
            )
        )
    if len(quotes) < _MIN_EURO_ROWS:
        raise Titan007ParseError(
            f"titan007 欧赔仅解出 {len(quotes)} 家（< {_MIN_EURO_ROWS}）——降级响应，拒绝当作无盘"
        )
    return quotes


class Titan007Client:
    """titan007 抓取器。GBK 解码 + 浏览器 UA + 各端点自己的 Referer。

    ``transport`` 注入用于测试（``httpx.MockTransport``），生产留空走真网络。
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )

    def __enter__(self) -> "Titan007Client":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get_text(self, url: str, *, referer: str) -> str:
        """抓一个端点并解码。

        响应只发 ``text/plain`` 不带 charset，httpx 会猜错，必须显式解。两个端点实测
        都是 UTF-8（欧赔带 BOM，``utf-8-sig`` 两者通吃）。

        **一律 strict**：宁可炸也不做有损解码。按 GBK/``errors="replace"`` 解会在非法
        字节处错位，而 GBK 尾字节范围覆盖 ``0x5E``（``^`` 分隔符），错位会凭空吞掉或
        伪造字段边界——实测把整齐的 24 字段撕成 ``{24:5, 23:4, 22:1}``。那种坏法不报
        错、只让下游拿到错数据，是最该避免的一类。gb18030 兜底留给站点未来真的改回
        国标编码，同样 strict。
        """
        try:
            response = self._client.get(url, headers={"Referer": referer})
        except httpx.HTTPError as exc:
            raise Titan007Error(f"titan007 抓取失败 {url}: {exc}") from exc
        if response.status_code != 200:
            raise Titan007Error(
                f"titan007 抓取失败 {url}: HTTP {response.status_code}"
            )
        body = response.content
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return body.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise Titan007ParseError(
            f"titan007 响应既非 UTF-8 也非 gb18030 {url}——疑似降级/二进制响应"
        )

    def fetch_board(self) -> list[Titan007BoardRow]:
        """当日竞彩板面（竞彩号 ↔ 007 id）。"""
        return parse_board(self._get_text(_BOARD_URL, referer=_BOARD_REFERER))

    def fetch_euro_odds(self, match_id: str) -> list[Titan007BookQuote]:
        """某场各家国际欧赔（初赔 + 即时赔）。"""
        url = _EURO_URL_TEMPLATE.format(match_id=match_id)
        return parse_euro_odds(self._get_text(url, referer=_EURO_REFERER))

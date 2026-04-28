# WeChat Draft Publisher Design

## Goal

Add a WeChat official account draft workflow for Nutmeg's JCZQ analysis. Each day, Nutmeg should turn the internal mixed-parlay report into a compliant, data-analysis style WeChat article, push it to the official account draft box, and leave final editing and publishing to the human operator.

The public article is not a betting recommendation. It is a football data column: two focus-match deep dives using public fixtures, official odds movement, team context, tactical variables, and uncertainty analysis.

## Confirmed Product Direction

- Article positioning: data-analysis type, not strong recommendation type.
- Daily scope: two focus matches.
- Article style: professional, restrained, similar to a football data column.
- Betting boundary: article may mention public odds and risk, but must not tell readers what to buy.
- Combination boundary: keep a low-key "combination observation" section that discusses risk overlap only.
- Publishing mode: push to WeChat draft box; never auto-publish in v1.

## Recommended Approach

Build a separate WeChat publisher layer on top of the existing JCZQ and content publisher foundations:

```text
jczq-mixed-report JSON
-> select two article-worthy matches
-> build WeChat-safe article content
-> enforce compliance and disclaimer gates
-> render local review artifacts
-> optionally create a WeChat draft
-> human review and manual publish in WeChat backend
```

This keeps betting-analysis generation, public copywriting, compliance checks, and platform API calls separate. It also preserves the current safety posture: external platform actions are explicit, auditable, and limited to drafts.

## Alternatives Considered

1. **Manual copy package only**: Generate Markdown/HTML and have the operator copy into WeChat. Lowest platform risk, but less efficient than the requested workflow.
2. **Draft box push**: Generate local artifacts and create a WeChat draft for human review. Recommended because it reduces copy/paste work without removing editorial control.
3. **Automatic publish**: Generate and publish directly. Rejected for v1 because sports-analysis content involving odds has compliance and platform-review risk.

## Article Template

Each article follows a stable two-match deep-dive structure:

```text
Title: Tonight's Two Focus Matches: Key Variables Behind Public Odds Movement

Intro:
- Explain data sources and scope.
- State that the article is public match analysis, not betting advice.
- Frame the day's core observation question.

Focus Match 1:
- Core question: what is the market or football problem worth examining?
- Variable 1: fundamentals, form, schedule pressure, home/away context.
- Variable 2: official odds structure and movement.
- Variable 3: squad and lineup uncertainty.
- Variable 4: tactical matchup, transition risk, set pieces, tempo.
- Variable 5: uncertainty and what could invalidate the read.

Focus Match 2:
- Same five-variable structure for consistency and reader habit.

Combination Observation:
- Discuss only risk overlap between the two matches.
- Avoid betting verbs, staking language, and guaranteed-outcome phrasing.

Closing Disclaimer:
- Public match information and data analysis only.
- Does not constitute betting advice.
- Match outcomes are uncertain; read rationally.
```

## Public Language Rules

Allowed phrasing:

- "公开赔率变化显示市场预期有所调整。"
- "这场的主要观察点是主队热度是否已经被充分计入。"
- "如果把两场放在同一观察框架里，风险主要来自热门热度、临场阵容和赔率波动。"
- "该方向具备观察价值，但仍受临场信息影响。"

Disallowed phrasing:

- "直接买主胜。"
- "稳胆 / 包红 / 必中 / 放心上。"
- "重仓 / 回血 / 跟单 / 私信拿单。"
- "高赔冲击 / 收费方案 / 保证收益。"

## Components

### Domain Models

Add WeChat-specific publisher models, likely under `nutmeg.domain.content` or a new narrow module:

- `WeChatArticlePack`: title, digest, author, content HTML, source URL, cover reference, selected matches, compliance result, artifact paths.
- `WeChatDraftPayload`: WeChat `articles` payload prepared for the draft API.
- `WeChatDraftResult`: draft `media_id`, timestamp, request metadata, and warnings.
- `WeChatConfig`: app ID, app secret reference, cover media ID, author, source URL, dry-run defaults.

### Services

- `JczqWechatMatchSelector`: chooses two focus matches from the JCZQ report using explainable criteria such as sellable status, attention score, odds movement, match importance, and analysis depth.
- `WeChatArticleBuilder`: converts selected matches and internal analysis into safe title, digest, Markdown, HTML, and draft payload.
- `WeChatComplianceGate`: reuses or extends existing content compliance checks for WeChat-specific rules.
- `WeChatDraftClient`: handles access token retrieval, optional token caching, permanent media expectations, and draft creation.
- `WeChatPublisherService`: orchestrates pack generation, artifact writes, compliance gate, and optional draft creation.

### CLI

Add two operator commands:

```bash
uv run nutmeg wechat-article-pack \
  --report-file .nutmeg-data/jczq/latest.json \
  --output-dir .nutmeg-data/wechat/2026-04-28 \
  --format json

uv run nutmeg wechat-draft-push \
  --pack-dir .nutmeg-data/wechat/2026-04-28 \
  --cover-media-id MEDIA_ID \
  --confirm
```

Default behavior should be dry-run or local-artifact-only unless the operator passes an explicit confirmation flag.

## Data Flow

```text
Sporttery / JCZQ report source
-> existing jczq-mixed-report workflow
-> report JSON under .nutmeg-data/jczq
-> WeChat match selector chooses two matches
-> article builder renders Markdown and HTML
-> compliance gate classifies LOW / MEDIUM / HIGH / BLOCKED
-> artifact writer stores review package
-> draft client creates WeChat draft only if risk is LOW or MEDIUM and confirmation is explicit
-> operator reviews and publishes manually in WeChat backend
```

## Artifacts

Each run writes a dated folder:

```text
.nutmeg-data/wechat/YYYY-MM-DD/
├── article.md
├── article.html
├── draft-payload.json
├── compliance.json
├── selected-matches.json
├── cover-prompt.txt
├── draft-result.json        # only after a real draft push
└── publish-checklist.md
```

## WeChat API Preparation

The operator must prepare:

- WeChat official account with developer access enabled.
- `WECHAT_APP_ID` and `WECHAT_APP_SECRET` stored outside source control.
- Developer IP allowlist configured in the WeChat backend.
- A default cover image uploaded as permanent media, producing a `thumb_media_id` / cover `media_id` for draft articles.
- Optional source URL and author values.

The implementation should use official WeChat APIs for access token retrieval, material/draft payload conventions, and draft creation. v1 must not call the publish endpoint.

Reference docs:

- Access token: https://developers.weixin.qq.com/doc/offiaccount/Basic_Information/Get_access_token.html
- Permanent assets: https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/Adding_Permanent_Assets.html
- Add draft: https://developers.weixin.qq.com/doc/offiaccount/Draft_Box/Add_draft.html
- Publish endpoint, intentionally out of v1 scope: https://developers.weixin.qq.com/doc/offiaccount/Publish/Publish.html

## Compliance Gates

The draft push command is blocked unless all gates pass:

1. **Input gate**: report JSON is present, parseable, and contains enough match/odds information for two selected matches.
2. **Template gate**: article includes title, digest, two match sections, combination observation, and disclaimer.
3. **Language gate**: blocked terms such as 稳胆、包红、必中、重仓、回血、跟单、私信拿单、收费方案、保证收益 are absent.
4. **Advice gate**: betting instructions such as 买主胜、直接上、串关方案 are absent from public text.
5. **Risk gate**: only LOW or MEDIUM content can be pushed to WeChat draft. HIGH and BLOCKED content remains local only.
6. **Human gate**: v1 creates drafts only. Final publish is manual.

## Error Handling

- Missing credentials: fail with a clear message and keep local artifacts intact.
- Invalid cover media ID: fail before draft creation, with remediation instructions.
- Token retrieval failure: report WeChat error code/message and do not retry indefinitely.
- Draft API failure: write `draft-error.json` with request metadata excluding secrets.
- Compliance failure: write artifacts and checklist, but block draft push.
- Partial artifact failure: prefer atomic writes where practical and avoid leaving a misleading success result.

## Testing Strategy

- Unit tests for match selection using sample JCZQ reports.
- Unit tests for article template rendering and required section presence.
- Unit tests for blocked/high-risk language detection.
- Unit tests that HIGH/BLOCKED packs cannot call the draft client.
- CLI tests for local artifact generation and dry-run draft payload output.
- HTTP-client tests with mocked WeChat responses for access token and draft creation.
- Existing repository verification through `scripts/verify.sh` after implementation.

## Scope Boundaries

In scope for v1:

- Generate two-match WeChat article packs from JCZQ reports.
- Render Markdown, HTML, draft payload, compliance report, and checklist.
- Create WeChat draft when explicitly confirmed and compliant.
- Keep final publish manual.

Out of scope for v1:

- Auto-publishing WeChat articles.
- Paid groups, private messages, subscription paywalls, or betting-platform links.
- Guaranteed-result language or staking instructions.
- Image generation beyond a local cover prompt or pre-uploaded cover media ID.
- Circumventing WeChat review, captcha, or platform restrictions.

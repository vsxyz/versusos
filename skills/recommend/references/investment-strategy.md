# Investment Strategy — Advisory & Education Overlay

A general expert's strategy for choosing stablecoin DeFi yield vaults, applied by
the `recommend` skill as an **advisory and educational overlay** on top of the
deterministic safety-score ranking.

**It never changes eligibility, scores, or ordering** (see `../SKILL.md`
Boundaries). The deterministic ranking decides *what is shown and in what order*;
this strategy decides *what to warn about and what to teach the user to check*.
It does two things:

- **Auto-caution** — where a VersusOS cache already carries the signal, annotate the
  affected pick with the relevant caution.
- **User checklist** — where VersusOS does not collect the signal, present the
  expert threshold as a "verify-it-yourself before depositing" item, so the user
  can confirm it manually.

**Core principle: a safe exit matters more than a high APY.** Prefer vaults a
retail user can realistically *enter and leave*, not simply the highest APY.

> Retail framing. These thresholds describe a conservative retail profile. They
> are the baseline advisory; when the user selects a Pick bucket (Conservative /
> Balanced / Aggressive), apply the same checklist but tune the emphasis —
> Conservative flags every shortfall, Aggressive notes the user is knowingly
> accepting more of these risks. Tuning the *advice tone* is allowed; the
> *ranking* still comes only from the deterministic rules in SKILL.md.

**Availability tag per section** (presentation routing, not a filter):

- `[auto]` — VersusOS can surface this from a cache → auto-caution.
- `[partial]` — partly from cache, the rest user-verified.
- `[verify]` — not collected → present as a user-checklist item.

**Severity routing** (display only — see recommend `SKILL.md` §3 (the gate) + §4
(presentation) for the cache-backed exclusion rules; flags never change rank /
eligibility / score): the
cache-certain hard-cuts render as **🚨 retail disqualification-line** on the pick —
§14 exploit ≤ 3 months, §4 exit liquidity < $50K, §3 vault TVL < $100K, §13 depeg in
the last 30 days (deep only). Their softer bands render as **⚠** — §4 $50K–$500K, §14
exploit > 3 months, plus pair-vault IL and reward-heavy yield. The §3 retail TVL band
(≥ $20M / $100M / $500M) stays educational (the TVL is shown per pick — auto-flagging
it would fire on most candidates), §10 audit stays checklist + `research-audit`
annotation (CTS = 0 means *unmapped*, not *unaudited*), and every uncollected item
remains the verify-yourself checklist.

---

## 1. Chain liquidity  `[verify]`

A vault's chain needs baseline liquidity and trading activity; a thin chain means
bridge delays, high slippage, low DEX volume, and limited exit paths even when the
vault score looks good.

| Chain DeFi TVL | Read |
|---|---|
| ≥ $1B | Very good — preferred on chain-liquidity grounds |
| $100M – $1B | Good — normal DeFi operation |
| $50M – $100M | Minimum pass — check vault TVL & pool liquidity more conservatively |
| < $50M | Low priority |

| 24h DEX volume | Read |
|---|---|
| ≥ $100M | Very good |
| $30M – $100M | Good |
| $3M – $30M | Minimum pass |
| < $3M | Activity too low — low priority |

**Minimum:** chain DeFi TVL ≥ **$50M** AND 24h DEX volume ≥ **$3M** (both). If
either sits only in its minimum band, treat as minimum-pass and verify vault TVL,
pool liquidity, and exit path more conservatively. Per-chain stablecoin supply is
not a core gate.

## 2. Protocol total TVL  `[verify]`

A larger protocol generally means more users, capital, market validation, and
operating history — and more capacity to respond to an exploit, halt, liquidity
shortage, oracle fault, or withdrawal delay. Large TVL is not a safety guarantee.

| Protocol total TVL | Read |
|---|---|
| ≥ $1B | Priority |
| $300M – $1B | Normal |
| $100M – $300M | Caution |
| $50M – $100M | Small size only |
| < $50M | Excluded from general recommendations |

**< $100M → approach conservatively. < $50M → exclude from general recommendations
even at high APY.**

## 3. Vault TVL  `[auto]`  (`tvlUsd`)

How much is deposited in the specific vault. A large protocol with a small target
vault is still judged conservatively on the vault itself.

| Vault TVL | Read |
|---|---|
| ≥ $500M | Very good — large vault, relatively safe for retail |
| $100M – $500M | Good — priority candidate |
| $50M – $100M | Usable — review risks carefully |
| $20M – $50M | Minimum review — only if APY is high and other risks are low |
| $1M – $20M | Conservative — small test / limited use |
| $100K – $1M | Very small — excluded from general recommendations |
| < $100K | **Never used** |

**General minimum ≥ $20M. Hard floor: < $100K is never used** (APY distortion,
withdrawal/operational/liquidity risk dominate).

> **Separate lens from the score — not a contradiction.** The safety-score
> `vault_tvl` factor saturates at **≥ $1M → full points** (it only screens
> microcaps), so a vault can score full TVL points yet still warrant a retail-size
> caution here — e.g. a $5M vault is score-full but "$1M–$20M conservative" for
> retail entry/exit. This band *refines* what the saturated score cannot
> distinguish; it never overrides the ranking. Aligning the two scales would
> change the safety-score formula — a broader decision, out of scope for this
> advisory overlay.

## 4. Pool liquidity / exit liquidity  `[partial]`

After withdrawing, can the received token / receipt token be swapped into a major
stable (USDC/USDT)? Exit matters more than entry, so look at the *counterparty*
liquidity you can actually leave through — not just total pool TVL.

| Priority | Pair | Read |
|---|---|---|
| 1 | token / receipt token ÷ **USDC** | Most preferred |
| 2 | token / receipt token ÷ **USDT** | Preferred |
| 3 | token / receipt token ÷ native coin | Secondary |
| excl. | token / receipt token ÷ project's own token | Not real exit liquidity |

| Pool liquidity | Read |
|---|---|
| ≥ $1M | Very good — basic exit fine |
| $500K – $1M | Good |
| $250K – $500K | Usable — limit deposit size |
| $100K – $250K | Small only |
| $50K – $100K | Minimum pass — very conservative |
| < $50K | **Not used** |

**Minimum ≥ $50K on a USDC/USDT pair; prefer ≥ $500K; ≥ $1M is comfortable.**
`[partial]`: VersusOS auto-surfaces liquidity for the *designated* DEX pools it
tracks; for any other receipt-token exit pair, route to the user checklist.

## 5. Deposit size vs liquidity  `[verify — user applies]`

Even with liquidity present, a deposit that is large relative to the pool is risky.

| Metric | Guidance |
|---|---|
| deposit ÷ pool liquidity | < 5% (baseline) |
| conservative | ≤ 1–2% |
| max allowed | ≤ 5% |
| > 5% | reduce deposit size |

| Pool liquidity | Max deposit (5%) |
|---|---|
| $50K | $2.5K |
| $100K | $5K |
| $250K | $12.5K |
| $500K | $25K |
| $1M | $50K |

Present as a general principle ("an expert keeps deposit ≤ 5%, ideally 1–2%, of
the exit pool"); the user supplies their own amount. This stays **education-only**:
the full max-deposit (portfolio-% cap × vault withdrawal liquidity ×
market-depth-at-price) needs inputs VersusOS does not collect. Grounding it per pick
— showing "5% of this pick's tracked USDC/USDT exit pool = $X" from the DEX cache —
is a candidate enhancement deferred to the max-deposit decision. Advisory only —
not financial advice.

## 6. APY bands  `[auto]`

Is the reward enough for the risk taken?

| APY | Read |
|---|---|
| ≤ 3% | Low priority — reward too low for the risk |
| 3 – 7% | Conservative stable yield |
| 7 – 15% | Main recommendation band |
| 15 – 25% | Check structural risk |
| ≥ 25% | High-risk APY — treat the yield itself as a risk signal |

For elevated APY, distinguish whether it comes from lending interest / protocol
revenue / trading fees (`apyBase`) vs token incentives or points farming
(`apyReward`, `rewardTokens`).

## 7. Chain-specific minimum APY  `[auto]`

Entry/exit cost, bridge cost, slippage, and depth differ by chain, so the same APY
reads differently.

| Chain / environment | Minimum-review APY |
|---|---|
| Ethereum mainnet | ≥ 3 – 5% |
| Arbitrum / Base / BNB Chain | ≥ 5 – 7% |
| Solana | ≥ 5 – 8% |
| Tron | ≥ 5 – 8% |
| New L2 / new EVM | ≥ 12 – 15% |
| Thin-liquidity env. (e.g. HyperEVM) | ≥ 20% |

## 8. Bridge cost  `[verify]`

A vault reachable only via a bridge has a lower *effective* yield.

| Metric | Safe | Moderate | Avoid |
|---|---|---|---|
| round-trip bridge cost ÷ deposit | ≤ 0.2% | 0.2 – 0.5% | > 0.5% |
| bridge time | ≤ 30 min | 30 min – 6 h | > 6 h |
| return to CEX / major chain | easy | possible but awkward | unclear |

Example: depositing $5,000 with a $50 round-trip bridge cost is 1% — erodes the
yield, lower the priority. Also weigh bridge-exploit, withdrawal-delay,
support-discontinuation, and cross-chain liquidity-fracture risk.

## 9. Lock-up / withdrawal restriction  `[verify]`

Prefer instantly withdrawable vaults.

| Withdrawal terms | Read |
|---|---|
| Instant | Priority |
| Within 24h | Normal |
| 1 – 7 day wait | Caution |
| 7 – 30 day wait | High-risk / needs high APY |
| ≥ 30 day lock-up | Excluded from general recommendations |
| No early exit (fixed maturity) | Excluded from general recommendations |

**Withdrawal wait ≥ 7 days → conservative even at high APY. ≥ 30 days → exclude
from general retail recommendations.** Fixed-maturity products, lock-ups,
withdrawal queues, and epoch-only exits all slow your response when something
breaks.

## 10. Audit  `[partial]`

Prefer vaults with a public audit *report*. "audited" alone is not enough — check
*which* auditor, *which* contract, *which* version.

| Audit status | Read |
|---|---|
| ≥ 1 Tier-1 / Tier-1.5 auditor | Priority |
| ≥ 1 Tier-2 auditor | Normal |
| ≥ 2 Tier-2 auditors | Good |
| Tier-3 only | Conservative |
| No audit report | Excluded |
| Unclear audit scope | Excluded / needs verification |

**Minimum ≥ 1 public official audit report.** "audited" with no published report
is not accepted. Confirm the *vault contract or token CA the user deposits into*
is inside the audit scope, not just the protocol generally. `[partial]`: VersusOS
carries the DeFiLlama `audits` code, and the optional `research-audit` skill adds
graded auditors / dated reports / URLs; auditor *tier* and *scope-in-contract*
remain user-verified.

## 11. Operating period  `[verify]`

A just-launched vault has little real-world validation.

| Operating period | Read |
|---|---|
| ≥ 2 years | Priority |
| 1 – 2 years | Stable candidate |
| 6 – 12 months | Normal |
| 3 – 6 months | Small size only |
| < 3 months | High-risk |
| < 1 month | Excluded from general recommendations |

**< 3 months → avoid large deposits even at high APY. < 1 month → exclude.** New
vaults often advertise high APY before code, ops, withdrawals, liquidity, and the
oracle setup have been time-tested.

## 12. Funding / backers  `[verify]`

Funding does not guarantee safety, but works as a qualitative filter.

| Signal | Read |
|---|---|
| Top-tier VC / major foundation | Positive |
| ≥ $10M raised | Positive |
| $3M – $10M raised | Secondary signal |
| Unclear investors | Neutral / caution |
| No team / investor / partner info | Negative |

Never recommend on funding alone. When TVL, audit, and age are comparable, prefer
the protocol with more credible backers (usually better early validation,
network, and operating resources).

## 13. Stablecoin  `[partial]`

For a stablecoin vault, the underlying stablecoin can matter more than the vault —
a depeg causes loss no matter how good the vault is.

| Metric | Safe | Moderate | Avoid |
|---|---|---|---|
| Peg-held duration | ≥ 180 days | 90 – 180 days | < 90 days |
| Depeg in last 30 days | none | 1 | ≥ 2 |
| Below $0.98 within 180 days | none | 1 | ≥ 2 |
| Redemption structure | clear | partly unclear | unclear |
| Reserve / collateral disclosure | clear | partly unclear | unclear |

**Peg history < 90 days → lower priority.** `[partial]`: VersusOS derives peg /
depeg history from 180-day OHLCV **only after the opt-in `collect-depeg-history`
(deep) step runs** — it is *not* collected on the fast-path first recommendation,
so until that step runs treat peg/depeg as user-verified too. The items below are
always user-verified:

| Item | Check |
|---|---|
| Reserve structure | what backs it |
| Redemption | is redemption actually possible |
| Issuer credibility | is the issuer identifiable |
| Token audit | is the token contract audited |
| Mint authority | unlimited-mint risk |
| Freeze / blacklist | centralized control |
| Bridge token | native asset vs bridge-wrapped |

## 14. Exploit history  `[auto]`

Protocols with past exploits are judged conservatively.

| Exploit history | Read |
|---|---|
| None | Normal |
| 1 exploit | Penalize, limited review |
| 2 exploits | High-risk |
| ≥ 3 exploits | Excluded from general recommendations |
| Exploit in last 12 months | Strong caution |
| Exploit in last 3 months | Excluded |

Check whether a re-audit, compensation, post-mortem, and contract replacement
clearly followed any recent exploit. A past exploit is not an automatic exclusion,
but a *recent* one — or the same contract line still in use — argues against new
deposits. VersusOS carries brand-wide exploit counts and dated events (recency is
derivable).

## 15. Admin key / governance  `[verify]`

Over-centralized control is an added risk even when the code is sound.

| Item | Preferred |
|---|---|
| Admin key | multisig, not a single EOA |
| Multisig signers | ≥ 3-of-5 |
| Timelock | ≥ 24h |
| Major-upgrade timelock | ≥ 48 – 72h preferred |
| Emergency pause | exists, low abuse potential |
| Power structure | disclosed in official docs |

Avoid setups where a single EOA holds upgrade authority.

## 16. Oracle  `[verify]`

For lending / collateral / leveraged vaults, check the oracle.

| Oracle setup | Read |
|---|---|
| Verified oracle (e.g. Chainlink) | Positive |
| TWAP + fallback | Positive |
| Self-built oracle only | Caution |
| Low-liquidity token as collateral | Caution |
| Undisclosed oracle | Negative |

An unclear oracle on a lending vault → conservative even at high APY (bad price
data causes bad debt, failed liquidations, mis-valued collateral).

## 17. Retail base filter  `[composite]`

Only vaults clearing these are first-pass candidates.

| Item | Minimum |
|---|---|
| Chain DeFi TVL | ≥ $50M |
| Chain 24h DEX volume | ≥ $3M |
| Protocol total TVL | ≥ $100M |
| Vault TVL | ≥ $20M |
| Vault TVL hard cut | < $100K not used |
| USDT/USDC pool liquidity | ≥ $50K |
| deposit ÷ pool liquidity | < 5% |
| Official audit report | ≥ 1 |
| Withdrawal wait | ≤ 7 days |
| Depeg in last 30 days | none |
| Exploit in last 3 months | none |

If vault TVL is $20M–$50M, require a sufficiently high APY and check audit, pool
liquidity, and withdrawal terms more closely. Vault TVL < $100K, or USDT/USDC pool
liquidity < $50K → generally not used. (Applied as advisory: where VersusOS lacks a
field, present it as a user-checklist item, never as a silent filter.)

## 18. Final priority profile  `[composite]`

A vault worth recommending first to a retail user is close to:

| Item | Priority target |
|---|---|
| Chain DeFi TVL | ≥ $100M (≥ $1B very good) |
| Chain 24h DEX volume | ≥ $3M |
| Protocol total TVL | ≥ $100M |
| Vault TVL | ≥ $100M |
| Large-vault mark | ≥ $500M |
| USDT/USDC pool liquidity | ≥ $500K |
| Minimum pool liquidity | ≥ $50K |
| deposit ÷ pool liquidity | < 5% |
| Operating period | ≥ 6 months |
| Audit | ≥ 1 official report |
| Withdrawal | instant or ≤ 7 days |
| Recent depeg | none |
| Recent exploit | none |

VersusOS recommends not simply the highest-APY vault, but the one a retail user can
realistically enter and exit. **The most important principle: a safe exit matters
more than a high APY.**

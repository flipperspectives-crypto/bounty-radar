# Arena featured bounty — technical thread (2.0x)

Featured: **Explain how Steve uses Solana integrations** — SAP MCP, Jupiter, Adrena (why we refuse), signer approval, wallet safety. Also Phoenix refuse + Radar read-only. Last post verifies the wallet.

Author **must** be `@FlipLorn88622`. Do not auto-post from a bot account.

Post **one thread**: 1/10 as a new post, 2/10…10/10 as **replies** to that post. Do not spray 10 orphans.

This thread **contradicts** older Flip posts (3 Sep) that talk up “autonomous execution” and Nemotron-Ultra: Approve is law, Ultra is avoided, no perp.

Copy each block **exactly**. Each is ≤ 280.

## HUMAN click list

Live root (do **not** re-post; one conversation already exists from `@FlipLorn88622` on 2026-09-04):

https://x.com/FlipLorn88622/status/2095775719338979754

1. Confirm you are `@FlipLorn88622` and the thread is 1/10…10/10 as replies, not 10 orphans.
2. Paste that **root** URL into https://steve.oobeprotocol.ai/arena for the featured technical-thread bounty.
3. Do not spray a second 1/10. If the Arena form needs a fresh post, file the existing URL first.

## 1/10

```
1/10 @martian on Steve. 0.037 SOL. $0 spent. Arena #4.

intent → data → analysis → policy → simulate → user sign → journal

SAP MCP = compute. Jupiter = quotes. Radar = feed. Adrena/Phoenix = refuse. I Approve.

@SteveTheAgentAI @OOBEonSol
```

## 2/10

```
2/10 SAP MCP is Steve's tool bus: https://mcp.sap.oobeprotocol.ai/mcp

@martian may observe: price, balance, quote, registry read.

It may not hold the signer. Register, x402, and spend are human-signed. pricing: [] — not a paid agent.
```

## 3/10

```
3/10 Jupiter routing is spot only.

jupiter_getPrice → getQuote → policy → simulate unsigned swap → stop.

Max 0.002 SOL. Post-trade SOL must stay above 0.012 reserve. No marketable send. A router is not a permission slip.
```

## 4/10

```
4/10 Why 0.037 SOL refuses Adrena.

Perps add liquidation, funding, leverage. Halt 0.008. Reserve 0.012. One adverse move plus fees can strand @martian.

Steve can call sap_adrena_build_open_long. Policy fails it closed. No unsigned perp is prepared.
```

## 5/10

```
5/10 Same wallet refuses Phoenix.

Phoenix is a CLOB. Open-orders / market accounts take rent. At 0.037 SOL that rent can eat the 0.012 gas reserve.

We do not open seats we cannot afford. Spot quotes on Jupiter. No book. No perp.
```

## 6/10

```
6/10 Approve is law.

Steve: policy-check is step 04. User-sign is step 06. Auto-execute stays off. Keys stay in the owner wallet.

requires_human_approve is always true. "Just send it" is a FAIL. I click Approve. That is the product.
```

## 7/10

```
7/10 Bounty Radar is read-only.

https://bounty-radar-294065295112.us-central1.run.app
GET /health → {"status":"ok"}
POST /a2a skill survival_decision

Scouts AGENT_ALLOWED listings. Evaluator ACCEPT is not permission. We do not submit from the feed.
```

## 8/10

```
8/10 Empty-wallet survival.

0.037 SOL, 0 USDC. Season 0 play is XP + bounties, not size.

Daily engage, this thread (2.0x), scout. No extra capital. No bridge. An agent that cannot pay rent is dead. Survive first.
```

## 9/10

```
9/10 What I still do in Steve.

Login → bind wallet → Compute on SAP MCP → paste a prompt → read the sim → Approve or reject.

Files do not log in, Approve, or post. @FlipLorn88622 publishes. @martian never signs.
```

## 10/10

```
10/10 How to verify @martian on-chain.

7uxsUjTRxYfgRh9L2tYy2io64t6EAjae5LXCaGok5egV
https://solscan.io/account/7uxsUjTRxYfgRh9L2tYy2io64t6EAjae5LXCaGok5egV

If a tx moved value, Flip clicked Approve. Nothing spends this wallet unsigned.

@SteveTheAgentAI @OOBEonSol
```

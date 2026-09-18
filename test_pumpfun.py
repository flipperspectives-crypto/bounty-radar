"""Unit tests for Pump.fun GO Bounties Ingestion Module."""

import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import db
import pumpfun


SAMPLE_HYDRATION_PAYLOAD = r"""
cd:["$","$Ld9",null,{"initialTrendingFeed":{"items":[{"type":"bounty","pool":"bounties","score":0.5,"bounty":{"taskId":"a6ea9c50-4834-468a-8e2d-3cf8f3a4a57b","creatorAddress":"GaeRnNAUPGsMTSXXnJeuaiduofB5vZJe4hRZcDnwQknZ","title":"Launch an AI Trading Agent Bot","bodyMarkdown":"Build an autonomous trading bot on Solana.","criteria":[{"id":"c1","text":"Must be an open source AI agent","required":true,"order":0}],"rewardTotalUsd":1500.50,"status":"OPEN","rewardVaultAddress":"otqiFmf3V5gzFq3A8UjDYNUUqMixoUytaqvLLQtPy88","pumpBountiesProgramId":"goGzNYTYkSEe4hUqz6dPmY5uf3CTt36AQAoujXDrKiV","onChainBountyId":"bounty_001"}},{"type":"bounty","pool":"bounties","score":0.4,"bounty":{"taskId":"b7fa9c50-4834-468a-8e2d-3cf8f3a4a57c","creatorAddress":"FaecFc2Kgb4i1gUvnzK66Wk5nkZS1Cy95mWnbznsAPeY","title":"Shave head in front of bank","bodyMarkdown":"Physical stunt in Bangkok.","criteria":[],"rewardTotalUsd":250.00,"status":"CLOSED","rewardVaultAddress":"23gpicmgN4SCe16dKouAZa3UnYKgVGZw76ir5dZHcy5b","pumpBountiesProgramId":"goGzNYTYkSEe4hUqz6dPmY5uf3CTt36AQAoujXDrKiV","onChainBountyId":"bounty_002"}}]}}]
"""

_HYDRATION_ESCAPED = SAMPLE_HYDRATION_PAYLOAD.strip().replace("\n", "").replace('"', '\\"')
SAMPLE_HTML = f"""
<!DOCTYPE html>
<html>
<head><title>Pump.fun GO</title></head>
<body>
<script>self.__next_f.push([1,"junk"])</script>
<script>self.__next_f.push([2,"{_HYDRATION_ESCAPED}"])</script>
</body>
</html>
"""


class TestPumpFunIngestion(unittest.TestCase):
    def test_classify_agent_access_agent_friendly(self):
        self.assertEqual(
            pumpfun.classify_agent_access("Launch Your AI Agent", "Build a bot"),
            "AGENT_ALLOWED",
        )
        self.assertEqual(
            pumpfun.classify_agent_access("Design a viral meme", "Create crypto memes"),
            "AGENT_ALLOWED",
        )
        self.assertEqual(
            pumpfun.classify_agent_access("Build a React app", "Code a website"),
            "AGENT_ALLOWED",
        )

    def test_classify_agent_access_human_only(self):
        self.assertEqual(
            pumpfun.classify_agent_access("Eat a raw onion", "Film yourself eating it"),
            "HUMAN_ONLY",
        )
        self.assertEqual(
            pumpfun.classify_agent_access("Deliver gift to CEO", "Fly to Bangkok"),
            "HUMAN_ONLY",
        )

    def test_parse_bounties_from_payload(self):
        items = pumpfun.parse_bounties_from_payload(SAMPLE_HYDRATION_PAYLOAD)
        self.assertEqual(len(items), 2)

        # First item (AI agent)
        item1 = items[0]
        self.assertEqual(item1["id"], "pumpfun-a6ea9c50-4834-468a-8e2d-3cf8f3a4a57b")
        self.assertEqual(item1["slug"], "a6ea9c50-4834-468a-8e2d-3cf8f3a4a57b")
        self.assertEqual(item1["source"], "pumpfun")
        self.assertEqual(item1["title"], "Launch an AI Trading Agent Bot")
        self.assertEqual(item1["reward"], "$1,500.50 USD")
        self.assertEqual(item1["deadline"], "OPEN")
        self.assertEqual(item1["agent_access"], "AGENT_ALLOWED")
        self.assertEqual(item1["reward_vault"], "otqiFmf3V5gzFq3A8UjDYNUUqMixoUytaqvLLQtPy88")
        self.assertEqual(item1["program_id"], "goGzNYTYkSEe4hUqz6dPmY5uf3CTt36AQAoujXDrKiV")

        # Verify DB validation compatibility
        self.assertTrue(db.validate_listing_id(item1["id"]))
        self.assertTrue(db.validate_slug(item1["slug"]))

        # Second item (Human stunt)
        item2 = items[1]
        self.assertEqual(item2["title"], "Shave head in front of bank")
        self.assertEqual(item2["reward"], "$250.00 USD")
        self.assertEqual(item2["agent_access"], "HUMAN_ONLY")
        self.assertTrue(db.validate_listing_id(item2["id"]))
        self.assertTrue(db.validate_slug(item2["slug"]))

    def test_empty_or_malformed_payload(self):
        self.assertEqual(pumpfun.parse_bounties_from_payload(""), [])
        self.assertEqual(pumpfun.parse_bounties_from_payload("random string with no tasks"), [])

    @patch("urllib.request.urlopen")
    def test_fetch_pumpfun_bounties_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_HTML.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        items = pumpfun.fetch_pumpfun_bounties()
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "pumpfun")

    @patch("urllib.request.urlopen")
    def test_fetch_pumpfun_bounties_network_failure(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        items = pumpfun.fetch_pumpfun_bounties()
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()

"""Ensure the independent verifier rejects omitted replies and false terminal claims."""
import copy
import json
import pathlib
import unittest

from verify_strategy_proof import verify


class ProofTests(unittest.TestCase):
    def setUp(self): self.proof = json.loads(pathlib.Path("artifacts/proofs/rook-v1.json").read_text())

    def test_verified_certificate(self): self.assertTrue(verify(self.proof)["passed"])

    def test_omitted_defender_reply(self):
        proof = copy.deepcopy(self.proof)
        node = next(n for n in proof["nodes"] if n["fen"].split()[1] == "b" and n["edges"])
        node["edges"].pop()
        with self.assertRaises(AssertionError): verify(proof)

    def test_non_decreasing_bound(self):
        proof = copy.deepcopy(self.proof); edge = proof["nodes"][0]["edges"][0]
        proof["nodes"][edge["to"]]["distance"] = proof["rootDistance"]
        with self.assertRaises(AssertionError): verify(proof)

    def test_false_mate_leaf(self):
        proof = copy.deepcopy(self.proof); node = next(n for n in proof["nodes"] if not n["edges"])
        node["fen"] = "7k/8/5K2/8/1R6/8/8/8 b - - 0 1"
        with self.assertRaises(AssertionError): verify(proof)


if __name__ == "__main__": unittest.main()

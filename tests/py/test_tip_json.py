from __future__ import print_function, unicode_literals

import json

from liberapay.testing import Harness


class TestTipJson(Harness):

    def tip(self, tipper, tippee, amount, raise_immediately=True):
        return self.client.POST(
            "/%s/tip.json" % tippee,
            {'amount': amount},
            auth_as=tipper,
            xhr=True,
            raise_immediately=raise_immediately,
        )

    def test_get_amount_and_total_back_from_api(self):
        "Test that we get correct amounts and totals back on POSTs to tip.json"

        # First, create some test data
        # We need accounts
        self.make_participant("test_tippee1")
        self.make_participant("test_tippee2")
        test_tipper = self.make_participant("test_tipper", balance=100)

        # Then, add a $1.50 and $3.00 tip
        response1 = self.tip(test_tipper, "test_tippee1", "1.00")
        response2 = self.tip(test_tipper, "test_tippee2", "3.00")

        # Confirm we get back the right amounts.
        first_data = json.loads(response1.text)
        second_data = json.loads(response2.text)
        assert first_data['amount'] == "1.00"
        assert first_data['total_giving'] == "1.00"
        assert second_data['amount'] == "3.00"
        assert second_data['total_giving'] == "4.00"

    def test_set_tip_out_of_range(self):
        self.make_participant("alice")
        bob = self.make_participant("bob")

        response = self.tip(bob, "alice", "110.00", raise_immediately=False)
        assert "not a valid donation amount" in response.text
        assert response.code == 400

        response = self.tip(bob, "alice", "-1.00", raise_immediately=False)
        assert "not a valid donation amount" in response.text
        assert response.code == 400

    def test_set_tip_to_patron(self):
        self.make_participant("alice", goal='-1')
        bob = self.make_participant("bob")

        response = self.tip(bob, "alice", "10.00", raise_immediately=False)
        assert "doesn't accept donations" in response.text, response.text
        assert response.code == 400

    def test_tip_to_unclaimed(self):
        alice = self.make_elsewhere('twitter', 1, 'alice')
        bob = self.make_participant("bob")
        response = self.tip(bob, alice.participant.username, "10.00")
        data = json.loads(response.text)
        assert response.code == 200
        assert data['amount'] == "10.00"
        assert "alice" in data['msg']

        # Stop pledging
        response = self.tip(bob, alice.participant.username, "0.00")
        data = json.loads(response.text)
        assert response.code == 200
        assert data['amount'] == "0.00"
        assert "alice" in data['msg']

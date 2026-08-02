"""The pricing page reads /api/plans, so what that endpoint drops, the page cannot do.

A response model that silently filtered out ``purchasable`` once made every card on the
pricing page unclickable while every backend test still passed.
"""

from backend.app.services import plans


def test_the_catalogue_says_which_plans_can_be_bought(client):
    catalogue = {item["key"]: item for item in client.get("/api/plans").json()}
    assert catalogue["free"]["purchasable"] is False
    assert catalogue["standart"]["purchasable"] is True
    assert catalogue["pro"]["purchasable"] is True
    assert catalogue["biznes"]["purchasable"] is True


def test_the_owner_plan_is_not_served_to_the_pricing_page(client):
    assert all(item["key"] != "owner" for item in client.get("/api/plans").json())


def test_every_field_the_plan_defines_survives_the_response(client):
    served = {item["key"]: item for item in client.get("/api/plans").json()}
    for key, plan in plans.PLANS.items():
        if not plan.listed:
            continue
        expected = plan.as_dict()
        assert set(expected) <= set(served[key]), f"{key} loses fields on the way out"
        for field, value in expected.items():
            assert served[key][field] == value, f"{key}.{field} changed in transit"

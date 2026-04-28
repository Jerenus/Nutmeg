from nutmeg.core.identity import UserTier, owner_identity


def test_owner_identity_defaults_to_owner_tier() -> None:
    owner = owner_identity({'language': 'en'})

    assert owner.user_id == 'owner'
    assert owner.tier == UserTier.OWNER
    assert owner.preferences['language'] == 'en'

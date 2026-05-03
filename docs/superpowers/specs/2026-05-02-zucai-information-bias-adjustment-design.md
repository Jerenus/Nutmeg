# Zucai Information-Bias Adjustment Design

Date: 2026-05-02

## Intent

Add a reusable Zucai decision layer for the user's recurring observation: public information does not affect every bettor equally. Injuries, form, motivation, fame, derby narratives, and media recommendations often create an apparently reasonable direction. The report should treat those inputs first as evidence of where money may be guided, then decide whether the signal is true strength or an over-expanded narrative.

## Decision Principle

The layer is not a blind contrarian switch. It only changes or annotates a pick when the market shape suggests a possible mismatch between public narrative and actual risk/reward:

- A low-odds favorite in the 1.70-2.05 comfort zone should be interrogated rather than treated as safe.
- A public consensus direction can be downgraded when it is merely reasonable but not backed by a hard strength gap.
- A team with negative narratives can be restored when the odds still imply it is live.
- Strong real-strength gaps remain protected; the layer must not force cold picks against very short favorites.

## Inputs

The baseline service already has match metadata, average 3/1/0 odds, overrides, and custom plans. The new layer will use:

- Average odds: infer comfort favorites, volatility, and plausible ignored outcomes.
- Match risk flags: allow issue/override files to mark narrative-driven risks.
- Override metadata: optional fields such as `public_pick`, `narrative_bias`, and `value_pick` can express user judgment for a specific issue without hardcoding teams.

## Outputs

Each recommendation can include:

- Adjusted pick and primary direction.
- Risk tier `bias_adjusted` or `narrative_trap` where applicable.
- Rationale that explicitly names the information-bias check.
- Warnings such as `information_bias_check` for downstream report text.

Plans may still be supplied by overrides for high-budget 任九 construction. The service should preserve existing behavior unless the bias layer has clear inputs or a generic comfort-zone trigger.

## Today 26070 Application

The final issue-specific override will encode the approved 288 yuan three-ticket 任九 structure:

1. 主攻票: `310 10 3 3 31 - - 31 - - 3 10 - 10`
2. 变量补强票: `- 31 3 3 - 30 30 - 31 31 3 - 0 -`
3. 冷门校准票: `30 - 3 3 31 - 0 31 - - 3 10 - 0`

The match-level overrides should highlight 1, 7, 12, 13 as the clearest information-bias opportunities, while keeping 3, 4, 11 as strength anchors.

## Testing

Add service tests that prove:

- A comfort-zone favorite with public consensus and a value counter-pick becomes bias-adjusted.
- Strong favorites are not overruled by the bias layer without explicit override.
- Override plans keep the expected 288 yuan total structure.

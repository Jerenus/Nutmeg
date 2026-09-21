# T12 Prospective Corpus Gate Evidence

Generated on 2026-09-21 from a fresh corpus build against the then-current
`.nutmeg-data` inputs. The generated verification corpus was written outside the
repository so the existing user-modified `experiments/corpus-v2.json` was not
overwritten.

## Corpus provenance

- rows: 1,055
- provenance distribution: `true=40`, `false=0`, `null=1,015`
- labeled rows: research `true=26`; other labels `true=14`, `null=114`
- pre-2026-09-19 Zucai rows: `null=420`, `true=0`, `false=0`
- 2026-09-19 research-labeled rows: `true=12`
- rows missing either required provenance field: 0

The handoff baseline was 1,027 rows and 12 provable labeled rows. The live input
set had advanced by verification time: 2026-09-20 contributed 14 additional
provable research-labeled rows, while recent Zucai calls metadata contributed 14
provable rows without a research `label_source`. The historical rows were not
reclassified.

## N0 dual-stratum rerun

All runs used seed `20260920` and 1,000 permutations. Counts are factor-level
statistical rows after factor expansion.

| factor | stratum | n | provable_n | unproven_n | observed_pp | floor 2.5% | floor 97.5% | p | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| c7_live_precedent | only-provable | 110 | 110 | 0 | -9.867094 | -19.125880 | 18.908655 | 0.280719 | indistinguishable |
| c7_live_precedent | all | 383 | 110 | 273 | 2.319563 | -8.757296 | 9.268253 | 0.626374 | indistinguishable |
| anchor_integrity | only-provable | 33 | 33 | 0 | -10.324517 | -34.905535 | 32.788309 | 0.559441 | indistinguishable |
| anchor_integrity | all | 130 | 33 | 97 | -13.278701 | -16.920716 | 16.644488 | 0.106893 | indistinguishable |
| death_proof_count | only-provable | 66 | 66 | 0 | 11.773457 | -19.525838 | 20.860165 | 0.286713 | indistinguishable |
| death_proof_count | all | 66 | 66 | 0 | 11.773457 | -19.525838 | 20.860165 | 0.286713 | indistinguishable |

`death_proof_count` has no unproven statistical rows because that factor exists
only in the admitted research artifacts in this snapshot. The equal strict/full
result is therefore a data property, not a relaxed gate.

from __future__ import annotations

import json

from nutmeg.services.evals import EvalService


def test_eval_service_scores_local_keyword_dataset(tmp_path) -> None:
    dataset = tmp_path / 'starter.json'
    dataset.write_text(
        json.dumps(
            {
                'name': 'starter',
                'cases': [
                    {
                        'id': 'case-1',
                        'category': 'odds',
                        'query': 'Should I back Arsenal?',
                        'expected_keywords': ['判断', '置信度'],
                        'output_text': '判断：Arsenal edge is live. 置信度：中。',
                    },
                    {
                        'id': 'case-2',
                        'category': 'tactics',
                        'query': 'Explain the pressing risk.',
                        'expected_keywords': ['pressing', 'counter'],
                        'output_text': 'The pressing shape is strong but counter risk remains.',
                    },
                ],
            }
        ),
        encoding='utf-8',
    )

    result = EvalService(dataset_dir=tmp_path).run_dataset('starter')

    assert result.dataset == 'starter'
    assert result.total_cases == 2
    assert result.passed_cases == 2
    assert result.results[0].passed is True


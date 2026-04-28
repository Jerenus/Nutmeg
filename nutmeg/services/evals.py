from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nutmeg.domain.evals import EvalCase, EvalCaseResult, EvalRunResult


class EvalDatasetNotFoundError(FileNotFoundError):
    pass


class EvalService:
    def __init__(self, *, dataset_dir: Path) -> None:
        self._dataset_dir = dataset_dir

    def run_dataset(self, dataset: str) -> EvalRunResult:
        cases = self._load_cases(dataset)
        results = [self._run_case(case) for case in cases]
        passed = sum(1 for result in results if result.passed)
        return EvalRunResult(
            dataset=dataset,
            generated_at=datetime.now(UTC).replace(microsecond=0),
            total_cases=len(results),
            passed_cases=passed,
            failed_cases=len(results) - passed,
            results=results,
        )

    def _load_cases(self, dataset: str) -> list[EvalCase]:
        path = self._dataset_dir / f'{dataset}.json'
        if not path.exists():
            raise EvalDatasetNotFoundError(f'Eval dataset `{dataset}` was not found at {path}.')
        payload = json.loads(path.read_text(encoding='utf-8'))
        return [
            EvalCase(
                case_id=str(item['id']),
                category=str(item['category']),
                query=str(item['query']),
                expected_keywords=[str(keyword) for keyword in item.get('expected_keywords', [])],
                output_text=item.get('output_text'),
                fixture_id=item.get('fixture_id'),
            )
            for item in payload.get('cases', [])
        ]

    def _run_case(self, case: EvalCase) -> EvalCaseResult:
        output = case.output_text or ''
        normalized_output = output.casefold()
        missing_keywords = [
            keyword
            for keyword in case.expected_keywords
            if keyword.casefold() not in normalized_output
        ]
        return EvalCaseResult(
            case_id=case.case_id,
            category=case.category,
            passed=not missing_keywords,
            missing_keywords=missing_keywords,
            output_text=output,
        )


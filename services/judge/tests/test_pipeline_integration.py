"""End-to-end runner test: real sandboxed containers fetching test cases from
localstack S3, for every verdict. Requires the Docker socket and localstack
(both up under `make test`); skips cleanly otherwise.

This is the Session B required integration test (correct / wrong / TLE / MLE),
extended to also cover CE and RE.
"""

import uuid

import pytest

from app.contracts import Language, Limits, SubmissionJob, TestCaseRef, Verdict
from app.runner import run
from tests.conftest import _Uploader

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_or_skip")]

# Reads "a b" from stdin and prints their sum — the reference "correct" program.
CORRECT_PY = "a, b = map(int, input().split())\nprint(a + b)\n"


def _job(source: str, cases: list[TestCaseRef], *, language: Language = Language.PYTHON,
         time_ms: int = 3000, memory_mb: int = 256) -> SubmissionJob:
    return SubmissionJob(
        submission_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        language=language,
        source=source,
        limits=Limits(time_ms=time_ms, memory_mb=memory_mb),
        cases=cases,
    )


def test_correct_solution_all_ac(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"5\n")
    result = run(_job(CORRECT_PY, [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)]))
    assert result.summary_verdict == Verdict.AC
    assert result.cases[0].verdict == Verdict.AC
    assert result.cases[0].runtime_ms >= 0
    assert result.cases[0].memory_kb > 0  # real measurement came back


def test_wrong_answer(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"999\n")
    result = run(_job(CORRECT_PY, [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)]))
    assert result.cases[0].verdict == Verdict.WA


def test_infinite_loop_is_tle(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"5\n")
    result = run(_job("while True:\n    pass\n", [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)], time_ms=1000))
    assert result.cases[0].verdict == Verdict.TLE


def test_memory_bomb_is_mle(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"5\n")
    bomb = "x = bytearray(512 * 1024 * 1024)\nprint(len(x))\n"
    result = run(_job(bomb, [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)], memory_mb=128))
    assert result.cases[0].verdict == Verdict.MLE


def test_runtime_error(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"5\n")
    result = run(_job("raise SystemExit(1)\n", [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)]))
    assert result.cases[0].verdict == Verdict.RE


def test_compile_error_cpp(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"5\n")
    result = run(_job("int main() { this is not valid c++ }", [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)], language=Language.CPP))
    assert result.summary_verdict == Verdict.CE
    assert result.cases == []
    assert result.compile_error


def test_correct_cpp_and_java(upload_case: _Uploader) -> None:
    input_key, output_key = upload_case(b"2 3\n", b"5\n")
    cpp = "#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<\"\\n\";}"
    cpp_result = run(_job(cpp, [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)], language=Language.CPP))
    assert cpp_result.cases[0].verdict == Verdict.AC

    java = "import java.util.*;\npublic class Main{public static void main(String[] a){Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+s.nextInt());}}"
    java_result = run(_job(java, [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)], language=Language.JAVA))
    assert java_result.cases[0].verdict == Verdict.AC

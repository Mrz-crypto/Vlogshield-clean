"""Run the test suite with a concise pass/fail summary."""

from pathlib import Path
import sys
import unittest


class SummaryResult(unittest.TestResult):
    """Print one clear status line for each test and a final summary."""

    def __init__(self, stream):
        super().__init__()
        self.stream = stream
        self.passed = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed += 1
        self.stream.write(f"PASS  {test.id()}\n")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.stream.write(f"FAIL  {test.id()}\n")

    def addError(self, test, err):
        super().addError(test, err)
        self.stream.write(f"ERROR {test.id()}\n")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.stream.write(f"SKIP  {test.id()} ({reason})\n")


def main() -> int:
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(root / "tests"),
        pattern="test*.py",
        top_level_dir=str(root),
    )
    result = SummaryResult(sys.stdout)
    result.startTestRun()
    try:
        suite.run(result)
    finally:
        result.stopTestRun()

    total = result.testsRun
    if result.wasSuccessful():
        print(f"\nPASS: {result.passed}/{total} tests passed")
        return 0

    failed = len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses)
    print(f"\nFAIL: {result.passed}/{total} tests passed ({failed} failed or errored)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

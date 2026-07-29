from app.evaluation.complexity import classify

PY_NO_LOOP = "a, b = map(int, input().split())\nprint(a + b)\n"

PY_FLAT_LOOP = "n = int(input())\ntotal = 0\nfor i in range(n):\n    total += i\nprint(total)\n"

PY_NESTED_LOOP = (
    "n = int(input())\n"
    "for i in range(n):\n"
    "    for j in range(n):\n"
    "        print(i, j)\n"
)

PY_SORT_THEN_SCAN = (
    "xs = list(map(int, input().split()))\n"
    "xs.sort()\n"
    "for x in xs:\n"
    "    print(x)\n"
)

PY_NAIVE_RECURSION = (
    "def fib(n):\n"
    "    if n < 2:\n"
    "        return n\n"
    "    return fib(n - 1) + fib(n - 2)\n"
    "print(fib(int(input())))\n"
)

PY_TRIPLE_NESTED = (
    "n = int(input())\n"
    "for i in range(n):\n"
    "    for j in range(n):\n"
    "        for k in range(n):\n"
    "            print(i, j, k)\n"
)


def test_python_no_loop_is_constant() -> None:
    assert classify("python", PY_NO_LOOP) == "O(1)"


def test_python_flat_loop_is_linear() -> None:
    assert classify("python", PY_FLAT_LOOP) == "O(n)"


def test_python_nested_loop_is_quadratic() -> None:
    assert classify("python", PY_NESTED_LOOP) == "O(n^2)"


def test_python_triple_nested_loop_is_cubic() -> None:
    assert classify("python", PY_TRIPLE_NESTED) == "O(n^3)"


def test_python_sort_then_scan_is_linearithmic() -> None:
    assert classify("python", PY_SORT_THEN_SCAN) == "O(n log n)"


def test_python_naive_recursion_is_exponential() -> None:
    assert classify("python", PY_NAIVE_RECURSION) == "O(2^n)"


def test_python_syntax_error_is_unknown() -> None:
    assert classify("python", "def broken(:\n") == "unknown"


JAVA_NO_LOOP = "class Main { public static void main(String[] a) { System.out.println(1); } }"

JAVA_FLAT_LOOP = (
    "class Main { public static void main(String[] a) { "
    "for (int i = 0; i < 10; i++) { System.out.println(i); } } }"
)

JAVA_NESTED_LOOP = (
    "class Main { public static void main(String[] a) { "
    "for (int i = 0; i < 10; i++) { "
    "for (int j = 0; j < 10; j++) { System.out.println(j); } } } }"
)

CPP_FLAT_WHILE = (
    "int main() { int i = 0; while (i < 10) { i++; } return 0; }"
)


def test_java_no_loop_is_constant() -> None:
    assert classify("java", JAVA_NO_LOOP) == "O(1)"


def test_java_flat_loop_is_linear() -> None:
    assert classify("java", JAVA_FLAT_LOOP) == "O(n)"


def test_java_nested_loop_is_quadratic() -> None:
    assert classify("java", JAVA_NESTED_LOOP) == "O(n^2)"


def test_cpp_flat_while_is_linear() -> None:
    assert classify("cpp", CPP_FLAT_WHILE) == "O(n)"

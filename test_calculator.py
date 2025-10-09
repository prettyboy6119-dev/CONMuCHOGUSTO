#!/usr/bin/env python3
"""
Quick test script for the calculator logic.
Run this to test changes without starting the full Telegram bot.

Usage: python3 test_calculator.py
"""

import ast
import re


def _safe_eval_expr(expr: str) -> float:
    """Safely evaluate a basic arithmetic expression using AST.

    Allowed: +, -, *, /, %, **, //, parentheses, unary +/-, integers and floats.
    """
    # Normalize some unicode operators
    expr = expr.replace('×', '*').replace('÷', '/').replace('–', '-').replace('−', '-')

    # Parse to AST
    node = ast.parse(expr, mode='eval')

    allowed_binops = (
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv
    )

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Num):  # Py<3.8
            return n.n
        if hasattr(ast, 'Constant') and isinstance(n, ast.Constant):  # Py>=3.8
            if isinstance(n.value, (int, float)):
                return n.value
            raise ValueError("Only numeric constants are allowed")
        if isinstance(n, ast.BinOp) and isinstance(n.op, allowed_binops):
            left = _eval(n.left)
            right = _eval(n.right)
            if isinstance(n.op, ast.Add):
                return left + right
            if isinstance(n.op, ast.Sub):
                return left - right
            if isinstance(n.op, ast.Mult):
                return left * right
            if isinstance(n.op, ast.Div):
                return left / right
            if isinstance(n.op, ast.Mod):
                return left % right
            if isinstance(n.op, ast.Pow):
                return left ** right
            if isinstance(n.op, ast.FloorDiv):
                return left // right
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            operand = _eval(n.operand)
            if isinstance(n.op, ast.UAdd):
                return +operand
            return -operand
        if isinstance(n, ast.Tuple):  # Prevent tuple expressions
            raise ValueError("Tuples are not allowed")
        # Disallow everything else (names, calls, attributes, etc.)
        raise ValueError("Invalid or unsafe expression")

    return _eval(node)


_MATH_TOKEN_RE = re.compile(r"^[\s\d\.+\-*/%()xX×÷,^]+$")


def looks_like_math(text: str) -> bool:
    """Heuristic: text contains only math tokens and at least one operator."""
    if not text:
        return False
    if not _MATH_TOKEN_RE.match(text):
        return False
    return any(op in text for op in ['+', '-', '*', '×', 'x', 'X', '/', '÷', '%', '^'])


def test_expression(expr: str):
    """Test a single expression and print the result."""
    print(f"\nInput: {expr}")
    
    if not looks_like_math(expr):
        print("❌ Not recognized as math expression")
        return
    
    try:
        # Normalize caret to power for user convenience
        normalized = expr.replace('^', '**').replace('x', '*').replace('X', '*')
        result = _safe_eval_expr(normalized)
        
        # Render as integer if whole number, otherwise round to 5 decimal places
        if isinstance(result, float):
            if result.is_integer():
                result = int(result)
            else:
                result = round(result, 5)
        
        print(f"✅ Output: {expr} = {result}")
    except Exception as e:
        print(f"❌ Error: {e}")


def run_tests():
    """Run a suite of test cases."""
    print("=" * 50)
    print("CALCULATOR TEST SUITE")
    print("=" * 50)
    
    test_cases = [
        "2+2",
        "5*10",
        "12*(3+4)/2",
        "5^3",
        "10 ÷ 4",
        "100 - 25 * 2",
        "(10+5)*2",
        "2**8",
        "17 % 5",
        "20 // 3",
        "-5 + 10",
        "3.14 * 2",
        "invalid text",
        "hello world",
    ]
    
    for expr in test_cases:
        test_expression(expr)
    
    print("\n" + "=" * 50)


def interactive_mode():
    """Interactive mode for testing expressions."""
    print("\n" + "=" * 50)
    print("INTERACTIVE CALCULATOR TEST")
    print("=" * 50)
    print("Enter expressions to test (or 'quit' to exit)")
    print("Examples: 2+2, 5^3, 12*(3+4)/2")
    print()
    
    while True:
        try:
            expr = input(">>> ").strip()
            if expr.lower() in ['quit', 'exit', 'q']:
                break
            if not expr:
                continue
            test_expression(expr)
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except EOFError:
            break


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Test specific expression from command line
        expr = " ".join(sys.argv[1:])
        test_expression(expr)
    else:
        # Run test suite first
        run_tests()
        
        # Then interactive mode
        interactive_mode()

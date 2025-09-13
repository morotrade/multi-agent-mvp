def add(a, b):
    """Return the sum of two numbers."""
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        raise ValueError("Both arguments must be numbers.")
    return a + b

def multiply(a, b):
    """Return the product of two numbers."""
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        raise ValueError("Both arguments must be numbers.")
    return a * b

if __name__ == "__main__":
    print("Math Utility")
    print("Add 2 + 3 =", add(2, 3))
    print("Multiply 2 * 3 =", multiply(2, 3))

def add(a, b):
    """Return the sum of a and b after validating inputs."""
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        raise ValueError("Both arguments must be numbers.")
    return a + b

def multiply(a, b):
    """Return the product of a and b after validating inputs."""
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        raise ValueError("Both arguments must be numbers.")
    return a * b

if __name__ == "__main__":
    # Example usage
    print("Add 2 and 3:", add(2, 3))
    print("Multiply 2 and 3:", multiply(2, 3))

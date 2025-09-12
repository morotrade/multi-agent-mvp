def add(a, b):
    """
    Adds two numbers with basic input validation.

    Parameters:
    a (int, float): The first number.
    b (int, float): The second number.

    Returns:
    int, float: The sum of a and b.

    Raises:
    ValueError: If a or b is not a number.
    """
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Both a and b must be numbers.")
    return a + b

def multiply(a, b):
    """
    Multiplies two numbers with basic input validation.

    Parameters:
    a (int, float): The first number.

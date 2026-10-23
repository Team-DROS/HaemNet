"""Expand emergency recruitment selections into individual donor blood groups."""

def request_groups(selection: str) -> tuple[str, ...]:
    if selection == "All positive":
        return ("A+", "B+", "AB+", "O+")
    if selection == "All negative":
        return ("A-", "B-", "AB-", "O-")
    return (selection,)

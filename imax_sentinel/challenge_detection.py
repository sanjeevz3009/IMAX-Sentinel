# Challenge detection
def is_challenge_page(html: str) -> bool:
    markers = [
        "performing security verification",
        "cf-turnstile-response",
        "just a moment",
    ]
    lowered = html.lower()

    return any(marker in lowered for marker in markers)

import os
import sys
import urllib.request


def main() -> None:
    target = os.getenv("HEALTH_URL")
    if not target:
        print("HEALTH_URL is not set", file=sys.stderr)
        sys.exit(1)

    try:
        with urllib.request.urlopen(target, timeout=10) as response:
            status = response.status
            body = response.read(200)
            print(f"Pinged {target} -> {status}")
            if status >= 400:
                print(body.decode("utf-8", "ignore"), file=sys.stderr)
                sys.exit(2)
    except Exception as exc:  # pragma: no cover
        print(f"Failed to ping {target}: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()


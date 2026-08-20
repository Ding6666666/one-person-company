import json

from dsh_company.foundation.app import create_app


def main() -> None:
    print(json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

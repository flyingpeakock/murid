"""Minimal persistent calibredb stand-in, executed in a separate process by tests."""

import json
import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("calibredb integration fixture")
        return

    assert args[0] == "--with-library"
    library = Path(args[1])
    args = args[2:]
    database = library / "books.json"
    books = json.loads(database.read_text())
    if args[0] == "list":
        print(json.dumps(books))
    elif args[0] == "add":
        if (library / "fail-import").exists():
            sys.exit("simulated Calibre import failure")
        assert Path(args[-1]).is_file()
        identifiers = dict(
            args[index + 1].split(":", 1)
            for index, value in enumerate(args)
            if value == "--identifier"
        )
        books.append(
            {
                "id": len(books) + 1,
                "title": args[args.index("--title") + 1],
                "authors": args[args.index("--authors") + 1],
                "identifiers": identifiers,
            }
        )
        database.write_text(json.dumps(books))
        with (library / "imports.jsonl").open("a") as handle:
            handle.write(json.dumps(args) + "\n")
        print(f"Added book ids: {len(books)}")
    else:
        raise AssertionError(f"Unexpected calibredb command: {args}")


if __name__ == "__main__":
    main()

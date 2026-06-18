from murid import Book


def test_book_str():
    book = Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=1,
        isbn=[],
        source="test",
    )

    assert str(book) == "Dune by Frank Herbert"


def test_book_str_multiple_authors():
    book = Book(
        title="Good Omens",
        authors=["Terry Pratchett", "Neil Gaiman"],
        id=1,
        isbn=[],
        source="test",
    )

    assert str(book) == "Good Omens by Terry Pratchett, Neil Gaiman"

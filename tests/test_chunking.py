import pytest

from app.chunking import chunk_pages


def test_short_page_is_one_chunk():
    chunks = chunk_pages([(1, "Hello world.")])
    assert len(chunks) == 1
    assert chunks[0].page == 1
    assert chunks[0].content == "Hello world."


def test_empty_pages_produce_no_chunks():
    assert chunk_pages([(1, ""), (2, "   \n  ")]) == []


def test_chunks_respect_size_and_overlap():
    words = [f"word{i}" for i in range(600)]
    text = " ".join(words)
    chunks = chunk_pages([(3, text)], size=800, overlap=120)

    assert len(chunks) > 1
    assert all(len(c.content) <= 800 for c in chunks)
    assert all(c.page == 3 for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))

    # Consecutive chunks overlap: the next chunk starts with words the previous one ended with.
    for a, b in zip(chunks, chunks[1:]):
        first_word = b.content.split()[0]
        assert first_word in a.content.split()

    # Nothing is lost: every word appears in some chunk, and none is cut in half.
    seen = set(w for c in chunks for w in c.content.split())
    assert seen == set(words)


def test_page_numbers_and_positions_across_pages():
    chunks = chunk_pages([(1, "a " * 500), (2, "b " * 10)], size=800, overlap=120)
    assert chunks[-1].page == 2
    assert chunks[0].page == 1
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        chunk_pages([(1, "x")], size=100, overlap=100)

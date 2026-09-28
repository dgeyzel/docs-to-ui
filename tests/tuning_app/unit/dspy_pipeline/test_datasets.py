import pytest

from dspy_pipeline.datasets_io import Split, dataset_hash, entry_surface, load_entries


@pytest.mark.parametrize("split", ["train", "dev"])
@pytest.mark.parametrize("language", ["openapi", "python"])
def test_every_dataset_entry_extracts_like_the_app(language: str, split: Split) -> None:
    entries = load_entries(languages=[language], split=split)

    assert entries
    for entry in entries:
        surface, adapter = entry_surface(entry)
        assert surface.language == language
        assert adapter.name == language
        assert surface.operations


def test_datasets_include_multi_file_zip_entries() -> None:
    entries = load_entries(languages=["openapi", "python"], split="train")

    zips = [entry for entry in entries if entry.origin == "zip"]
    assert {entry.language for entry in zips} == {"openapi", "python"}
    assert all(len(entry.files) > 1 for entry in zips)


def test_dataset_ids_are_unique_across_splits() -> None:
    entries = load_entries(
        languages=["openapi", "python"], split="train"
    ) + load_entries(languages=["openapi", "python"], split="dev")

    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids))


def test_dataset_hash_is_stable_and_content_sensitive() -> None:
    entries = load_entries(languages=["openapi"], split="dev")

    assert dataset_hash(entries) == dataset_hash(list(entries))
    assert dataset_hash(entries) != dataset_hash(entries[:-1])

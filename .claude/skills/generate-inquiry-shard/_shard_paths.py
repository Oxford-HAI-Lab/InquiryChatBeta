"""Context-file boundary checks shared by the runtime and portable checker."""
import re
from pathlib import Path


_SAFE_NODE_ID = re.compile(r"[A-Za-z0-9_-]+")


def validate_node_id(node_id: object) -> str:
    """Accept a filename-safe ID; uppercase spelling remains a format convention."""
    if not isinstance(node_id, str) or _SAFE_NODE_ID.fullmatch(node_id) is None:
        raise ValueError(
            "node id must be a nonempty string containing only ASCII letters, "
            "digits, underscores or hyphens"
        )
    return node_id


def context_directory(shard_file: Path) -> Path:
    """Keep the contexts root at its expected location, without redirection."""
    try:
        shard_directory = shard_file.parent.resolve()
        expected = shard_directory / "contexts"
        contexts = expected.resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError("cannot safely resolve the shard's contexts directory") from error
    if contexts != expected:
        raise ValueError("contexts directory resolves outside its expected location")
    return contexts


def context_document_path(shard_file: Path, node_id: object) -> Path:
    """Return a context path only after validating its ID and resolved location."""
    safe_id = validate_node_id(node_id)
    contexts = context_directory(shard_file)
    try:
        document = (contexts / f"{safe_id}.md").resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"cannot safely resolve context document for {safe_id}") from error
    if not document.is_relative_to(contexts):
        raise ValueError(f"context document for {safe_id} resolves outside the contexts directory")
    return document

"""GitHub API service for managing Git content within a repository."""

import base64
import hashlib
import logging

from ohc_backend.services.github.rest import GitHubRestAPI

from .models import (
    CommitFilesRequest,
    GitBlob,
    GitCommit,
    GitReference,
    GitTree,
    GitTreeItem,
)

logger = logging.getLogger(__name__)


class GitHubContentManager:
    """Handles Git content operations within a repository."""

    def __init__(self, api: GitHubRestAPI, repository_full_name: str) -> None:
        """Initialize the content manager."""
        self.api = api
        self.repository_full_name = repository_full_name
        self.base_url = f"{api.base_url}/repos/{repository_full_name}"

    async def create_blob(self, content: str) -> GitBlob:
        """Create a Git blob from content."""
        logger.debug("Creating new blob for file content")
        data = {
            "content": base64.b64encode(content.encode()).decode(),
            "encoding": "base64",
        }
        response = await self.api.make_request(
            "POST",
            f"{self.base_url}/git/blobs",
            json=data,
        )
        blob = GitBlob(**response)
        logger.debug("Created blob with SHA: %s", blob.sha)
        return blob

    async def create_tree(self, items: list[GitTreeItem]) -> GitTree:
        """Create a Git tree containing multiple items."""
        logger.debug("Creating new tree with %d items", len(items))
        data = {"tree": [item.model_dump(exclude_none=True) for item in items]}
        response = await self.api.make_request(
            "POST",
            f"{self.base_url}/git/trees",
            json=data,
        )
        tree = GitTree(**response)
        logger.debug("Created tree with SHA: %s", tree.sha)
        return tree

    async def get_tree(self, tree_sha: str, *, recursive: bool = False) -> GitTree:
        """Get a Git tree by its SHA."""
        logger.debug("Fetching tree with SHA: %s (recursive: %s)",
                     tree_sha, recursive)
        params = {"recursive": "1"} if recursive else {}
        response = await self.api.make_request(
            "GET",
            f"{self.base_url}/git/trees/{tree_sha}",
            params=params,
        )
        tree = GitTree(**response)
        logger.debug("Retrieved tree containing %d items", len(tree.tree))
        return tree

    async def create_commit(
        self,
        tree_sha: str,
        message: str,
        parent_sha: str,
    ) -> GitCommit:
        """Create a Git commit pointing to a tree."""
        logger.debug("Creating new commit for tree: %s", tree_sha)
        data = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
        response = await self.api.make_request(
            "POST",
            f"{self.base_url}/git/commits",
            json=data,
        )
        commit = GitCommit(**response)
        logger.debug("Created commit with SHA: %s", commit.sha)
        return commit

    async def get_branch_reference(self, branch: str = "main") -> GitReference:
        """Get the current commit SHA for a branch."""
        logger.debug("Fetching reference for branch: %s", branch)
        response = await self.api.make_request(
            "GET",
            f"{self.base_url}/git/refs/heads/{branch}",
        )
        ref = GitReference(**response)
        logger.debug("Branch %s is at commit: %s", branch, ref.object["sha"])
        return ref

    async def update_branch_reference(
        self,
        branch: str,
        commit_sha: str,
    ) -> GitReference:
        """Update branch to point to a new commit."""
        logger.debug("Updating branch %s to point to commit: %s",
                     branch, commit_sha)
        url = f"{self.base_url}/git/refs/heads/{branch}"
        data = {"sha": commit_sha, "force": True}
        response = await self.api.make_request("PATCH", url, json=data)
        ref = GitReference(**response)
        logger.debug("Successfully updated branch %s", branch)
        return ref

    async def commit_files(
        self,
        request: CommitFilesRequest,
        ref: GitReference = None,
        tree: GitTree = None
    ) -> GitCommit:
        """Commit multiple files to a branch."""
        logger.debug(
            "Starting commit of %d files to branch: %s",
            len(request.files),
            request.branch,
        )
        try:
            if ref is None or tree is None:
                # Only fetch if not provided
                current_ref = await self.get_branch_reference(request.branch)
                current_tree = await self.get_tree(current_ref.object["sha"])
            else:
                # Use provided ref and tree
                current_ref = ref
                current_tree = tree

            tree_items = []
            if request.update_only:
                logger.debug(
                    "Preserving existing files not included in this commit")
                tree_items.extend(
                    item for item in current_tree.tree if item.path not in request.files)

            logger.debug("Creating blobs for new/updated files")
            for path, content in request.files.items():
                logger.debug("Processing file: %s", path)
                blob = await self.create_blob(content)
                tree_items.append(GitTreeItem(path=path, sha=blob.sha))

            logger.debug("Creating new tree with %d total items",
                         len(tree_items))
            new_tree = await self.create_tree(tree_items)

            logger.debug("Creating commit with the new tree")
            commit = await self.create_commit(
                new_tree.sha,
                request.message,
                current_ref.object["sha"],
            )

            logger.debug("Updating branch %s to the new commit",
                         request.branch)
            await self.update_branch_reference(request.branch, commit.sha)

            logger.debug("Files successfully committed")

        except Exception:
            logger.exception("Failed to commit files: %s")
            raise
        else:
            return commit

    def calculate_blob_sha(self, content: str) -> str:
        """Calculate the SHA-1 hash that GitHub would assign to this content."""
        content_bytes = content.encode("utf-8")
        header = f"blob {len(content_bytes)}\0".encode("ascii")
        full_blob = header + content_bytes
        return hashlib.sha1(full_blob).hexdigest()  # noqa: S324

    async def get_changed_files(self, files: dict[str, str], branch: str = "main") -> dict[str, str]:
        """Determine which files have actually changed compared to the repository."""
        logger.debug("Checking for changes in %d files", len(files))

        # Get current tree
        current_ref = await self.get_branch_reference(branch)
        current_tree = await self.get_tree(current_ref.object["sha"], recursive=True)

        # Create path to SHA mapping of current tree
        current_shas = {item.path: item.sha for item in current_tree.tree}

        # Compare SHAs to find changes
        changed_files = {}
        for path, content in files.items():
            new_sha = self.calculate_blob_sha(content)
            if path not in current_shas or current_shas[path] != new_sha:
                changed_files[path] = content

        logger.debug("Found %d changed files", len(changed_files))
        return changed_files, current_ref, current_tree

    async def commit_changed_files(
        self,
        files: dict[str, str],
        message: str,
        branch: str = "main",
    ) -> GitCommit | None:
        """Commit only files that have actually changed."""
        result = await self.get_changed_files(files, branch)
        changed_files, current_ref, current_tree = result
        logger.debug("Changed files: %s", list(changed_files.keys()))

        if not changed_files:
            logger.debug("No files have changed, skipping commit")
            return None

        request = CommitFilesRequest(
            files=changed_files,
            message=message,
            branch=branch,
            update_only=True,
        )

        return await self.commit_files(request, current_ref, current_tree)

    async def get_file_contents(self, path: str) -> str | None:
        """Fetch a file from the repository if it exists."""
        logger.debug("Checking for file %s in repository: %s",
                     path, self.repository_full_name)

        response = await self.api.make_request(
            "GET",
            f"{self.base_url}/contents/{path}",
        )
        if response is None:  # 404 Not Found
            logger.debug("File %s not found", path)
            return None

        return base64.b64decode(response["content"]).decode("utf-8")

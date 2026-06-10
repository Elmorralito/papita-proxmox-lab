"""Tool input schemas and validation helpers.

Pydantic models and validators shared by MCP tool implementations for node names, guest
references, pagination, and write-operation confirmation gates.
"""

import re

from pydantic import BaseModel, Field, field_validator

from proxmox_ve_mcp.constants import NODE_NAME_PATTERN

_NODE_RE = re.compile(NODE_NAME_PATTERN)


def validate_node_name(value: str) -> str:
    """Validate a Proxmox cluster node short name against the allowed pattern.

    Args:
        value: Node name from tool input (for example ``pvenode-001``).

    Returns:
        The validated *value* unchanged when it matches :data:`NODE_NAME_PATTERN`.

    Raises:
        ValueError: When *value* does not match the configured node name regex.
    """
    if not _NODE_RE.match(value):
        raise ValueError(f"Invalid node name {value!r}; must match {NODE_NAME_PATTERN}")
    return value


class NodeNameInput(BaseModel):
    """Single node name parameter for tools scoped to one cluster member.

    Attributes:
        node: Proxmox cluster node short name (for example ``pvenode-001``).
    """

    node: str = Field(description="Proxmox cluster node name, e.g. pvenode-001")

    @field_validator("node")
    @classmethod
    def check_node(cls, value: str) -> str:
        """Validate the required node field against the cluster node name pattern."""
        return validate_node_name(value)


class ListResourcesInput(BaseModel):
    """Filters and pagination for cluster resource listing.

    Attributes:
        type: Optional resource type filter (``node``, ``qemu``, ``lxc``, ``storage``, etc.).
        node: Optional node name filter.
        start: Pagination offset (zero-based).
        limit: Maximum number of resources to return (1–500).
    """

    type: str | None = Field(
        default=None,
        description="Filter by resource type: node, qemu, lxc, storage, pool, ...",
    )
    node: str | None = Field(default=None, description="Filter by node name")
    start: int | None = Field(default=None, ge=0, description="Pagination offset")
    limit: int | None = Field(default=None, ge=1, le=500, description="Pagination limit")

    @field_validator("node")
    @classmethod
    def check_node(cls, value: str | None) -> str | None:
        """Validate optional node filter when present."""
        if value is None:
            return value
        return validate_node_name(value)


class ListGuestsInput(BaseModel):
    """Optional node scope for guest listing.

    Attributes:
        node: When set, limit results to one node; omit to query cluster-wide resources.
    """

    node: str | None = Field(
        default=None,
        description="Limit to one node; omit for all nodes via cluster resources",
    )

    @field_validator("node")
    @classmethod
    def check_node(cls, value: str | None) -> str | None:
        """Validate optional guest-list node scope when present."""
        if value is None:
            return value
        return validate_node_name(value)


class GuestRefInput(BaseModel):
    """Node, VMID, and guest type for operations on a single VM or container.

    Attributes:
        node: Node hosting the guest.
        vmid: Guest VMID (minimum 100).
        guest_type: ``qemu`` for VMs or ``lxc`` for containers.
    """

    node: str = Field(description="Node hosting the guest")
    vmid: int = Field(ge=100, description="Guest VMID")
    guest_type: str = Field(description="Guest type: qemu or lxc")

    @field_validator("node")
    @classmethod
    def check_node(cls, value: str) -> str:
        """Validate the guest node field against the cluster node name pattern."""
        return validate_node_name(value)

    @field_validator("guest_type")
    @classmethod
    def check_guest_type(cls, value: str) -> str:
        """Normalize and restrict guest_type to qemu or lxc."""
        normalized = value.strip().lower()
        if normalized not in {"qemu", "lxc"}:
            raise ValueError("guest_type must be 'qemu' or 'lxc'")
        return normalized


class ListStorageInput(BaseModel):
    """Optional node scope for storage listing.

    Attributes:
        node: When set, include per-node storage status from this node.
    """

    node: str | None = Field(
        default=None,
        description="When set, include per-node storage status from this node",
    )

    @field_validator("node")
    @classmethod
    def check_node(cls, value: str | None) -> str | None:
        """Validate optional storage-list node scope when present."""
        if value is None:
            return value
        return validate_node_name(value)


class ListTasksInput(BaseModel):
    """Filters and pagination for cluster task listing.

    Attributes:
        statusfilter: Task status filter (for example ``running``, ``stopped``, ``all``).
        start: Pagination offset (zero-based).
        limit: Maximum tasks to return (1–500).
    """

    statusfilter: str | None = Field(
        default=None,
        description="Filter tasks: e.g. running, stopped, all",
    )
    start: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=500)


class ConfirmWriteInput(BaseModel):
    """Explicit confirmation gate for mutating MCP tools.

    Attributes:
        confirm: Must be ``True`` to allow the write operation to proceed.
    """

    confirm: bool = Field(description="Must be true to execute mutating operation")

    @field_validator("confirm")
    @classmethod
    def must_be_true(cls, value: bool) -> bool:
        """Reject mutating tool calls unless confirm is explicitly true."""
        if value is not True:
            raise ValueError("confirm must be true")
        return value

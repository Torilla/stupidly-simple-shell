"""The StupidlySimpleShell

This module implements a basic FileSystem, (remotely) inspired by the Unix
filesystem, as well as a StupidlySimpleShell that adds 'bash-like'
functionality on top. See the respective class documentation for details.

"""
from __future__ import annotations
from typing import Any
from types import TracebackType
from collections.abc import Set, Iterator, Callable, Iterable, Hashable

from functools import wraps
import contextlib
import pathlib


__author__ = "Thomas Mullan"
__copyright__ = "Copyright 2023, Thomas Mullan"
__license__ = "GNU General Public License v3.0"
__version__ = "0.0.1"
__maintainer__ = "Thomas Mullan"
__status__ = "Prototype"


class FilesystemError(Exception):

    """Emitted when a Filesystem operation fails. Base class for more precise
    Filesystem type errors.
    """


class DuplicateNodeNameError(FilesystemError):

    """Raised when trying to add a node to a NodeSet with a name that is
    already present in the NodeSet.
    """


class NodeDoesNotExistError(FilesystemError):

    """Raised when trying to access a node that does not exist"""


class AbstractNode:

    """Class providing common attributes and methods for all Node types.
    Not meant to be used directly.

    Attributes:
        name (str): The name of the node
        parent (Node | None): The parent Node instance of this node.
    """

    def __init__(
        self,
        name: str,
        parent: Node | None = None,
    ):
        """Initialize a new AbstractNode instance.

        Args:
            name (str): The name of the node.
            parent (Node | None, optional): The parent Node instance of this
                node.
        """
        self.name = name
        self.set_parent(parent)

        # dict that stores arbitrary metadata in key: value form. Only
        # publicly accessible via get_, set_ and del_metadata
        self._meta: dict[Hashable, Any] = {}

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, n: str) -> None:
        self._name = n

    @property
    def parent(self) -> Node | None:
        return self._parent

    @parent.setter
    def parent(self, p: Node | None) -> None:
        self.set_parent(p)

    def set_parent(self, parent: Node | None) -> None:
        """Set the parent of this node to parent. If parent is a Node instance,
        this node will take ownership of the current node and it will add
        itself to the list of child nodes of the new parent node. If it is
        None, and the node previously had a parent, it will no longer be owned
        by that parent and it will remove itself from the parents set of child
        nodes.

        Args:
            parent (Node | None): The new parent node of this node.
        """
        if (old_parent := getattr(self, "parent", None)) is not None:
            old_parent.children.remove(self.name)

        if parent is not None:
            parent.children.add(self)

        self._parent = parent

    def get_metadata(self, key: Hashable) -> Any:
        return self._meta[key]

    def set_metadata(self, key: Hashable, value: Any) -> None:
        self._meta[key] = value

    def del_metadata(self, key: Hashable) -> Any:
        return self._meta.pop(key)

    def get_path(self) -> pathlib.Path:
        """Return a pathlib.Path instance pointing from the root of the tree
        this node is part to the node itself.

        Returns:
            pathlib.Path: The absolute path to this node.
        """
        path = pathlib.Path(self.name)

        while self.parent:
            self = self.parent
            path = self.name / path

        return path


class LeafNode(AbstractNode):
    """Representing leafs in a Filesystem tree. LeafNodes are akin to
    regular File like objects in a file system, as they can carry data but
    can not have any child nodes, as opposed to directory like nodes.
    """

    def __init__(self, name: str, parent: Node | None, data: Any = None):
        """Initialize a new LeafNode.

        Args:
            name (str): The name of the node.
            parent (Node | None): The parent node of this node.
            data (object, optional): The data associated with this leaf node.
        """
        super().__init__(name=name, parent=parent)

        self._data = data
        self._callbacks: set[Callable[[pathlib.Path], None]] = set()

    @property
    def data(self) -> Any:
        return self._data

    @data.setter
    def data(self, d: Any) -> None:
        self.set_data(d)

    def set_data(self, d: Any) -> None:
        self._data = d
        self.execute_callbacks()

    def clear_data(self):
        self._data = None
        self.execute_callbacks()

    def watch(self, callback: Callable[[pathlib.Path], None]) -> None:
        """Register a callback that is triggered whenever the data in this
        LeafNode changes. The callback receives the absolute path to this
        node.

        Args:
            callback (Callable[[pathlib.Path], None]): The callback to invoke
                when the data associated with this leaf node changes.
        """
        self._callbacks.add(callback)

    def unwatch(self, *callbacks: Callable[[pathlib.Path], None]) -> None:
        if callbacks:
            for callback in callbacks:
                self._callbacks.remove(callback)

        else:
            self._callbacks.clear()

    def execute_callbacks(self) -> None:
        path = self.get_path()
        for callback in self._callbacks:
            callback(path)


class Node(AbstractNode):
    def __init__(
        self, name: str, parent: Node | None = None, children: Iterable[Node] = []
    ):
        super().__init__(name=name, parent=parent)

        self._children = NodeSet(owner=self)
        for child in children:
            self.add_child(child)

    @property
    def children(self) -> NodeSet:
        """The NodeSet that stores the children of this node

        Returns:
            NodeSet: The NodeSet that stores the children of this node
        """
        return self._children

    def add_child(self, child: Node | LeafNode) -> None:
        """Add a new child node to the set of child nodes.

        Args:
            child (Node | LeafNode): The node to add as child. The current
                node will take ownership of the child node.
        """
        child.set_parent(self)

    def remove_child(self, name: str) -> Node | LeafNode:
        """Remove a node from the set of child nodes

        Args:
            name (str): The name of the node to remove. The child node will
                no longer be owned by the current node.

        Returns:
            Node | LeafNode: The removed node. It will no longer have a parent.

        Raises:
            NoSuchChildLeafNodeError: If the child does not exist.
        """

        try:
            child = self.children.get(name)
        except NodeDoesNotExistError as err:
            raise err from None

        child.set_parent(None)

        return child

    def get_child(self, name: str) -> Node | LeafNode:
        """Return the node with name equal to the given name

        Args:
            name (str): The name of the requested node

        Returns:
            Node | LeafNode: The node with name equal to the given name.

        Raises:
            NodeDoesNotExistError: If no child node with the given name exists.
        """
        try:
            child = self.children.get(name)
        except NodeDoesNotExistError as err:
            raise err from None

        return child

    def tree_repr(self, indent: int = 0) -> str:
        """Return a representation of the tree where the current node is
            the root and its children are the branches and leafs.

        Args:
            indent (int, optional): Internal variable not meant for using.
                Determines the indentation of the current level. Is used
                recursively.

        Returns:
            str: The tree representation of this node tree
        """
        string = f"{self.name}/"

        for kid in sorted(self.children, key=lambda node: node.name):
            string += "\n" + "|  " * indent
            if isinstance(kid, Node):
                string += f"|__{kid.tree_repr(indent + 1)}"

            else:
                string += f"|__{kid.name}"

        return string


class NodeSet(Set[Node | LeafNode]):

    """class NodeSet

    Class storing a unique set of Nodes. Uniqueness of Nodes is based on
    their name. Each name can only exist once in the set.
    """

    def __init__(self, owner: Node, members: Iterable[Node | LeafNode] = []):
        """Initialize new NodeSet"""
        self._owner = owner
        self._members: set[Node | LeafNode] = set()

        for member in members:
            self.add(member)

    def __iter__(self) -> Iterator[Node | LeafNode]:
        """Return an iterator of the members of the set

        Returns:
            Iterator[LeafNode]: The iterator returning the members of the set
        """
        return iter(self._members)

    def __len__(self) -> int:
        """Returns the number of members in the set.

        Returns:
            int: The number of LeafNodes in the set.
        """
        return len(self._members)

    def __contains__(self, name: object) -> bool:
        """If name is given as string, return true if a member with a name
        given to the equal name exists, false otherwise. If name is given as
        an AbstractNode instance, return true if the node itself is member of
        the set, false otherwise. Any other object will raise a TypeErro

        Args:
            name (str | Node | LeafNode ): A string with the name or a
                Node or LeafNode instance to test for membership

        Returns:
            bool: True if a node with the tested name or the node itself
                exists, false otherwise

        Raises:
            TypeError: If name is not an instance of str or AbstractNode
        """
        if not isinstance(name, (str, AbstractNode)):
            raise TypeError(f"Expected str or AbstractNode, got {type(name)}")

        elif isinstance(name, AbstractNode):
            name = name.name

        return any(node.name == name for node in self)

    def __bool__(self) -> bool:
        """Determines the truth value of the set

        Returns:
            bool: Returns false if the set is empty else true
        """
        return bool(self._members)

    def add(self, node: Node | LeafNode) -> None:
        """Adds another node to the set of child nodes

        Args:
            node (Node | LeafNode): The node to add

        Raises:
            DuplicateNodeNameError: If a node with the same name
                already exists in the set.
            TypeError: If node is not an instance of AbstractNode
        """
        if not isinstance(node, AbstractNode):
            raise TypeError(
                f"Expected instance of {AbstractNode}, got {type(node)}"
            )

        if node in self:
            raise DuplicateNodeNameError(node.name)

        self._members.add(node)

    def get(self, name: str) -> Node | LeafNode:
        """Return the node with name equal to the given name.

        Args:
            name (str): The name of the node to return

        Returns:
            Node | LeafNode: The node with name equal to the given name

        Raises:
            NodeDoesNotExistError: If no node with the given name exists in
                the set
        """
        member: Node | LeafNode

        for member in self:
            if member.name == name:
                break
        else:
            raise NodeDoesNotExistError(name)

        return member

    def remove(self, name: str) -> Node | LeafNode:
        """Remove node with name equal to the given name from the set.

        Args:
            name (str): The name of the node to remove.

        Returns:
            Node | LeafNode: The removed node

        Raises:
            NodeDoesNotExistError: If no node with the given name exists.
        """
        for member in self:
            if member.name == name:
                self._members.remove(member)
                break
        else:
            raise NodeDoesNotExistError(name)

        return member


class InvalidPathError(FilesystemError):
    pass


class Filesystem:
    def __init__(self):
        # root node of the filesystem
        self._root = Node(name="/")

    @property
    def root(self) -> Node:
        return self._root

    def get_node(self, path: str | pathlib.Path) -> Node | LeafNode:
        path = pathlib.Path(path)
        root, *parts = path.parts

        if root == self.root.name:
            node: Node | LeafNode = self.root
        else:
            try:
                node = self.root.get_child(root)
            except NodeDoesNotExistError as err:
                raise err from None

        for part in parts:
            try:
                node = node.get_child(part)

            except NodeDoesNotExistError as err:
                raise err from None

        return node

    def remove_node(self, path: str | pathlib.Path) -> Node | LeafNode:
        path = pathlib.Path(path)

        try:
            node = self.get_node(path.parent)
        except NodeDoesNotExistError:
            raise InvalidPathError(path)

        if not isinstance(node, Node):
            raise InvalidPathError(path)

        try:
            node = node.remove_child(path.name)
        except NodeDoesNotExistError:
            raise InvalidPathError(path) from None

        return node

    def move_node(
        self, source_path: str | pathlib.Path, target_path: str | pathlib.Path
    ) -> None:
        source_path = pathlib.Path(source_path)
        target_path = pathlib.Path(target_path)

        if not source_path.name:
            raise InvalidPathError(f"Invalid source: {source_path}")

        elif not target_path.name:
            raise InvalidPathError(f"Invalid target: {target_path}")

        try:
            source = self.get_node(source_path)
        except NodeDoesNotExistError:
            msg = f"Source does not exist: {source_path}"
            raise InvalidPathError(msg) from None

        try:
            target = self.get_node(target_path)
        except NodeDoesNotExistError:
            # if the last node in target_path does not exist but its parent
            # does, the last node in target_path is the new name of the last
            # node in source_path. I.e it gets renamed as in bash mv command.
            try:
                target = self.get_node(target_path.parent)
            except NodeDoesNotExistError:
                msg = f"Target does not exist: {target_path}"
                raise InvalidPathError(msg) from None

            source.name = target_path.name

        if not isinstance(target, Node):
            raise InvalidPathError(f"Invalid target: {target}")

        # this should be an atomic operation, i.e. if set_parent fails and the
        # node has been renamed, it should keep its old name.
        source.set_parent(target)


class ChangeDirContextManager(contextlib.AbstractContextManager):
    def __init__(self, shell: StupidlySimpleShell, target_dir: str | pathlib.Path):
        self._shell = shell
        self._target = target_dir

    def __enter__(self) -> StupidlySimpleShell:
        self._pwd = self._shell.pwd()
        self._shell.cd(self._target)

        return self._shell

    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None
    ) -> None:
        self._shell.cd(self._pwd)


def resolved_path(
    default_path: str | pathlib.Path | None = None, double_paths: bool = False
) -> Callable:
    def outer_wrapper(func: Callable) -> Callable:
        if default_path is None and double_paths:
            @wraps(func)
            def wrapper(
                self: StupidlySimpleShell,
                path1: str | pathlib.Path,
                path2: str | pathlib.Path,
                *args,
                **kwargs,
            ) -> Any:
                path1 = self.resolve_path(path1)
                path2 = self.resolve_path(path2)

                return func(self, path1, path2, *args, **kwargs)

        elif default_path is None:
            @wraps(func)
            def wrapper(
                self: StupidlySimpleShell, path: str | pathlib.Path, *args, **kwargs
            ) -> Any:
                path = self.resolve_path(path)

                return func(self, path, *args, **kwargs)

        else:
            @wraps(func)
            def wrapper(
                self: StupidlySimpleShell,
                path: str | pathlib.Path = default_path,
                *args,
                **kwargs,
            ) -> Any:
                path = self.resolve_path(path)

                return func(self, *args, path=path, **kwargs)

        return wrapper

    return outer_wrapper


class StupidlySimpleShell:
    def __init__(self) -> None:
        self._filesystem: Filesystem = Filesystem()

        self._cwd: Node = self.filesystem.root

    @property
    def filesystem(self) -> Filesystem:
        return self._filesystem

    def pwd(self) -> pathlib.Path:
        """Return the current working directory as pathlib.Path instance

        Returns:
            pathlib.Path: The current working directory
        """
        return self._cwd.get_path()

    @resolved_path(default_path=".")
    def tree(self, path: pathlib.Path) -> str:
        node = self.filesystem.get_node(path)
        if not isinstance(node, Node):
            raise InvalidPathError(f"Not a directory: {path}")

        return node.tree_repr()

    def resolve_path(self, path: str | pathlib.Path) -> pathlib.Path:
        """Return the absolute representation of path, with all relative parts
        resolved: 'this/is/a/loooong/../path' -> '/path/to/root/this/is/a/path'

        Args:
            path (str | pathlib.Path): The path to resolve

        Returns:
            pathlib.Path: The resolved, absolute path.

        Raises:
            InvalidPathError: Raised when the provided path cannot be resolved.
        """
        path = pathlib.Path(path)
        try:
            root, *parts = path.parts
        except ValueError:
            # if path is just the current dir, i.e. '.', there are not
            # enough values to unpack, but it is still a valid path.
            if str(path) != ".":
                raise InvalidPathError(path) from None

            root, parts = ".", []

        if root != self.filesystem.root.name:
            # this is a relative path to the cwd, make it absolute by
            # prepending the current work path and reset the root and parts
            path = self.pwd() / path
            root, *parts = path.parts

        if "." in parts or ".." in parts:
            # '.' just refers to the same dir as the previous part of the path
            # so we can just remove it, '..' refers to the second to last dir
            # in the path, so also remove the previous dir
            for idx, part in enumerate(parts):
                if part == ".":
                    del parts[idx]

                elif part == "..":
                    del parts[idx]
                    # if there are no more parts left we are at the root dir
                    if parts:
                        del parts[idx - 1]

            path = pathlib.Path(root)
            for part in parts:
                path /= part

        return path

    @resolved_path()
    def cd(self, path: pathlib.Path) -> None:
        """Change the current working directory to path. All subsequent
        Filesystem operations will be relative to this directory.

        Args:
            path (str | pathlib.Path): The path to change to.
        """
        try:
            node = self.filesystem.get_node(path)
        except NodeDoesNotExistError:
            raise InvalidPathError(path) from None

        if not isinstance(node, Node):
            raise InvalidPathError(f"Not a directory: {path}")

        self._cwd = node

    def managed_cd(self, path: str | pathlib.Path) -> ChangeDirContextManager:
        """Create a context manager that changes the current working directory
        to path on enter and returns to the previous working directory on exit.

        Args:
            path (str | pathlib.Path): The path to change to when entering the
                context manager

        Returns:
            ChangeDirContextManager: The context manager that manages the
                change dir.
        """
        return ChangeDirContextManager(self, path)

    @resolved_path()
    def mkdir(self, path: pathlib.Path, parents: bool = False) -> None:
        """Create a new directory at path. If parents is true all non-existing
        directories in path will also be created.

        Args:
            path (str | pathlib.Path): The path to the directory which should
                be created
            parents (bool, optional): Create non-existing directories in path
                on the fly if true, else raise an InvalidPathError if any
                directories in path do not exist.

        Raises:
            InvalidPathError: When parents is false and any of the directories
                in path do not exist or an invalid path has been supplied.
        """

        if not path.name:
            raise InvalidPathError(path)

        if not parents:
            try:
                parent = self.filesystem.get_node(path.parent)
            except NodeDoesNotExistError:
                msg = f"No such directory: {path.parent}"
                raise InvalidPathError(msg) from None

            if not isinstance(parent, Node):
                raise InvalidPathError(f"Not a directory: {path}")

            try:
                Node(name=path.name, parent=parent)
            except DuplicateNodeNameError:
                msg = f"Directory already exists: {path}"
                raise InvalidPathError(msg) from None

        else:
            try:
                node = self.filesystem.get_node(path.root)
            except InvalidPathError as err:
                raise err from None

            if not isinstance(node, Node):
                raise InvalidPathError(path)

            for part in path.parts[1:]:
                try:
                    node = node.get_child(part)
                except NodeDoesNotExistError:
                    node = Node(name=part, parent=node)

                if not isinstance(node, Node):
                    raise InvalidPathError(path)

    @resolved_path(double_paths=True)
    def mv(self, source_path: pathlib.Path, target_path: pathlib.Path) -> None:
        """Move the directory in source_path to the directory specified in
        target_path. If the last directory in target_path does not exist, but
        the second to last does, the source_path directory gets renamed to the
        name of the last directory in target_path before it is moved. This is
        the same behavior as the bash mv command.

        Args:
            source_path (str | pathlib.Path): The path to the directory to move
            target_path (str | pathlib.Path): The path to the directory which
                to move the source directory to
        """
        try:
            self.filesystem.move_node(source_path, target_path)
        except InvalidPathError as err:
            raise err from None

    @resolved_path()
    def touch(self, path: pathlib.Path, file_type: type[LeafNode] = LeafNode) -> None:
        if not path.name:
            raise InvalidPathError(path)

        try:
            parent = self.filesystem.get_node(path.parent)
        except NodeDoesNotExistError:
            raise InvalidPathError(path) from None

        if not isinstance(parent, Node):
            raise InvalidPathError(f"Not a directory: {path}")

        try:
            file_type(name=path.name, parent=parent)
        except DuplicateNodeNameError:
            raise InvalidPathError(f"Already exists: {path}") from None

    @resolved_path()
    def get_data(self, path: pathlib.Path) -> Any:
        try:
            node = self.filesystem.get_node(path)
        except NodeDoesNotExistError:
            raise InvalidPathError(path) from None

        if not isinstance(node, LeafNode):
            raise InvalidPathError(f"Not a file: {path}")

        return node.data

    @resolved_path()
    def set_data(self, path: pathlib.Path, data: Any, *args, **kwargs) -> None:
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        if not isinstance(node, LeafNode):
            raise InvalidPathError(f"Not a file: {path}")

        node.set_data(data, *args, **kwargs)

    @resolved_path()
    def clear_data(self, path: pathlib.Path):
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        if not isinstance(node, LeafNode):
            raise InvalidPathError(f"Not a file: {path}")

        node.clear_data()

    @resolved_path()
    def get_metadata(self, path: pathlib.Path, key: Hashable) -> Any:
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        try:
            data = node.get_metadata(key)
        except KeyError:
            raise KeyError(f"No such metadata '{key}' for node {path}") from None

        return data

    @resolved_path()
    def set_metadata(self, path: pathlib.Path, key: Hashable, value: Any) -> None:
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        node.set_metadata(key, value)

    @resolved_path()
    def del_metadata(self, path: pathlib.Path, key: Hashable) -> Any:
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        try:
            data = node.del_metadata(key)
        except KeyError:
            raise KeyError(f"No such metadata '{key}' for {path}") from None

        return data

    @resolved_path()
    def rm(self, path: pathlib.Path, recursive: bool = False) -> Node | LeafNode:
        try:
            node = self.filesystem.get_node(path)
        except NodeDoesNotExistError:
            raise InvalidPathError(path) from None

        if isinstance(node, Node) and not recursive:
            raise InvalidPathError("Use recursive=true to remove directories!")

        elif not node.parent:
            raise InvalidPathError("Can't remove root!")

        return node.parent.remove_child(node.name)

    @resolved_path(default_path=".")
    def ls(self, path: pathlib.Path) -> list[str]:
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        if not isinstance(node, Node):
            raise InvalidPathError(f"Not a directory: {path}")

        return sorted(c.name for c in node.children)

    @resolved_path()
    def watch_file(
        self, path: pathlib.Path, callback: Callable[[pathlib.Path], None]
    ) -> None:
        """Register a callback that will be triggered whenever the data
        stored in path changes. The callback will receive the path to the
        data object that has changed.

        Args:
            path (pathlib.Path): The path to the data object to monitor
            callback (Callable[[pathlib.Path], None]): The callback to invoke
                when the data in path has changed.
        """

        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        if not isinstance(node, LeafNode):
            raise InvalidPathError(f"Not a file: {path}")

        node.watch(callback)

    @resolved_path()
    def unwatch_file(
        self, path: pathlib.Path, *connections: Callable[[pathlib.Path], None]
    ) -> None:
        try:
            node = self.filesystem.get_node(path)
        except InvalidPathError as err:
            raise err from None

        if not isinstance(node, LeafNode):
            raise InvalidPathError(f"Not a file: {path}")

        node.unwatch(*connections)

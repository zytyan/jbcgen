from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar, cast

from ..annotations import Annotation
from ..diagnostics import AnnotationError


class PluginError(ValueError):
    pass


StateT = TypeVar("StateT")


@dataclass(frozen=True)
class PluginKey(Generic[StateT]):
    id: str
    state_type: type[StateT]


@dataclass(frozen=True)
class _PluginEntry:
    id: str
    state: object


@dataclass(frozen=True, init=False)
class PluginSet:
    """Immutable, deterministically ordered collection of typed plugin states."""

    entries: tuple[_PluginEntry, ...]

    def __init__(self, values: tuple[tuple[PluginKey[object], object], ...] = ()):
        entries: list[_PluginEntry] = []
        seen: set[str] = set()
        for key, state in values:
            if key.id in seen:
                raise PluginError(f"duplicate plugin ID {key.id!r}")
            if not isinstance(state, key.state_type):
                raise PluginError(
                    f"plugin {key.id!r} requires state {key.state_type.__name__}, "
                    f"got {type(state).__name__}"
                )
            seen.add(key.id)
            entries.append(_PluginEntry(key.id, state))
        object.__setattr__(self, "entries", tuple(sorted(entries, key=lambda item: item.id)))

    def get(self, key: PluginKey[StateT]) -> StateT | None:
        for entry in self.entries:
            if entry.id != key.id:
                continue
            if not isinstance(entry.state, key.state_type):
                raise PluginError(
                    f"plugin {key.id!r} contains {type(entry.state).__name__}, "
                    f"not {key.state_type.__name__}"
                )
            return cast(StateT, entry.state)
        return None

    def require(self, key: PluginKey[StateT]) -> StateT:
        state = self.get(key)
        if state is None:
            raise PluginError(f"required plugin {key.id!r} is missing")
        return state


class AnnotationMode(Enum):
    FLAG = "flag"
    VALUE = "value"


@dataclass(frozen=True)
class AnnotationArgumentSpec:
    name: str
    mode: AnnotationMode
    repeatable: bool = False


@dataclass(frozen=True)
class AnnotationCommandSpec:
    name: str
    arguments: tuple[AnnotationArgumentSpec, ...] = ()


class AnnotationRegistry:
    """Merged annotation vocabulary declared by schema plugins."""

    def __init__(self, declarations: tuple[tuple[str, AnnotationCommandSpec], ...]):
        commands: dict[str, dict[str, AnnotationArgumentSpec]] = {}
        owners: dict[tuple[str, str], str] = {}
        for plugin_id, command in declarations:
            arguments = commands.setdefault(command.name, {})
            for argument in command.arguments:
                previous = arguments.get(argument.name)
                if previous is not None and previous != argument:
                    owner = owners[(command.name, argument.name)]
                    raise PluginError(
                        f"annotation parameter @{command.name}({argument.name}) is declared "
                        f"incompatibly by {owner!r} and {plugin_id!r}"
                    )
                arguments[argument.name] = argument
                owners.setdefault((command.name, argument.name), plugin_id)
        self._commands = {
            name: tuple(sorted(arguments.values(), key=lambda item: item.name))
            for name, arguments in sorted(commands.items())
        }

    @classmethod
    def from_plugins(cls, plugins: tuple[SchemaPlugin, ...]) -> AnnotationRegistry:
        return cls(
            tuple(
                (plugin.key.id, command)
                for plugin in plugins
                for command in plugin.annotation_commands()
            )
        )

    def validate(self, annotation: Annotation) -> None:
        declarations = self._commands.get(annotation.name)
        if declarations is None:
            raise AnnotationError(
                f"unknown annotation @{annotation.name}", annotation.location
            )
        specs = {item.name: item for item in declarations}
        seen: set[str] = set()
        for argument in annotation.arguments:
            spec = specs.get(argument.name)
            if spec is None:
                raise AnnotationError(
                    f"unknown @{annotation.name} argument {argument.name!r}",
                    annotation.location,
                )
            if spec.mode is AnnotationMode.FLAG and argument.value is not None:
                raise AnnotationError(
                    f"@{annotation.name} argument {argument.name!r} is a flag",
                    annotation.location,
                )
            if spec.mode is AnnotationMode.VALUE and argument.value is None:
                raise AnnotationError(
                    f"@{annotation.name} argument {argument.name!r} requires a value",
                    annotation.location,
                )
            if argument.name in seen and not spec.repeatable:
                raise AnnotationError(
                    f"duplicate @{annotation.name} argument {argument.name!r}",
                    annotation.location,
                )
            seen.add(argument.name)


class SchemaPlugin(Protocol):
    key: PluginKey[object]

    def annotation_commands(self) -> tuple[AnnotationCommandSpec, ...]: ...

    def format_state(self, state: object) -> str: ...

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Generic, Iterable, Mapping, Protocol, TypeVar, cast

from ..annotations import Annotation
from ..diagnostics import AnnotationError, SourceLocation

if TYPE_CHECKING:
    from ..clang_frontend import TranslationUnit
    from ..schema_core import CoreSchemaIR


class PluginError(ValueError):
    pass


StateT = TypeVar("StateT")
ValueT = TypeVar("ValueT")


def frozen_map(items: Iterable[tuple[str, ValueT]]) -> Mapping[str, ValueT]:
    return MappingProxyType(dict(sorted(items, key=lambda item: item[0])))


@dataclass(frozen=True)
class PluginKey(Generic[StateT]):
    id: str
    state_type: type[StateT]


@dataclass(frozen=True, init=False)
class PluginSet:
    """Immutable, deterministically ordered collection of typed plugin states."""

    states: Mapping[str, object]

    def __init__(self, values: tuple[tuple[PluginKey[object], object], ...] = ()):
        states: dict[str, object] = {}
        for key, state in values:
            if key.id in states:
                raise PluginError(f"duplicate plugin ID {key.id!r}")
            if not isinstance(state, key.state_type):
                raise PluginError(
                    f"plugin {key.id!r} requires state {key.state_type.__name__}, "
                    f"got {type(state).__name__}"
                )
            states[key.id] = state
        object.__setattr__(self, "states", frozen_map(states.items()))

    def get(self, key: PluginKey[StateT]) -> StateT | None:
        state = self.states.get(key.id)
        if state is None:
            return None
        if not isinstance(state, key.state_type):
            raise PluginError(
                f"plugin {key.id!r} contains {type(state).__name__}, "
                f"not {key.state_type.__name__}"
            )
        return cast(StateT, state)

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


def flag_argument(name: str) -> AnnotationArgumentSpec:
    return AnnotationArgumentSpec(name, AnnotationMode.FLAG)


def value_argument(name: str, *, repeatable: bool = False) -> AnnotationArgumentSpec:
    return AnnotationArgumentSpec(name, AnnotationMode.VALUE, repeatable)


def find_annotation(
    annotations: tuple[Annotation, ...], name: str, location: SourceLocation
) -> Annotation | None:
    matches = tuple(item for item in annotations if item.name == name)
    if len(matches) > 1:
        raise AnnotationError(f"a declaration may contain only one @{name} annotation", location)
    return matches[0] if matches else None


def argument_value(annotation: Annotation | None, name: str) -> str | None:
    values = annotation.values(name) if annotation else ()
    return values[0] if values else None


def has_flag(annotation: Annotation | None, name: str) -> bool:
    return bool(annotation and annotation.values(name))


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
        self._commands = frozen_map(
            (name, frozen_map(arguments.items())) for name, arguments in commands.items()
        )

    @classmethod
    def from_plugins(cls, plugins: tuple[SchemaPlugin[object], ...]) -> AnnotationRegistry:
        return cls(
            tuple(
                (plugin.key.id, command)
                for plugin in plugins
                for command in plugin.annotation_commands
            )
        )

    def validate(self, annotation: Annotation) -> None:
        specs = self._commands.get(annotation.name)
        if specs is None:
            raise AnnotationError(
                f"unknown annotation @{annotation.name}", annotation.location
            )
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


@dataclass(frozen=True)
class PluginBuildContext:
    unit: TranslationUnit
    core: CoreSchemaIR | None
    states: PluginSet


@dataclass(frozen=True)
class PluginValidationContext:
    unit: TranslationUnit
    core: CoreSchemaIR
    states: PluginSet


class SchemaPlugin(Protocol[StateT]):
    key: PluginKey[StateT]
    annotation_commands: tuple[AnnotationCommandSpec, ...]
    dependencies: tuple[PluginKey[object], ...]

    def build(self, context: PluginBuildContext) -> StateT: ...

    def validate(self, context: PluginValidationContext, state: StateT) -> None: ...

    def format_state(self, state: StateT) -> str: ...


class SchemaPluginBase(Generic[StateT]):
    """Defaults for plugins that only implement the phases they need."""

    key: PluginKey[StateT]
    annotation_commands: tuple[AnnotationCommandSpec, ...] = ()
    dependencies: tuple[PluginKey[object], ...] = ()

    def validate(self, context: PluginValidationContext, state: StateT) -> None:
        pass

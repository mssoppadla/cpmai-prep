from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str = "base"
    model: str | None = None

    @abstractmethod
    def complete(self, system: str, messages: list[dict], **kwargs) -> str: ...
